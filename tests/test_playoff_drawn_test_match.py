"""
Test-match knockout progression (simulator/tournament/engine.py).

Bug: a Test match ending in a genuine draw/tie ("Match Drawn"/"Match Tied",
is_no_result/is_tie True, winner=None) left _run_playoffs with a None winner
for that fixture. _resolve_playoff_slot propagates that None winner forward as
the literal string "TBD" into every later round, permanently stalling bracket
progression for the rest of the knockout - exactly the same failure mode the
existing Super-Over-tied fix (test_playoff_tiebreak.py) already patched for
limited overs, just via a different route (is_no_result instead of a tied
Super Over).

Fix: _resolve_undecided_playoff dispatches any no-winner playoff fixture to
the right chain for its format:
  - Super Over tied (limited overs) -> _resolve_playoff_tie (unchanged)
  - anything else (currently: Test draws/ties) -> _resolve_drawn_playoff:
      1. first-innings lead (Test only)
      2. group-stage rank (always resolves - same mechanism as the SO case)

No live DB connection required - StatsRepository is bypassed via conn=None,
matching tests/test_playoff_tiebreak.py.
"""
from unittest.mock import MagicMock, patch

import simulator.tournament.engine as engine_mod
from db.stats_repository import StatsRepository
from simulator.entities.inning import Inning
from simulator.entities.inning_team import InningTeam
from simulator.entities.match import MatchResult, SimulationMatch
from simulator.entities.team import MatchTeam
from simulator.tournament.config import (
    Fixture, PlayoffConfig, ScheduleConfig, TeamConfig, TournamentConfig,
)
from simulator.tournament.engine import TournamentEngine


def _make_config(fmt="Test"):
    teams = [
        TeamConfig(name=name, short_name=name[:3].upper(), players=[], home_venue=None)
        for name in ("Alpha", "Bravo", "Charlie", "Delta")
    ]
    return TournamentConfig(
        tournament_name="Test Championship",
        format=fmt,
        gender="male",
        season="2025",
        venues=[],
        teams=teams,
        schedule=ScheduleConfig(type="round_robin"),
        playoffs=PlayoffConfig(format="semis_final"),
    )


def _make_engine(config) -> TournamentEngine:
    fake_repo = StatsRepository.__new__(StatsRepository)
    fake_repo.conn = None
    engine = TournamentEngine(config, repo=fake_repo, silent=True)
    engine._player_cache = {}
    engine._outcome_strat = MagicMock()
    engine._bowling_strat = MagicMock()
    return engine


def _record(engine, home, away, result, home_runs=150, away_runs=140):
    engine._points_table.record_result(home, away, result, home_runs, 120, away_runs, 120)


def _inning(num: int, team_name: str, runs: int, team_id: int = 1) -> Inning:
    team = InningTeam(team=MatchTeam(id=team_id, name=team_name))
    team.total_runs = runs
    other = InningTeam(team=MatchTeam(id=99, name="Other"))
    return Inning(inning_number=num, batting_team=team, bowling_team=other)


def _drawn_match_result() -> MatchResult:
    return MatchResult(winner=None, is_no_result=True, description="Match Drawn", team_innings_summary={})


def _tied_match_result() -> MatchResult:
    return MatchResult(winner=None, is_tie=True, description="Match Tied", team_innings_summary={})


class TestFirstInningsRuns:

    def _match_with_first_innings(self, home_runs, away_runs, home="Alpha", away="Bravo"):
        match = SimulationMatch(id=1, home_team=MatchTeam(id=1, name=home), away_team=MatchTeam(id=2, name=away))
        match.innings = [_inning(1, home, home_runs), _inning(2, away, away_runs)]
        return match

    def test_reads_runs_for_each_team_regardless_of_batting_order(self):
        engine = _make_engine(_make_config())
        match = self._match_with_first_innings(300, 250)

        assert engine._first_innings_runs(match, "Alpha") == 300
        assert engine._first_innings_runs(match, "Bravo") == 250

    def test_works_when_away_team_batted_first(self):
        """Toss decides batting order, not fixture.home/away - innings[0]
        could belong to either team."""
        engine = _make_engine(_make_config())
        match = self._match_with_first_innings(220, 310, home="Alpha", away="Bravo")
        match.innings = [_inning(1, "Bravo", 310), _inning(2, "Alpha", 220)]

        assert engine._first_innings_runs(match, "Alpha") == 220
        assert engine._first_innings_runs(match, "Bravo") == 310

    def test_unbatted_team_returns_none(self):
        engine = _make_engine(_make_config())
        match = SimulationMatch(id=1, home_team=MatchTeam(id=1, name="Alpha"), away_team=MatchTeam(id=2, name="Bravo"))
        match.innings = [_inning(1, "Alpha", 300)]

        assert engine._first_innings_runs(match, "Alpha") == 300
        assert engine._first_innings_runs(match, "Bravo") is None


class TestFirstInningsLeadWinner:

    def test_higher_first_innings_score_leads(self):
        engine = _make_engine(_make_config())
        match = SimulationMatch(id=1, home_team=MatchTeam(id=1, name="Alpha"), away_team=MatchTeam(id=2, name="Bravo"))
        match.innings = [_inning(1, "Alpha", 320), _inning(2, "Bravo", 275)]

        winner, margin = engine._first_innings_lead_winner(match, "Alpha", "Bravo")

        assert winner == "Alpha"
        assert margin == 45

    def test_away_team_can_lead(self):
        engine = _make_engine(_make_config())
        match = SimulationMatch(id=1, home_team=MatchTeam(id=1, name="Alpha"), away_team=MatchTeam(id=2, name="Bravo"))
        match.innings = [_inning(1, "Alpha", 200), _inning(2, "Bravo", 260)]

        winner, margin = engine._first_innings_lead_winner(match, "Alpha", "Bravo")

        assert winner == "Bravo"
        assert margin == 60

    def test_equal_first_innings_returns_none(self):
        engine = _make_engine(_make_config())
        match = SimulationMatch(id=1, home_team=MatchTeam(id=1, name="Alpha"), away_team=MatchTeam(id=2, name="Bravo"))
        match.innings = [_inning(1, "Alpha", 250), _inning(2, "Bravo", 250)]

        assert engine._first_innings_lead_winner(match, "Alpha", "Bravo") == (None, None)


class TestResolveDrawnPlayoff:

    def test_test_format_uses_first_innings_lead(self):
        engine = _make_engine(_make_config(fmt="Test"))
        # group stage rank would favor Bravo if reached - proves the lead took priority
        _record(engine, "Bravo", "Charlie", "home_win")
        match = SimulationMatch(id=1, home_team=MatchTeam(id=1, name="Alpha"), away_team=MatchTeam(id=2, name="Bravo"))
        match.innings = [_inning(1, "Alpha", 340), _inning(2, "Bravo", 290)]
        match.result = _drawn_match_result()
        fixture = Fixture(home="Alpha", away="Bravo", venue=None, match_number=1, match_label="Semi-final 1")

        winner = engine._resolve_drawn_playoff(match, fixture)

        assert winner == "Alpha"
        assert match.result.winner == "Alpha"
        assert match.result.tiebreak_reason == "first_innings_lead"
        # Margin is still recorded (useful data) even though the description
        # text below deliberately doesn't show it.
        assert match.result.tiebreak_margin == 50
        assert match.result.description == "Match Drawn · Alpha advanced on first-innings lead"

    def test_test_format_falls_back_to_group_stage_rank_when_first_innings_also_tied(self):
        engine = _make_engine(_make_config(fmt="Test"))
        _record(engine, "Bravo", "Charlie", "home_win")  # Bravo: 2pts > Alpha's 0pts
        match = SimulationMatch(id=1, home_team=MatchTeam(id=1, name="Alpha"), away_team=MatchTeam(id=2, name="Bravo"))
        match.innings = [_inning(1, "Alpha", 250), _inning(2, "Bravo", 250)]
        match.result = _tied_match_result()
        fixture = Fixture(home="Alpha", away="Bravo", venue=None, match_number=1, match_label="Semi-final 1")

        winner = engine._resolve_drawn_playoff(match, fixture)

        assert winner == "Bravo"
        assert match.result.tiebreak_reason == "group_stage_rank"
        assert match.result.tiebreak_margin is None
        assert match.result.description == "Match Tied · Bravo advanced due to better group stage finish"

    def test_non_test_format_skips_straight_to_group_stage_rank(self):
        """Guards against ever trying an innings-based tiebreak for a format
        that doesn't have the concept."""
        engine = _make_engine(_make_config(fmt="ODI"))
        _record(engine, "Alpha", "Charlie", "home_win")  # Alpha finishes above Bravo
        match = SimulationMatch(id=1, home_team=MatchTeam(id=1, name="Alpha"), away_team=MatchTeam(id=2, name="Bravo"))
        match.innings = [_inning(1, "Bravo", 400), _inning(2, "Alpha", 100)]  # Bravo miles ahead if lead were checked
        match.result = _tied_match_result()
        fixture = Fixture(home="Alpha", away="Bravo", venue=None, match_number=1, match_label="Semi-final 1")

        winner = engine._resolve_drawn_playoff(match, fixture)

        assert winner == "Alpha"  # group-stage rank, not the (irrelevant) innings totals
        assert match.result.tiebreak_reason == "group_stage_rank"


class TestResolveUndecidedPlayoffDispatch:

    def test_super_over_tied_routes_to_existing_mechanism(self):
        engine = _make_engine(_make_config(fmt="T20"))
        _record(engine, "Alpha", "Charlie", "home_win")
        match = MagicMock(result=MatchResult(winner=None, is_tie=True, description="Super Over Tied", team_innings_summary={}))
        fixture = Fixture(home="Alpha", away="Bravo", venue=None, match_number=1, match_label="Semi-final 1")

        winner = engine._resolve_undecided_playoff(match, fixture)

        assert winner == "Alpha"
        assert match.result.tiebreak_reason == "super_over_tied_rank"

    def test_test_draw_routes_to_drawn_playoff_chain(self):
        engine = _make_engine(_make_config(fmt="Test"))
        _record(engine, "Bravo", "Charlie", "home_win")
        match = SimulationMatch(id=1, home_team=MatchTeam(id=1, name="Alpha"), away_team=MatchTeam(id=2, name="Bravo"))
        match.innings = [_inning(1, "Alpha", 250), _inning(2, "Bravo", 250)]
        match.result = _drawn_match_result()
        fixture = Fixture(home="Alpha", away="Bravo", venue=None, match_number=1, match_label="Semi-final 1")

        winner = engine._resolve_undecided_playoff(match, fixture)

        assert winner == "Bravo"
        assert match.result.tiebreak_reason == "group_stage_rank"


class TestRunFixtureTestDrawPlayoffHook:

    def test_run_fixture_advances_winner_instead_of_stalling_bracket(self):
        """End-to-end through _run_fixture: a fake EngineFactory-produced
        engine mimics TestMatchEngine leaving a genuinely drawn result (with
        distinct first-innings scores) on the real match object _run_fixture
        builds internally. Before the fix, this fixture would return None,
        and _resolve_playoff_slot would silently turn that into the literal
        string "TBD" for every subsequent round - "the draw is stopping
        there"."""
        engine = _make_engine(_make_config(fmt="Test"))
        _record(engine, "Bravo", "Charlie", "home_win")  # only matters if rank fallback is (wrongly) reached

        def _fake_create(match, outcome_strat, bowling_strat):
            def _simulate():
                match.innings = [_inning(1, "Alpha", 410), _inning(2, "Bravo", 300)]
                match.result = _drawn_match_result()
            fake_engine = MagicMock()
            fake_engine.simulate = _simulate
            return fake_engine

        fixture = Fixture(home="Alpha", away="Bravo", venue=None, match_number=1, match_label="Semi-final 1")

        with patch.object(engine_mod.EngineFactory, "create", side_effect=_fake_create):
            winner = engine._run_fixture(fixture, stage="playoff")

        assert winner == "Alpha"  # first-innings lead, not group-stage rank
        # Points table must stay untouched by playoff fixtures.
        assert engine._points_table["Alpha"].played == 0

    def test_run_fixture_leaves_group_stage_test_draws_alone(self):
        """The hook is playoff-only - a genuinely drawn GROUP-STAGE Test match
        must stay a no-result, not be forced to a winner."""
        engine = _make_engine(_make_config(fmt="Test"))

        def _fake_create(match, outcome_strat, bowling_strat):
            def _simulate():
                match.innings = [_inning(1, "Alpha", 300), _inning(2, "Bravo", 200)]
                match.result = _drawn_match_result()
            fake_engine = MagicMock()
            fake_engine.simulate = _simulate
            return fake_engine

        fixture = Fixture(home="Alpha", away="Bravo", venue=None, match_number=1, match_label="Match 1")

        with patch.object(engine_mod.EngineFactory, "create", side_effect=_fake_create):
            winner = engine._run_fixture(fixture, stage="group")

        assert winner is None
        assert engine._points_table["Alpha"].played == 1
