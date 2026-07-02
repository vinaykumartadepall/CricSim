"""
Unit tests for HistoricalBowlingOrder in validation/run_comprehensive_v2.py.

Covers the toss-flip bug: when the simulation toss goes opposite to the historical
match, the bowling plan's player IDs belong to the batting team, not the bowling
team.  The fix detects this via set intersection and swaps the inning lookup.
"""
import sys
import os
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.strategies.bowling.historical.replay import HistoricalBowlingOrder
from simulator.entities.player import Player
from simulator.entities.inning_player import InningPlayer


# ── Helpers ──────────────────────────────────────────────────────────────────

def _player(pid):
    return Player(id=pid, name=f"Player{pid}")


def _inning_player(pid):
    return InningPlayer(player=_player(pid))


def _make_match(bowling_pids, current_inning=1, current_over=0, current_bowler=None):
    """Build a minimal mock SimulationMatch."""
    match = MagicMock()
    match.current_inning = current_inning
    match.current_over   = current_over
    match.current_bowler = current_bowler

    inning_players = [_inning_player(pid) for pid in bowling_pids]
    bowling_team   = MagicMock()
    bowling_team.inning_players = inning_players
    match.current_bowling_team  = bowling_team
    return match, inning_players


# ── Fixtures ─────────────────────────────────────────────────────────────────

# Historical match: Team A (pids 1-5) batted innings 1, Team B (pids 6-10) batted
# innings 2.  Therefore:
#   innings 1 bowlers = Team B (6-10)
#   innings 2 bowlers = Team A (1-5)
PLAN = {
    1: {0: 6, 1: 7, 2: 8, 3: 9, 4: 6, 5: 7},   # Team B bowled innings 1
    2: {0: 1, 1: 2, 2: 3, 3: 4, 4: 1, 5: 2},    # Team A bowled innings 2
}


# ── Tests: normal toss (matches historical) ───────────────────────────────────

class TestNormalToss:
    """Simulation toss matches the historical match — no flip needed."""

    def test_returns_correct_bowler_for_each_over(self):
        strategy = HistoricalBowlingOrder(PLAN)
        # Team B (pids 6-10) is bowling innings 1, same as historically.
        match, ips = _make_match(bowling_pids=[6, 7, 8, 9, 10], current_inning=1)
        for over, expected_pid in [(0, 6), (1, 7), (2, 8), (3, 9)]:
            match.current_over = over
            result = strategy.select_bowler(match)
            assert result.id == expected_pid, (
                f"Over {over}: expected pid {expected_pid}, got {result.id}"
            )

    def test_innings_2_lookup(self):
        strategy = HistoricalBowlingOrder(PLAN)
        # Team A (pids 1-5) is bowling innings 2, same as historically.
        match, _ = _make_match(bowling_pids=[1, 2, 3, 4, 5], current_inning=2)
        for over, expected_pid in [(0, 1), (1, 2), (2, 3)]:
            match.current_over = over
            assert strategy.select_bowler(match).id == expected_pid


# ── Tests: toss-flip (simulation opposite to historical) ─────────────────────

class TestTossFlip:
    """
    Toss went opposite to historical:
      - Simulation innings 1: Team A (pids 1-5) is bowling
      - Simulation innings 2: Team B (pids 6-10) is bowling

    Without the fix, plan[1][over] = Team B pid, not found in Team A's bowling
    team → falls back to eligible[0] (always the first player in list).

    With the fix, the strategy detects the flip and looks up plan[2] instead,
    finding the correct Team A bowlers.
    """

    def test_flip_innings1_returns_correct_bowler(self):
        strategy = HistoricalBowlingOrder(PLAN)
        # Team A (pids 1-5) bowling in simulation innings 1 (historically they batted)
        match, ips = _make_match(bowling_pids=[1, 2, 3, 4, 5], current_inning=1)
        for over, expected_pid in [(0, 1), (1, 2), (2, 3), (3, 4)]:
            match.current_over = over
            result = strategy.select_bowler(match)
            assert result.id == expected_pid, (
                f"Toss-flip over {over}: expected pid {expected_pid}, got {result.id}"
            )

    def test_flip_innings2_returns_correct_bowler(self):
        strategy = HistoricalBowlingOrder(PLAN)
        # Team B (pids 6-10) bowling in simulation innings 2 (historically they batted)
        match, _ = _make_match(bowling_pids=[6, 7, 8, 9, 10], current_inning=2)
        for over, expected_pid in [(0, 6), (1, 7), (2, 8)]:
            match.current_over = over
            result = strategy.select_bowler(match)
            assert result.id == expected_pid

    def test_without_fix_would_return_fallback(self):
        """
        Demonstrates the pre-fix behaviour: plan pid not in bowling team →
        eligible[0] (pid=1, always the first player) regardless of over number.
        This test documents what the bug looked like — the fix should NOT trigger
        this branch (the assertion below verifies the fix avoids eligible[0]).
        """
        strategy = HistoricalBowlingOrder(PLAN)
        match, ips = _make_match(bowling_pids=[1, 2, 3, 4, 5], current_inning=1,
                                 current_bowler=ips[0] if False else None)
        # Over 1 → plan[1][1] = 7 (Team B), not in Team A → fix swaps to plan[2][1] = 2
        match.current_over = 1
        result = strategy.select_bowler(match)
        # After fix: returns pid=2, NOT eligible[0] (pid=1)
        assert result.id == 2, (
            f"Expected pid 2 (flipped plan), got {result.id} — toss-flip not handled"
        )
        assert result.id != 1, "Returned eligible[0] fallback — toss-flip bug not fixed"


# ── Tests: missing over in plan (simulation runs longer than historical) ───────

class TestMissingOverInPlan:
    """When the simulation runs more overs than the historical match, fall back
    gracefully to the first eligible bowler."""

    def test_over_beyond_plan_falls_back_to_eligible(self):
        strategy = HistoricalBowlingOrder(PLAN)
        match, ips = _make_match(bowling_pids=[6, 7, 8, 9, 10], current_inning=1,
                                 current_bowler=ips[0] if False else None)
        match.current_bowler = ips[0]  # pid=6 is current bowler
        match.current_over   = 99      # way beyond any plan entry
        result = strategy.select_bowler(match)
        # Should return someone from the bowling team (not the current bowler)
        assert result in ips
        assert result != ips[0]        # not the current bowler

    def test_empty_plan_falls_back(self):
        strategy = HistoricalBowlingOrder({})
        match, ips = _make_match(bowling_pids=[1, 2, 3], current_inning=1)
        match.current_bowler = ips[0]
        result = strategy.select_bowler(match)
        assert result in ips[1:]


# ── Tests: edge cases ─────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_no_bowling_team_returns_current_bowler(self):
        strategy = HistoricalBowlingOrder(PLAN)
        match = MagicMock()
        match.current_inning = 1
        match.current_over   = 0
        match.current_bowler = _inning_player(99)
        match.current_bowling_team = None
        assert strategy.select_bowler(match).id == 99

    def test_empty_inning_players_returns_current_bowler(self):
        strategy = HistoricalBowlingOrder(PLAN)
        match = MagicMock()
        match.current_inning = 1
        match.current_over   = 0
        sentinel = _inning_player(99)
        match.current_bowler = sentinel
        bowling_team = MagicMock()
        bowling_team.inning_players = []
        match.current_bowling_team  = bowling_team
        assert strategy.select_bowler(match) is sentinel

    def test_current_inning_zero_treated_as_one(self):
        """current_inning=0 (falsy) should be treated as innings 1."""
        strategy = HistoricalBowlingOrder(PLAN)
        # Team B bowling (matches plan[1])
        match, _ = _make_match(bowling_pids=[6, 7, 8, 9, 10], current_inning=0)
        match.current_over = 0
        result = strategy.select_bowler(match)
        assert result.id == 6
