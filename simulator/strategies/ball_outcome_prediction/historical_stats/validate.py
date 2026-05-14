"""
Model Validator
===============
Backtests a ball-outcome strategy against held-out historical deliveries.

Usage (command-line):
    python -m simulator.strategies.ball_outcome_prediction.historical_stats.validate

Usage (programmatic):
    from db.stats_repository import StatsRepository
    from simulator.strategies.ball_outcome_prediction.enhanced_historical_stats import (
        T20EnhancedHistoricalStatsStrategy,
    )
    from simulator.strategies.ball_outcome_prediction.historical_stats.validate import ModelValidator

    validator = ModelValidator(StatsRepository())
    result = validator.validate(T20EnhancedHistoricalStatsStrategy(), match_format='T20')
    result.report()

How it works
------------
1. A random sample of historical deliveries is fetched from the DB with full
   context: batter_id, bowler_id, venue_id, inning_number, over_number,
   tournament_id, actual outcome, and batter_score_before (computed via window
   function in SQL).
2. All unique players and venues in the sample are used to pre-load the strategy's
   caches — the same way init_model() would for a live match.
3. For each delivery, _compute_distribution() is called to get the predicted
   probability distribution WITHOUT sampling or pressure modifiers (which require
   live match state that is unavailable in historical context).
4. The actual outcome is looked up in that distribution and several metrics are
   accumulated.

Metrics
-------
log_loss            Primary metric. -mean(log(p(actual))). Lower = better.
                    Baseline (uniform over all keys) is also reported for reference.
boundary_rate_err   |mean predicted boundary prob − actual boundary rate|.
wicket_rate_err     |mean predicted wicket prob − actual wicket rate|.
dot_rate_err        |mean predicted dot prob − actual dot rate|.
extra_rate_err      |mean predicted extra prob − actual extra rate|.
economy_err         |predicted mean runs/ball − actual mean runs/ball|.
"""

import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from db.stats_repository import StatsRepository
from simulator.strategies.ball_outcome_prediction.enhanced_historical_stats import (
    EnhancedBaseHistoricalStatsStrategy,
)


@dataclass
class ValidationResult:
    match_format:     str
    gender:           str
    sample_size:      int
    scored_count:     int   # deliveries where predicted prob > 0
    log_loss:         float
    baseline_log_loss: float
    boundary_rate_err: float
    wicket_rate_err:  float
    dot_rate_err:     float
    extra_rate_err:   float
    economy_err:      float
    elapsed_s:        float
    per_category: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def report(self) -> str:
        lift = self.baseline_log_loss - self.log_loss
        lines = [
            "",
            f"  ══ Validation: {self.match_format} ({self.gender}) ══",
            f"  Deliveries scored : {self.scored_count:,} / {self.sample_size:,}",
            f"  Log-loss          : {self.log_loss:.4f}   (baseline {self.baseline_log_loss:.4f}, lift {lift:+.4f})",
            f"  Boundary rate err : {self.boundary_rate_err:.4f}",
            f"  Wicket rate err   : {self.wicket_rate_err:.4f}",
            f"  Dot rate err      : {self.dot_rate_err:.4f}",
            f"  Extra rate err    : {self.extra_rate_err:.4f}",
            f"  Economy err       : {self.economy_err:.4f} runs/ball",
            f"  Elapsed           : {self.elapsed_s:.1f}s",
        ]
        if self.per_category:
            lines.append("  Per-category log-loss:")
            for cat, metrics in sorted(self.per_category.items()):
                lines.append(f"    {cat:<12} loss={metrics['log_loss']:.4f}  n={metrics['count']:,}")
        lines.append("")
        text = "\n".join(lines)
        print(text)
        return text


class ModelValidator:
    """
    Validates an EnhancedBaseHistoricalStatsStrategy by comparing its predicted
    probability distributions against actual historical delivery outcomes.
    """

    def __init__(self, repo: Optional[StatsRepository] = None):
        self.repo = repo or StatsRepository()

    def validate(
        self,
        strategy: EnhancedBaseHistoricalStatsStrategy,
        match_format: str = 'T20',
        gender: str = 'male',
        sample_size: int = 5000,
    ) -> ValidationResult:
        t_start = time.perf_counter()

        rows = self.repo.get_validation_deliveries(match_format, gender, sample_size)
        if not rows:
            raise RuntimeError(f"No validation data found for {match_format}/{gender}.")

        self._init_strategy_caches(strategy, rows, match_format, gender)

        baseline_keys  = list(strategy.baseline_outcome_probs.keys())
        n_keys         = len(baseline_keys)
        uniform_log_loss = math.log(n_keys)  # worst-case reference

        total_log_loss   = 0.0
        scored           = 0
        skipped          = 0

        # Rate accumulators: predicted vs actual
        pred_boundary = pred_wicket = pred_dot = pred_extra = 0.0
        act_boundary  = act_wicket  = act_dot  = act_extra  = 0
        pred_runs_per_ball = act_runs_per_ball = 0.0

        per_cat_loss  = defaultdict(lambda: {'total': 0.0, 'count': 0})

        for row in rows:
            (batter_id, bowler_id, venue_id, inning, over_number,
             tournament_id, r_bat, r_ext, o_type, o_kind, batter_score) = row

            actual_key = (r_bat, r_ext, o_type, o_kind)
            if actual_key not in strategy.baseline_outcome_probs:
                skipped += 1
                continue

            venue_probs = strategy.venue_cache      if strategy.venue_cache      else strategy.baseline_outcome_probs
            tourn_probs = strategy.tournament_cache if strategy.tournament_cache else strategy.baseline_outcome_probs

            dist = strategy._compute_distribution(
                batter_id     = batter_id,
                bowler_id     = bowler_id,
                inning        = inning,
                over_1indexed = over_number,
                batter_runs   = int(batter_score or 0),
                venue_probs   = venue_probs,
                tourn_probs   = tourn_probs,
            )

            pred_p = dist.get(actual_key, 1e-10)
            total_log_loss -= math.log(max(pred_p, 1e-10))
            scored += 1

            # Per-category log-loss
            cat = self._categorise(actual_key)
            per_cat_loss[cat]['total'] += -math.log(max(pred_p, 1e-10))
            per_cat_loss[cat]['count'] += 1

            # Rate predictions (mean predicted prob across sample)
            for k, p in dist.items():
                rb, _, ot, _ = k
                if rb >= 4:       pred_boundary += p
                if ot == 'Wicket': pred_wicket  += p
                if ot == 'Dot':    pred_dot      += p
                if ot == 'Extras': pred_extra    += p
                pred_runs_per_ball += p * (rb + (1 if ot == 'Extras' else 0))

            # Actual rates
            if r_bat >= 4:        act_boundary += 1
            if o_type == 'Wicket': act_wicket  += 1
            if o_type == 'Dot':    act_dot      += 1
            if o_type == 'Extras': act_extra    += 1
            act_runs_per_ball += r_bat + r_ext

        if scored == 0:
            raise RuntimeError("No deliveries could be scored — check baseline key coverage.")

        log_loss    = total_log_loss / scored
        norm        = 1.0 / scored

        per_category = {
            cat: {
                'log_loss': v['total'] / max(1, v['count']),
                'count':    v['count'],
            }
            for cat, v in per_cat_loss.items()
        }

        return ValidationResult(
            match_format      = match_format,
            gender            = gender,
            sample_size       = sample_size,
            scored_count      = scored,
            log_loss          = log_loss,
            baseline_log_loss = uniform_log_loss,
            boundary_rate_err = abs(pred_boundary * norm - act_boundary * norm),
            wicket_rate_err   = abs(pred_wicket   * norm - act_wicket   * norm),
            dot_rate_err      = abs(pred_dot       * norm - act_dot       * norm),
            extra_rate_err    = abs(pred_extra     * norm - act_extra     * norm),
            economy_err       = abs(pred_runs_per_ball * norm - act_runs_per_ball * norm),
            elapsed_s         = time.perf_counter() - t_start,
            per_category      = per_category,
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _init_strategy_caches(
        self,
        strategy: EnhancedBaseHistoricalStatsStrategy,
        rows: List[tuple],
        match_format: str,
        gender: str,
    ):
        """
        Pre-loads the strategy's player/phase/milestone caches using all unique
        players and contexts that appear in the validation sample.  Venue and
        tournament caches are left empty — validation uses baseline fallback for
        those to avoid over-fitting to a single match's context.
        """
        from simulator.entities.rules import MatchRules
        unified = MatchRules.get_unified_format(match_format)
        strategy._match_format = unified

        batter_ids  = list({r[0] for r in rows if r[0]})
        bowler_ids  = list({r[1] for r in rows if r[1]})

        def _timed(label, fn, *args, **kwargs):
            t = time.perf_counter()
            result = fn(*args, **kwargs)
            print(f"  [Validator] {label:<42} {time.perf_counter()-t:.2f}s")
            return result

        batters_data  = _timed("batters_with_counts",  self.repo.get_batters_distribution_with_counts,  batter_ids, unified, gender)
        bowlers_data  = _timed("bowlers_with_counts",  self.repo.get_bowlers_distribution_with_counts,  bowler_ids, unified, gender)
        matchups_data = _timed("matchups_with_counts", self.repo.get_matchup_distribution_with_counts,  batter_ids, bowler_ids, unified, gender)

        strategy.batter_cache       = {pid: d[0] for pid, d in batters_data.items()}
        strategy.batter_ball_counts = {pid: d[1] for pid, d in batters_data.items()}
        strategy.bowler_cache       = {pid: d[0] for pid, d in bowlers_data.items()}
        strategy.bowler_ball_counts = {pid: d[1] for pid, d in bowlers_data.items()}
        strategy.matchup_cache      = {pair: d[0] for pair, d in matchups_data.items()}
        strategy.matchup_ball_counts = {pair: d[1] for pair, d in matchups_data.items()}

        strategy.phase_cache     = _timed("phase_distribution",    self.repo.get_phase_distribution,            unified, gender)
        strategy.milestone_cache = _timed("milestone_distribution", self.repo.get_batter_milestone_distribution, unified, gender)
        strategy.innings_cache   = _timed("innings_distribution",  self.repo.get_innings_distribution,          unified, gender)

        # Venue and tournament left empty — baseline fallback used during validation
        strategy.venue_cache      = {}
        strategy.tournament_cache = {}

        strategy.baseline_outcome_probs = _timed("full_aggregate_baseline", self.repo.get_full_aggregate_distribution, unified, gender)
        if not strategy.baseline_outcome_probs:
            from simulator.strategies.ball_outcome_prediction.common.utils import BASELINE_FALLBACK
            strategy.baseline_outcome_probs = BASELINE_FALLBACK

        from simulator.strategies.ball_outcome_prediction.enhanced_historical_stats.strategy import _compute_distinctiveness
        strategy.batter_distinctiveness  = {
            pid: _compute_distinctiveness(dist, strategy.baseline_outcome_probs)
            for pid, dist in strategy.batter_cache.items() if dist
        }
        strategy.bowler_distinctiveness  = {
            pid: _compute_distinctiveness(dist, strategy.baseline_outcome_probs)
            for pid, dist in strategy.bowler_cache.items() if dist
        }
        strategy.matchup_distinctiveness = {
            pair: _compute_distinctiveness(dist, strategy.baseline_outcome_probs)
            for pair, dist in strategy.matchup_cache.items() if dist
        }

        print(f"  [Validator] Caches loaded: {len(strategy.batter_cache)} batters, "
              f"{len(strategy.bowler_cache)} bowlers, {len(strategy.matchup_cache)} matchups, "
              f"{len(strategy.phase_cache)} phases, {len(strategy.milestone_cache)} milestones")

    @staticmethod
    def _categorise(outcome_key: tuple) -> str:
        runs_batter, _, outcome_type, _ = outcome_key
        if outcome_type == 'Wicket': return 'wicket'
        if outcome_type == 'Extras': return 'extra'
        if runs_batter >= 4:         return 'boundary'
        if runs_batter == 0:         return 'dot'
        return 'rotation'


# ── CLI entry point ────────────────────────────────────────────────────────────

def _cli():
    import argparse
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', '..')))

    parser = argparse.ArgumentParser(description="Validate the enhanced ball-outcome strategy against historical data")
    parser.add_argument('--format',  default='T20',   choices=['T20', 'ODI', 'Test'])
    parser.add_argument('--gender',  default='male',  choices=['male', 'female'])
    parser.add_argument('--samples', default=5000,    type=int)
    args = parser.parse_args()

    from simulator.strategies.ball_outcome_prediction.enhanced_historical_stats import (
        T20EnhancedHistoricalStatsStrategy,
        ODIEnhancedHistoricalStatsStrategy,
        TestEnhancedHistoricalStatsStrategy,
    )

    strategy_map = {
        'T20':  T20EnhancedHistoricalStatsStrategy,
        'ODI':  ODIEnhancedHistoricalStatsStrategy,
        'Test': TestEnhancedHistoricalStatsStrategy,
    }

    repo      = StatsRepository()
    strategy  = strategy_map[args.format]()
    validator = ModelValidator(repo)

    print(f"\nValidating {args.format} ({args.gender}) — {args.samples:,} deliveries …\n")
    result = validator.validate(strategy, args.format, args.gender, args.samples)
    result.report()


if __name__ == '__main__':
    _cli()
