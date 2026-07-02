"""
Enhanced Historical Statistics Ball Outcome Strategy
=====================================================
Relative Multiplicative Scaling (RMS) model — improved in four areas over the
base historical strategy:

1. Fine-grained phase context
   T20: 6 buckets (pp1/pp2/mid1/mid2/death1/death2).
   ODI: 7 buckets (pp1/pp2/mid1/mid2/mid3/death1/death2).
   Test: 4 buckets (new/early/middle/late).
   Each bucket covers a narrower slice of innings so the signal is sharper without
   being as sparse as the original per-over lookup.

2. Batter confidence context
   Conditions on the batter's running score in the current innings: 'new' (0–5),
   'settling' (6–20), 'set' (21–49), 'dominant' (50+).  Distribution is pre-computed
   from historical data via window functions that track score_before each delivery.
   A new batter genuinely faces different outcomes than a set batter — this makes that
   explicit rather than blending it into the global batter historical average.

3. Data-reliability-weighted context blending
   Sparse player/matchup data should not compete equally with rich phase/venue data.
   For each context, a reliability score [0, 1] is computed from the number of balls
   in the cache (linear ramp to a format-specific threshold).  The base weights are
   rescaled by these reliability scores and renormalised — so an uncached batter
   (reliability = 0) releases their share of weight to the remaining contexts rather
   than silently falling back to a 1.0 multiplier while still consuming weight budget.

4. Outcome-category-aware context relevance
   Wickets are more predictable from bowler history; boundaries from batter history;
   extras are almost entirely a bowler trait.  A relevance table adjusts each context's
   effective contribution per outcome category.  Values are calibrated from cricket
   domain knowledge and kept modest (≤ ±30%) to avoid introducing bias without
   data-backed learning.

Additional improvements:
- Baseline from full delivery-level aggregate (not an averaged innings distribution).
- Candidate key set restricted to baseline keys — sparse contexts cannot inject
  rare outcome keys with inflated multipliers.
- Clean (ratio ** weight) multiplier with no salt or aggression constant, so
  weights are directly interpretable and correctly optimised by optimize_weights.py.
- Game pressure modifier for run chases (applied post-RMS).
- _compute_distribution() extracted so the ModelValidator can call it without a
  full SimulationMatch object.
"""

import logging
import math
import random
from abc import abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from db.stats_repository import StatsRepository
from enums.constants import ExtraType
from simulator.entities.ball_outcome import BallOutcome
from simulator.entities.match import SimulationMatch
from simulator.entities.rules import MatchRules
from simulator.strategies.ball_outcome_prediction.strategy_interface import BallOutcomeStrategy
from simulator.strategies.ball_outcome_prediction.common.utils import (
    BASELINE_FALLBACK,
    apply_free_hit_modifier,
    collect_player_ids,
    load_venue_distribution,
    load_tournament_distribution,
)
from simulator.logger import get_logger
from simulator.strategies.bowling.historical.base import _region_countries

log = get_logger()

# ── Multiplier bounds ──────────────────────────────────────────────────────────
_BASELINE_EPSILON = 1e-6
_RATIO_MIN        = 0.1
_RATIO_MAX        = 10.0

# ── Prob^k sharpness ──────────────────────────────────────────────────────────
_SHARPNESS_K: float = 2.0
_MILESTONE_K: float = 3.0


def _batting_position_group(wickets_fallen: int) -> str:
    if wickets_fallen <= 2:
        return 'top_order'
    elif wickets_fallen <= 5:
        return 'middle_order'
    return 'lower_order'


# All supported era-normalization contexts.  Used as the default when the config
# does not specify era_normalize_contexts.  Test cricket ignores this list entirely
# (normalization is disabled in init_model regardless of what is passed).
ERA_NORMALIZE_ALL: List[str] = [
    "batter", "bowler", "batter_phase", "player_milestone", "player_venue", "matchup",
]

# ── Minimum balls before a context is considered reliable (linear ramp) ────────
_RELIABILITY_THRESHOLDS: Dict[str, Dict[str, int]] = {
    'T20':  {'batter': 100, 'bowler': 100, 'matchup': 30},
    'ODI':  {'batter': 150, 'bowler': 150, 'matchup': 50},
    'Test': {'batter': 200, 'bowler': 200, 'matchup': 60},
}

# ── Player venue/country stat blending ────────────────────────────────────────
# Ball counts at which each level saturates to _PLAYER_LOC_MAX_W.
# Venue data is sparse (a few matches), country data is richer.
_PLAYER_LOC_THRESHOLDS: Dict[str, Dict[str, int]] = {
    'T20':  {'venue':  80, 'country': 200},
    'ODI':  {'venue': 120, 'country': 350},
    'Test': {'venue': 150, 'country': 500},
}
# Maximum weight given to player-specific location stats when fully saturated.
_PLAYER_LOC_MAX_W = 0.88

# ── Phase blending ─────────────────────────────────────────────────────────────
# Adaptive blend: batter's own phase distribution → bowler's career distribution → global phase.
# Batter weight ramps from 0 to _PHASE_BATTER_MAX_W as phase ball count reaches the threshold.
# Bowler takes up to _PHASE_BOWLER_MAX_W of the remaining weight (after batter), scaled by
# the standard bowler reliability score.  Global phase always absorbs the remainder.
_PHASE_BATTER_MAX_W:   Dict[str, float] = {'T20': 0.35, 'ODI': 0.35, 'Test': 0.35}
_PHASE_BATTER_THRESHOLD: Dict[str, int] = {'T20': 30,   'ODI': 50,   'Test': 100}
_PHASE_BOWLER_MAX_W = 0.30   # fraction of post-batter remaining weight

# ── Part-timer bowling distribution ───────────────────────────────────────────
# Ball count at which a bowler is treated as "genuine" (alpha → 0).
# Intentionally equal to the bowler reliability threshold so the two systems
# are consistent: full reliability ↔ zero part-timer blending.
_PARTTIME_THRESHOLDS: Dict[str, int] = {
    'T20': 120, 'ODI': 180, 'Test': 300,
}

# Category-level multipliers vs. the aggregate baseline, per format.
# T20:  batters slog at part-timers — many boundaries, but also miscued-shot wickets.
# ODI:  moderate aggression, some wickets from injudicious attacking shots.
# Test: batters patiently milk singles/twos; part-timers almost never break through.
_PARTTIME_CATEGORY_MULT: Dict[str, Dict[str, float]] = {
    'T20': {
        'boundary': 2.00,
        'wicket':   0.40,
        'dot':      0.40,
        'extra':    1.00,
        'default':  1.05,
    },
    'ODI': {
        'boundary': 1.80,
        'wicket':   0.28,
        'dot':      0.55,
        'extra':    1.00,
        'default':  1.10,
    },
    'Test': {
        'boundary': 1.80,
        'wicket':   0.20,
        'dot':      0.50,
        'extra':    1.00,
        'default':  1.15,
    },
}


def _make_parttime_probs(baseline: dict, match_format: str) -> dict:
    """
    Derives a 'part-timer bowling' distribution from the aggregate baseline
    by shifting probability mass toward boundaries and away from wickets/dots.
    Operates in the same key-space as baseline so no key mismatches downstream.
    """
    mults = _PARTTIME_CATEGORY_MULT.get(match_format, _PARTTIME_CATEGORY_MULT['Test'])
    raw = {k: v * mults.get(_outcome_category(k), 1.0)
           for k, v in baseline.items()}
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()} if total > 0 else dict(baseline)


def _parttime_alpha(ball_count: int, match_format: str) -> float:
    """
    Returns how 'part-timer-like' a bowler is: 1.0 = pure part-timer (no data),
    0.0 = genuine bowler (ball_count ≥ threshold).
    """
    threshold = _PARTTIME_THRESHOLDS.get(match_format, 200)
    return max(0.0, 1.0 - ball_count / threshold)


def _blend_with_parttime(parttime: dict, player: dict, alpha: float) -> dict:
    if alpha <= 0.0 or not parttime:
        return player
    if alpha >= 1.0:
        return parttime
    all_keys = set(parttime) | set(player)
    return {k: alpha * parttime.get(k, 0.0) + (1.0 - alpha) * player.get(k, 0.0)
            for k in all_keys}

# ── Outcome-category-aware relevance table ─────────────────────────────────────
_CATEGORY_RELEVANCE: Dict[str, Dict[str, float]] = {
    'boundary': {
        'batter': 1.30, 'bowler': 1.00, 'matchup': 1.30,
        'phase':  1.20, 'venue':  1.00, 'tournament': 0.90,
        'innings': 0.85, 'milestone': 1.30,
    },
    'wicket': {
        'batter': 1.10, 'bowler': 1.30, 'matchup': 1.30,
        'phase':  1.20, 'venue':  0.80, 'tournament': 0.85,
        'innings': 1.10, 'milestone': 1.30,
    },
    'extra': {
        'batter': 0.40, 'bowler': 1.60, 'matchup': 1.00,
        'phase':  1.20, 'venue':  0.55, 'tournament': 0.55,
        'innings': 0.85, 'milestone': 0.80,
    },
    'dot': {
        'batter': 1.00, 'bowler': 1.30, 'matchup': 1.35,
        'phase':  1.25, 'venue':  1.10, 'tournament': 0.85,
        'innings': 1.00, 'milestone': 1.30,
    },
    'default': {
        'batter': 1.30, 'bowler': 1.00, 'matchup': 1.00,
        'phase':  1.10, 'venue':  1.00, 'tournament': 1.00,
        'innings': 1.00, 'milestone': 1.30,
    },
}


def _get_milestone(runs_scored: int) -> str:
    """10-run bucket: 'm0' (0-9), 'm10' (10-19), ..., 'm100' (100+)."""
    return f'm{min((runs_scored // 10) * 10, 100)}'


def _clean_multiplier(context_prob: float, baseline_prob: float, weight: float, k: float = 1.0) -> float:
    if baseline_prob < _BASELINE_EPSILON:
        return 1.0
    capped_ratio = max(_RATIO_MIN, min(_RATIO_MAX, context_prob / baseline_prob))
    return capped_ratio ** (k * weight)


def _outcome_category(outcome_key: tuple) -> str:
    runs_batter, _, outcome_type, _ = outcome_key
    if outcome_type == 'Wicket': return 'wicket'
    if outcome_type == 'Extras': return 'extra'
    if runs_batter >= 4:         return 'boundary'
    if runs_batter == 0:         return 'dot'
    return 'default'


def _era_normalize_probs(
    per_year_counts: Dict[int, Dict[Tuple, int]],
    global_yearly_baseline: Dict[int, Dict[Tuple, float]],
    current_baseline: Dict[Tuple, float],
    half_life: float = 5.0,
) -> Optional[Dict[Tuple, float]]:
    """
    Converts per-year raw delivery counts into a current-era probability distribution.

    For each calendar year in the player's data, we compute how the player's outcome
    distribution *deviated from the era average* (global_yearly_baseline for that year).
    Those per-year ratios are aggregated with exponential time decay (same half-life as
    the existing decay parameters so that old data receives less weight).  Finally we
    project the decay-weighted ratio onto the current baseline to produce an estimate of
    what the player would look like under present-day conditions.

    Formula:
        ratio[outcome] = Σ_year(decay × player_prob_year / global_prob_year) / Σ_year(decay)
        era_prob[outcome] = current_baseline[outcome] × ratio[outcome]
        → renormalized so all outcomes sum to 1

    Returns None when there is no overlap between the player's years and the global
    baseline (no data to work with).
    """
    current_year = date.today().year
    total_weight = 0.0
    weighted_ratio: Dict[Tuple, float] = {}

    for year, year_counts in per_year_counts.items():
        global_year = global_yearly_baseline.get(year)
        if not global_year:
            continue
        year_total = sum(year_counts.values())
        if year_total == 0:
            continue

        age_years = max(0, current_year - year)
        decay = math.exp(-math.log(2) / half_life * age_years)

        for key in current_baseline:
            player_prob = year_counts.get(key, 0) / year_total
            global_prob = global_year.get(key, 0.0)
            if global_prob < 1e-9:
                continue
            weighted_ratio[key] = weighted_ratio.get(key, 0.0) + decay * (player_prob / global_prob)

        total_weight += decay

    if total_weight < 1e-9:
        return None

    result: Dict[Tuple, float] = {}
    for key, baseline_prob in current_baseline.items():
        ratio = weighted_ratio.get(key, 0.0) / total_weight
        result[key] = baseline_prob * ratio

    total = sum(result.values())
    if total < 1e-9:
        return None
    return {k: v / total for k, v in result.items()}


def _compute_distinctiveness(dist: dict, baseline: dict) -> float:
    """
    Measures how strongly a player's distribution deviates from baseline.
    Uses baseline-weighted |log(ratio)|. Returns [0, 1].
    """
    if not dist:
        return 0.0
    score = 0.0
    for key, bp in baseline.items():
        if bp < _BASELINE_EPSILON:
            continue
        cp    = dist.get(key, 0.0)
        ratio = max(_RATIO_MIN, min(_RATIO_MAX, cp / bp if bp > 0 else 1.0))
        score += bp * abs(math.log(ratio))
    return min(1.0, score / 0.7)


@dataclass
class PressureContext:
    score_p: float
    dot_p: float
    wicket_p: float
    partnership_p: float
    match_format: str
    batter_runs: int = 0
    current_over: int = 0
    wkts_remaining: int = 10

    @property
    def is_significant(self) -> bool:
        return (
            abs(self.score_p) >= 0.05
            or self.dot_p      >= 0.10
            or self.wicket_p   >= 0.10
            or self.partnership_p >= 0.10
        )


class EnhancedBaseHistoricalStatsStrategy(BallOutcomeStrategy):
    """
    Enhanced data-driven ball outcome predictor.

    init_model()         — called once at match start; populates all caches from DB.
    predict_next_ball()  — called once per delivery; returns a sampled BallOutcome.
    _compute_distribution() — pure probability computation without sampling;
                              used by the ModelValidator for backtesting.
    """

    def __init__(self, repo=None):
        if repo is None:
            repo = StatsRepository()
        self.repo = repo

        self.batter_cache     = {}
        self.bowler_cache     = {}
        self.matchup_cache    = {}
        self.venue_cache         = {}
        self.player_venue_cache:   dict = {}  # {player_id: (probs, ball_count)} — venue-specific
        self.player_country_cache: dict = {}  # {player_id: (probs, ball_count)} — country/region
        self.tournament_cache = {}
        self.innings_cache    = {}
        self.phase_cache      = {}
        self.milestone_cache  = {}
        self.fielding_cache   = {}
        self.baseline_outcome_probs = {}
        self._ordered_keys: list = []
        self._key_categories: Dict[tuple, str] = {}

        self.batter_ball_counts  = {}
        self.bowler_ball_counts  = {}
        self.matchup_ball_counts = {}
        self._last_raw_weights: Dict[tuple, float] = {}

        self.batter_phase_cache: dict = {}        # {player_id: {phase: {outcome_key: prob}}}
        self.batter_phase_ball_counts: dict = {}  # {player_id: {phase: int}}

        self.batter_distinctiveness  = {}
        self.bowler_distinctiveness  = {}
        self.matchup_distinctiveness = {}

        self.spinner_ids: set = set()
        self._match_format = 'T20'
        self.parttime_bowler_probs: dict = {}
        self.position_baseline: dict = {}
        self._initialized = False
        self._era_normalize_contexts: set = set()
        self._global_yearly_baseline: Dict[int, Dict[Tuple, float]] = {}

    @property
    @abstractmethod
    def WEIGHTS(self) -> dict:
        """
        Base context weights summing to 1.0.
        Keys: batter, bowler, matchup, phase, venue, tournament, innings, milestone.
        """

    # ── Initialisation ─────────────────────────────────────────────────────────

    def init_model(self, match: SimulationMatch):
        if self._initialized:
            self._extend_player_caches(match)
            return

        match_format = MatchRules.get_unified_format(getattr(match, 'match_format', 'T20'))
        gender = getattr(match, 'gender', 'male').lower()
        self._match_format = match_format
        self._gender = gender

        log.info("[EnhancedStrategy] Initialising — format: %s (%s)", match_format, gender)

        all_player_ids = collect_player_ids(match)
        venue      = getattr(match, 'venue',      None)
        tournament = getattr(match, 'tournament', None)

        def _q(method, *args, **kw):
            return lambda repo: getattr(repo, method)(*args, **kw)

        def _venue_fn(repo):
            if not venue or not venue.id:
                return {}
            result = repo.get_venue_distribution(venue.id, match_format, gender)
            if not result and getattr(venue, 'country', None):
                result = repo.get_country_distribution(venue.country, match_format, gender)
                log.info("[Model] Venue absent — using country distribution (%s)", venue.country)
            return result

        def _tourn_fn(repo):
            if not tournament or not tournament.id:
                return {}
            return repo.get_tournament_distribution(tournament.id)

        venue_country        = getattr(venue, 'country', None) if venue else None
        venue_country_group  = _region_countries(venue_country) if venue_country else None

        era_contexts = set(getattr(match, 'era_normalize_contexts', []))
        if match_format == 'Test':
            era_contexts = set()  # Era normalization not applicable to Test cricket
        self._era_normalize_contexts = era_contexts

        def _player_venue_pc_fn(repo):
            if not venue or not venue.id:
                return {}
            return repo.get_player_venue_probs_precomputed(all_player_ids, venue.id, match_format, gender)

        def _player_country_fn(repo):
            if not venue_country_group:
                return {}
            return repo.get_player_country_distribution(
                all_player_ids, venue_country_group[0], match_format, gender,
                countries=venue_country_group,
            )

        tasks: list = [
            ("phase",             _q("get_phase_distribution",                match_format, gender)),
            ("milestone_global",  _q("get_batter_milestone_distribution",     match_format, gender)),
            ("innings",           _q("get_innings_distribution",              match_format, gender)),
            ("fielding",          _q("get_fielding_distribution",             match_format, gender)),
            ("baseline",          _q("get_full_aggregate_distribution",       match_format, gender)),
            ("position_baseline", _q("get_batting_position_baseline",         match_format, gender)),
            ("keepers",           _q("get_wicket_keepers",                    all_player_ids, gender)),
            ("spinners",          _q("get_spinner_ids",                       all_player_ids, gender, match_format)),
            ("venue",             _venue_fn),
            ("tournament",        _tourn_fn),
            ("player_country",    _player_country_fn),
            ("batters_pc",        _q("get_batters_probs_precomputed",         all_player_ids, match_format, gender)),
            ("bowlers_pc",        _q("get_bowlers_probs_precomputed",         all_player_ids, match_format, gender)),
            ("batter_phase_pc",   _q("get_batter_phase_probs_precomputed",   all_player_ids, match_format, gender)),
            ("milestone_pc",      _q("get_player_milestone_probs_precomputed", all_player_ids, match_format, gender)),
            ("matchups_pc",       _q("get_matchup_probs_precomputed",         all_player_ids, all_player_ids, match_format, gender)),
            ("player_venue_pc",   _player_venue_pc_fn),
        ]

        repo = StatsRepository()
        results = {}
        for label, fn in tasks:
            try:
                results[label] = fn(repo)
            except Exception as e:
                log.warning("[EnhancedModel] Cache '%s' failed: %s", label, e)
                results[label] = {}

        # Baseline must be resolved first — all era-normalization calls reference it.
        self.baseline_outcome_probs = results["baseline"]
        if not self.baseline_outcome_probs:
            log.warning("[EnhancedStrategy] No aggregate data — using empirical prior.")
            self.baseline_outcome_probs = BASELINE_FALLBACK
        self._ordered_keys = list(self.baseline_outcome_probs.keys())
        self._key_categories = {k: _outcome_category(k) for k in self._ordered_keys}

        # ── Batter cache ────────────────────────────────────────────────────────
        self.batter_cache = {}
        self.batter_ball_counts = {}
        for pid, (raw, era, count) in results.get("batters_pc", {}).items():
            probs = era if ('batter' in era_contexts and era is not None) else raw
            if probs:
                self.batter_cache[pid] = probs
                self.batter_ball_counts[pid] = count

        # ── Bowler cache ────────────────────────────────────────────────────────
        self.bowler_cache = {}
        self.bowler_ball_counts = {}
        for pid, (raw, era, count) in results.get("bowlers_pc", {}).items():
            probs = era if ('bowler' in era_contexts and era is not None) else raw
            if probs:
                self.bowler_cache[pid] = probs
                self.bowler_ball_counts[pid] = count

        # ── Matchup cache ───────────────────────────────────────────────────────
        self.matchup_cache = {}
        self.matchup_ball_counts = {}
        for pair, (raw, era, count) in results.get("matchups_pc", {}).items():
            probs = era if ('matchup' in era_contexts and era is not None) else raw
            if probs:
                self.matchup_cache[pair] = probs
                self.matchup_ball_counts[pair] = count

        # ── Batter-phase cache ──────────────────────────────────────────────────
        self.batter_phase_cache = {}
        self.batter_phase_ball_counts = {}
        for pid, phase_data in results.get("batter_phase_pc", {}).items():
            self.batter_phase_cache[pid] = {}
            self.batter_phase_ball_counts[pid] = {}
            for phase, (raw, era, count) in phase_data.items():
                probs = era if ('batter_phase' in era_contexts and era is not None) else raw
                if probs:
                    self.batter_phase_cache[pid][phase] = probs
                    self.batter_phase_ball_counts[pid][phase] = count

        # ── Player milestone cache ──────────────────────────────────────────────
        self.player_milestone_cache = {}
        for pid, milestones in results.get("milestone_pc", {}).items():
            self.player_milestone_cache[pid] = {}
            for milestone, (raw, era, count) in milestones.items():
                probs = era if ('player_milestone' in era_contexts and era is not None) else raw
                if probs:
                    self.player_milestone_cache[pid][milestone] = probs

        # ── Player venue cache ──────────────────────────────────────────────────
        self.player_venue_cache = {}
        for pid, (raw, era, count) in results.get("player_venue_pc", {}).items():
            probs = era if ('player_venue' in era_contexts and era is not None) else raw
            if probs:
                self.player_venue_cache[pid] = (probs, count)

        # ── Remaining caches (no era normalization) ─────────────────────────────
        self.phase_cache            = results["phase"]
        self.milestone_cache        = results["milestone_global"]
        self.innings_cache          = results["innings"]
        self.fielding_cache         = results["fielding"]
        self.venue_cache            = results["venue"]
        self.tournament_cache       = results["tournament"]
        self.player_country_cache   = results["player_country"]

        self.position_baseline = results.get("position_baseline", {})
        self.parttime_bowler_probs = _make_parttime_probs(self.baseline_outcome_probs, match_format)

        self.batter_distinctiveness  = {
            pid: _compute_distinctiveness(dist, self.baseline_outcome_probs)
            for pid, dist in self.batter_cache.items() if dist
        }
        self.bowler_distinctiveness  = {
            pid: _compute_distinctiveness(dist, self.baseline_outcome_probs)
            for pid, dist in self.bowler_cache.items() if dist
        }
        self.matchup_distinctiveness = {
            pair: _compute_distinctiveness(dist, self.baseline_outcome_probs)
            for pair, dist in self.matchup_cache.items() if dist
        }

        keeper_ids = results["keepers"]
        for team in (match.home_team, match.away_team):
            if team:
                for p in team.players:
                    p.is_keeper = (p.id in keeper_ids)

        self.spinner_ids = results["spinners"]

        era_note = (f"era_normalize={sorted(era_contexts)}" if era_contexts
                    else "era_normalize=disabled(Test)" if match_format == 'Test'
                    else "era_normalize=matchup_only")
        log.info(
            "[EnhancedStrategy] Loaded → batters=%d bowlers=%d matchups=%d "
            "phases=%s milestones=%s baseline_keys=%d | %s",
            len(self.batter_cache), len(self.bowler_cache), len(self.matchup_cache),
            list(self.phase_cache.keys()), list(self.milestone_cache.keys()),
            len(self.baseline_outcome_probs), era_note,
        )
        self._initialized = True

    def _extend_player_caches(self, match: SimulationMatch) -> None:
        """Load stats for players in this match not seen in the first match's init_model call."""
        all_ids = [pid for pid in collect_player_ids(match) if pid]
        existing_ids = set(self.batter_cache) | set(self.bowler_cache)
        new_ids = [pid for pid in all_ids if pid not in existing_ids]
        if not new_ids:
            return

        fmt      = self._match_format
        gender   = self._gender
        era_ctxs = self._era_normalize_contexts

        def _run(fn):
            return fn(StatsRepository())

        all_known_ids = list(existing_ids | set(new_ids))

        # The bulk precomputed tables are already process-cached from init_model's
        # _load_player_stat_cache calls.  These calls are instant dict lookups.
        tasks: dict = {
            "keepers":      lambda repo: repo.get_wicket_keepers(new_ids, gender),
            "spinners":     lambda repo: repo.get_spinner_ids(new_ids, gender, fmt),
            "batters_pc":   lambda repo: repo.get_batters_probs_precomputed(new_ids, fmt, gender),
            "bowlers_pc":   lambda repo: repo.get_bowlers_probs_precomputed(new_ids, fmt, gender),
            "batter_phase_pc": lambda repo: repo.get_batter_phase_probs_precomputed(new_ids, fmt, gender),
            "milestone_pc": lambda repo: repo.get_player_milestone_probs_precomputed(new_ids, fmt, gender),
            "matchups_pc":  lambda repo: repo.get_matchup_probs_precomputed(new_ids, all_known_ids, fmt, gender),
            "matchups_pc2": lambda repo: repo.get_matchup_probs_precomputed(list(existing_ids), new_ids, fmt, gender),
        }

        repo = StatsRepository()
        results = {}
        for label, fn in tasks.items():
            try:
                results[label] = fn(repo)
            except Exception as e:
                log.warning("[EnhancedStrategy] Extend '%s' failed: %s", label, e)
                results[label] = {}

        # ── Batter cache ────────────────────────────────────────────────────────
        for pid, (raw, era, count) in results.get("batters_pc", {}).items():
            probs = era if ('batter' in era_ctxs and era is not None) else raw
            if probs:
                self.batter_cache[pid] = probs
                self.batter_ball_counts[pid] = count

        # ── Bowler cache ────────────────────────────────────────────────────────
        for pid, (raw, era, count) in results.get("bowlers_pc", {}).items():
            probs = era if ('bowler' in era_ctxs and era is not None) else raw
            if probs:
                self.bowler_cache[pid] = probs
                self.bowler_ball_counts[pid] = count

        # ── Matchup cache ───────────────────────────────────────────────────────
        new_matchup_pairs: set = set()
        combined_matchups = {**results.get("matchups_pc", {}), **results.get("matchups_pc2", {})}
        for pair, (raw, era, count) in combined_matchups.items():
            probs = era if ('matchup' in era_ctxs and era is not None) else raw
            if probs:
                self.matchup_cache[pair] = probs
                self.matchup_ball_counts[pair] = count
                new_matchup_pairs.add(pair)

        # ── Batter-phase cache ──────────────────────────────────────────────────
        for pid, phase_data in results.get("batter_phase_pc", {}).items():
            self.batter_phase_cache.setdefault(pid, {})
            self.batter_phase_ball_counts.setdefault(pid, {})
            for phase, (raw, era, count) in phase_data.items():
                probs = era if ('batter_phase' in era_ctxs and era is not None) else raw
                if probs:
                    self.batter_phase_cache[pid][phase] = probs
                    self.batter_phase_ball_counts[pid][phase] = count

        # ── Player milestone cache ──────────────────────────────────────────────
        for pid, milestones in results.get("milestone_pc", {}).items():
            self.player_milestone_cache.setdefault(pid, {})
            for milestone, (raw, era, count) in milestones.items():
                probs = era if ('player_milestone' in era_ctxs and era is not None) else raw
                if probs:
                    self.player_milestone_cache[pid][milestone] = probs

        keeper_ids = results["keepers"]
        for team in (match.home_team, match.away_team):
            if team:
                for p in team.players:
                    if p.id in new_ids:
                        p.is_keeper = (p.id in keeper_ids)

        self.spinner_ids |= results["spinners"]

        # Update distinctiveness for new players
        for pid in new_ids:
            if pid in self.batter_cache and self.batter_cache[pid]:
                self.batter_distinctiveness[pid] = _compute_distinctiveness(self.batter_cache[pid], self.baseline_outcome_probs)
            if pid in self.bowler_cache and self.bowler_cache[pid]:
                self.bowler_distinctiveness[pid] = _compute_distinctiveness(self.bowler_cache[pid], self.baseline_outcome_probs)
        for pair in new_matchup_pairs:
            if pair in self.matchup_cache:
                self.matchup_distinctiveness[pair] = _compute_distinctiveness(self.matchup_cache[pair], self.baseline_outcome_probs)

        log.info(
            "[EnhancedStrategy] Extended caches for %d new players → batters=%d bowlers=%d matchups=%d",
            len(new_ids), len(self.batter_cache), len(self.bowler_cache), len(self.matchup_cache),
        )

    def _get_player_venue_probs(self, batter_id: Optional[int]) -> dict:
        """
        Three-level adaptive blend for venue context:
          player-venue stats → player-country/region stats → general venue distribution.

        Weights ramp from 0 to _PLAYER_LOC_MAX_W (88%) as ball count grows toward the
        format-specific threshold.  This means a batter with 150+ Test balls at a venue
        gets ~88% weight on their own data; one with only 30 balls gets ~35%.
        Falls back cleanly: no player data → general venue; no venue at all → baseline.
        """
        general = self.venue_cache if self.venue_cache else self.baseline_outcome_probs

        if not batter_id:
            return general

        thresholds = _PLAYER_LOC_THRESHOLDS.get(self._match_format, _PLAYER_LOC_THRESHOLDS['Test'])

        v_entry = self.player_venue_cache.get(batter_id)
        c_entry = self.player_country_cache.get(batter_id)

        if not v_entry and not c_entry:
            return general

        n_v = v_entry[1] if v_entry else 0
        n_c = c_entry[1] if c_entry else 0

        vw = min(_PLAYER_LOC_MAX_W, _PLAYER_LOC_MAX_W * n_v / thresholds['venue'])   if n_v > 0 else 0.0
        remaining = 1.0 - vw
        cw = min(_PLAYER_LOC_MAX_W * remaining,
                 remaining * min(1.0, n_c / thresholds['country']))                    if n_c > 0 else 0.0
        gw = 1.0 - vw - cw

        vp = v_entry[0] if v_entry else {}
        cp = c_entry[0] if c_entry else {}

        all_keys = set(general) | set(vp) | set(cp)
        blended  = {
            k: vw * vp.get(k, 0.0) + cw * cp.get(k, 0.0) + gw * general.get(k, 0.0)
            for k in all_keys
        }
        total = sum(blended.values())
        return {k: v / total for k, v in blended.items()} if total > 0 else general

    def _compute_phase_probs(
        self,
        batter_id: Optional[int],
        bowler_id: Optional[int],
        phase: str,
    ) -> dict:
        """
        Adaptive three-level blend for the phase context:
          batter's own phase distribution → bowler's career distribution → global phase.

        Batter weight ramps 0 → _PHASE_BATTER_MAX_W as phase-ball count reaches threshold.
        Bowler weight ramps 0 → _PHASE_BOWLER_MAX_W of the post-batter remainder, scaled
        by the standard bowler reliability score.  Global phase takes the rest.

        Degrades cleanly: no player data → pure global phase.
        """
        global_phase = self.phase_cache.get(phase, self.baseline_outcome_probs)

        batter_max_w  = _PHASE_BATTER_MAX_W.get(self._match_format, 0.60)
        batter_thresh = _PHASE_BATTER_THRESHOLD.get(self._match_format, 50)
        rel_thresholds = _RELIABILITY_THRESHOLDS.get(self._match_format, _RELIABILITY_THRESHOLDS['T20'])

        # Batter's phase-specific distribution
        batter_phase_dist  = self.batter_phase_cache.get(batter_id, {}).get(phase) if batter_id else None
        batter_phase_balls = self.batter_phase_ball_counts.get(batter_id, {}).get(phase, 0) if batter_id else 0
        bw = min(batter_max_w, batter_max_w * batter_phase_balls / batter_thresh) if batter_phase_dist else 0.0

        # Bowler's career distribution (proxy for their phase tendency)
        bowler_dist  = self.bowler_cache.get(bowler_id) if bowler_id else None
        bowler_balls = self.bowler_ball_counts.get(bowler_id, 0) if bowler_id else 0
        remaining    = 1.0 - bw
        ow = min(_PHASE_BOWLER_MAX_W * remaining,
                 remaining * min(1.0, bowler_balls / rel_thresholds['bowler'])) if bowler_dist else 0.0

        gw = 1.0 - bw - ow

        bp = batter_phase_dist or {}
        bd = bowler_dist or {}
        all_keys = set(global_phase) | set(bp) | set(bd)
        blended  = {
            k: bw * bp.get(k, 0.0) + ow * bd.get(k, 0.0) + gw * global_phase.get(k, 0.0)
            for k in all_keys
        }
        total = sum(blended.values())
        return {k: v / total for k, v in blended.items()} if total > 0 else global_phase

    # ── Weight computation ─────────────────────────────────────────────────────

    def _compute_effective_weights(
        self,
        batter_id: Optional[int],
        bowler_id: Optional[int],
        matchup_key: Optional[Tuple[int, int]],
    ) -> Dict[str, float]:
        thresholds = _RELIABILITY_THRESHOLDS.get(self._match_format, _RELIABILITY_THRESHOLDS['T20'])

        def _reliability(balls: int, threshold: int) -> float:
            return min(1.0, balls / threshold)

        batter_balls  = self.batter_ball_counts.get(batter_id, 0)  if batter_id  else 0
        bowler_balls  = self.bowler_ball_counts.get(bowler_id, 0)  if bowler_id  else 0
        matchup_balls = self.matchup_ball_counts.get(matchup_key, 0) if matchup_key else 0

        w = self.WEIGHTS
        eff = {
            'batter':     w['batter']     * _reliability(batter_balls,  thresholds['batter']),
            'bowler':     w['bowler']     * _reliability(bowler_balls,  thresholds['bowler']),
            'matchup':    w['matchup']    * _reliability(matchup_balls, thresholds['matchup']),
            'phase':      w['phase'],
            'venue':      w['venue']      if self.venue_cache      else 0.0,
            'tournament': w['tournament'] if self.tournament_cache else 0.0,
            'innings':    w['innings'],
            'milestone':  w['milestone'],
        }

        # T20 only: freed matchup budget goes 60% to phase, 20% to batter group, 20% to bowler.
        # Phase is a population-level prior for this context window; routing the majority
        # there prevents sparse-matchup situations from over-amplifying extreme batter profiles.
        if self._match_format == 'T20':
            freed = w['matchup'] - eff['matchup']
            if freed > 0:
                eff['phase']     += freed * 0.60
                eff['batter']    += freed * 0.10
                eff['milestone'] += freed * 0.10
                eff['bowler']    += freed * 0.20

        total = sum(eff.values())
        if total > 0:
            return {k: v / total for k, v in eff.items()}
        return {k: 1.0 / len(eff) for k in eff}

    @staticmethod
    def _apply_category_relevance(
        effective_weights: Dict[str, float], outcome_key: tuple
    ) -> Dict[str, float]:
        relevance = _CATEGORY_RELEVANCE[_outcome_category(outcome_key)]
        adjusted  = {k: v * relevance[k] for k, v in effective_weights.items()}
        total     = sum(adjusted.values())
        if total > 0:
            return {k: v / total for k, v in adjusted.items()}
        return effective_weights

    # ── Pressure modifier ─────────────────────────────────────────────────────

    def _is_invalid_outcome(self, outcome_kind: Optional[str], bowler_id: Optional[int]) -> bool:
        if outcome_kind == 'stumped' and bowler_id not in self.spinner_ids:
            return True
        return False

    def _compute_pressure(self, match: SimulationMatch) -> PressureContext:
        batting    = match.current_batting_team
        deliveries = match.innings[-1].deliveries if match.innings else []
        fmt        = match.match_format

        if match.target_score is not None and batting:
            runs_needed = match.target_score - batting.total_runs
            if runs_needed <= 0:
                score_p = 0.0
            else:
                balls_rem = max(
                    1,
                    (match.overs_per_innings or 90) * match.balls_per_over - batting.total_balls,
                )
                req_rr  = (runs_needed / balls_rem) * match.balls_per_over
                cur_rr  = (batting.total_runs / max(1, batting.total_balls)) * match.balls_per_over
                delta   = req_rr - cur_rr
                score_p = max(-1.0, min(1.0, delta / max(1.0, req_rr + cur_rr) * 2.0))
                if runs_needed <= 5:
                    score_p = max(score_p, -0.2)
        elif fmt in ('T20', 'ODI') and batting and batting.total_balls >= 12:
            wkts_rem    = 10 - batting.total_wickets
            _ph         = MatchRules.get_fine_grained_phase(match.current_over + 1, fmt)
            total_overs = match.overs_per_innings or (20 if fmt == 'T20' else 50)
            overs_pct   = min(1.0, (match.current_over + 1) / total_overs)
            if _ph in ('death1', 'death2'):
                # Death: always attack with a floor so even a collapsed side swings;
                # ceiling scales with wickets in hand
                score_p = min(0.40, max(0.15, wkts_rem / 10.0 * 0.40))
            elif wkts_rem >= 5:
                # Wickets in hand — neutral; phase distribution already encodes the base scoring rate
                score_p = 0.0
            else:
                # Wickets running low in non-death overs: firm conservation pressure.
                # Death phase already handled above, so no need to decay with overs_pct.
                wkt_conserve = ((5 - wkts_rem) / 5.0) * 0.30
                score_p = max(-0.30, -wkt_conserve)
        else:
            score_p = 0.0

        consecutive_dots = 0
        for d in reversed(deliveries):
            if d.extras_type in (ExtraType.WIDE, ExtraType.NOBALL):
                continue
            if d.runs_batter == 0 and not d.is_wicket:
                consecutive_dots += 1
            else:
                break
        dot_p = min(1.0, (consecutive_dots / 6.0) * (1.0 + max(0.0, score_p) * 0.4))

        if batting and batting.total_balls >= 6:
            wpr      = batting.total_wickets / (batting.total_balls / 6.0)
            wicket_p = min(1.0, wpr / 0.6)
        else:
            wicket_p = 0.0

        balls_since_wicket = 0
        for d in reversed(deliveries):
            if d.is_wicket:
                break
            if d.extras_type not in (ExtraType.WIDE, ExtraType.NOBALL):
                balls_since_wicket += 1
        partnership_p = min(1.0, balls_since_wicket / 60.0)

        return PressureContext(
            score_p        = score_p,
            dot_p          = dot_p,
            wicket_p       = wicket_p,
            partnership_p  = partnership_p,
            match_format   = fmt,
            current_over   = match.current_over,
            wkts_remaining = 10 - (batting.total_wickets if batting else 0),
        )

    @staticmethod
    def _apply_pressure_modifier(
        weights: list, ordered_keys: list, ctx: PressureContext
    ) -> list:
        if not ctx.is_significant:
            return weights

        phase    = MatchRules.get_fine_grained_phase(ctx.current_over + 1, ctx.match_format)
        is_death = phase in ('death1', 'death2')
        fmt      = ctx.match_format

        if is_death:
            conservation_weight = 0.10
        elif fmt == 'ODI' and phase in ('pp1', 'pp2'):
            conservation_weight = 0.50
        elif fmt == 'T20' and phase in ('pp1', 'pp2'):
            conservation_weight = 0.45
        else:
            conservation_weight = 0.70

        if is_death:
            settle_threshold = 0
        elif fmt == 'T20':
            settle_threshold = 10 if phase in ('pp1', 'pp2') else 15
        elif fmt == 'ODI':
            settle_threshold = 15 if phase in ('pp1', 'pp2') else 30
        else:
            settle_threshold = 50

        settle_scale = 0.0 if is_death else (1.3 if fmt == 'Test' else 1.0)
        test_mult    = 1.5 if fmt == 'Test' else 1.0

        wicket_conservation = ctx.wicket_p * test_mult * max(0.0, 1.0 - abs(ctx.score_p))
        net_attack = ctx.score_p - wicket_conservation * conservation_weight + ctx.dot_p * 0.2
        bowl_loose = ctx.partnership_p * test_mult * 0.12

        # Scale attacking intent by wickets in hand — more wickets = more freedom to attack
        wkt_risk_scale = min(1.0, max(0.2, ctx.wkts_remaining / 7.0))

        adjusted = []
        for i, key in enumerate(ordered_keys):
            runs_batter, _, outcome_type, _ = key
            modifier = 1.0

            if net_attack > 0:
                if runs_batter >= 6:           modifier = 1.0 + net_attack * 0.28 * wkt_risk_scale
                elif runs_batter == 4:         modifier = 1.0 + net_attack * 0.18 * wkt_risk_scale
                elif runs_batter in (2, 3):    modifier = 1.0 + net_attack * 0.10 * wkt_risk_scale
                elif outcome_type == 'Dot':    modifier = max(0.1, 1.0 - net_attack * 0.30 * wkt_risk_scale)
                elif outcome_type == 'Wicket': modifier = 1.0 + net_attack * 0.25 * wkt_risk_scale
            elif net_attack < 0:
                if runs_batter >= 4:           modifier = 1.0 + net_attack * 0.30
                elif outcome_type == 'Dot':    modifier = 1.0 - net_attack * 0.20
                elif outcome_type == 'Wicket': modifier = 1.0 + net_attack * 0.20

            if ctx.dot_p > 0.15:
                if runs_batter >= 4:           modifier += ctx.dot_p * 0.08
                elif outcome_type == 'Wicket': modifier += ctx.dot_p * 0.04
                elif outcome_type == 'Dot':    modifier -= ctx.dot_p * 0.04

            if bowl_loose > 0.01:
                if runs_batter >= 1:           modifier += bowl_loose
                elif outcome_type == 'Wicket': modifier += bowl_loose * 0.5

            if settle_scale > 0 and ctx.wicket_p > 0.2 and ctx.batter_runs < settle_threshold:
                settle_p = ctx.wicket_p * settle_scale * (1.0 - ctx.batter_runs / settle_threshold)
                if runs_batter >= 6:
                    modifier *= max(0.25, 1.0 - settle_p * 0.45)
                elif runs_batter == 4:
                    modifier *= max(0.40, 1.0 - settle_p * 0.25)
                elif outcome_type == 'Dot':
                    modifier *= 1.0 + settle_p * 0.18
                elif outcome_type == 'Wicket':
                    modifier *= max(0.55, 1.0 - settle_p * 0.30)

            adjusted.append(weights[i] * max(0.0, modifier))

        return adjusted

    # ── Core distribution computation ─────────────────────────────────────────

    def _compute_distribution(
        self,
        batter_id: Optional[int],
        bowler_id: Optional[int],
        inning: int,
        over_1indexed: int,
        batter_runs: int,
        venue_probs: dict,
        tourn_probs: dict,
        _eff_w: Optional[Dict[str, float]] = None,
        wickets_fallen: int = 0,
        _override_batter_probs: Optional[dict] = None,
        _override_bowler_probs: Optional[dict] = None,
    ) -> Dict[tuple, float]:
        phase     = MatchRules.get_fine_grained_phase(over_1indexed, self._match_format)
        milestone = _get_milestone(batter_runs)
        matchup_key = (batter_id, bowler_id) if batter_id and bowler_id else None

        pos_baseline = self.position_baseline.get(_batting_position_group(wickets_fallen), self.baseline_outcome_probs)
        batter_probs = (
            _override_batter_probs
            if _override_batter_probs is not None
            else (self.batter_cache.get(batter_id, pos_baseline) if batter_id else pos_baseline)
        )

        if _override_bowler_probs is not None:
            bowler_probs = _override_bowler_probs
        elif bowler_id:
            _raw_bowler  = self.bowler_cache.get(bowler_id, self.baseline_outcome_probs)
            _pt_alpha    = _parttime_alpha(self.bowler_ball_counts.get(bowler_id, 0), self._match_format)
            bowler_probs = _blend_with_parttime(self.parttime_bowler_probs, _raw_bowler, _pt_alpha)
        else:
            bowler_probs = self.baseline_outcome_probs

        matchup_probs  = self.matchup_cache.get(matchup_key, self.baseline_outcome_probs) if matchup_key else self.baseline_outcome_probs
        phase_probs = self._compute_phase_probs(batter_id, bowler_id, phase)
        _player_ms     = self.player_milestone_cache.get(batter_id, {}) if batter_id else {}
        milestone_probs = (
            _player_ms.get(milestone)
            or self.milestone_cache.get(milestone)
            or self.baseline_outcome_probs
        )
        innings_probs  = self.innings_cache.get(inning, self.baseline_outcome_probs)

        eff_w = _eff_w if _eff_w is not None else self._compute_effective_weights(batter_id, bowler_id, matchup_key)

        raw_weights  = []
        ordered_keys = self._ordered_keys

        # Precompute per-category weights once (5 categories) instead of once per key (~76 keys)
        cw_per_cat: Dict[str, Dict[str, float]] = {}
        for cat, relevance in _CATEGORY_RELEVANCE.items():
            adj = {k: v * relevance[k] for k, v in eff_w.items()}
            total = sum(adj.values())
            cw_per_cat[cat] = {k: v / total for k, v in adj.items()} if total > 0 else eff_w

        for outcome_key in ordered_keys:
            baseline_prob = self.baseline_outcome_probs[outcome_key]

            batter_prob    = batter_probs.get(outcome_key,    baseline_prob)
            bowler_prob    = bowler_probs.get(outcome_key,    baseline_prob)
            matchup_prob   = matchup_probs.get(outcome_key,   baseline_prob)
            phase_prob     = phase_probs.get(outcome_key,     baseline_prob)
            milestone_prob = milestone_probs.get(outcome_key, baseline_prob)
            innings_prob   = innings_probs.get(outcome_key,   baseline_prob)
            venue_prob     = venue_probs.get(outcome_key,     baseline_prob)
            tourn_prob     = tourn_probs.get(outcome_key,     baseline_prob)

            cw = cw_per_cat[self._key_categories[outcome_key]]

            raw_weights.append(
                baseline_prob
                * _clean_multiplier(batter_prob,    baseline_prob, cw['batter'],     _SHARPNESS_K)
                * _clean_multiplier(bowler_prob,    baseline_prob, cw['bowler'],     _SHARPNESS_K)
                * _clean_multiplier(matchup_prob,   baseline_prob, cw['matchup'],    _SHARPNESS_K)
                * _clean_multiplier(phase_prob,     baseline_prob, cw['phase'])
                * _clean_multiplier(milestone_prob, baseline_prob, cw['milestone'],  _MILESTONE_K)
                * _clean_multiplier(innings_prob,   baseline_prob, cw['innings'])
                * _clean_multiplier(venue_prob,     baseline_prob, cw['venue'])
                * _clean_multiplier(tourn_prob,     baseline_prob, cw['tournament'])
            )

        total = sum(raw_weights)
        if total > 0:
            norm = [w / total for w in raw_weights]
        else:
            norm = [1.0 / len(ordered_keys)] * len(ordered_keys)

        # Stash unnormalised weights for debug logging (keyed by outcome tuple).
        self._last_raw_weights: Dict[tuple, float] = dict(zip(ordered_keys, raw_weights))

        return dict(zip(ordered_keys, norm))

    # ── Debug logging ──────────────────────────────────────────────────────────

    def _log_prediction_detail(
        self,
        ball_label: str,
        batter_name: str,
        bowler_name: str,
        batter_id: Optional[int],
        bowler_id: Optional[int],
        matchup_key: Optional[Tuple[int, int]],
        phase: str,
        milestone: str,
        inning: int,
        eff_w: Dict[str, float],
        venue_probs: dict,
        tourn_probs: dict,
        distribution: Dict[tuple, float],
        selected_key: tuple,
        pressure: PressureContext,
    ) -> None:
        # Logger is always at DEBUG level to not block handlers; check handler levels directly.
        if not any(h.level <= logging.DEBUG for h in log.handlers):
            return
        thresholds  = _RELIABILITY_THRESHOLDS.get(self._match_format, _RELIABILITY_THRESHOLDS['T20'])
        base_w      = self.WEIGHTS

        batter_balls  = self.batter_ball_counts.get(batter_id,   0) if batter_id   else 0
        bowler_balls  = self.bowler_ball_counts.get(bowler_id,   0) if bowler_id   else 0
        matchup_balls = self.matchup_ball_counts.get(matchup_key, 0) if matchup_key else 0

        batter_rel  = min(1.0, batter_balls  / thresholds['batter'])  if batter_id   else 0.0
        bowler_rel  = min(1.0, bowler_balls  / thresholds['bowler'])  if bowler_id   else 0.0
        matchup_rel = min(1.0, matchup_balls / thresholds['matchup']) if matchup_key else 0.0

        batter_hit  = batter_id  is not None and batter_id  in self.batter_cache
        bowler_hit  = bowler_id  is not None and bowler_id  in self.bowler_cache
        matchup_hit = matchup_key is not None and matchup_key in self.matchup_cache
        phase_hit   = phase   in self.phase_cache
        _player_ms_hit = bool(batter_id and self.player_milestone_cache.get(batter_id, {}).get(milestone))
        mlstn_hit   = _player_ms_hit or (milestone in self.milestone_cache)
        inn_hit     = inning  in self.innings_cache
        venue_hit   = bool(self.venue_cache)
        tourn_hit   = bool(self.tournament_cache)

        SEP = '─' * 104

        lines: List[str] = [
            SEP,
            f"  BALL  {ball_label}  │  {batter_name}  vs  {bowler_name}",
            f"  Phase: {phase}  │  Milestone: {milestone}  │  Innings: {inning}"
            f"  │  Pressure: score={pressure.score_p:+.2f} dot={pressure.dot_p:.2f}"
            f" wkt={pressure.wicket_p:.2f} prt={pressure.partnership_p:.2f}",
            SEP,
        ]

        lines.append(
            f"  {'CONTEXT':<22} {'CACHE':<6} {'BALLS':>7}  {'RELIAB':>6}  {'BASE_WT':>7}  {'EFF_WT':>7}  {'K':>4}"
        )
        lines.append(f"  {'─'*68}")

        def _ctx_row(label, hit, balls, rel, base_wt, eff_wt, k=1.0):
            balls_s = f"{balls:>7.2f}" if balls else f"{'—':>7}"
            rel_s   = f"{rel:>6.3f}" if rel is not None else f"{'—':>6}"
            k_s     = f"{k:>4.1f}" if k != 1.0 else f"{'1':>4}"
            return (f"  {label:<22} {'HIT' if hit else 'MISS':<6} {balls_s}  {rel_s}  "
                    f"{base_wt:>7.4f}  {eff_wt:>7.4f}  {k_s}")

        lines.append(_ctx_row(f"batter [{batter_name[:12]}]", batter_hit, batter_balls, batter_rel,
                               base_w['batter'], eff_w['batter'], _SHARPNESS_K))
        lines.append(_ctx_row(f"bowler [{bowler_name[:12]}]", bowler_hit, bowler_balls, bowler_rel,
                               base_w['bowler'], eff_w['bowler'], _SHARPNESS_K))
        lines.append(_ctx_row(f"matchup [head-to-head]", matchup_hit, matchup_balls, matchup_rel,
                               base_w['matchup'], eff_w['matchup'], _SHARPNESS_K))
        lines.append(_ctx_row(f"phase [{phase}]",       phase_hit,   None, None,
                               base_w['phase'],   eff_w['phase']))
        _ms_src = "p" if _player_ms_hit else "g"
        lines.append(_ctx_row(f"milestone[{_ms_src}][{milestone}]", mlstn_hit, None, None,
                               base_w['milestone'], eff_w['milestone'], _MILESTONE_K))
        lines.append(_ctx_row(f"innings [{inning}]",    inn_hit,     None, None,
                               base_w['innings'],  eff_w['innings']))
        lines.append(_ctx_row("venue",                  venue_hit,   None, None,
                               base_w['venue'],    eff_w['venue']))
        lines.append(_ctx_row("tournament",             tourn_hit,   None, None,
                               base_w['tournament'], eff_w['tournament']))

        dropped = base_w['venue'] * (not venue_hit) + base_w['tournament'] * (not tourn_hit)
        if dropped > 1e-4:
            lines.append(f"  [Dropped {dropped:.4f} weight from missing venue/tournament — redistributed to active contexts]")

        lines.append("")
        lines.append(
            f"  {'OUTCOME KEY':<38} {'BASE':>6} {'BAT':>6} {'BOWL':>6} "
            f"{'MTCH':>6} {'PHASE':>6} {'MLSTN':>6} {'INN':>6} {'CAT':<10} {'RAW_W':>7} {'PROB%':>6}"
        )
        lines.append(f"  {'─'*110}")

        batter_probs  = self.batter_cache.get(batter_id,    self.baseline_outcome_probs) if batter_id   else self.baseline_outcome_probs
        bowler_probs  = self.bowler_cache.get(bowler_id,    self.baseline_outcome_probs) if bowler_id   else self.baseline_outcome_probs
        matchup_probs = self.matchup_cache.get(matchup_key, self.baseline_outcome_probs) if matchup_key else self.baseline_outcome_probs
        # Use blended phase (same as _compute_distribution) and player-specific milestone
        phase_probs   = self._compute_phase_probs(batter_id, bowler_id, phase)
        _player_ms    = self.player_milestone_cache.get(batter_id, {}) if batter_id else {}
        mlstn_probs   = _player_ms.get(milestone) or self.milestone_cache.get(milestone) or self.baseline_outcome_probs
        inn_probs     = self.innings_cache.get(inning,   self.baseline_outcome_probs)

        raw_weights_map = getattr(self, '_last_raw_weights', {})

        sorted_items = sorted(distribution.items(), key=lambda kv: kv[1], reverse=True)

        for outcome_key, final_prob in sorted_items:
            base  = self.baseline_outcome_probs.get(outcome_key, 0.0)
            bat   = batter_probs.get(outcome_key,  base)
            bowl  = bowler_probs.get(outcome_key,  base)
            mtch  = matchup_probs.get(outcome_key, base)
            ph    = phase_probs.get(outcome_key,   base)
            ml    = mlstn_probs.get(outcome_key,   base)
            inn   = inn_probs.get(outcome_key,     base)
            cat   = _outcome_category(outcome_key)
            raw_w = raw_weights_map.get(outcome_key, 0.0)
            mark  = " ◀" if outcome_key == selected_key else ""
            lines.append(
                f"  {str(outcome_key):<38} {base:>6.4f} {bat:>6.4f} {bowl:>6.4f} "
                f"{mtch:>6.4f} {ph:>6.4f} {ml:>6.4f} {inn:>6.4f} {cat:<10} {raw_w:>7.4f} {final_prob*100:>5.2f}%{mark}"
            )

        sel_prob = distribution.get(selected_key, 0.0)
        lines.append("")
        lines.append(
            f"  ▶ SELECTED  {str(selected_key):<42}  prob={sel_prob*100:.2f}%   "
            f"category={_outcome_category(selected_key)}"
        )
        lines.append(SEP)

        log.debug("\n".join(lines))

    # ── Prediction ─────────────────────────────────────────────────────────────

    def predict_next_ball(self, match: SimulationMatch) -> BallOutcome:
        batter = match.striker
        bowler = match.current_bowler
        inning = match.current_inning
        over   = match.current_over + 1   # 0-indexed → 1-indexed

        batter_id      = batter.id if batter else None
        bowler_id      = bowler.id if bowler else None
        batter_runs    = batter.runs_scored if batter else 0
        wickets_fallen = match.current_batting_team.total_wickets if match.current_batting_team else 0
        matchup_key    = (batter_id, bowler_id) if batter_id and bowler_id else None

        venue_probs = self._get_player_venue_probs(batter_id)
        tourn_probs = self.tournament_cache if self.tournament_cache else self.baseline_outcome_probs

        # On a free hit the batter attacks without dismissal fear — nullify the matchup
        # weight so the batter's own profile dominates (and the T20 70/30 batter/bowler
        # redistribution kicks in). The matchup context still shapes the delivery type
        # via _compute_distribution but with zero exponent influence.
        eff_w_matchup = None if getattr(match, 'is_free_hit', False) else matchup_key
        eff_w = self._compute_effective_weights(batter_id, bowler_id, eff_w_matchup)

        # Super over: substitute all-over batter cache with the batter's own death-phase
        # distribution so each batter's death-over tendencies drive the simulation.
        # Only applied when the batter has at least _PHASE_BATTER_THRESHOLD balls in that
        # phase — below the threshold the sample is too sparse and all-over stats are
        # more reliable. Bowler is left as-is — the phase component already anchors the
        # blend to the death phase, so overriding it too would double-count and inflate
        # wicket probability. Matchup has no phase-specific variant so it stays as-is.
        _override_batter: Optional[dict] = None
        _override_bowler: Optional[dict] = None
        if getattr(match, 'is_super_over', False) and batter_id:
            _phase     = MatchRules.get_fine_grained_phase(over, self._match_format)
            _bp        = self.batter_phase_cache.get(batter_id, {})
            _bp_counts = self.batter_phase_ball_counts.get(batter_id, {})
            _threshold = _PHASE_BATTER_THRESHOLD.get(self._match_format, 30)
            for _ph in (_phase, 'death2', 'death1'):
                _candidate = _bp.get(_ph)
                if _candidate and _bp_counts.get(_ph, 0) >= _threshold:
                    _override_batter = _candidate
                    break

        distribution = self._compute_distribution(
            batter_id              = batter_id,
            bowler_id              = bowler_id,
            inning                 = inning,
            over_1indexed          = over,
            batter_runs            = batter_runs,
            venue_probs            = venue_probs,
            tourn_probs            = tourn_probs,
            _eff_w                 = eff_w,
            wickets_fallen         = wickets_fallen,
            _override_batter_probs = _override_batter,
            _override_bowler_probs = _override_bowler,
        )

        ordered_keys = list(distribution.keys())
        weights      = list(distribution.values())

        pressure = self._compute_pressure(match)
        pressure.batter_runs = batter_runs
        weights  = self._apply_pressure_modifier(weights, ordered_keys, pressure)

        if getattr(match, 'is_free_hit', False):
            weights = apply_free_hit_modifier(weights, ordered_keys)

        total = sum(weights)
        normalised = [w / total for w in weights] if total > 0 else [1.0 / len(weights)] * len(weights)

        _MAX_RESAMPLE = 5
        for _attempt in range(_MAX_RESAMPLE):
            selected_key = random.choices(ordered_keys, weights=normalised, k=1)[0]
            runs_batter, runs_extras, outcome_type, outcome_kind = selected_key
            if not self._is_invalid_outcome(outcome_kind, bowler_id):
                break
            log.debug(
                "[predict] Resampling invalid outcome '%s' for bowler %s (attempt %d)",
                outcome_kind, bowler_id, _attempt + 1,
            )
        else:
            if self._is_invalid_outcome(outcome_kind, bowler_id):
                selected_key = (0, 0, 'Dot', None)
                runs_batter, runs_extras, outcome_type, outcome_kind = selected_key

        batter_name = batter.name if batter else "unknown"
        bowler_name = bowler.name if bowler else "unknown"
        ball_label  = f"Inn{inning} Ov{over}"
        phase       = MatchRules.get_fine_grained_phase(over, self._match_format)
        milestone   = _get_milestone(batter_runs)

        if log.isEnabledFor(logging.DEBUG):
            self._log_prediction_detail(
                ball_label   = ball_label,
                batter_name  = batter_name,
                bowler_name  = bowler_name,
                batter_id    = batter_id,
                bowler_id    = bowler_id,
                matchup_key  = matchup_key,
                phase        = phase,
                milestone    = milestone,
                inning       = inning,
                eff_w        = eff_w,
                venue_probs  = venue_probs,
                tourn_probs  = tourn_probs,
                distribution = distribution,
                selected_key = selected_key,
                pressure     = pressure,
            )

        outcome_player = self._assign_fielder(outcome_type, outcome_kind, bowler, match)

        if outcome_type == 'Wicket':
            result_desc = f"WICKET({outcome_kind})"
        elif outcome_type == 'Extras':
            result_desc = f"EXTRA({outcome_kind}, {runs_extras}r)"
        else:
            result_desc = f"{runs_batter} runs"

        pressure_s = (
            f"  [s={pressure.score_p:+.2f} d={pressure.dot_p:.2f}"
            f" w={pressure.wicket_p:.2f} P={pressure.partnership_p:.2f}]"
        )
        log.info(
            "  %-12s %-18s vs %-20s  →  %-20s [%s/%s]%s",
            ball_label, batter_name, bowler_name, result_desc, phase, milestone, pressure_s,
        )

        return BallOutcome(
            runs_batter    = runs_batter,
            runs_extras    = runs_extras,
            is_wicket      = (outcome_type == 'Wicket'),
            wicket_kind    = outcome_kind if outcome_type == 'Wicket' else None,
            extras_type    = outcome_kind if outcome_type == 'Extras' else None,
            outcome_player = outcome_player,
        )

    def _assign_fielder(self, outcome_type, outcome_kind, bowler, match):
        """Assigns a fielder for caught/run-out/stumped dismissals."""
        is_fielded = (
            outcome_type == 'Wicket'
            and outcome_kind in ['caught', 'run out', 'stumped', 'c and b', 'caught and bowled']
        )
        if not is_fielded:
            return None

        if outcome_kind in ['c and b', 'caught and bowled']:
            return bowler

        if outcome_kind == 'stumped':
            return match.current_bowling_team.wicket_keeper if match.current_bowling_team else None

        if match.current_bowling_team and match.current_bowling_team.inning_players:
            eligible = [ip for ip in match.current_bowling_team.inning_players if ip != bowler]
            if eligible:
                fw = [self.fielding_cache.get(f.id, 1) for f in eligible]
                return random.choices(eligible, weights=fw, k=1)[0]
            return bowler

        return None


# ── Format-specific subclasses ─────────────────────────────────────────────────

class T20EnhancedHistoricalStatsStrategy(EnhancedBaseHistoricalStatsStrategy):
    @property
    def WEIGHTS(self):
        # Optimised via optimize_params.py on 5k held-out deliveries (Δ log-loss = -0.038).
        # Matchup dominates because batter×bowler head-to-head history captures the
        # specific context better than global batter/bowler averages.
        # batter/innings kept at a small floor so reliability redistribution still works
        # when matchup data is absent.
        return {
            'batter':     0.03,
            'bowler':     0.10,
            'matchup':    0.44,
            'phase':      0.19,
            'venue':      0.05,
            'tournament': 0.04,
            'innings':    0.02,
            'milestone':  0.13,
        }


class ODIEnhancedHistoricalStatsStrategy(EnhancedBaseHistoricalStatsStrategy):
    @property
    def WEIGHTS(self):
        # Optimised on 5k held-out deliveries (Δ log-loss = -0.045).
        # Phase still matters in ODI but matchup is the primary signal.
        return {
            'batter':     0.03,
            'bowler':     0.08,
            'matchup':    0.46,
            'phase':      0.21,
            'venue':      0.06,
            'tournament': 0.05,
            'innings':    0.02,
            'milestone':  0.09,
        }


class TestEnhancedHistoricalStatsStrategy(EnhancedBaseHistoricalStatsStrategy):
    @property
    def WEIGHTS(self):
        # Optimised on 5k held-out deliveries (Δ log-loss = -0.030).
        # Innings context matters more in Test (3rd/4th innings are very different).
        # Phase weight is lower because Test phases are broader buckets.
        return {
            'batter':     0.03,
            'bowler':     0.06,
            'matchup':    0.37,
            'phase':      0.12,
            'venue':      0.06,
            'tournament': 0.06,
            'innings':    0.16,
            'milestone':  0.14,
        }
