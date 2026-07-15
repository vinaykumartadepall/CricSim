"""
SimulationRepository.save_match's win_type sentinel for playoff tiebreak
winners (db/simulation_repository.py) - a knockout fixture whose genuine
outcome was a draw/tie but got a winner via TournamentEngine's playoff
tiebreak chain must persist that winner distinguishably from a normal
"no result"/"tie" row (which normally carries no winner_id at all), without
disturbing the pre-existing Super-Over-tied-then-rank-advance encoding
(is_super_over=True), which keeps its original representation untouched.

No live DB connection - cursor is mocked per this project's convention (see
tests/test_simulation_repository_potm_standings.py).
"""
from unittest.mock import MagicMock

from db.simulation_repository import SimulationRepository
from simulator.entities.match import MatchResult, SimulationMatch
from simulator.entities.team import MatchTeam

# INSERT params tuple positional indices (db/simulation_repository.py::save_match)
_RESULT, _RESULT_TYPE, _WINNER_ID, _WIN_TYPE, _WIN_BY, _IS_SUPER_OVER = 11, 12, 13, 14, 15, 16


def _make_repo():
    repo = SimulationRepository.__new__(SimulationRepository)
    repo.cur = MagicMock()
    repo.cur.fetchone.return_value = (999,)
    return repo


def _match(result: MatchResult, is_super_over: bool = False) -> SimulationMatch:
    m = SimulationMatch(id=1, home_team=MatchTeam(id=1, name="Alpha"), away_team=MatchTeam(id=2, name="Bravo"))
    m.result = result
    m.is_super_over = is_super_over
    return m


class TestFirstInningsLeadPersistence:
    def test_writes_sentinel_win_type_and_margin(self):
        repo = _make_repo()
        result = MatchResult(winner="Alpha", is_no_result=True, description="Match Drawn · Alpha advanced on 50-run first-innings lead")
        result.tiebreak_reason = "first_innings_lead"
        result.tiebreak_margin = 50

        repo.save_match(
            "sim-1", "Semi-final 1", _match(result),
            home_team_id=10, away_team_id=20, venue_id=None,
        )

        _, params = repo.cur.execute.call_args[0]
        assert params[_RESULT] == "no result"       # genuine outcome unchanged
        assert params[_WINNER_ID] == 10              # Alpha == home
        assert params[_WIN_TYPE] == "first_innings_lead"
        assert params[_WIN_BY] == 50


class TestGroupStageRankPersistence:
    def test_test_format_draw_writes_sentinel(self):
        repo = _make_repo()
        result = MatchResult(winner="Bravo", is_no_result=True, description="Match Drawn · Bravo advanced due to better group stage finish")
        result.tiebreak_reason = "group_stage_rank"

        repo.save_match(
            "sim-1", "Semi-final 1", _match(result),
            home_team_id=10, away_team_id=20, venue_id=None,
        )

        _, params = repo.cur.execute.call_args[0]
        assert params[_RESULT] == "no result"
        assert params[_WINNER_ID] == 20              # Bravo == away
        assert params[_WIN_TYPE] == "group_stage_rank"
        assert params[_WIN_BY] is None

    def test_pre_existing_super_over_tied_case_is_left_untouched(self):
        """Same tiebreak_reason value, but is_super_over=True - this is the
        ORIGINAL limited-overs mechanism's encoding (result='tie' +
        is_super_over, no win_type sentinel), which must not be overwritten."""
        repo = _make_repo()
        result = MatchResult(winner="Alpha", is_tie=True, description="Match tied · Super Over tied · Alpha advanced due to better group stage finish")
        result.tiebreak_reason = "super_over_tied_rank"

        repo.save_match(
            "sim-1", "Semi-final 1", _match(result, is_super_over=True),
            home_team_id=10, away_team_id=20, venue_id=None,
        )

        _, params = repo.cur.execute.call_args[0]
        assert params[_RESULT] == "tie"
        assert params[_WINNER_ID] == 10
        assert params[_WIN_TYPE] is None             # unchanged - relies on is_super_over, not win_type
        assert params[_IS_SUPER_OVER] is True


class TestNormalResultsUnaffected:
    def test_decisive_win_unaffected(self):
        repo = _make_repo()
        result = MatchResult(winner="Alpha", description="Alpha won by 34 runs")

        repo.save_match(
            "sim-1", "Match 1", _match(result),
            home_team_id=10, away_team_id=20, venue_id=None,
        )

        _, params = repo.cur.execute.call_args[0]
        assert params[_RESULT] == "win"
        assert params[_WINNER_ID] == 10
        assert params[_WIN_TYPE] == "runs"
        assert params[_WIN_BY] == 34

    def test_genuine_draw_with_no_tiebreak_has_no_winner(self):
        """A group-stage Test draw (tiebreak_reason never set) must still
        persist with no winner at all."""
        repo = _make_repo()
        result = MatchResult(winner=None, is_no_result=True, description="Match Drawn")

        repo.save_match(
            "sim-1", "Match 1", _match(result),
            home_team_id=10, away_team_id=20, venue_id=None,
        )

        _, params = repo.cur.execute.call_args[0]
        assert params[_RESULT] == "no result"
        assert params[_WINNER_ID] is None
        assert params[_WIN_TYPE] is None
