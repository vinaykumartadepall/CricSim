"""
Parameter Optimizer
===================
Learns optimal values for the manually-tuned scalar and blend-weight
parameters in EnhancedHistoricalStatsStrategy by minimising held-out
log-loss with scipy.optimize (Nelder-Mead, gradient-free).

What gets optimised (per format):
  WEIGHTS       8-dimensional simplex: batter / bowler / matchup / phase /
                venue / tournament / innings / milestone.
                venue and tournament weights are fixed at current values
                during training because the validator uses empty caches for
                those; only the 6 active sources are trained.
  sharpness_k   scalar ∈ [1.0, 4.0] — exponent for batter/bowler/matchup mults
  milestone_k   scalar ∈ [1.0, 5.0] — sharper exponent for milestone context

Algorithm detail
  Objective is vectorised with NumPy: per-delivery context distributions are
  pre-computed and stored as log-ratio matrices so each evaluation only does
  matrix multiplications (no DB access).
  Typical run: ~2000 Nelder-Mead evaluations × 5000 deliveries → < 2 minutes.

Usage:
    python -m simulator.predictors.ball_outcome_prediction.historical_stats.optimize_params \\
        --format T20 --train-samples 8000 --valid-samples 2000

    # Fix sharpness/milestone k, only train weights:
    python -m ... --fix-scalars

    # Show current vs optimal parameter table only (no full optimization):
    python -m ... --dry-run
"""

import math
import os
import sys
import time
from typing import Dict, List, Optional

import numpy as np

from db.stats_repository import StatsRepository
from simulator.entities.rules import MatchRules
from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy import (
    _RELIABILITY_THRESHOLDS,
    _RATIO_MIN,
    _RATIO_MAX,
    _BASELINE_EPSILON,
    _SHARPNESS_K,
    _MILESTONE_K,
    _make_parttime_probs,
    _parttime_alpha,
    _blend_with_parttime,
    _get_milestone,
    _outcome_category,
    _CATEGORY_RELEVANCE,
)
from validation.delivery_validator import (
    ModelValidator,
)

# ── Which context sources the optimizer trains (indices map to WEIGHT_KEYS) ───
WEIGHT_KEYS = ['batter', 'bowler', 'matchup', 'phase', 'venue', 'tournament', 'innings', 'milestone']
# venue and tournament caches are empty in validation → optimizing them has no
# effect on the objective; fix them at their current values and train only these:
TRAINABLE_KEYS  = ['batter', 'bowler', 'matchup', 'phase', 'innings', 'milestone']
FIXED_KEYS      = ['venue', 'tournament']

# Source index in the pre-computed matrices (6 trainable sources)
_SRC_BATTER   = 0
_SRC_BOWLER   = 1
_SRC_MATCHUP  = 2
_SRC_PHASE    = 3
_SRC_INNINGS  = 4
_SRC_MILESTONE= 5
_N_SOURCES    = 6

# K-exponent per source (milestone gets milestone_k, batter/bowler/matchup get sharpness_k,
# phase and innings use k=1).  The optimizer patches indices 0-2 with sharpness_k,
# index 5 with milestone_k.
_K_STATIC = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0])  # overridden in objective


class ParameterOptimizer:
    """
    Trains WEIGHTS, sharpness_k, and milestone_k for a given format.

    Usage:
        opt = ParameterOptimizer(match_format='T20')
        opt.load_data(n_train=8000, n_valid=2000)
        result = opt.optimize(fix_scalars=False, max_iter=500)
        result.report()
    """

    def __init__(self, match_format: str = 'T20', gender: str = 'male', repo=None):
        self.match_format = MatchRules.get_unified_format(match_format)
        self.gender       = gender
        self.repo         = repo or StatsRepository()
        self._strategy    = None     # loaded in load_data()
        self._train_rows  = []
        self._valid_rows  = []

        # Pre-computed matrices (set by _precompute)
        self._log_ratio   = None   # (N_SRC, N_VALID, N_KEYS)
        self._reliability = None   # (N_SRC, N_VALID)
        self._cat_rel_mat = None   # (N_SRC, N_KEYS) — category relevance (fixed)
        self._log_baseline= None   # (N_KEYS,)
        self._actual_idx  = None   # (N_VALID,) integer index into ordered_keys
        self._n_valid     = 0

        self._ordered_keys = []
        self._current_weights: Dict[str, float] = {}

    # ── Data loading ──────────────────────────────────────────────────────────

    def load_data(self, n_train: int = 8000, n_valid: int = 2000):
        from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats import (
            T20EnhancedHistoricalStatsStrategy,
            ODIEnhancedHistoricalStatsStrategy,
            TestEnhancedHistoricalStatsStrategy,
        )
        strategy_cls = {
            'T20':  T20EnhancedHistoricalStatsStrategy,
            'ODI':  ODIEnhancedHistoricalStatsStrategy,
            'Test': TestEnhancedHistoricalStatsStrategy,
        }[self.match_format]

        print(f"\n[Optimizer] Loading {n_train + n_valid:,} deliveries for {self.match_format} ({self.gender}) …")
        t0 = time.perf_counter()

        all_rows = self.repo.get_validation_deliveries(
            self.match_format, self.gender, n_train + n_valid
        )
        if not all_rows:
            raise RuntimeError(f"No data for {self.match_format}/{self.gender}.")

        # Deterministic 80/20 split (first n_train for training cache, rest for valid)
        self._train_rows = all_rows[:n_train]
        self._valid_rows  = all_rows[n_train:]

        self._strategy = strategy_cls()
        validator = ModelValidator(self.repo)
        # Use ALL rows to build caches (more coverage)
        validator._init_strategy_caches(self._strategy, all_rows, self.match_format, self.gender)
        self._current_weights = dict(self._strategy.WEIGHTS)

        print(f"[Optimizer] Cache loaded in {time.perf_counter()-t0:.1f}s. Pre-computing matrices …")
        self._precompute()
        print(f"[Optimizer] Ready. Valid set: {self._n_valid:,} deliveries, {len(self._ordered_keys)} outcome keys.")

    def _precompute(self):
        """
        Build fixed-cost matrices from the validation rows so that the
        objective function only does numpy algebra (no dict lookups per evaluation).
        """
        strat  = self._strategy
        fmt    = self.match_format
        thresh = _RELIABILITY_THRESHOLDS.get(fmt, _RELIABILITY_THRESHOLDS['T20'])
        baseline = strat.baseline_outcome_probs

        self._ordered_keys = list(baseline.keys())
        N_KEYS = len(self._ordered_keys)
        key_index = {k: i for i, k in enumerate(self._ordered_keys)}
        log_baseline = np.array([math.log(max(p, _BASELINE_EPSILON)) for p in baseline.values()])
        self._log_baseline = log_baseline

        # ── Category relevance matrix (N_SRC, N_KEYS) — fixed ────────────
        cat_rel = np.ones((_N_SOURCES, N_KEYS))
        src_names = TRAINABLE_KEYS  # 6 sources
        for ki, key in enumerate(self._ordered_keys):
            cat = _outcome_category(key)
            rel = _CATEGORY_RELEVANCE.get(cat, _CATEGORY_RELEVANCE['default'])
            for si, src in enumerate(src_names):
                cat_rel[si, ki] = rel.get(src, 1.0)
        self._cat_rel_mat = cat_rel

        # ── Per-delivery context matrices ─────────────────────────────────
        valid_rows = self._valid_rows
        N_VALID_RAW = len(valid_rows)

        log_ratio   = np.zeros((_N_SOURCES, N_VALID_RAW, N_KEYS))
        reliability = np.ones((_N_SOURCES, N_VALID_RAW))
        actual_idx  = np.full(N_VALID_RAW, -1, dtype=np.int32)

        kept = 0
        for d, row in enumerate(valid_rows):
            (batter_id, bowler_id, _, inning, over_1idx,
             _, r_bat, r_ext, o_type, o_kind, batter_score, _, _) = row

            actual_key = (r_bat, r_ext, o_type, o_kind)
            if actual_key not in baseline:
                continue

            actual_idx[kept] = key_index[actual_key]
            matchup_key = (batter_id, bowler_id) if batter_id and bowler_id else None

            # Context distributions
            batter_probs  = strat.batter_cache.get(batter_id, baseline)   if batter_id   else baseline
            _raw_bowler   = strat.bowler_cache.get(bowler_id, baseline)    if bowler_id   else baseline
            _pt_alpha     = _parttime_alpha(strat.bowler_ball_counts.get(bowler_id, 0) if bowler_id else 0, fmt)
            bowler_probs  = _blend_with_parttime(strat.parttime_bowler_probs, _raw_bowler, _pt_alpha)
            matchup_probs = strat.matchup_cache.get(matchup_key, baseline) if matchup_key else baseline
            phase         = MatchRules.get_fine_grained_phase(over_1idx, fmt)
            phase_probs   = strat.phase_cache.get(phase, baseline)
            innings_probs = strat.innings_cache.get(inning, baseline)
            milestone     = _get_milestone(int(batter_score or 0))
            _player_ms    = strat.player_milestone_cache.get(batter_id, {}) if batter_id else {}
            milestone_probs = (
                _player_ms.get(milestone)
                or strat.milestone_cache.get(milestone)
                or baseline
            )

            ctx_dists = [batter_probs, bowler_probs, matchup_probs,
                         phase_probs, innings_probs, milestone_probs]

            for ki, key in enumerate(self._ordered_keys):
                bp = baseline.get(key, _BASELINE_EPSILON)
                for si, ctx in enumerate(ctx_dists):
                    cp    = ctx.get(key, bp)
                    ratio = max(_RATIO_MIN, min(_RATIO_MAX, cp / max(bp, _BASELINE_EPSILON)))
                    log_ratio[si, kept, ki] = math.log(ratio)

            # Reliability per source
            b_balls  = strat.batter_ball_counts.get(batter_id, 0)   if batter_id   else 0
            bw_balls = strat.bowler_ball_counts.get(bowler_id, 0)   if bowler_id   else 0
            mk_balls = strat.matchup_ball_counts.get(matchup_key, 0) if matchup_key else 0
            reliability[_SRC_BATTER,    kept] = min(1.0, b_balls  / thresh['batter'])
            reliability[_SRC_BOWLER,    kept] = min(1.0, bw_balls / thresh['bowler'])
            reliability[_SRC_MATCHUP,   kept] = min(1.0, mk_balls / thresh['matchup'])
            # phase, innings, milestone always fully reliable
            reliability[_SRC_PHASE,     kept] = 1.0
            reliability[_SRC_INNINGS,   kept] = 1.0
            reliability[_SRC_MILESTONE, kept] = 1.0

            kept += 1

        self._log_ratio   = log_ratio[:, :kept, :]
        self._reliability = reliability[:, :kept]
        self._actual_idx  = actual_idx[:kept]
        self._n_valid     = kept

    # ── Objective function ────────────────────────────────────────────────────

    def objective(self, theta: np.ndarray) -> float:
        """
        Vectorised log-loss on the validation set.

        theta layout (fix_scalars=False):
          [0..5]  logit weights for 6 trainable sources
          [6]     log(sharpness_k)
          [7]     log(milestone_k)

        With fix_scalars=True: theta has only [0..5].
        """
        n_w = _N_SOURCES
        has_scalars = (len(theta) > n_w)

        # Recover weights (softmax from logits)
        w_logit = theta[:n_w]
        w_exp   = np.exp(w_logit - w_logit.max())
        w       = w_exp / w_exp.sum()  # shape (N_SRC,)

        # K-exponent per source
        if has_scalars:
            sk = float(np.exp(np.clip(theta[n_w],   math.log(0.5), math.log(6.0))))
            mk = float(np.exp(np.clip(theta[n_w+1], math.log(0.5), math.log(8.0))))
        else:
            sk = _SHARPNESS_K
            mk = _MILESTONE_K

        K = np.array([sk, sk, sk, 1.0, 1.0, mk])  # shape (N_SRC,)

        # Effective weights: (N_SRC, N_VALID) = base_w × reliability
        eff = w[:, np.newaxis] * self._reliability          # (N_SRC, N_VALID)
        eff_sum = eff.sum(axis=0, keepdims=True)            # (1, N_VALID)
        eff_norm = eff / np.maximum(eff_sum, 1e-10)        # (N_SRC, N_VALID), sums to 1 per delivery

        # Category-relevance adjustment: (N_SRC, N_VALID, N_KEYS)
        # eff_norm[:, :, newaxis] × cat_rel[:, newaxis, :]
        adj = eff_norm[:, :, np.newaxis] * self._cat_rel_mat[:, np.newaxis, :]
        adj_sum = adj.sum(axis=0, keepdims=True)            # (1, N_VALID, N_KEYS)
        cw  = adj / np.maximum(adj_sum, 1e-10)             # (N_SRC, N_VALID, N_KEYS)

        # Weighted log-ratio sum: sum_src K[src] * cw[src] * log_ratio[src]
        # K[:, newaxis, newaxis] * cw * log_ratio  → (N_SRC, N_VALID, N_KEYS)
        weighted = K[:, np.newaxis, np.newaxis] * cw * self._log_ratio
        weighted_sum = weighted.sum(axis=0)                 # (N_VALID, N_KEYS)

        # Log unnormalized: log_baseline + weighted_sum
        log_raw = self._log_baseline[np.newaxis, :] + weighted_sum

        # Numerically-stable softmax normalisation per delivery
        log_raw -= log_raw.max(axis=1, keepdims=True)
        raw_exp  = np.exp(log_raw)
        norm     = raw_exp / raw_exp.sum(axis=1, keepdims=True)

        # Log-loss on actual outcomes
        pred_p   = norm[np.arange(self._n_valid), self._actual_idx]
        log_loss = -np.log(np.maximum(pred_p, 1e-10)).mean()
        return float(log_loss)

    # ── Optimization ──────────────────────────────────────────────────────────

    def optimize(
        self,
        fix_scalars: bool = False,
        max_iter: int = 500,
    ) -> 'OptimResult':
        from scipy.optimize import minimize

        current_w = self._current_weights
        # Initial logit weights from current WEIGHTS (normalized over trainable sources)
        trainable_sum = sum(current_w.get(k, 0.0) for k in TRAINABLE_KEYS)
        init_w = np.array([
            max(1e-6, current_w.get(k, 0.125)) / max(trainable_sum, 1.0)
            for k in TRAINABLE_KEYS
        ])
        init_logit = np.log(init_w)
        init_logit -= init_logit.mean()  # centre for numerical stability

        if fix_scalars:
            x0 = init_logit
        else:
            x0 = np.concatenate([
                init_logit,
                [math.log(_SHARPNESS_K), math.log(_MILESTONE_K)]
            ])

        loss_before = self.objective(x0)
        print(f"\n[Optimizer] Optimising {len(x0)} parameters, max_iter={max_iter} …")
        print(f"[Optimizer] Initial log-loss: {loss_before:.5f}")

        t0 = time.perf_counter()
        res = minimize(
            self.objective,
            x0,
            method='Nelder-Mead',
            options={'maxiter': max_iter, 'xatol': 1e-5, 'fatol': 1e-5, 'disp': True},
        )
        elapsed = time.perf_counter() - t0

        # Decode optimal parameters
        w_logit = res.x[:_N_SOURCES]
        w_exp   = np.exp(w_logit - w_logit.max())
        opt_w   = w_exp / w_exp.sum()

        if not fix_scalars:
            opt_sk = float(np.exp(np.clip(res.x[_N_SOURCES],   math.log(0.5), math.log(6.0))))
            opt_mk = float(np.exp(np.clip(res.x[_N_SOURCES+1], math.log(0.5), math.log(8.0))))
        else:
            opt_sk = _SHARPNESS_K
            opt_mk = _MILESTONE_K

        # Reconstruct full 8-key WEIGHTS (fixed keys keep current values)
        fixed_sum   = sum(current_w.get(k, 0.0) for k in FIXED_KEYS)
        train_total = 1.0 - fixed_sum
        opt_weights = {}
        for ki, key in enumerate(TRAINABLE_KEYS):
            opt_weights[key] = float(opt_w[ki]) * train_total
        for key in FIXED_KEYS:
            opt_weights[key] = current_w.get(key, 0.0)

        return OptimResult(
            match_format    = self.match_format,
            gender          = self.gender,
            loss_before     = loss_before,
            loss_after      = float(res.fun),
            current_weights = current_w,
            optimal_weights = opt_weights,
            current_sk      = _SHARPNESS_K,
            optimal_sk      = opt_sk,
            current_mk      = _MILESTONE_K,
            optimal_mk      = opt_mk,
            n_valid         = self._n_valid,
            n_evals         = res.nfev,
            elapsed_s       = elapsed,
            converged       = res.success,
        )

    # ── Training loss (for verification) ──────────────────────────────────────

    def current_valid_loss(self) -> float:
        """Log-loss with current default parameters."""
        current_w = self._current_weights
        trainable_sum = sum(current_w.get(k, 0.0) for k in TRAINABLE_KEYS)
        init_w = np.array([
            max(1e-6, current_w.get(k, 0.125)) / max(trainable_sum, 1.0)
            for k in TRAINABLE_KEYS
        ])
        init_logit = np.log(init_w)
        init_logit -= init_logit.mean()
        x0 = np.concatenate([init_logit, [math.log(_SHARPNESS_K), math.log(_MILESTONE_K)]])
        return self.objective(x0)


# ── Result container ──────────────────────────────────────────────────────────

class OptimResult:

    def __init__(self, match_format, gender, loss_before, loss_after,
                 current_weights, optimal_weights, current_sk, optimal_sk,
                 current_mk, optimal_mk, n_valid, n_evals, elapsed_s, converged):
        self.match_format    = match_format
        self.gender          = gender
        self.loss_before     = loss_before
        self.loss_after      = loss_after
        self.current_weights = current_weights
        self.optimal_weights = optimal_weights
        self.current_sk      = current_sk
        self.optimal_sk      = optimal_sk
        self.current_mk      = current_mk
        self.optimal_mk      = optimal_mk
        self.n_valid         = n_valid
        self.n_evals         = n_evals
        self.elapsed_s       = elapsed_s
        self.converged       = converged

    def report(self) -> str:
        delta = self.loss_after - self.loss_before
        lines = [
            "",
            f"  ══ Parameter Optimization: {self.match_format} ({self.gender}) ══",
            f"  Valid deliveries : {self.n_valid:,}",
            f"  Evaluations      : {self.n_evals:,}",
            f"  Elapsed          : {self.elapsed_s:.1f}s",
            f"  Converged        : {self.converged}",
            f"  Log-loss  before : {self.loss_before:.5f}",
            f"  Log-loss  after  : {self.loss_after:.5f}  (Δ = {delta:+.5f})",
            "",
            f"  {'Parameter':<20}  {'Current':>8}  {'Optimal':>8}  {'Δ':>8}",
            f"  {'─'*52}",
        ]

        all_keys = WEIGHT_KEYS + ['sharpness_k', 'milestone_k']
        for key in all_keys:
            if key == 'sharpness_k':
                cur = self.current_sk
                opt = self.optimal_sk
            elif key == 'milestone_k':
                cur = self.current_mk
                opt = self.optimal_mk
            else:
                cur = self.current_weights.get(key, 0.0)
                opt = self.optimal_weights.get(key, 0.0)
            d = opt - cur
            fixed_note = "  [fixed]" if key in FIXED_KEYS else ""
            lines.append(f"  {key:<20}  {cur:>8.4f}  {opt:>8.4f}  {d:>+8.4f}{fixed_note}")

        if delta < -0.002:
            lines.append("\n  ✓ Meaningful improvement found — consider updating strategy WEIGHTS.")
        elif delta < 0:
            lines.append("\n  ~ Small improvement found (< 0.002 nats). May not be worth the change.")
        else:
            lines.append("\n  ✓ Current parameters already near-optimal.")

        lines.append("")
        text = "\n".join(lines)
        print(text)
        return text

    def as_weights_dict(self) -> Dict[str, float]:
        """Returns the optimal WEIGHTS dict suitable for copy-paste into strategy.py."""
        return {k: round(v, 4) for k, v in self.optimal_weights.items()}


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    import argparse
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

    parser = argparse.ArgumentParser(description="Optimise ball-outcome strategy parameters")
    parser.add_argument('--format',        default='T20',   choices=['T20', 'ODI', 'Test'])
    parser.add_argument('--gender',        default='male',  choices=['male', 'female'])
    parser.add_argument('--train-samples', default=8000,    type=int)
    parser.add_argument('--valid-samples', default=2000,    type=int)
    parser.add_argument('--max-iter',      default=500,     type=int)
    parser.add_argument('--fix-scalars',   action='store_true',
                        help="Only train WEIGHTS; keep sharpness_k and milestone_k fixed")
    parser.add_argument('--dry-run',       action='store_true',
                        help="Load data and print current loss only, no optimization")
    args = parser.parse_args()

    repo = StatsRepository()
    opt  = ParameterOptimizer(args.format, args.gender, repo)
    opt.load_data(args.train_samples, args.valid_samples)

    if args.dry_run:
        loss = opt.current_valid_loss()
        print(f"\n[Optimizer] Current log-loss on {opt._n_valid:,} valid deliveries: {loss:.5f}")
        return

    result = opt.optimize(fix_scalars=args.fix_scalars, max_iter=args.max_iter)
    result.report()

    print("  Optimal WEIGHTS dict (copy into strategy subclass):")
    print("  " + repr(result.as_weights_dict()))


if __name__ == '__main__':
    _cli()
