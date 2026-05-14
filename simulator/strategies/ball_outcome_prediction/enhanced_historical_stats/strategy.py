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
import time
from abc import abstractmethod
from dataclasses import dataclass
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

log = get_logger()

# ── Multiplier bounds ──────────────────────────────────────────────────────────
_BASELINE_EPSILON = 1e-6
_RATIO_MIN        = 0.1
_RATIO_MAX        = 10.0

# ── Prob^k sharpness ──────────────────────────────────────────────────────────
_SHARPNESS_K: float = 2.5
_MILESTONE_K: float = 3.0

# ── Minimum balls before a context is considered reliable (linear ramp) ────────
_RELIABILITY_THRESHOLDS: Dict[str, Dict[str, int]] = {
    'T20':  {'batter': 100, 'bowler': 100, 'matchup': 30},
    'ODI':  {'batter': 150, 'bowler': 150, 'matchup': 50},
    'Test': {'batter': 200, 'bowler': 200, 'matchup': 60},
}

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
        self.venue_cache      = {}
        self.player_venue_cache: dict = {}  # {player_id: (probs, ball_count)}
        self.tournament_cache = {}
        self.innings_cache    = {}
        self.phase_cache      = {}
        self.milestone_cache  = {}
        self.fielding_cache   = {}
        self.baseline_outcome_probs = {}

        self.batter_ball_counts  = {}
        self.bowler_ball_counts  = {}
        self.matchup_ball_counts = {}

        self.batter_distinctiveness  = {}
        self.bowler_distinctiveness  = {}
        self.matchup_distinctiveness = {}

        self.spinner_ids: set = set()
        self._match_format = 'T20'

    @property
    @abstractmethod
    def WEIGHTS(self) -> dict:
        """
        Base context weights summing to 1.0.
        Keys: batter, bowler, matchup, phase, venue, tournament, innings, milestone.
        """

    # ── Initialisation ─────────────────────────────────────────────────────────

    def init_model(self, match: SimulationMatch):
        match_format = MatchRules.get_unified_format(getattr(match, 'match_format', 'T20'))
        gender = getattr(match, 'gender', 'male').lower()
        self._match_format = match_format

        log.info("[EnhancedStrategy] Initialising — format: %s (%s)", match_format, gender)

        all_player_ids = collect_player_ids(match)

        def _timed(label, fn, *args, **kwargs):
            t = time.perf_counter()
            result = fn(*args, **kwargs)
            log.info("[EnhancedModel]   %-40s  %.2fs", label, time.perf_counter() - t)
            return result

        batters_data  = _timed("batters_with_counts",  self.repo.get_batters_distribution_with_counts,  all_player_ids, match_format, gender)
        bowlers_data  = _timed("bowlers_with_counts",  self.repo.get_bowlers_distribution_with_counts,  all_player_ids, match_format, gender)
        matchups_data = _timed("matchups_with_counts", self.repo.get_matchup_distribution_with_counts,  all_player_ids, all_player_ids, match_format, gender)

        self.batter_cache       = {pid: d[0] for pid, d in batters_data.items()}
        self.batter_ball_counts = {pid: d[1] for pid, d in batters_data.items()}
        self.bowler_cache       = {pid: d[0] for pid, d in bowlers_data.items()}
        self.bowler_ball_counts = {pid: d[1] for pid, d in bowlers_data.items()}
        self.matchup_cache      = {pair: d[0] for pair, d in matchups_data.items()}
        self.matchup_ball_counts = {pair: d[1] for pair, d in matchups_data.items()}

        self.phase_cache            = _timed("phase_distribution",      self.repo.get_phase_distribution,             match_format, gender)
        self.milestone_cache        = _timed("milestone_global",         self.repo.get_batter_milestone_distribution,  match_format, gender)
        self.player_milestone_cache = _timed("milestone_per_player",     self.repo.get_player_milestone_distributions, all_player_ids, match_format, gender)
        self.innings_cache          = _timed("innings_distribution",     self.repo.get_innings_distribution,           match_format, gender)
        self.fielding_cache         = _timed("fielding_distribution",    self.repo.get_fielding_distribution,          match_format, gender)

        self.venue_cache      = load_venue_distribution(self.repo, match, match_format, gender, _timed, log)
        self.tournament_cache = load_tournament_distribution(self.repo, match, _timed)
        self.player_venue_cache = self._load_player_venue_cache(match, all_player_ids, match_format, gender, _timed)

        self.baseline_outcome_probs = _timed("full_aggregate_baseline", self.repo.get_full_aggregate_distribution, match_format, gender)
        if not self.baseline_outcome_probs:
            log.warning("[EnhancedStrategy] No aggregate data — using empirical prior.")
            self.baseline_outcome_probs = BASELINE_FALLBACK

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

        keeper_ids = _timed("wicket_keepers", self.repo.get_wicket_keepers, all_player_ids, gender)
        for team in (match.home_team, match.away_team):
            if team:
                for p in team.players:
                    p.is_keeper = (p.id in keeper_ids)

        self.spinner_ids = _timed("spinner_ids", self.repo.get_spinner_ids, all_player_ids, gender)

        log.info(
            "[EnhancedStrategy] Loaded → batters=%d bowlers=%d matchups=%d "
            "phases=%s milestones=%s baseline_keys=%d",
            len(self.batter_cache), len(self.bowler_cache), len(self.matchup_cache),
            list(self.phase_cache.keys()), list(self.milestone_cache.keys()),
            len(self.baseline_outcome_probs),
        )

    def _load_player_venue_cache(self, match, player_ids, match_format, gender, _timed) -> dict:
        """
        Loads per-player outcome distributions at this match's venue (or country fallback).
        Only called when a venue is already known; returns empty dict otherwise.
        """
        venue = getattr(match, 'venue', None)
        if not venue:
            return {}
        if venue.id:
            data = _timed("player_venue_distribution",
                          self.repo.get_player_venue_distribution,
                          player_ids, venue.id, match_format, gender)
            if data:
                return data
        if getattr(venue, 'country', None):
            return _timed("player_country_distribution",
                          self.repo.get_player_country_distribution,
                          player_ids, venue.country, match_format, gender)
        return {}

    def _get_player_venue_probs(self, batter_id: Optional[int]) -> dict:
        """
        Returns venue probability distribution for a specific batter.

        Blends the player's own venue stats with the general venue distribution.
        The player's weight ramps from 0 (no data) to 0.65 (≥60 balls at venue),
        so sparse data has little effect while a well-documented player's venue
        record meaningfully adjusts the distribution.
        """
        if not self.venue_cache:
            return self.baseline_outcome_probs
        if not batter_id or batter_id not in self.player_venue_cache:
            return self.venue_cache

        player_probs, ball_count = self.player_venue_cache[batter_id]
        alpha = min(0.65, ball_count / 60 * 0.65)
        if alpha < 0.01:
            return self.venue_cache

        all_keys = set(player_probs) | set(self.venue_cache)
        blended  = {
            k: alpha * player_probs.get(k, 0.0) + (1 - alpha) * self.venue_cache.get(k, 0.0)
            for k in all_keys
        }
        total = sum(blended.values())
        return {k: v / total for k, v in blended.items()} if total > 0 else self.venue_cache

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
            par_rr  = 8.0 if fmt == 'T20' else 5.0
            cur_rr  = (batting.total_runs / max(1, batting.total_balls)) * match.balls_per_over
            score_p = max(-0.35, min(0.35, (par_rr - cur_rr) / par_rr * 0.55))
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
            score_p       = score_p,
            dot_p         = dot_p,
            wicket_p      = wicket_p,
            partnership_p = partnership_p,
            match_format  = fmt,
            current_over  = match.current_over,
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

        adjusted = []
        for i, key in enumerate(ordered_keys):
            runs_batter, _, outcome_type, _ = key
            modifier = 1.0

            if net_attack > 0:
                if runs_batter >= 6:           modifier = 1.0 + net_attack * 0.28
                elif runs_batter == 4:         modifier = 1.0 + net_attack * 0.18
                elif runs_batter in (2, 3):    modifier = 1.0 + net_attack * 0.10
                elif outcome_type == 'Dot':    modifier = max(0.1, 1.0 - net_attack * 0.30)
                elif outcome_type == 'Wicket': modifier = 1.0 + net_attack * 0.25
            elif net_attack < 0:
                if runs_batter >= 4:           modifier = 1.0 + net_attack * 0.30
                elif outcome_type == 'Dot':    modifier = 1.0 - net_attack * 0.20

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
    ) -> Dict[tuple, float]:
        phase     = MatchRules.get_fine_grained_phase(over_1indexed, self._match_format)
        milestone = _get_milestone(batter_runs)
        matchup_key = (batter_id, bowler_id) if batter_id and bowler_id else None

        batter_probs   = self.batter_cache.get(batter_id,    self.baseline_outcome_probs) if batter_id  else self.baseline_outcome_probs
        bowler_probs   = self.bowler_cache.get(bowler_id,    self.baseline_outcome_probs) if bowler_id  else self.baseline_outcome_probs
        matchup_probs  = self.matchup_cache.get(matchup_key, self.baseline_outcome_probs) if matchup_key else self.baseline_outcome_probs
        phase_probs    = self.phase_cache.get(phase,     self.baseline_outcome_probs)
        _player_ms     = self.player_milestone_cache.get(batter_id, {}) if batter_id else {}
        milestone_probs = (
            _player_ms.get(milestone)
            or self.milestone_cache.get(milestone)
            or self.baseline_outcome_probs
        )
        innings_probs  = self.innings_cache.get(inning, self.baseline_outcome_probs)

        eff_w = _eff_w if _eff_w is not None else self._compute_effective_weights(batter_id, bowler_id, matchup_key)

        raw_weights  = []
        ordered_keys = list(self.baseline_outcome_probs.keys())

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

            cw = self._apply_category_relevance(eff_w, outcome_key)

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
            f"  {'CONTEXT':<22} {'CACHE':<6} {'BALLS':>6}  {'RELIAB':>6}  {'BASE_WT':>7}  {'EFF_WT':>7}  {'K':>4}"
        )
        lines.append(f"  {'─'*68}")

        def _ctx_row(label, hit, balls, rel, base_wt, eff_wt, k=1.0):
            balls_s = f"{balls:>6}" if balls else f"{'—':>6}"
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
            f"{'MTCH':>6} {'PHASE':>6} {'MLSTN':>6} {'INN':>6} {'CAT':<10} {'PROB%':>6}"
        )
        lines.append(f"  {'─'*100}")

        batter_probs  = self.batter_cache.get(batter_id,    self.baseline_outcome_probs) if batter_id   else self.baseline_outcome_probs
        bowler_probs  = self.bowler_cache.get(bowler_id,    self.baseline_outcome_probs) if bowler_id   else self.baseline_outcome_probs
        matchup_probs = self.matchup_cache.get(matchup_key, self.baseline_outcome_probs) if matchup_key else self.baseline_outcome_probs
        phase_probs   = self.phase_cache.get(phase,     self.baseline_outcome_probs)
        mlstn_probs   = self.milestone_cache.get(milestone, self.baseline_outcome_probs)
        inn_probs     = self.innings_cache.get(inning,   self.baseline_outcome_probs)

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
            mark  = " ◀" if outcome_key == selected_key else ""
            lines.append(
                f"  {str(outcome_key):<38} {base:>6.4f} {bat:>6.4f} {bowl:>6.4f} "
                f"{mtch:>6.4f} {ph:>6.4f} {ml:>6.4f} {inn:>6.4f} {cat:<10} {final_prob*100:>5.2f}%{mark}"
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

        batter_id   = batter.id if batter else None
        bowler_id   = bowler.id if bowler else None
        batter_runs = batter.runs_scored if batter else 0
        matchup_key = (batter_id, bowler_id) if batter_id and bowler_id else None

        venue_probs = self._get_player_venue_probs(batter_id)
        tourn_probs = self.tournament_cache if self.tournament_cache else self.baseline_outcome_probs

        eff_w = self._compute_effective_weights(batter_id, bowler_id, matchup_key)

        distribution = self._compute_distribution(
            batter_id     = batter_id,
            bowler_id     = bowler_id,
            inning        = inning,
            over_1indexed = over,
            batter_runs   = batter_runs,
            venue_probs   = venue_probs,
            tourn_probs   = tourn_probs,
            _eff_w        = eff_w,
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
        return {
            'batter':     0.22,
            'bowler':     0.22,
            'matchup':    0.14,
            'phase':      0.17,
            'venue':      0.05,
            'tournament': 0.04,
            'innings':    0.04,
            'milestone':  0.12,
        }


class ODIEnhancedHistoricalStatsStrategy(EnhancedBaseHistoricalStatsStrategy):
    @property
    def WEIGHTS(self):
        return {
            'batter':     0.10,
            'bowler':     0.13,
            'matchup':    0.11,
            'phase':      0.37,
            'venue':      0.06,
            'tournament': 0.05,
            'innings':    0.06,
            'milestone':  0.12,
        }


class TestEnhancedHistoricalStatsStrategy(EnhancedBaseHistoricalStatsStrategy):
    @property
    def WEIGHTS(self):
        return {
            'batter':     0.21,
            'bowler':     0.26,
            'matchup':    0.14,
            'phase':      0.08,
            'venue':      0.06,
            'tournament': 0.06,
            'innings':    0.04,
            'milestone':  0.15,
        }
