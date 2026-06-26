"""
Unit tests for EnhancedBaseHistoricalStatsStrategy.

Covers:
1. Batter phase cache prioritisation: phase-specific distribution is used
   when enough balls exist, and career distribution is used as fallback.
2. Dynamic par score / pressure context: wicket-aware score_p logic.
"""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass
from typing import Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.strategies.ball_outcome_prediction.enhanced_historical_stats.strategy import (
    EnhancedBaseHistoricalStatsStrategy,
    PressureContext,
)
from simulator.entities.rules import MatchRules


# ── Minimal strategy subclass for testing ────────────────────────────────────

class _TestStrategy(EnhancedBaseHistoricalStatsStrategy):
    """Concrete subclass with no-op DB calls so we can set caches manually."""

    _FORMAT = 'T20'

    @property
    def WEIGHTS(self) -> dict:
        return {
            'batter': 0.20, 'bowler': 0.20, 'matchup': 0.10, 'phase': 0.20,
            'venue': 0.05, 'tournament': 0.05, 'innings': 0.10, 'milestone': 0.10,
        }

    def __init__(self):
        # Bypass __init__ entirely — set attributes manually
        self._match_format = 'T20'
        self.baseline_outcome_probs = {(0, 0, 'Dot', None): 0.40, (4, 0, 'Runs', None): 0.12,
                                        (0, 0, 'Wicket', 'bowled'): 0.06, (1, 0, 'Runs', None): 0.42}
        self.position_baseline = {}
        self.batter_cache = {}
        self.batter_ball_counts = {}
        self.batter_phase_cache = {}
        self.batter_phase_ball_counts = {}
        self.bowler_cache = {}
        self.bowler_ball_counts = {}
        self.matchup_cache = {}
        self.phase_cache = {}
        self.milestone_cache = {}
        self.player_milestone_cache = {}
        self.venue_cache = {}
        self.tournament_cache = {}
        self.innings_cache = {}
        self.parttime_bowler_probs = self.baseline_outcome_probs
        self._reliability_thresholds = {'batter': 500, 'bowler': 500, 'matchup': 100,
                                         'phase': 1000, 'venue': 2000, 'tournament': 1000,
                                         'innings': 2000, 'milestone': 500}
        from simulator.strategies.ball_outcome_prediction.enhanced_historical_stats.strategy import _outcome_category
        self._ordered_keys = list(self.baseline_outcome_probs.keys())
        self._key_categories = {k: _outcome_category(k) for k in self._ordered_keys}

    def init_model(self, match):
        pass

    def predict_outcome(self, match):
        pass


# ── Batter phase cache tests ──────────────────────────────────────────────────

CAREER_DIST = {
    (0, 0, 'Dot', None): 0.40,
    (4, 0, 'Runs', None): 0.10,
    (0, 0, 'Wicket', 'bowled'): 0.06,
    (1, 0, 'Runs', None): 0.44,
}

PHASE_DIST = {
    (0, 0, 'Dot', None): 0.20,  # much lower dot rate in death phase
    (4, 0, 'Runs', None): 0.30,  # much higher boundary rate in death phase
    (0, 0, 'Wicket', 'bowled'): 0.05,
    (6, 0, 'Runs', None): 0.10,
    (1, 0, 'Runs', None): 0.35,
}

BATTER_ID = 42
BOWLER_ID = 99


class TestBatterPhaseCache:
    """Phase-specific distribution takes priority over career distribution."""

    def setup_method(self):
        self.strat = _TestStrategy()
        self.strat.batter_cache[BATTER_ID] = CAREER_DIST
        # Give the batter full reliability so batter context has real weight in blending
        self.strat.batter_ball_counts[BATTER_ID] = 500

    def _compute(self, over_1indexed=18, phase_balls=50):
        """Helper: compute distribution for over 18 (death2 in T20)."""
        phase = MatchRules.get_fine_grained_phase(over_1indexed, 'T20')
        if phase_balls > 0:
            self.strat.batter_phase_cache[BATTER_ID] = {phase: PHASE_DIST}
            self.strat.batter_phase_ball_counts[BATTER_ID] = {phase: phase_balls}
        else:
            self.strat.batter_phase_cache.pop(BATTER_ID, None)
            self.strat.batter_phase_ball_counts.pop(BATTER_ID, None)
        return self.strat._compute_distribution(
            batter_id=BATTER_ID,
            bowler_id=None,
            inning=1,
            over_1indexed=over_1indexed,
            batter_runs=0,
            venue_probs={},
            tourn_probs={},
            wickets_fallen=0,
        )

    def test_phase_dist_used_when_sufficient_balls(self):
        dist_full  = self._compute(phase_balls=50)  # T20 threshold is 30
        dist_none  = self._compute(phase_balls=0)   # no phase data
        full_bp  = sum(v for (rb, rx, ot, ok), v in dist_full.items() if rb >= 4)
        none_bp  = sum(v for (rb, rx, ot, ok), v in dist_none.items() if rb >= 4)
        # Phase dist has 0.30 boundary rate; baseline is 0.12.
        # batter_phase blends 35% phase / 65% global so the effect is moderate,
        # but with sufficient data the boundary_prob should be above baseline (0.12)
        # and above the no-phase baseline (which batter alone drags below 0.12).
        assert full_bp > 0.12, f"Expected phase lift above baseline, boundary_prob={full_bp}"
        assert full_bp > none_bp, f"Expected more boundaries with phase data, full={full_bp} none={none_bp}"

    def test_career_dist_used_when_insufficient_balls(self):
        dist = self._compute(phase_balls=10)  # Below T20 threshold of 30
        boundary_prob = sum(v for (rb, rx, ot, ok), v in dist.items() if rb >= 4)
        # Career distribution has 0.10 boundary rate — should be closer to that
        assert boundary_prob < 0.20, f"Expected career distribution, boundary_prob={boundary_prob}"

    def test_career_dist_used_when_no_phase_data(self):
        dist = self._compute(phase_balls=0)  # No phase data at all
        boundary_prob = sum(v for (rb, rx, ot, ok), v in dist.items() if rb >= 4)
        assert boundary_prob < 0.20, f"Expected career distribution, boundary_prob={boundary_prob}"

    def test_phase_dist_exact_boundary_ball_count_triggers_upgrade(self):
        """Ball count exactly at threshold should trigger the phase distribution."""
        dist_at   = self._compute(phase_balls=30)   # exactly at T20 threshold
        dist_none = self._compute(phase_balls=0)    # no phase data baseline
        bp_at   = sum(v for (rb, rx, ot, ok), v in dist_at.items()   if rb >= 4)
        bp_none = sum(v for (rb, rx, ot, ok), v in dist_none.items() if rb >= 4)
        # At threshold the batter-phase weight is at its maximum (bw=1.0×max_w),
        # so boundary_prob should be above baseline (0.12) and above the no-phase case.
        assert bp_at > 0.12,   f"Threshold should activate phase lift, boundary_prob={bp_at}"
        assert bp_at > bp_none, f"Threshold case should dominate no-phase case, at={bp_at} none={bp_none}"

    def test_phase_dist_one_below_threshold_uses_career(self):
        dist = self._compute(phase_balls=29)  # one below threshold
        boundary_prob = sum(v for (rb, rx, ot, ok), v in dist.items() if rb >= 4)
        assert boundary_prob < 0.20, f"Below threshold should use career dist, boundary_prob={boundary_prob}"

    def test_different_phases_use_correct_dist(self):
        """A powerplay over should NOT use death2's phase distribution."""
        phase = 'death2'
        self.strat.batter_phase_cache[BATTER_ID] = {phase: PHASE_DIST}
        self.strat.batter_phase_ball_counts[BATTER_ID] = {phase: 100}
        # Over 1 → powerplay, death2 cache doesn't apply
        dist = self.strat._compute_distribution(
            batter_id=BATTER_ID,
            bowler_id=None,
            inning=1,
            over_1indexed=1,
            batter_runs=0,
            venue_probs={},
            tourn_probs={},
            wickets_fallen=0,
        )
        boundary_prob = sum(v for (rb, rx, ot, ok), v in dist.items() if rb >= 4)
        # Should use career (0.10 boundary), not phase death2 (0.30)
        assert boundary_prob < 0.20, f"Wrong phase dist applied, boundary_prob={boundary_prob}"


# ── Dynamic pressure / par score tests ───────────────────────────────────────

class TestDynamicPressure:
    """_compute_pressure uses wicket-aware logic, not a fixed par_rr."""

    def setup_method(self):
        self.strat = _TestStrategy()

    def _make_match(self, total_runs, total_balls, total_wickets, current_over=14, fmt='T20'):
        match = MagicMock()
        match.current_over = current_over
        match.match_format = fmt
        match.target_score = None   # innings 1 (no target)
        match.overs_per_innings = 20
        match.balls_per_over = 6
        match.innings = []          # empty → no deliveries to iterate
        batting = MagicMock()
        batting.total_runs = total_runs
        batting.total_balls = total_balls
        batting.total_wickets = total_wickets
        match.current_batting_team = batting
        match.current_bowling_team = MagicMock()
        return match, batting

    def test_score_p_neutral_with_plenty_wickets_in_hand(self):
        """≥5 wickets remaining in non-death over → score_p = 0.0 (neutral)."""
        match, _ = self._make_match(total_runs=60, total_balls=84, total_wickets=3,
                                     current_over=8, fmt='T20')
        ctx = self.strat._compute_pressure(match)
        assert ctx.score_p == pytest.approx(0.0, abs=1e-9)

    def test_score_p_negative_when_many_wickets_lost_in_non_death(self):
        """Fewer than 5 wickets remaining in mid-over → negative score_p."""
        match, _ = self._make_match(total_runs=80, total_balls=84, total_wickets=6,
                                     current_over=8, fmt='T20')
        ctx = self.strat._compute_pressure(match)
        assert ctx.score_p < 0.0, f"Expected negative score_p, got {ctx.score_p}"

    def test_score_p_positive_in_death_with_wickets(self):
        """Death over with many wickets in hand → positive score_p (attack)."""
        match, _ = self._make_match(total_runs=120, total_balls=90, total_wickets=2,
                                     current_over=16, fmt='T20')
        ctx = self.strat._compute_pressure(match)
        assert ctx.score_p >= 0.0, f"Expected non-negative score_p in death with wkts, got {ctx.score_p}"

    def test_wkts_remaining_tracked_in_context(self):
        match, _ = self._make_match(total_runs=100, total_balls=90, total_wickets=4,
                                     current_over=12, fmt='T20')
        ctx = self.strat._compute_pressure(match)
        assert ctx.wkts_remaining == 6  # 10 - 4

    def test_score_p_bounded(self):
        """score_p should never exceed ±0.40."""
        for wkts_lost in range(0, 10):
            match, _ = self._make_match(total_runs=100, total_balls=90,
                                         total_wickets=wkts_lost, current_over=16, fmt='T20')
            ctx = self.strat._compute_pressure(match)
            assert -0.40 <= ctx.score_p <= 0.40, (
                f"score_p={ctx.score_p} out of bounds for wkts_lost={wkts_lost}"
            )
