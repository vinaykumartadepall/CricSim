"""
Tests for TournamentEngine's playoff tie-break (simulator/tournament/engine.py).

Bug: when a playoff match ties and the ensuing super over ALSO ties,
LimitedOversEngine sets match.result = MatchResult(winner=None, is_tie=True,
description="Super Over Tied", ...). Before this fix, that None winner
propagated through _run_playoffs/_resolve_playoff_slot as the literal string
"TBD", silently stalling bracket progression (the "TBD" team can't be
resolved to a real team config, so the next fixture is skipped, and so on
for every later round). The fix: the team that finished higher in the
group stage advances, via _group_stage_rank/_resolve_playoff_tie.

No live DB connection required - StatsRepository is bypassed via conn=None,
matching the pattern in test_tournament_engine_prewarm.py.
"""
from unittest.mock import MagicMock, patch

import simulator.tournament.engine as engine_mod
from db.stats_repository import StatsRepository
from simulator.entities.match import MatchResult
from simulator.tournament.config import (
    Fixture, PlayoffConfig, ScheduleConfig, TeamConfig, TournamentConfig,
)
from simulator.tournament.engine import TournamentEngine


def _make_config():
    teams = [
        TeamConfig(name=name, short_name=name[:3].upper(), players=[], home_venue=None)
        for name in ("Alpha", "Bravo", "Charlie", "Delta")
    ]
    return TournamentConfig(
        tournament_name="Test Cup",
        format="T20",
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


def _tied_super_over_result() -> MatchResult:
    return MatchResult(winner=None, is_tie=True, description="Super Over Tied", team_innings_summary={})


class TestGroupStageRank:

    def test_best_team_has_rank_zero(self):
        engine = _make_engine(_make_config())
        _record(engine, "Alpha", "Bravo", "home_win")
        _record(engine, "Charlie", "Delta", "home_win")

        assert engine._group_stage_rank("Alpha") == 0

    def test_unranked_team_gets_sentinel(self):
        engine = _make_engine(_make_config())

        assert engine._group_stage_rank("Nobody FC") == 999


class TestResolvePlayoffTie:

    def test_higher_placed_team_advances_when_home(self):
        engine = _make_engine(_make_config())
        _record(engine, "Alpha", "Charlie", "home_win")  # Alpha: 2 pts; Bravo: 0 pts
        fixture = Fixture(home="Alpha", away="Bravo", venue=None, match_number=1, match_label="Semi-final 1")
        match_result = _tied_super_over_result()
        match = MagicMock(result=match_result)

        winner = engine._resolve_playoff_tie(match, fixture)

        assert winner == "Alpha"
        assert match.result.winner == "Alpha"
        assert match.result.description == (
            "Match tied · Super Over tied · Alpha advanced due to better group stage finish"
        )

    def test_higher_placed_team_advances_when_away(self):
        """Rank comparison must not silently assume home is always better placed."""
        engine = _make_engine(_make_config())
        _record(engine, "Bravo", "Charlie", "home_win")  # Bravo: 2 pts > Alpha's 0 pts
        fixture = Fixture(home="Alpha", away="Bravo", venue=None, match_number=1, match_label="Semi-final 1")
        match = MagicMock(result=_tied_super_over_result())

        winner = engine._resolve_playoff_tie(match, fixture)

        assert winner == "Bravo"
        assert match.result.winner == "Bravo"


class TestRunFixturePlayoffTieHook:

    def test_run_fixture_advances_winner_instead_of_tbd(self):
        """End-to-end through _run_fixture: a fake EngineFactory-produced engine
        mimics LimitedOversEngine leaving a tied-super-over result on the real
        match object _run_fixture builds internally; the fixture must come back
        with a real winner (not None, which _resolve_playoff_slot would
        otherwise silently turn into the literal string "TBD")."""
        engine = _make_engine(_make_config())
        _record(engine, "Alpha", "Charlie", "home_win")  # Alpha finishes above Bravo

        fake_sim_engine = MagicMock()

        def _fake_create(match, outcome_strat, bowling_strat):
            fake_sim_engine.simulate = lambda: setattr(match, "result", _tied_super_over_result())
            return fake_sim_engine

        fixture = Fixture(home="Alpha", away="Bravo", venue=None, match_number=1, match_label="Semi-final 1")

        with patch.object(engine_mod.EngineFactory, "create", side_effect=_fake_create):
            winner = engine._run_fixture(fixture, stage="playoff")

        assert winner == "Alpha"
        # Points table must stay untouched by playoff fixtures.
        assert engine._points_table["Alpha"].played == 1  # only the earlier group match recorded
        assert engine._points_table["Bravo"].played == 0

    def test_run_fixture_leaves_group_stage_ties_alone(self):
        """The hook is playoff-only - a genuinely tied group-stage match (no
        super over concept there) must not be rewritten."""
        engine = _make_engine(_make_config())

        fake_sim_engine = MagicMock()

        def _fake_create(match, outcome_strat, bowling_strat):
            fake_sim_engine.simulate = lambda: setattr(
                match, "result",
                MatchResult(winner=None, is_tie=True, description="Match Tied", team_innings_summary={}),
            )
            return fake_sim_engine

        fixture = Fixture(home="Alpha", away="Bravo", venue=None, match_number=1, match_label="Match 1")

        with patch.object(engine_mod.EngineFactory, "create", side_effect=_fake_create):
            winner = engine._run_fixture(fixture, stage="group")

        assert winner is None
        assert engine._points_table["Alpha"].tied == 1
