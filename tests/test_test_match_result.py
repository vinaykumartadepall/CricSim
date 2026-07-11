"""
Result-decision logic for Test matches: tie vs. draw vs. decisive finish.

Rules under test (simulator/engines/test_engine.py::TestMatchEngine._finalize_match):
- Tied  -> both teams' aggregate run totals across all innings are exactly equal.
- Drawn -> 4th innings ends (over cap reached / follow-on side survives) without the
           target being reached, the side batting 4th being bowled out, or a tie.
- Decisive -> target reached (win by wickets) or all out with unequal totals (win by runs),
              even if this coincides with the global over cap being hit.
"""

from simulator.engines.test_engine import TestMatchEngine
from simulator.entities.team import MatchTeam
from simulator.entities.inning_team import InningTeam
from simulator.entities.inning import Inning


class _NullLogger:
    def headline(self, *args, **kwargs):
        pass

    def close(self, *args, **kwargs):
        pass


def _make_engine(innings, target_score=None, overs_total=0):
    engine = TestMatchEngine.__new__(TestMatchEngine)
    engine.match = type("M", (), {})()
    engine.match.innings = innings
    engine.match.target_score = target_score
    engine.match.result = None
    engine.match_overs_total = overs_total
    engine.logger = _NullLogger()
    return engine


def _inning(num, team_name, runs, wickets, balls=300, team_id=None):
    # Distinct id per team, mirroring production (match_runner assigns 1/2):
    # _finalize_match identifies teams by id, not name, since multiplayer
    # display names can collide. Derived from the name here so existing
    # call sites ("A"/"B") keep working; pass team_id explicitly to model
    # two different teams sharing one name.
    if team_id is None:
        team_id = _TEAM_IDS.setdefault(team_name, len(_TEAM_IDS) + 1)
    team = InningTeam(team=MatchTeam(id=team_id, name=team_name))
    team.total_runs = runs
    team.total_wickets = wickets
    team.total_balls = balls
    other = InningTeam(team=MatchTeam(id=99, name="Other"))
    return Inning(inning_number=num, batting_team=team, bowling_team=other)


_TEAM_IDS: dict = {}


class TestTestMatchTie:
    def test_equal_totals_across_four_innings_is_tie(self):
        innings = [
            _inning(1, "A", 300, 10),
            _inning(2, "B", 280, 10),
            _inning(3, "A", 150, 10),
            _inning(4, "B", 170, 10),
        ]
        engine = _make_engine(innings, target_score=171)
        engine._finalize_match()

        assert engine.match.result.is_tie is True
        assert engine.match.result.winner is None
        assert engine.match.result.description == "Match Tied"

    def test_tie_takes_priority_even_if_overs_cap_reached(self):
        innings = [
            _inning(1, "A", 300, 10),
            _inning(2, "B", 280, 10),
            _inning(3, "A", 150, 10),
            _inning(4, "B", 170, 10),
        ]
        engine = _make_engine(innings, target_score=171, overs_total=450)
        engine._finalize_match()

        assert engine.match.result.is_tie is True


class TestTestMatchDraw:
    def test_fourth_innings_incomplete_without_target_is_draw(self):
        innings = [
            _inning(1, "A", 300, 10),
            _inning(2, "B", 280, 10),
            _inning(3, "A", 150, 10),
            _inning(4, "B", 100, 4),  # short of target, not all out
        ]
        engine = _make_engine(innings, target_score=171, overs_total=450)
        engine._finalize_match()

        assert engine.match.result.is_no_result is True
        assert engine.match.result.winner is None
        assert engine.match.result.description == "Match Drawn"

    def test_more_than_four_innings_is_draw(self):
        innings = [_inning(n, "A" if n % 2 else "B", 100, 5) for n in range(1, 6)]
        engine = _make_engine(innings)
        engine._finalize_match()

        assert engine.match.result.is_no_result is True
        assert engine.match.result.description == "Match Drawn"


class TestTestMatchDecisive:
    def test_target_reached_wins_by_wickets_even_at_overs_cap(self):
        innings = [
            _inning(1, "A", 300, 10),
            _inning(2, "B", 280, 10),
            _inning(3, "A", 150, 10),
            _inning(4, "B", 172, 6),  # reached target of 171
        ]
        engine = _make_engine(innings, target_score=171, overs_total=450)
        engine._finalize_match()

        assert engine.match.result.is_tie is False
        assert engine.match.result.is_no_result is False
        assert engine.match.result.winner == "B"
        assert "won by 4 wickets" in engine.match.result.description

    def test_all_out_short_of_target_wins_by_runs(self):
        innings = [
            _inning(1, "A", 300, 10),
            _inning(2, "B", 280, 10),
            _inning(3, "A", 150, 10),
            _inning(4, "B", 150, 10),  # all out, short of target of 171
        ]
        engine = _make_engine(innings, target_score=171)
        engine._finalize_match()

        assert engine.match.result.is_tie is False
        assert engine.match.result.is_no_result is False
        assert engine.match.result.winner == "A"
        assert "won by 20 run" in engine.match.result.description

    def test_innings_victory_within_three_innings(self):
        innings = [
            _inning(1, "A", 500, 10),
            _inning(2, "B", 150, 10),
            _inning(3, "B", 200, 10),
        ]
        engine = _make_engine(innings)
        engine._finalize_match()

        assert engine.match.result.winner == "A"
        assert "won by an innings" in engine.match.result.description

    def test_innings_victory_becomes_draw_if_overs_cap_hit(self):
        innings = [
            _inning(1, "A", 500, 10),
            _inning(2, "B", 150, 10),
            _inning(3, "B", 200, 8),  # not all out; day/over cap ends it here
        ]
        engine = _make_engine(innings, overs_total=450)
        engine._finalize_match()

        assert engine.match.result.is_no_result is True
        assert engine.match.result.description == "Match Drawn"


class TestDuplicateTeamNames:
    """Two teams sharing one display name (multiplayer 1v1 where both players
    had identical names) crashed _finalize_match with IndexError - teams were
    deduplicated by name, collapsing both sides into one entry. Reproduces
    prod sim 3a974ea4; teams are identified by id now."""

    def test_four_innings_with_identical_names_does_not_crash(self):
        innings = [
            _inning(1, "Vinay", 300, 10, team_id=1),
            _inning(2, "Vinay", 250, 10, team_id=2),
            _inning(3, "Vinay", 150, 10, team_id=1),
            _inning(4, "Vinay", 120, 10, team_id=2),
        ]
        engine = _make_engine(innings, target_score=201)
        engine._finalize_match()

        # team 1: 450, team 2: 370, all out -> team 1 wins by 80 runs
        assert engine.match.result.winner == "Vinay"
        assert "won by 80 run" in engine.match.result.description

    def test_innings_victory_with_identical_names(self):
        innings = [
            _inning(1, "Vinay", 500, 10, team_id=1),
            _inning(2, "Vinay", 150, 10, team_id=2),
            _inning(3, "Vinay", 200, 10, team_id=2),
        ]
        engine = _make_engine(innings)
        engine._finalize_match()

        assert "won by an innings and 150 run" in engine.match.result.description

    def test_tie_with_identical_names(self):
        innings = [
            _inning(1, "Vinay", 300, 10, team_id=1),
            _inning(2, "Vinay", 280, 10, team_id=2),
            _inning(3, "Vinay", 150, 10, team_id=1),
            _inning(4, "Vinay", 170, 10, team_id=2),
        ]
        engine = _make_engine(innings, target_score=171)
        engine._finalize_match()

        assert engine.match.result.is_tie is True
