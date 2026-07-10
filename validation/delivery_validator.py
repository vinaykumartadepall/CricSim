"""
Comprehensive Model Validator
==============================
Backtest of ball-outcome prediction strategies against held-out historical
deliveries.  Supports multiple model types (enhanced and basic historical),
tests every calibrated mechanism individually, and validates at the
individual-player level - not just global averages.

Usage:
    # Enhanced strategy (default)
    python -m validation.delivery_validator \\
        --format Test --gender male --samples 5000

    # Basic historical strategy (for comparison)
    python -m ... --model basic

    # Save regression baseline after deliberate model changes
    python -m ... --save-baseline

    # Venue context test (with vs without venue caches)
    python -m ... --venue "Lord's, London"

What is tested
--------------
Global accuracy
  log-loss, boundary/wicket/dot/extra rate error, economy error.

Stratified breakdowns (all computed in a single pass)
  by_phase              fine-grained phase per format
  by_innings            innings 1-4
  by_batter_state       new/settling/set/dominant (confidence arc)
  by_bowler_type        genuine vs part-timer (suppression check)
  by_milestone          tension bands: fresh/building/tension_50/post_50/tension_100/century
  by_matchup_richness   no_data / thin / reliable
  by_player_richness    low / medium / high (combined batter+bowler ball count)
  by_pressure_proxy     inning×phase scenario proxy

Per-player accuracy  ← KEY: this is what actually matters
  For every batter/bowler in the sample, compare the model's predicted
  aggregate rates against their actual outcomes AND against the naive
  baseline (just using the raw player cache with no context blending).
  Reports: MAE distribution, decile analysis by data richness, worst-
  predicted players, and whether context blending helps over naive.

Calibration
  5-bin predicted-probability bins vs actual frequency per category.

Direction assertions
  8 expected-direction checks (✓/✗) for every tuned mechanism.

Regression detection
  JSON baseline comparison; metrics degrading beyond threshold are flagged.

Venue context lift  (--venue)
  Same deliveries run twice - empty caches vs loaded venue+player_venue -
  to measure how much venue context improves predictions.

Note on pressure modifier
  _apply_pressure_modifier runs AFTER _compute_distribution in
  predict_next_ball.  It is NOT tested by this validator (which only tests
  the distribution step).  Use validate_simulation.py for end-to-end
  pressure testing.
"""

import json
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from db.stats_repository import StatsRepository
from simulator.entities.rules import MatchRules
from simulator.predictors.ball_outcome_prediction.strategy_interface import BallOutcomeStrategy

# ── Regression thresholds ──────────────────────────────────────────────────────
# Thresholds are per-format because sampling noise scales with event frequency.
# T20 has ~5.5% wicket rate → σ≈0.003 at n=5000, so threshold must be ≥2σ=0.006.
# Test has ~1.7% wicket rate → σ≈0.002 at n=5000, so 0.003 is fine there.
_REGRESSION_THRESHOLDS: Dict[str, Dict[str, float]] = {
    'Test': {
        'log_loss':          0.015,
        'boundary_rate_err': 0.007,
        'wicket_rate_err':   0.003,
        'dot_rate_err':      0.020,   # Test dot rate ~70%; σ≈0.007 → 2σ gap between runs
        'extra_rate_err':    0.007,
        'economy_err':       0.300,   # high variance - phase-composition shifts with sampling
    },
    'ODI': {
        'log_loss':          0.015,
        'boundary_rate_err': 0.007,
        'wicket_rate_err':   0.005,
        'dot_rate_err':      0.020,
        'extra_rate_err':    0.007,
        'economy_err':       0.350,
    },
    'T20': {
        'log_loss':          0.050,
        'boundary_rate_err': 0.010,
        'wicket_rate_err':   0.007,
        'dot_rate_err':      0.020,
        'extra_rate_err':    0.008,
        'economy_err':       0.400,
    },
}

_BASELINE_FILE  = os.path.join(os.path.dirname(__file__), 'baseline.json')
_MIN_PLAYER_N   = 20   # minimum deliveries per player for per-player analysis
_N_WORST        = 10   # top-N worst-predicted players to show
_N_CAL_BINS     = 5
_N_DECILES      = 5    # data-richness deciles for player analysis

_BATTER_STATES = [
    ('new',       0,   5),
    ('settling',  6,  20),
    ('set',      21,  49),
    ('dominant', 50, 999),
]


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class BucketMetrics:
    n:             int
    log_loss:      float
    pred_boundary: float;  act_boundary: float
    pred_wicket:   float;  act_wicket:   float
    pred_dot:      float;  act_dot:      float
    pred_economy:  float;  act_economy:  float


@dataclass
class CalibrationBin:
    pred_sum:  float = 0.0
    act_count: int   = 0
    n:         int   = 0

    @property
    def pred_rate(self) -> float: return self.pred_sum / self.n if self.n else 0.0
    @property
    def act_rate(self)  -> float: return self.act_count / self.n if self.n else 0.0
    @property
    def gap(self)       -> float: return self.act_rate - self.pred_rate


@dataclass
class PlayerMetrics:
    player_id:       int
    n:               int
    log_loss:        float
    pred_boundary:   float;  act_boundary:  float
    pred_wicket:     float;  act_wicket:    float
    pred_economy:    float;  act_economy:   float
    cache_boundary:  float   # raw cache rate (naive baseline, no context blending)
    cache_wicket:    float
    balls_in_cache:  int

    @property
    def boundary_mae(self) -> float: return abs(self.pred_boundary - self.act_boundary)
    @property
    def wicket_mae(self)   -> float: return abs(self.pred_wicket   - self.act_wicket)
    @property
    def naive_boundary_mae(self) -> float:
        return abs(self.cache_boundary - self.act_boundary) if self.cache_boundary >= 0 else float('nan')


@dataclass
class PlayerSummary:
    role:              str     # 'batter' or 'bowler'
    n_players:         int     # players with >= _MIN_PLAYER_N deliveries
    min_deliveries:    int

    mean_loss:         float
    mean_boundary_mae: float   # MAE of boundary rate prediction, averaged across players
    mean_wicket_mae:   float
    mean_economy_mae:  float

    # Context blending vs naive cache comparison
    mean_naive_boundary_mae: float   # MAE using raw cache rate (no blending)
    blending_helps_boundary: bool    # mean_boundary_mae < mean_naive_boundary_mae

    # Correlation: log(balls_in_cache) vs log_loss  (negative = more data → lower loss)
    corr_balls_loss:   float

    # Worst-predicted players (by boundary MAE)
    worst_boundary:    List[PlayerMetrics]
    worst_wicket:      List[PlayerMetrics]

    # Data-richness decile analysis
    by_decile:         List[Dict]   # [{decile, n_players, mean_loss, mean_boundary_mae}]


@dataclass
class VenueContextLift:
    venue_name:      str
    n_deliveries:    int
    loss_no_venue:   float
    loss_with_venue: float

    @property
    def lift(self) -> float: return self.loss_no_venue - self.loss_with_venue


@dataclass
class ValidationResult:
    model_name:        str
    match_format:      str
    gender:            str
    sample_size:       int
    scored_count:      int
    log_loss:          float
    baseline_log_loss: float
    boundary_rate_err: float
    wicket_rate_err:   float
    dot_rate_err:      float
    extra_rate_err:    float
    economy_err:       float
    elapsed_s:         float
    per_category:      Dict[str, Dict] = field(default_factory=dict)

    by_phase:           Dict[str, BucketMetrics] = field(default_factory=dict)
    by_innings:         Dict[int,  BucketMetrics] = field(default_factory=dict)
    by_batter_state:    Dict[str,  BucketMetrics] = field(default_factory=dict)
    by_bowler_type:     Dict[str,  BucketMetrics] = field(default_factory=dict)
    by_milestone:       Dict[str,  BucketMetrics] = field(default_factory=dict)
    by_matchup_richness: Dict[str, BucketMetrics] = field(default_factory=dict)
    by_player_richness: Dict[str,  BucketMetrics] = field(default_factory=dict)
    by_pressure_proxy:  Dict[str,  BucketMetrics] = field(default_factory=dict)

    calibration: Dict[str, List[CalibrationBin]] = field(default_factory=dict)

    batter_summary: Optional[PlayerSummary] = None
    bowler_summary: Optional[PlayerSummary] = None

    assertions:       List[str] = field(default_factory=list)
    regression_flags: List[str] = field(default_factory=list)
    venue_lift:       Optional[VenueContextLift] = None

    # ── Report ────────────────────────────────────────────────────────────────

    def report(self) -> str:
        lift = self.baseline_log_loss - self.log_loss
        lines = [
            "",
            f"  ══ Validation: {self.model_name} / {self.match_format} ({self.gender}) ══",
            f"  Deliveries scored : {self.scored_count:,} / {self.sample_size:,}",
            f"  Log-loss          : {self.log_loss:.4f}   (baseline {self.baseline_log_loss:.4f}, lift {lift:+.4f})",
            f"  Boundary rate err : {self.boundary_rate_err:.4f}",
            f"  Wicket rate err   : {self.wicket_rate_err:.4f}",
            f"  Dot rate err      : {self.dot_rate_err:.4f}",
            f"  Extra rate err    : {self.extra_rate_err:.4f}",
            f"  Economy err       : {self.economy_err:.4f} runs/over",
            f"  Elapsed           : {self.elapsed_s:.1f}s",
        ]

        if self.per_category:
            lines.append("  Per-category log-loss:")
            for cat, m in sorted(self.per_category.items()):
                lines.append(f"    {cat:<12} loss={m['log_loss']:.4f}  n={m['count']:,}")

        def _bucket_table(title, data, order=None, min_n=0):
            if not data:
                return
            lines.append(f"\n  {title}:")
            lines.append(f"    {'Bucket':<20}  {'n':>6}  {'loss':>6}  "
                         f"{'wkt_pred':>8}  {'wkt_act':>7}  {'bnd_pred':>8}  {'bnd_act':>7}  {'eco_pred':>7}  {'eco_act':>7}")
            keys = order if order else sorted(data)
            for k in keys:
                m = data.get(k)
                if not m or (min_n and m.n < min_n):
                    continue
                lines.append(
                    f"    {str(k):<20}  {m.n:>6,}  {m.log_loss:>6.3f}  "
                    f"{m.pred_wicket:>8.3f}  {m.act_wicket:>7.3f}  "
                    f"{m.pred_boundary:>8.3f}  {m.act_boundary:>7.3f}  "
                    f"{m.pred_economy:>7.2f}  {m.act_economy:>7.2f}"
                )

        _bucket_table("By phase", self.by_phase)
        _bucket_table("By innings", self.by_innings, order=[1,2,3,4])
        _bucket_table(
            "By batter state (confidence arc - tests _SHARPNESS_K on batter context)",
            self.by_batter_state,
            order=['new', 'settling', 'set', 'dominant']
        )

        if self.by_bowler_type:
            _bucket_table(
                "By bowler type (tests _PARTTIME_CATEGORY_MULT, _PARTTIME_THRESHOLDS)",
                self.by_bowler_type,
                order=['genuine', 'parttimer']
            )
            gen = self.by_bowler_type.get('genuine')
            pt  = self.by_bowler_type.get('parttimer')
            if gen and pt:
                ok = pt.pred_wicket < gen.pred_wicket
                lines.append(
                    f"    → Suppression: {'✓ SUPPRESSED' if ok else '✗ NOT SUPPRESSED'}  "
                    f"(pt={pt.pred_wicket:.3f} vs gen={gen.pred_wicket:.3f})"
                )

        _bucket_table(
            "By milestone bucket (tests _MILESTONE_K, milestone_cache)",
            self.by_milestone,
            order=['fresh', 'building', 'tension_50', 'post_50', 'tension_100', 'century']
        )
        _bucket_table(
            "By matchup data richness (tests reliability scaling for matchup)",
            self.by_matchup_richness,
            order=['no_data', 'thin', 'reliable']
        )
        _bucket_table(
            "By player data richness (tests _RELIABILITY_THRESHOLDS)",
            self.by_player_richness,
            order=['low', 'medium', 'high']
        )
        _bucket_table(
            "By pressure proxy - base dist only, _apply_pressure_modifier not tested here",
            self.by_pressure_proxy,
            min_n=30
        )

        # ── Per-player analysis ────────────────────────────────────────────────
        for summ in [self.batter_summary, self.bowler_summary]:
            if not summ:
                continue
            role = summ.role.capitalize()
            lines += [
                "",
                f"  {role}-level prediction accuracy ({summ.n_players} {summ.role}s with ≥{summ.min_deliveries} deliveries):",
                f"    Mean log-loss       : {summ.mean_loss:.4f}",
                f"    Boundary MAE        : {summ.mean_boundary_mae:.4f}  (model)"
                f"  vs  {summ.mean_naive_boundary_mae:.4f}  (raw cache, no blending)  "
                f"{'✓ blending helps' if summ.blending_helps_boundary else '✗ blending hurts'}",
                f"    Wicket MAE          : {summ.mean_wicket_mae:.4f}",
                f"    Economy MAE         : {summ.mean_economy_mae:.4f} rpo",
                f"    Corr(balls,loss)    : {summ.corr_balls_loss:+.3f}  "
                f"({'✓ more data → lower loss' if summ.corr_balls_loss < -0.05 else '✗ data richness not helping'})",
            ]

            if summ.by_decile:
                lines.append(f"    Data-richness deciles (balls in cache):")
                lines.append(f"      {'Decile':<12}  {'n':>5}  {'mean_loss':>9}  {'bnd_mae':>7}  {'wkt_mae':>7}")
                for d in summ.by_decile:
                    lines.append(
                        f"      {d['label']:<12}  {d['n']:>5}  {d['mean_loss']:>9.4f}  "
                        f"{d['bnd_mae']:>7.4f}  {d['wkt_mae']:>7.4f}"
                    )

            if summ.worst_boundary:
                lines.append(f"    Worst-predicted {summ.role}s (boundary rate MAE, ≥{summ.min_deliveries} deliveries):")
                lines.append(f"      {'ID':>8}  {'n':>5}  {'pred_bnd':>8}  {'act_bnd':>8}  {'cache_bnd':>9}  {'mae':>6}  {'balls':>7}")
                for pm in summ.worst_boundary[:_N_WORST]:
                    cache_s = f"{pm.cache_boundary:.3f}" if pm.cache_boundary >= 0 else "  n/a"
                    lines.append(
                        f"      {pm.player_id:>8}  {pm.n:>5}  {pm.pred_boundary:>8.3f}  "
                        f"{pm.act_boundary:>8.3f}  {cache_s:>9}  {pm.boundary_mae:>6.3f}  {pm.balls_in_cache:>7,}"
                    )

            if summ.worst_wicket:
                lines.append(f"    Worst-predicted {summ.role}s (wicket rate MAE, ≥{summ.min_deliveries} deliveries):")
                lines.append(f"      {'ID':>8}  {'n':>5}  {'pred_wkt':>8}  {'act_wkt':>8}  {'cache_wkt':>9}  {'mae':>6}  {'balls':>7}")
                for pm in summ.worst_wicket[:_N_WORST]:
                    cache_s = f"{pm.cache_wicket:.3f}" if pm.cache_wicket >= 0 else "  n/a"
                    lines.append(
                        f"      {pm.player_id:>8}  {pm.n:>5}  {pm.pred_wicket:>8.3f}  "
                        f"{pm.act_wicket:>8.3f}  {cache_s:>9}  {pm.wicket_mae:>6.3f}  {pm.balls_in_cache:>7,}"
                    )

        # ── Calibration ───────────────────────────────────────────────────────
        if self.calibration:
            lines += ["", "  Calibration (predicted prob vs actual frequency):"]
            lines.append(f"    {'Cat':<10}  {'Bin':<12}  {'n':>5}  {'pred':>6}  {'actual':>6}  {'gap':>7}")
            for cat in ('boundary', 'wicket', 'dot', 'extra'):
                for i, b in enumerate(self.calibration.get(cat, [])):
                    if b.n < 10:
                        continue
                    lo, hi = i / _N_CAL_BINS, (i + 1) / _N_CAL_BINS
                    gap_marker = " ✗" if abs(b.gap) > 0.05 else ""
                    lines.append(
                        f"    {cat:<10}  [{lo:.1f},{hi:.1f})  {b.n:>5}  "
                        f"{b.pred_rate:>6.3f}  {b.act_rate:>6.3f}  {b.gap:>+7.3f}{gap_marker}"
                    )

        if self.assertions:
            lines += ["", "  Direction assertions:"]
            for a in self.assertions:
                lines.append(f"    {a}")

        if self.venue_lift:
            vl = self.venue_lift
            sign = "+" if vl.lift > 0 else ""
            lines += [
                "", f"  Venue context lift ({vl.venue_name}, n={vl.n_deliveries:,}):",
                f"    No venue  → loss {vl.loss_no_venue:.4f}",
                f"    W/ venue  → loss {vl.loss_with_venue:.4f}  (lift {sign}{vl.lift:.4f})",
                f"    {'✓ venue data helps' if vl.lift > 0 else '✗ venue data hurts or neutral'}",
            ]

        if self.regression_flags:
            lines += ["", "  ⚠  REGRESSIONS DETECTED:"]
            for flag in self.regression_flags:
                lines.append(f"     {flag}")

        lines.append("")
        text = "\n".join(lines)
        print(text)
        return text

    def as_baseline_dict(self) -> dict:
        return {
            'log_loss':          round(self.log_loss,          5),
            'boundary_rate_err': round(self.boundary_rate_err, 5),
            'wicket_rate_err':   round(self.wicket_rate_err,   5),
            'dot_rate_err':      round(self.dot_rate_err,       5),
            'extra_rate_err':    round(self.extra_rate_err,     5),
            'economy_err':       round(self.economy_err,        5),
        }


# ── Accumulators ──────────────────────────────────────────────────────────────

class _Acc:
    """Per-bucket accumulator for stratified breakdowns."""
    __slots__ = ('n', 'll', 'pb', 'ab', 'pw', 'aw', 'pd', 'ad', 'pe', 'ae', 'pr', 'ar')

    def __init__(self):
        self.n = self.ll = 0.0
        self.pb = self.ab = self.pw = self.aw = 0.0
        self.pd = self.ad = self.pe = self.ae = 0.0
        self.pr = self.ar = 0.0

    def push(self, pred_p: float, stats: dict):
        self.n  += 1
        self.ll -= math.log(max(pred_p, 1e-10))
        self.pb += stats['pb']; self.ab += stats['ab']
        self.pw += stats['pw']; self.aw += stats['aw']
        self.pd += stats['pd']; self.ad += stats['ad']
        self.pe += stats['pe']; self.ae += stats['ae']
        self.pr += stats['pr']; self.ar += stats['ar']

    def to_metrics(self) -> Optional[BucketMetrics]:
        if self.n == 0:
            return None
        n = self.n
        return BucketMetrics(
            n             = int(n),
            log_loss      = self.ll / n,
            pred_boundary = self.pb / n,  act_boundary = self.ab / n,
            pred_wicket   = self.pw / n,  act_wicket   = self.aw / n,
            pred_dot      = self.pd / n,  act_dot      = self.ad / n,
            pred_economy  = self.pr / n * 6,  act_economy  = self.ar / n * 6,
        )


class _PlayerAcc:
    """Per-player accumulator for individual prediction quality analysis."""
    __slots__ = ('n', 'll', 'pb', 'ab', 'pw', 'aw', 'pr', 'ar',
                 'cache_boundary', 'cache_wicket', 'balls')

    def __init__(self, cache_boundary: float, cache_wicket: float, balls: int):
        self.n = self.ll = 0.0
        self.pb = self.ab = self.pw = self.aw = 0.0
        self.pr = self.ar = 0.0
        self.cache_boundary = cache_boundary
        self.cache_wicket   = cache_wicket
        self.balls          = balls

    def push(self, pred_p, pb, pw, pr, ab, aw, ar):
        self.n  += 1
        self.ll -= math.log(max(pred_p, 1e-10))
        self.pb += pb; self.ab += ab
        self.pw += pw; self.aw += aw
        self.pr += pr; self.ar += ar

    def to_metrics(self, player_id: int) -> Optional[PlayerMetrics]:
        if self.n < _MIN_PLAYER_N:
            return None
        n = self.n
        return PlayerMetrics(
            player_id      = player_id,
            n              = int(n),
            log_loss       = self.ll / n,
            pred_boundary  = self.pb / n,  act_boundary = self.ab / n,
            pred_wicket    = self.pw / n,  act_wicket   = self.aw / n,
            pred_economy   = self.pr / n * 6,  act_economy  = self.ar / n * 6,
            cache_boundary = self.cache_boundary,
            cache_wicket   = self.cache_wicket,
            balls_in_cache = self.balls,
        )


# ── Classifier helpers ─────────────────────────────────────────────────────────

def _milestone_group(batter_score: int) -> str:
    try:
        from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy import _get_milestone
        m_val = int(_get_milestone(batter_score)[1:])
    except Exception:
        m_val = (batter_score // 10) * 10
    if m_val <= 10:   return 'fresh'
    if m_val <= 30:   return 'building'
    if m_val == 40:   return 'tension_50'
    if m_val <= 80:   return 'post_50'
    if m_val == 90:   return 'tension_100'
    return 'century'


def _matchup_richness(matchup_balls: int, match_format: str) -> str:
    try:
        from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy import _RELIABILITY_THRESHOLDS
        thresh = _RELIABILITY_THRESHOLDS.get(match_format, _RELIABILITY_THRESHOLDS['T20'])['matchup']
    except Exception:
        thresh = 40
    if matchup_balls == 0:          return 'no_data'
    if matchup_balls < thresh // 2: return 'thin'
    return 'reliable'


def _player_richness(batter_balls: int, bowler_balls: int, match_format: str) -> str:
    try:
        from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy import _RELIABILITY_THRESHOLDS
        thresh = _RELIABILITY_THRESHOLDS.get(match_format, _RELIABILITY_THRESHOLDS['T20'])
        b_rel  = min(1.0, batter_balls  / thresh['batter'])
        bw_rel = min(1.0, bowler_balls  / thresh['bowler'])
    except Exception:
        b_rel = bw_rel = 0.5
    combined = (b_rel + bw_rel) / 2.0
    if combined < 0.33: return 'low'
    if combined < 0.67: return 'medium'
    return 'high'


def _pressure_proxy(over_1idx: int, inning: int, match_format: str) -> str:
    if match_format == 'Test':
        if over_1idx <= 10:  return f'inn{inning}_new_ball'
        if over_1idx <= 30:  return f'inn{inning}_early'
        return f'inn{inning}_middle_late'
    phase = MatchRules.get_fine_grained_phase(over_1idx, match_format)
    if phase in ('death1', 'death2'): return f'inn{inning}_death'
    if phase in ('pp1', 'pp2'):       return f'inn{inning}_pp'
    return f'inn{inning}_mid'


# ── Player summary builder ─────────────────────────────────────────────────────

def _build_player_summary(
    accs: Dict[int, _PlayerAcc],
    role: str,
) -> Optional[PlayerSummary]:
    metrics = [
        acc.to_metrics(pid)
        for pid, acc in accs.items()
        if acc.to_metrics(pid) is not None
    ]
    if not metrics:
        return None

    n = len(metrics)
    mean_loss         = sum(m.log_loss        for m in metrics) / n
    mean_bnd_mae      = sum(m.boundary_mae    for m in metrics) / n
    mean_wkt_mae      = sum(m.wicket_mae      for m in metrics) / n
    mean_eco_mae      = sum(abs(m.pred_economy - m.act_economy) for m in metrics) / n
    mean_naive_bnd_mae = sum(m.naive_boundary_mae for m in metrics
                             if not math.isnan(m.naive_boundary_mae)) / max(1, sum(
                             1 for m in metrics if not math.isnan(m.naive_boundary_mae)))

    blending_helps = (mean_bnd_mae < mean_naive_bnd_mae)

    # Pearson correlation: log(balls+1) vs log_loss
    log_balls = [math.log(m.balls_in_cache + 1) for m in metrics]
    losses    = [m.log_loss for m in metrics]
    mean_lb   = sum(log_balls) / n
    mean_l    = mean_loss
    cov  = sum((lb - mean_lb) * (l - mean_l) for lb, l in zip(log_balls, losses)) / n
    std_lb = math.sqrt(sum((lb - mean_lb)**2 for lb in log_balls) / n)
    std_l  = math.sqrt(sum((l - mean_l)**2   for l  in losses)    / n)
    corr   = cov / (std_lb * std_l) if std_lb > 0 and std_l > 0 else 0.0

    worst_boundary = sorted(metrics, key=lambda m: m.boundary_mae, reverse=True)[:_N_WORST]
    worst_wicket   = sorted(metrics, key=lambda m: m.wicket_mae,   reverse=True)[:_N_WORST]

    # Data-richness decile analysis (by balls_in_cache)
    sorted_by_balls = sorted(metrics, key=lambda m: m.balls_in_cache)
    decile_size = max(1, len(sorted_by_balls) // _N_DECILES)
    by_decile = []
    for di in range(_N_DECILES):
        lo = di * decile_size
        hi = lo + decile_size if di < _N_DECILES - 1 else len(sorted_by_balls)
        group = sorted_by_balls[lo:hi]
        if not group:
            continue
        lo_b = group[0].balls_in_cache
        hi_b = group[-1].balls_in_cache
        by_decile.append({
            'label':        f"{lo_b}-{hi_b}",
            'n':            len(group),
            'mean_loss':    sum(m.log_loss     for m in group) / len(group),
            'bnd_mae':      sum(m.boundary_mae for m in group) / len(group),
            'wkt_mae':      sum(m.wicket_mae   for m in group) / len(group),
        })

    return PlayerSummary(
        role              = role,
        n_players         = n,
        min_deliveries    = _MIN_PLAYER_N,
        mean_loss         = mean_loss,
        mean_boundary_mae = mean_bnd_mae,
        mean_wicket_mae   = mean_wkt_mae,
        mean_economy_mae  = mean_eco_mae,
        mean_naive_boundary_mae = mean_naive_bnd_mae,
        blending_helps_boundary = blending_helps,
        corr_balls_loss   = corr,
        worst_boundary    = worst_boundary,
        worst_wicket      = worst_wicket,
        by_decile         = by_decile,
    )


# ── Direction assertions ───────────────────────────────────────────────────────

def _build_assertions(result: ValidationResult) -> List[str]:
    out = []

    gen = result.by_bowler_type.get('genuine')
    pt  = result.by_bowler_type.get('parttimer')
    if gen and pt and gen.n >= 50 and pt.n >= 5:
        ok = pt.pred_wicket < gen.pred_wicket
        out.append(f"{'✓' if ok else '✗'} Part-timer wicket suppression  (pt={pt.pred_wicket:.3f} < gen={gen.pred_wicket:.3f})")

    t50 = result.by_milestone.get('tension_50')
    bld = result.by_milestone.get('building')
    if t50 and bld and t50.n >= 30 and bld.n >= 100:
        delta = abs(t50.pred_wicket - bld.pred_wicket)
        out.append(f"{'✓' if delta > 0.001 else '✗'} Milestone tension_50 shifts wkt_pred vs building  (|{t50.pred_wicket:.3f}-{bld.pred_wicket:.3f}|={delta:.4f})")

    t100 = result.by_milestone.get('tension_100')
    if t100 and bld and t100.n >= 10 and bld.n >= 100:
        delta = abs(t100.pred_wicket - bld.pred_wicket)
        out.append(f"{'✓' if delta > 0.001 else '✗'} Milestone tension_100 shifts wkt_pred vs building  (|{t100.pred_wicket:.3f}-{bld.pred_wicket:.3f}|={delta:.4f})")

    rel = result.by_matchup_richness.get('reliable')
    no  = result.by_matchup_richness.get('no_data')
    if rel and no and rel.n >= 100 and no.n >= 100:
        ok = rel.log_loss < no.log_loss
        out.append(f"{'✓' if ok else '✗'} Matchup data improves accuracy  (reliable={rel.log_loss:.3f} vs no_data={no.log_loss:.3f})")

    hi = result.by_player_richness.get('high')
    lo = result.by_player_richness.get('low')
    if hi and lo and hi.n >= 100 and lo.n >= 100:
        ok = hi.log_loss < lo.log_loss
        out.append(f"{'✓' if ok else '✗'} Richer player data improves accuracy  (high={hi.log_loss:.3f} vs low={lo.log_loss:.3f})")

    new_m = result.by_batter_state.get('new')
    dom_m = result.by_batter_state.get('dominant')
    if new_m and dom_m and new_m.n >= 100 and dom_m.n >= 100:
        ok_bnd = dom_m.pred_boundary > new_m.pred_boundary
        out.append(f"{'✓' if ok_bnd else '✗'} Confidence arc: dominant batters have higher pred_bnd  (dom={dom_m.pred_boundary:.3f} > new={new_m.pred_boundary:.3f})")
        if result.match_format == 'Test':
            # In Test, new batters are genuinely vulnerable - higher wicket probability
            ok_wkt = new_m.pred_wicket > dom_m.pred_wicket
            out.append(f"{'✓' if ok_wkt else '✗'} Confidence arc [Test]: new batters have higher pred_wkt  (new={new_m.pred_wicket:.3f} > dom={dom_m.pred_wicket:.3f})")
        else:
            # In T20/ODI, dominant batters take more risks and have higher wicket probability
            ok_wkt = dom_m.pred_wicket > new_m.pred_wicket
            out.append(f"{'✓' if ok_wkt else '✗'} Confidence arc [{result.match_format}]: dominant batters have higher pred_wkt (aggressive)  (dom={dom_m.pred_wicket:.3f} > new={new_m.pred_wicket:.3f})")

    if result.match_format in ('T20', 'ODI'):
        d2 = result.by_pressure_proxy.get('inn2_death')
        p2 = result.by_pressure_proxy.get('inn2_pp')
        if d2 and p2 and d2.n >= 30 and p2.n >= 30:
            # Check that death overs have higher economy than PP (always true - more aggressive play)
            ok_eco_act  = d2.act_economy  > p2.act_economy
            ok_eco_pred = d2.pred_economy > p2.pred_economy
            out.append(f"{'✓' if ok_eco_act  else '✗'} Chase: death overs have higher actual economy than PP  (death={d2.act_economy:.2f} vs pp={p2.act_economy:.2f})")
            out.append(f"{'✓' if ok_eco_pred else '✗'} Chase: model predicts higher economy in death vs PP  (pred: death={d2.pred_economy:.2f} vs pp={p2.pred_economy:.2f})")

    if result.batter_summary:
        bs = result.batter_summary
        out.append(f"{'✓' if bs.blending_helps_boundary else '✗'} Context blending improves over naive cache for batter boundary rate  (model={bs.mean_boundary_mae:.4f} vs naive={bs.mean_naive_boundary_mae:.4f})")
        out.append(f"{'✓' if bs.corr_balls_loss < -0.05 else '✗'} More batter data → lower loss  (corr={bs.corr_balls_loss:+.3f})")

    out.append(f"{'✓' if result.wicket_rate_err < 0.010 else '✗'} Wicket rate calibration within 1%  (err={result.wicket_rate_err:.4f})")

    return out


# ── Multi-model distribution computation ──────────────────────────────────────

def _get_distribution(
    strategy: BallOutcomeStrategy,
    batter_id: Optional[int],
    bowler_id: Optional[int],
    inning: int,
    over_1idx: int,
    batter_score: int,
    venue_probs: dict,
    tourn_probs: dict,
) -> dict:
    """
    Dispatches to the correct distribution computation for the strategy type.
    Enhanced strategy: calls _compute_distribution directly.
    Basic strategy:    reconstructs distribution from its simpler caches.
    """
    from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy import (
        EnhancedBaseHistoricalStatsStrategy,
    )
    if isinstance(strategy, EnhancedBaseHistoricalStatsStrategy):
        return strategy._compute_distribution(
            batter_id     = batter_id,
            bowler_id     = bowler_id,
            inning        = inning,
            over_1indexed = over_1idx,
            batter_runs   = batter_score,
            venue_probs   = venue_probs,
            tourn_probs   = tourn_probs,
        )
    else:
        return _compute_basic_distribution(strategy, batter_id, bowler_id, inning, over_1idx)


def _compute_basic_distribution(
    strategy: BallOutcomeStrategy,
    batter_id: Optional[int],
    bowler_id: Optional[int],
    inning: int,
    over_1idx: int,
) -> dict:
    """Reconstructs the distribution from the basic historical strategy's caches."""
    from simulator.predictors.ball_outcome_prediction.historical_stats.strategy import (
        compute_context_multiplier,
    )
    baseline = strategy.baseline_outcome_probs
    bp       = strategy.batter_cache.get(batter_id, baseline)  if batter_id  else baseline
    bwp      = strategy.bowler_cache.get(bowler_id, baseline)  if bowler_id  else baseline
    vp       = strategy.venue_cache      or baseline
    tp       = strategy.tournament_cache or baseline
    ip       = strategy.innings_cache.get(inning, baseline)
    op       = strategy.overs_cache.get(over_1idx, baseline)
    w        = strategy.WEIGHTS

    raw = {}
    for key in baseline:
        base_p = baseline.get(key, 1e-6)
        raw[key] = (
            base_p
            * compute_context_multiplier(bp.get(key,  base_p), base_p, w.get('batter',  0))
            * compute_context_multiplier(bwp.get(key, base_p), base_p, w.get('bowler',  0))
            * compute_context_multiplier(vp.get(key,  base_p), base_p, w.get('venue',   0))
            * compute_context_multiplier(tp.get(key,  base_p), base_p, w.get('tournament', 0))
            * compute_context_multiplier(ip.get(key,  base_p), base_p, w.get('innings', 0))
            * compute_context_multiplier(op.get(key,  base_p), base_p, w.get('over',    0))
        )
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()} if total > 0 else dict(baseline)


def _cache_rates(dist: Optional[dict]) -> Tuple[float, float]:
    """Returns (boundary_rate, wicket_rate) from a raw distribution dict."""
    if not dist:
        return -1.0, -1.0
    b_rate = sum(p for (rb, _, _, _), p in dist.items() if rb >= 4)
    w_rate = sum(p for (_, _, ot, _), p in dist.items() if ot == 'Wicket')
    return b_rate, w_rate


# ── Main validator ────────────────────────────────────────────────────────────

class ModelValidator:

    def __init__(self, repo: Optional[StatsRepository] = None):
        self.repo = repo or StatsRepository()

    def validate(
        self,
        strategy: BallOutcomeStrategy,
        match_format: str = 'T20',
        gender: str = 'male',
        sample_size: int = 5000,
        model_name: Optional[str] = None,
    ) -> ValidationResult:
        t_start = time.perf_counter()

        rows = self.repo.get_validation_deliveries(match_format, gender, sample_size)
        if not rows:
            raise RuntimeError(f"No validation data for {match_format}/{gender}.")

        self._init_strategy_caches(strategy, rows, match_format, gender)

        if model_name is None:
            model_name = type(strategy).__name__

        n_keys           = len(strategy.baseline_outcome_probs)
        uniform_log_loss = math.log(n_keys)

        # ── Accumulators ──────────────────────────────────────────────────────
        global_acc     = _Acc()
        phase_accs     : Dict[str, _Acc] = defaultdict(_Acc)
        inn_accs       : Dict[int,  _Acc] = defaultdict(_Acc)
        state_accs     : Dict[str,  _Acc] = defaultdict(_Acc)
        btype_accs     : Dict[str,  _Acc] = defaultdict(_Acc)
        milestone_accs : Dict[str,  _Acc] = defaultdict(_Acc)
        matchup_accs   : Dict[str,  _Acc] = defaultdict(_Acc)
        richness_accs  : Dict[str,  _Acc] = defaultdict(_Acc)
        pressure_accs  : Dict[str,  _Acc] = defaultdict(_Acc)

        batter_accs : Dict[int, _PlayerAcc] = {}
        bowler_accs : Dict[int, _PlayerAcc] = {}

        cal: Dict[str, List[CalibrationBin]] = {
            cat: [CalibrationBin() for _ in range(_N_CAL_BINS)]
            for cat in ('boundary', 'wicket', 'dot', 'extra')
        }
        per_cat_loss: Dict[str, Dict] = defaultdict(lambda: {'total': 0.0, 'count': 0})
        skipped = 0

        for row in rows:
            (batter_id, bowler_id, venue_id, inning, over_1idx,
             _tourn_id, r_bat, r_ext, o_type, o_kind, batter_score,
             team_score, team_wickets) = row

            actual_key = (r_bat, r_ext, o_type, o_kind)
            if actual_key not in strategy.baseline_outcome_probs:
                skipped += 1
                continue

            venue_probs = strategy.venue_cache      or strategy.baseline_outcome_probs
            tourn_probs = strategy.tournament_cache or strategy.baseline_outcome_probs

            dist = _get_distribution(
                strategy, batter_id, bowler_id, inning, over_1idx,
                int(batter_score or 0), venue_probs, tourn_probs,
            )

            pred_p     = dist.get(actual_key, 1e-10)
            actual_cat = _categorise(actual_key)

            per_cat_loss[actual_cat]['total'] += -math.log(max(pred_p, 1e-10))
            per_cat_loss[actual_cat]['count'] += 1

            # ── Single distribution pass for all rate accumulators ──
            p_boundary = p_wicket = p_dot = p_extra = p_runs = 0.0
            for k, p in dist.items():
                kb, kx, kot, _ = k
                if kb >= 4:          p_boundary += p
                if kot == 'Wicket':  p_wicket   += p
                if kot == 'Dot':     p_dot       += p
                if kot == 'Extras':  p_extra     += p
                p_runs += p * (kb + kx)

            a_boundary = 1 if r_bat >= 4       else 0
            a_wicket   = 1 if o_type == 'Wicket' else 0
            a_dot      = 1 if o_type == 'Dot'    else 0
            a_extra    = 1 if o_type == 'Extras' else 0
            a_runs     = r_bat + r_ext

            stats = {'pb': p_boundary, 'ab': a_boundary,
                     'pw': p_wicket,   'aw': a_wicket,
                     'pd': p_dot,      'ad': a_dot,
                     'pe': p_extra,    'ae': a_extra,
                     'pr': p_runs,     'ar': a_runs}

            global_acc.push(pred_p, stats)

            phase = MatchRules.get_fine_grained_phase(over_1idx, strategy._match_format)
            phase_accs[phase].push(pred_p, stats)
            inn_accs[inning].push(pred_p, stats)
            state_accs[_batter_state(int(batter_score or 0))].push(pred_p, stats)
            btype_accs[_bowler_type(bowler_id, strategy)].push(pred_p, stats)
            milestone_accs[_milestone_group(int(batter_score or 0))].push(pred_p, stats)

            matchup_key  = (batter_id, bowler_id) if batter_id and bowler_id else None
            mb = getattr(strategy, 'matchup_ball_counts', {}).get(matchup_key, 0) if matchup_key else 0
            matchup_accs[_matchup_richness(mb, strategy._match_format)].push(pred_p, stats)

            bb  = getattr(strategy, 'batter_ball_counts', {}).get(batter_id, 0) if batter_id else 0
            bwb = getattr(strategy, 'bowler_ball_counts', {}).get(bowler_id, 0) if bowler_id else 0
            richness_accs[_player_richness(bb, bwb, strategy._match_format)].push(pred_p, stats)
            pressure_accs[_pressure_proxy(over_1idx, inning, strategy._match_format)].push(pred_p, stats)

            # ── Per-player accumulators ────────────────────────────────────
            if batter_id:
                if batter_id not in batter_accs:
                    b_dist = strategy.batter_cache.get(batter_id)
                    cb, cw = _cache_rates(b_dist)
                    batter_accs[batter_id] = _PlayerAcc(cb, cw, bb)
                batter_accs[batter_id].push(pred_p, p_boundary, p_wicket, p_runs,
                                             a_boundary, a_wicket, a_runs)

            if bowler_id:
                if bowler_id not in bowler_accs:
                    bw_dist = strategy.bowler_cache.get(bowler_id)
                    cb, cw = _cache_rates(bw_dist)
                    bowler_accs[bowler_id] = _PlayerAcc(cb, cw, bwb)
                bowler_accs[bowler_id].push(pred_p, p_boundary, p_wicket, p_runs,
                                             a_boundary, a_wicket, a_runs)

            # ── Calibration ──────────────────────────────────────────────
            for cat, p_cat, a_cat in (
                ('boundary', p_boundary, a_boundary),
                ('wicket',   p_wicket,   a_wicket),
                ('dot',      p_dot,      a_dot),
                ('extra',    p_extra,    a_extra),
            ):
                bi = min(int(p_cat * _N_CAL_BINS), _N_CAL_BINS - 1)
                b  = cal[cat][bi]
                b.pred_sum  += p_cat
                b.act_count += a_cat
                b.n         += 1

        if global_acc.n == 0:
            raise RuntimeError("No deliveries scored - check baseline key coverage.")

        n = global_acc.n

        def _to_m(accs, filter_n=0):
            return {k: v.to_metrics() for k, v in accs.items()
                    if v.n >= max(1, filter_n)}

        result = ValidationResult(
            model_name         = model_name,
            match_format       = match_format,
            gender             = gender,
            sample_size        = sample_size,
            scored_count       = int(n),
            log_loss           = global_acc.ll / n,
            baseline_log_loss  = uniform_log_loss,
            boundary_rate_err  = abs(global_acc.pb - global_acc.ab) / n,
            wicket_rate_err    = abs(global_acc.pw - global_acc.aw) / n,
            dot_rate_err       = abs(global_acc.pd - global_acc.ad) / n,
            extra_rate_err     = abs(global_acc.pe - global_acc.ae) / n,
            economy_err        = abs(global_acc.pr - global_acc.ar) / n * 6,
            elapsed_s          = time.perf_counter() - t_start,
            per_category       = {
                cat: {'log_loss': v['total'] / max(1, v['count']), 'count': v['count']}
                for cat, v in per_cat_loss.items()
            },
            by_phase           = _to_m(phase_accs),
            by_innings         = _to_m(inn_accs),
            by_batter_state    = _to_m(state_accs),
            by_bowler_type     = _to_m(btype_accs),
            by_milestone       = _to_m(milestone_accs),
            by_matchup_richness= _to_m(matchup_accs),
            by_player_richness = _to_m(richness_accs),
            by_pressure_proxy  = _to_m(pressure_accs),
            calibration        = cal,
        )

        result.batter_summary = _build_player_summary(batter_accs, 'batter')
        result.bowler_summary = _build_player_summary(bowler_accs, 'bowler')

        result.assertions       = _build_assertions(result)
        result.regression_flags = self._check_regressions(result, match_format, gender, model_name)
        return result

    # ── Venue context comparison ───────────────────────────────────────────────

    def compare_venue_context(
        self,
        strategy: BallOutcomeStrategy,
        venue_name: str,
        match_format: str = 'Test',
        gender: str = 'male',
        n_deliveries: int = 2000,
    ) -> Optional[VenueContextLift]:
        vrow = self.repo._run_query(
            "SELECT venue_id, name FROM history.venues WHERE name ILIKE %s LIMIT 1",
            (f"%{venue_name}%",)
        )
        if not vrow:
            print(f"  [VenueTest] Venue '{venue_name}' not found.")
            return None
        venue_id, actual_name = vrow[0]
        print(f"  [VenueTest] Testing: {actual_name} (id={venue_id})")

        rows = self.repo.get_validation_deliveries(
            match_format, gender, n_deliveries, venue_id=venue_id
        )
        if not rows:
            return None

        self._init_strategy_caches(strategy, rows, match_format, gender)

        strategy.venue_cache = {}; strategy.player_venue_cache = {}; strategy.player_country_cache = {}
        loss_no_venue = self._compute_loss(strategy, rows)

        all_ids = list({r[0] for r in rows if r[0]} | {r[1] for r in rows if r[1]})
        strategy.venue_cache        = self.repo.get_venue_distribution(venue_id, match_format, gender)
        strategy.player_venue_cache = self.repo.get_player_venue_distribution(all_ids, venue_id, match_format, gender)
        strategy.player_country_cache = {}
        loss_with_venue = self._compute_loss(strategy, rows)

        return VenueContextLift(actual_name, len(rows), loss_no_venue, loss_with_venue)

    def _compute_loss(self, strategy, rows) -> float:
        total = 0.0; n = 0
        vp = strategy.venue_cache      or strategy.baseline_outcome_probs
        tp = strategy.tournament_cache or strategy.baseline_outcome_probs
        for row in rows:
            (batter_id, bowler_id, _, inning, over_1idx,
             _, r_bat, r_ext, o_type, o_kind, batter_score, _, _) = row
            ak = (r_bat, r_ext, o_type, o_kind)
            if ak not in strategy.baseline_outcome_probs:
                continue
            dist   = _get_distribution(strategy, batter_id, bowler_id, inning, over_1idx,
                                        int(batter_score or 0), vp, tp)
            pred_p = dist.get(ak, 1e-10)
            total -= math.log(max(pred_p, 1e-10))
            n += 1
        return total / max(n, 1)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _check_regressions(result: ValidationResult, fmt: str, gender: str, model_name: str) -> List[str]:
        flags = []
        if not os.path.exists(_BASELINE_FILE):
            return flags
        try:
            with open(_BASELINE_FILE) as f:
                baselines = json.load(f)
        except Exception:
            return flags
        baseline = baselines.get(model_name, {}).get(fmt, {}).get(gender)
        if not baseline:
            baseline = baselines.get(fmt, {}).get(gender)  # legacy key format
        if not baseline:
            return flags
        current = result.as_baseline_dict()
        thresholds = _REGRESSION_THRESHOLDS.get(fmt, _REGRESSION_THRESHOLDS['Test'])
        for metric, threshold in thresholds.items():
            bv = baseline.get(metric)
            cv = current.get(metric)
            if bv is None or cv is None:
                continue
            delta = cv - bv
            if delta > threshold:
                flags.append(f"{metric}: {cv:.5f} vs baseline {bv:.5f} (Δ={delta:+.5f}, threshold ±{threshold})")
        return flags

    def _init_strategy_caches(self, strategy, rows, match_format, gender):
        from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy import (
            EnhancedBaseHistoricalStatsStrategy,
        )
        if isinstance(strategy, EnhancedBaseHistoricalStatsStrategy):
            self._init_enhanced_caches(strategy, rows, match_format, gender)
        else:
            self._init_basic_caches(strategy, rows, match_format, gender)

    def _init_enhanced_caches(self, strategy, rows, match_format, gender):
        from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy import (
            _make_parttime_probs, _compute_distinctiveness,
        )
        unified = MatchRules.get_unified_format(match_format)
        strategy._match_format = unified

        batter_ids = list({r[0] for r in rows if r[0]})
        bowler_ids = list({r[1] for r in rows if r[1]})

        def _t(label, fn, *a, **kw):
            t = time.perf_counter()
            r = fn(*a, **kw)
            print(f"  [Validator] {label:<45} {time.perf_counter()-t:.2f}s")
            return r

        batters_data  = _t("batters_with_counts",  self.repo.get_batters_distribution_with_counts, batter_ids, unified, gender)
        bowlers_data  = _t("bowlers_with_counts",  self.repo.get_bowlers_distribution_with_counts, bowler_ids, unified, gender)
        matchups_data = _t("matchups_with_counts", self.repo.get_matchup_distribution_with_counts, batter_ids, bowler_ids, unified, gender)

        strategy.batter_cache        = {pid: d[0] for pid, d in batters_data.items()}
        strategy.batter_ball_counts  = {pid: d[1] for pid, d in batters_data.items()}
        strategy.bowler_cache        = {pid: d[0] for pid, d in bowlers_data.items()}
        strategy.bowler_ball_counts  = {pid: d[1] for pid, d in bowlers_data.items()}
        strategy.matchup_cache       = {pair: d[0] for pair, d in matchups_data.items()}
        strategy.matchup_ball_counts = {pair: d[1] for pair, d in matchups_data.items()}

        strategy.phase_cache            = _t("phase_distribution",   self.repo.get_phase_distribution,             unified, gender)
        strategy.milestone_cache        = _t("milestone_global",      self.repo.get_batter_milestone_distribution,  unified, gender)
        strategy.player_milestone_cache = _t("milestone_per_player",  self.repo.get_player_milestone_distributions, batter_ids, unified, gender)
        strategy.innings_cache          = _t("innings_distribution",  self.repo.get_innings_distribution,           unified, gender)
        strategy.fielding_cache         = _t("fielding_distribution", self.repo.get_fielding_distribution,          unified, gender)
        strategy.baseline_outcome_probs = _t("full_aggregate",        self.repo.get_full_aggregate_distribution,    unified, gender)

        if not strategy.baseline_outcome_probs:
            from simulator.predictors.ball_outcome_prediction.common.utils import BASELINE_FALLBACK
            strategy.baseline_outcome_probs = BASELINE_FALLBACK

        strategy.parttime_bowler_probs = _make_parttime_probs(strategy.baseline_outcome_probs, unified)
        strategy.venue_cache           = {}
        strategy.tournament_cache      = {}
        strategy.player_venue_cache    = {}
        strategy.player_country_cache  = {}
        strategy.spinner_ids           = set()

        strategy.batter_distinctiveness  = {pid: _compute_distinctiveness(d, strategy.baseline_outcome_probs) for pid, d in strategy.batter_cache.items() if d}
        strategy.bowler_distinctiveness  = {pid: _compute_distinctiveness(d, strategy.baseline_outcome_probs) for pid, d in strategy.bowler_cache.items() if d}
        strategy.matchup_distinctiveness = {pair: _compute_distinctiveness(d, strategy.baseline_outcome_probs) for pair, d in strategy.matchup_cache.items() if d}

        print(f"  [Validator] Caches: {len(strategy.batter_cache)} batters, "
              f"{len(strategy.bowler_cache)} bowlers, {len(strategy.matchup_cache)} matchups")

    def _init_basic_caches(self, strategy, rows, match_format, gender):
        unified = MatchRules.get_unified_format(match_format)
        strategy._match_format = unified

        batter_ids = list({r[0] for r in rows if r[0]})
        bowler_ids = list({r[1] for r in rows if r[1]})
        all_ids    = list(set(batter_ids + bowler_ids))

        def _t(label, fn, *a, **kw):
            t = time.perf_counter()
            r = fn(*a, **kw)
            print(f"  [Validator] {label:<45} {time.perf_counter()-t:.2f}s")
            return r

        strategy.batter_cache     = _t("batters_distribution",  self.repo.get_batters_distribution, batter_ids, unified, gender)
        strategy.bowler_cache     = _t("bowlers_distribution",  self.repo.get_bowlers_distribution, bowler_ids, unified, gender)
        strategy.innings_cache    = _t("innings_distribution",  self.repo.get_innings_distribution, unified, gender)
        strategy.overs_cache      = _t("overs_distribution",    self.repo.get_overs_distribution,   unified, gender)
        strategy.fielding_cache   = _t("fielding_distribution", self.repo.get_fielding_distribution, unified, gender)
        strategy.venue_cache      = {}
        strategy.tournament_cache = {}

        strategy.baseline_outcome_probs = _t("full_aggregate", self.repo.get_full_aggregate_distribution, unified, gender)
        if not strategy.baseline_outcome_probs:
            from simulator.predictors.ball_outcome_prediction.common.utils import BASELINE_FALLBACK
            strategy.baseline_outcome_probs = BASELINE_FALLBACK

        # Basic strategy has no ball counts - set empty dicts for per-player richness
        strategy.batter_ball_counts  = {}
        strategy.bowler_ball_counts  = {}
        strategy.matchup_ball_counts = {}
        strategy.matchup_cache       = {}

        print(f"  [Validator] Basic caches: {len(strategy.batter_cache)} batters, {len(strategy.bowler_cache)} bowlers")


# ── Shared static helpers ─────────────────────────────────────────────────────

def _categorise(key: tuple) -> str:
    rb, _, ot, _ = key
    if ot == 'Wicket': return 'wicket'
    if ot == 'Extras': return 'extra'
    if rb >= 4:        return 'boundary'
    if rb == 0:        return 'dot'
    return 'rotation'


def _batter_state(score: int) -> str:
    for label, lo, hi in _BATTER_STATES:
        if lo <= score <= hi:
            return label
    return 'dominant'


def _bowler_type(bowler_id: Optional[int], strategy: BallOutcomeStrategy) -> str:
    if not bowler_id:
        return 'genuine'
    balls = getattr(strategy, 'bowler_ball_counts', {}).get(bowler_id, 0)
    try:
        from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy import _parttime_alpha
        alpha = _parttime_alpha(balls, strategy._match_format)
        return 'parttimer' if alpha >= 0.5 else 'genuine'
    except Exception:
        return 'genuine'


# ── Baseline I/O ─────────────────────────────────────────────────────────────

def load_baseline() -> dict:
    if not os.path.exists(_BASELINE_FILE):
        return {}
    with open(_BASELINE_FILE) as f:
        return json.load(f)


def save_baseline(result: ValidationResult):
    data = load_baseline()
    # Store under model_name for multi-model support; also write legacy flat key
    data.setdefault(result.model_name, {}).setdefault(result.match_format, {})[result.gender] = result.as_baseline_dict()
    data.setdefault(result.match_format, {})[result.gender] = result.as_baseline_dict()  # legacy
    with open(_BASELINE_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"  [Validator] Baseline saved → {_BASELINE_FILE}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    import argparse
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

    parser = argparse.ArgumentParser(description="Validate ball-outcome prediction strategies")
    parser.add_argument('--format',        default='T20',      choices=['T20', 'ODI', 'Test'])
    parser.add_argument('--gender',        default='male',     choices=['male', 'female'])
    parser.add_argument('--samples',       default=5000,       type=int)
    parser.add_argument('--model',         default='enhanced', choices=['enhanced', 'basic'],
                        help="Which model class to validate")
    parser.add_argument('--save-baseline', action='store_true')
    parser.add_argument('--venue',         default=None,
                        help="Also run venue context comparison for this venue name")
    args = parser.parse_args()

    from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats import (
        T20EnhancedHistoricalStatsStrategy,
        ODIEnhancedHistoricalStatsStrategy,
        TestEnhancedHistoricalStatsStrategy,
    )
    from simulator.predictors.ball_outcome_prediction.historical_stats.strategy import (
        T20HistoricalStatsStrategy,
        ODIHistoricalStatsStrategy,
        TestHistoricalStatsStrategy,
    )

    enhanced_map = {
        'T20':  T20EnhancedHistoricalStatsStrategy,
        'ODI':  ODIEnhancedHistoricalStatsStrategy,
        'Test': TestEnhancedHistoricalStatsStrategy,
    }
    basic_map = {
        'T20':  T20HistoricalStatsStrategy,
        'ODI':  ODIHistoricalStatsStrategy,
        'Test': TestHistoricalStatsStrategy,
    }

    strategy_cls = enhanced_map[args.format] if args.model == 'enhanced' else basic_map[args.format]

    repo      = StatsRepository()
    strategy  = strategy_cls()
    validator = ModelValidator(repo)

    print(f"\nValidating {args.model}/{args.format} ({args.gender}) - {args.samples:,} deliveries …\n")
    result = validator.validate(strategy, args.format, args.gender, args.samples)

    if args.venue:
        result.venue_lift = validator.compare_venue_context(
            strategy, args.venue, args.format, args.gender
        )

    result.report()

    if args.save_baseline:
        save_baseline(result)


if __name__ == '__main__':
    _cli()
