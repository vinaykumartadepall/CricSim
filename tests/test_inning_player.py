"""Unit tests for simulator.entities.inning_player.InningPlayer stat tracking."""
import pytest
from unittest.mock import MagicMock
from simulator.entities.inning_player import InningPlayer
from simulator.entities.player import Player
from simulator.entities.ball_outcome import BallOutcome
from simulator.events import MatchEvent, EventType
from enums.constants import ExtraType


def _make_player(pid=1, name="Test"):
    return Player(id=pid, name=name)


def _make_inning_player(pid=1, name="Batter"):
    return InningPlayer(player=_make_player(pid, name))


def _ball_event(batter, bowler, outcome, match=None):
    if match is None:
        match = MagicMock()
        match.current_over = 0
        match.match_format = "T20"
    return MatchEvent(
        type=EventType.BALL_BOWLED,
        data={
            "batter": batter,
            "bowler": bowler,
            "outcome": outcome,
            "match": match,
        },
    )


def _over_event(bowler, runs):
    return MatchEvent(
        type=EventType.OVER_COMPLETED,
        data={"bowler": bowler, "runs": runs},
    )


class TestBatterStatTracking:
    def setup_method(self):
        self.batter = _make_inning_player(pid=1, name="Batter")
        self.bowler = _make_inning_player(pid=2, name="Bowler")

    def _send(self, outcome, match=None):
        self.batter.on_event(_ball_event(self.batter, self.bowler, outcome, match))

    def test_runs_accumulate(self):
        self._send(BallOutcome(runs_batter=4))
        self._send(BallOutcome(runs_batter=6))
        self._send(BallOutcome(runs_batter=1))
        assert self.batter.runs_scored == 11

    def test_balls_faced_counts_legal_only(self):
        # Cricket scoring: wides don't count; no-balls DO count (batter faced the delivery).
        self._send(BallOutcome(runs_batter=1))               # faced: 1
        self._send(BallOutcome(extras_type=ExtraType.WIDE))  # faced: 0
        self._send(BallOutcome(extras_type=ExtraType.NOBALL)) # faced: 1
        self._send(BallOutcome(runs_batter=4))               # faced: 1
        assert self.batter.balls_faced == 3

    def test_fours_counted(self):
        self._send(BallOutcome(runs_batter=4))
        self._send(BallOutcome(runs_batter=4))
        self._send(BallOutcome(runs_batter=6))
        assert self.batter.fours == 2

    def test_sixes_counted(self):
        self._send(BallOutcome(runs_batter=6))
        assert self.batter.sixes == 1

    def test_dot_ball_increments(self):
        self._send(BallOutcome(runs_batter=0))
        assert self.batter.dot_balls_faced == 1

    def test_wicket_ball_is_not_a_dot(self):
        self._send(BallOutcome(runs_batter=0, is_wicket=True, wicket_kind="bowled"))
        assert self.batter.dot_balls_faced == 0

    def test_wide_is_not_a_dot(self):
        self._send(BallOutcome(extras_type=ExtraType.WIDE))
        assert self.batter.dot_balls_faced == 0

    def test_is_out_set_on_wicket(self):
        assert not self.batter.is_out
        self._send(BallOutcome(is_wicket=True, wicket_kind="bowled"))
        assert self.batter.is_out

    def test_other_batter_events_ignored(self):
        other = _make_inning_player(pid=99, name="Other")
        self.batter.on_event(_ball_event(other, self.bowler, BallOutcome(runs_batter=6)))
        assert self.batter.runs_scored == 0

    def test_death_runs_tracked_in_death_over(self):
        match = MagicMock()
        match.current_over = 16
        match.match_format = "T20"
        self._send(BallOutcome(runs_batter=6), match=match)
        assert self.batter.death_runs_scored == 6
        assert self.batter.death_sixes == 1

    def test_non_death_runs_not_in_death_bucket(self):
        match = MagicMock()
        match.current_over = 5
        match.match_format = "T20"
        self._send(BallOutcome(runs_batter=4), match=match)
        assert self.batter.death_runs_scored == 0
        assert self.batter.death_fours == 0


class TestBowlerStatTracking:
    def setup_method(self):
        self.batter = _make_inning_player(pid=1, name="Batter")
        self.bowler = _make_inning_player(pid=2, name="Bowler")

    def _send(self, outcome, match=None):
        self.bowler.on_event(_ball_event(self.batter, self.bowler, outcome, match))

    def test_runs_conceded_includes_extras(self):
        self._send(BallOutcome(runs_batter=4, runs_extras=0))
        self._send(BallOutcome(runs_batter=0, runs_extras=1, extras_type=ExtraType.WIDE))
        assert self.bowler.runs_conceded == 5

    def test_balls_bowled_counts_legal_only(self):
        self._send(BallOutcome(runs_batter=1))
        self._send(BallOutcome(extras_type=ExtraType.WIDE))
        self._send(BallOutcome(extras_type=ExtraType.NOBALL))
        assert self.bowler.balls_bowled == 1

    def test_bowler_credited_wicket(self):
        self._send(BallOutcome(runs_batter=0, is_wicket=True, wicket_kind="bowled"))
        assert self.bowler.wickets_taken == 1

    def test_run_out_not_credited_to_bowler(self):
        self._send(BallOutcome(runs_batter=0, is_wicket=True, wicket_kind="run out"))
        assert self.bowler.wickets_taken == 0

    def test_wicket_counts_as_dot_for_bowler(self):
        self._send(BallOutcome(runs_batter=0, is_wicket=True, wicket_kind="bowled"))
        assert self.bowler.dot_balls_bowled == 1

    def test_zero_run_zero_extra_non_wicket_is_dot(self):
        self._send(BallOutcome(runs_batter=0, runs_extras=0))
        assert self.bowler.dot_balls_bowled == 1

    def test_runs_are_not_dots(self):
        self._send(BallOutcome(runs_batter=4))
        assert self.bowler.dot_balls_bowled == 0

    def test_maiden_on_zero_run_over(self):
        self.bowler.on_event(_over_event(self.bowler, 0))
        assert self.bowler.maidens == 1

    def test_no_maiden_on_run_over(self):
        self.bowler.on_event(_over_event(self.bowler, 6))
        assert self.bowler.maidens == 0

    def test_other_bowler_over_not_counted(self):
        other = _make_inning_player(pid=99, name="Other")
        self.bowler.on_event(_over_event(other, 0))
        assert self.bowler.maidens == 0

    def test_death_bowling_tracked(self):
        match = MagicMock()
        match.current_over = 17
        match.match_format = "T20"
        self.bowler.on_event(_ball_event(self.batter, self.bowler,
                                          BallOutcome(runs_batter=6), match))
        assert self.bowler.death_runs_conceded == 6
        assert self.bowler.death_balls_bowled == 1
