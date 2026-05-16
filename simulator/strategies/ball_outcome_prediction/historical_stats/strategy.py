"""
Historical Statistics Ball Outcome Strategy
============================================
For each delivery, this strategy uses historical match data to determine
the most statistically realistic outcome.

It uses a Relative Multiplicative Scaling model:
  - Start from a global baseline probability per outcome (e.g. "32% of T20 balls are dots")
  - Scale it up or down based on how each context (batter, bowler, venue, phase) differs from baseline
  - Sample randomly from the resulting weighted distribution

Outcome keys are 4-tuples stored throughout: (runs_batter, runs_extras, outcome_type, outcome_kind)
  e.g. (4, 0, 'Runs', None)         → batter hit a four, no extras
       (0, 1, 'Extras', 'Wide')     → wide ball, 1 run awarded to team
       (0, 0, 'Wicket', 'bowled')   → batter bowled for zero
       (0, 0, 'Dot', None)          → no run scored, no wicket
"""

import random
import time
from abc import abstractmethod
from collections import defaultdict

from db.stats_repository import StatsRepository
from simulator.entities.match import SimulationMatch
from simulator.entities.ball_outcome import BallOutcome
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

# Bounds for compute_context_multiplier
_BASELINE_EPSILON   = 1e-6
_RATIO_MIN          = 0.1
_RATIO_MAX          = 10.0
_AGGRESSION_HIGH    = 1.2
_AGGRESSION_LOW     = 0.8


def _batting_position_group(wickets_fallen: int) -> str:
    if wickets_fallen <= 2:
        return 'top_order'
    elif wickets_fallen <= 5:
        return 'middle_order'
    return 'lower_order'


def compute_context_multiplier(context_probability: float, baseline_probability: float, weight: float) -> float:
    """
    Returns a multiplier that represents how much a specific context (e.g. this batter,
    this bowler) shifts a given outcome probability relative to the global baseline.

    Formula: (context / baseline) ** weight

    Why a fractional exponent?
      Using a raw ratio would let one dominant context (e.g. a T20 powerplay) completely
      override all others. The exponent squashes the ratio towards 1.0 so that every
      context contributes proportionally rather than multiplicatively exploding.

    A multiplier of 1.0 means "this context matches the baseline — no effect".
    A multiplier > 1.0 means the outcome is more likely in this context.
    A multiplier < 1.0 means the outcome is less likely in this context.
    """
    if baseline_probability < _BASELINE_EPSILON:
        return 1.0

    raw_ratio    = context_probability / baseline_probability
    capped_ratio = max(_RATIO_MIN, min(_RATIO_MAX, raw_ratio))
    aggression   = _AGGRESSION_HIGH if capped_ratio > 1.0 else _AGGRESSION_LOW

    return (capped_ratio * aggression) ** weight


class BaseHistoricalStatsStrategy(BallOutcomeStrategy):
    """
    A data-driven ball outcome predictor backed by historical match statistics.

    init_model() is called once at match start to populate all caches from the database.
    predict_next_ball() is called once per delivery during the match simulation.
    """

    def __init__(self, repo=None):
        if repo is None:
            repo = StatsRepository()
        self.repo = repo

        self._initialized = False
        self.batter_cache       = {}
        self.bowler_cache       = {}
        self.venue_cache        = {}
        self.innings_cache      = {}
        self.overs_cache        = {}
        self.tournament_cache   = {}
        self.fielding_cache     = {}
        self.position_baseline  = {}
        self.baseline_outcome_probs = {}

    @property
    @abstractmethod
    def WEIGHTS(self) -> dict:
        """Probability weights for each context dimension: batter, bowler, over, venue, tournament, innings."""

    def init_model(self, match: SimulationMatch):
        """
        Loads all probability distributions from the database before the first ball.
        Also builds the dynamic global baseline from real innings data.
        """
        if self._initialized:
            return

        from simulator.entities.rules import MatchRules
        match_format = MatchRules.get_unified_format(getattr(match, 'match_format', 'T20'))
        gender = getattr(match, 'gender', 'male').lower()
        log.info(f"[Strategy] Initializing probability matrices — format: {match_format} ({gender})")

        all_player_ids = collect_player_ids(match)

        def _timed(label, fn, *args, **kwargs):
            t = time.perf_counter()
            result = fn(*args, **kwargs)
            log.info("[OutcomeModel]   %-38s  %.2fs", label, time.perf_counter() - t)
            return result

        self.batter_cache = _timed("batters_distribution", self.repo.get_batters_distribution,  all_player_ids, match_format, gender)
        self.bowler_cache = _timed("bowlers_distribution", self.repo.get_bowlers_distribution,  all_player_ids, match_format, gender)

        self.venue_cache      = load_venue_distribution(self.repo, match, match_format, gender, _timed, log)
        self.tournament_cache = load_tournament_distribution(self.repo, match, _timed)

        self.innings_cache     = _timed("innings_distribution",  self.repo.get_innings_distribution,       match_format, gender)
        self.overs_cache       = _timed("overs_distribution",    self.repo.get_overs_distribution,         match_format, gender)
        self.fielding_cache    = _timed("fielding_distribution",  self.repo.get_fielding_distribution,      match_format, gender)
        self.position_baseline = _timed("position_baseline",     self.repo.get_batting_position_baseline,  match_format, gender)

        self.baseline_outcome_probs = self._build_baseline()

        log.info(
            f"[Strategy] Stats loaded → Batters: {len(self.batter_cache)}, "
            f"Bowlers: {len(self.bowler_cache)}, "
            f"Venue Mapped: {bool(self.venue_cache)}, "
            f"Tournament Mapped: {bool(self.tournament_cache)}, "
            f"Baseline outcomes: {len(self.baseline_outcome_probs)}"
        )
        self._initialized = True

    def _build_baseline(self) -> dict:
        """
        Computes the global baseline by averaging first and second innings distributions.
        The result is a normalised probability dict over all known outcome keys.
        """
        innings_1 = self.innings_cache.get(1, {})
        innings_2 = self.innings_cache.get(2, {})

        combined = defaultdict(float)
        for outcome_key in set(innings_1.keys()).union(innings_2.keys()):
            combined[outcome_key] = (innings_1.get(outcome_key, 0) + innings_2.get(outcome_key, 0)) / 2.0

        total = sum(combined.values())

        if total > 0:
            return {key: probability / total for key, probability in combined.items()}

        log.warning("[Strategy] innings_cache is empty; falling back to empirical baseline distribution.")
        return BASELINE_FALLBACK

    def predict_next_ball(self, match: SimulationMatch) -> BallOutcome:
        """
        Predicts the outcome of one delivery using the Relative Multiplicative Scaling model.

        Steps:
          1. Fetch the probability vector for each context (batter, bowler, venue, over, innings)
          2. For every possible outcome key, multiply the baseline by each context's multiplier
          3. Normalise the combined weights and randomly sample one outcome
          4. Assign a fielder if the outcome is a catch or run-out
        """
        batter         = match.striker
        bowler         = match.current_bowler
        current_inning = match.current_inning
        current_over   = match.current_over + 1   # 0-indexed → 1-indexed for lookup

        batter_name = batter.name if batter else "unknown batter"
        bowler_name = bowler.name if bowler else "unknown bowler"
        ball_label  = f"Inn{current_inning} Ov{current_over}"

        wickets_fallen = match.current_batting_team.total_wickets if match.current_batting_team else 0
        pos_group = _batting_position_group(wickets_fallen)
        pos_baseline = self.position_baseline.get(pos_group, self.baseline_outcome_probs)

        batter_outcome_probs  = self.batter_cache.get(batter.id, pos_baseline) if batter else pos_baseline
        bowler_outcome_probs  = self.bowler_cache.get(bowler.id, self.baseline_outcome_probs) if bowler else self.baseline_outcome_probs
        venue_outcome_probs   = self.venue_cache      if self.venue_cache      else self.baseline_outcome_probs
        tournament_probs      = self.tournament_cache if self.tournament_cache else self.baseline_outcome_probs
        innings_outcome_probs = self.innings_cache.get(current_inning, self.baseline_outcome_probs)
        over_outcome_probs    = self.overs_cache.get(current_over, self.baseline_outcome_probs)

        log.debug(
            f"{'─'*70}\n"
            f"  BALL  {ball_label}  |  Batter: {batter_name}  vs  Bowler: {bowler_name}\n"
            f"{'─'*70}"
        )
        log.debug(f"  [Batter cache hit?  {'YES' if batter and batter.id in self.batter_cache else 'NO — using baseline'}]")
        log.debug(f"  [Bowler cache hit?  {'YES' if bowler and bowler.id in self.bowler_cache else 'NO — using baseline'}]")
        log.debug(f"  [Venue cache hit?   {'YES' if self.venue_cache else 'NO — using baseline'}]")
        log.debug(f"  [Over  cache hit?   {'YES' if current_over in self.overs_cache else 'NO — using baseline'}]")

        all_outcome_keys = set(self.baseline_outcome_probs.keys())
        all_outcome_keys.update(
            batter_outcome_probs.keys(),
            bowler_outcome_probs.keys(),
            venue_outcome_probs.keys(),
            innings_outcome_probs.keys(),
            over_outcome_probs.keys(),
            tournament_probs.keys(),
        )

        ordered_keys     = list(all_outcome_keys)
        combined_weights = []

        log.debug(
            f"\n  {'OUTCOME KEY':<45} {'BASE':>7} {'BAT':>7} {'BOWL':>7} "
            f"{'VEN':>7} {'OVR':>7} {'INN':>7} {'TRN':>7}  "
            f"{'mBAT':>6} {'mBOL':>6} {'mOVR':>6}   {'FINAL':>8}"
        )
        log.debug(f"  {'-'*140}")

        for outcome_key in ordered_keys:
            baseline_prob = self.baseline_outcome_probs.get(outcome_key, 0.0001)

            batter_prob    = batter_outcome_probs.get(outcome_key, baseline_prob)
            bowler_prob    = bowler_outcome_probs.get(outcome_key, baseline_prob)
            venue_prob     = venue_outcome_probs.get(outcome_key, baseline_prob)
            tournament_prob = tournament_probs.get(outcome_key, baseline_prob)
            innings_prob   = innings_outcome_probs.get(outcome_key, baseline_prob)
            over_prob      = over_outcome_probs.get(outcome_key, baseline_prob)

            multiplier_batter  = compute_context_multiplier(batter_prob,     baseline_prob, weight=self.WEIGHTS['batter'])
            multiplier_bowler  = compute_context_multiplier(bowler_prob,     baseline_prob, weight=self.WEIGHTS['bowler'])
            multiplier_over    = compute_context_multiplier(over_prob,       baseline_prob, weight=self.WEIGHTS['over'])
            multiplier_venue   = compute_context_multiplier(venue_prob,      baseline_prob, weight=self.WEIGHTS['venue'])
            multiplier_tourn   = compute_context_multiplier(tournament_prob, baseline_prob, weight=self.WEIGHTS['tournament'])
            multiplier_innings = compute_context_multiplier(innings_prob,    baseline_prob, weight=self.WEIGHTS['innings'])

            final_weight = (
                baseline_prob
                * multiplier_batter
                * multiplier_bowler
                * multiplier_venue
                * multiplier_tourn
                * multiplier_innings
                * multiplier_over
            )
            combined_weights.append(final_weight)

            log.debug(
                f"  {str(outcome_key):<45} {baseline_prob:>7.4f} {batter_prob:>7.4f} {bowler_prob:>7.4f} "
                f"{venue_prob:>7.4f} {over_prob:>7.4f} {innings_prob:>7.4f} {tournament_prob:>7.4f}  "
                f"{multiplier_batter:>6.3f} {multiplier_bowler:>6.3f} {multiplier_over:>6.3f}   {final_weight:>8.5f}"
            )

        if getattr(match, 'is_free_hit', False):
            combined_weights = apply_free_hit_modifier(combined_weights, ordered_keys)

        total_weight = sum(combined_weights)
        if total_weight > 0:
            normalised_weights = [weight / total_weight for weight in combined_weights]
        else:
            normalised_weights = [1.0 / len(ordered_keys)] * len(ordered_keys)

        selected_key  = random.choices(ordered_keys, weights=normalised_weights, k=1)[0]
        selected_prob = normalised_weights[ordered_keys.index(selected_key)]

        runs_batter, runs_extras, outcome_type, outcome_kind = selected_key

        log.debug(
            f"\n  ▶ SELECTED: {str(selected_key):<45}  "
            f"norm_prob = {selected_prob:.5f}  ({selected_prob*100:.2f}%)"
        )

        outcome_player = self._assign_fielder(outcome_type, outcome_kind, bowler, bowler_name, match)

        if outcome_type == 'Wicket':
            result_description = f"WICKET({outcome_kind})"
        elif outcome_type == 'Extras':
            result_description = f"EXTRA({outcome_kind}, {runs_extras}r)"
        else:
            result_description = f"{runs_batter} runs"

        log.info(f"  {ball_label:<12} {batter_name:<18} vs {bowler_name:<20}  →  {result_description}")

        return BallOutcome(
            runs_batter=runs_batter,
            runs_extras=runs_extras,
            is_wicket=(outcome_type == 'Wicket'),
            wicket_kind=outcome_kind if outcome_type == 'Wicket' else None,
            extras_type=outcome_kind if outcome_type == 'Extras' else None,
            outcome_player=outcome_player
        )

    def _assign_fielder(self, outcome_type, outcome_kind, bowler, bowler_name, match):
        """Assigns a fielder for caught/run-out/stumped dismissals."""
        is_fielded_dismissal = (
            outcome_type == 'Wicket'
            and outcome_kind in ['caught', 'run out', 'stumped', 'c and b', 'caught and bowled']
        )
        if not is_fielded_dismissal:
            return None

        if outcome_kind in ['c and b', 'caught and bowled']:
            log.debug(f"  ▶ Fielder: {bowler_name} (caught and bowled)")
            return bowler

        if match.current_bowling_team and match.current_bowling_team.inning_players:
            eligible_fielders = [
                ip for ip in match.current_bowling_team.inning_players if ip != bowler
            ]
            if eligible_fielders:
                fielder_weights = [self.fielding_cache.get(fielder.id, 1) for fielder in eligible_fielders]
                outcome_player  = random.choices(eligible_fielders, weights=fielder_weights, k=1)[0]
                log.debug(f"  ▶ Fielder: {outcome_player.name}  (weighted by fielding history)")
                return outcome_player
            log.debug(f"  ▶ Fielder: {bowler_name} (only fielder available)")
            return bowler

        return None


class T20HistoricalStatsStrategy(BaseHistoricalStatsStrategy):
    @property
    def WEIGHTS(self):
        return {
            'batter': 0.291,
            'bowler': 0.302,
            'over': 0.274,
            'venue': 0.052,
            'tournament': 0.048,
            'innings': 0.032
        }


class ODIHistoricalStatsStrategy(BaseHistoricalStatsStrategy):
    @property
    def WEIGHTS(self):
        return {
            'batter': 0.109,
            'bowler': 0.193,
            'over': 0.543,
            'venue': 0.052,
            'tournament': 0.063,
            'innings': 0.041
        }


class TestHistoricalStatsStrategy(BaseHistoricalStatsStrategy):
    @property
    def WEIGHTS(self):
        return {
            'batter': 0.270,
            'bowler': 0.358,
            'over': 0.084,
            'venue': 0.098,
            'tournament': 0.124,
            'innings': 0.068
        }
