"""
Tests for tournament simulation progress tracking (api/worker.py):
  - _PLAYOFF_MATCH_COUNTS stays in sync with every real branch of
    simulator.tournament.scheduler.generate_playoffs
  - total match count = group fixtures + playoff fixtures, computable upfront
  - _estimate_total_deliveries: exact for T20/ODI, labeled rough estimate for Test
  - get_tournament_progress() read access to the in-process progress store
  - _PersistingTournamentEngine._on_fixture_complete increments progress and
    appends a result line for every simulated match, regardless of whether
    persistence succeeds

No live DB connection required anywhere in this file — all the logic under
test is pure/in-process (fixture generation, dict bookkeeping).
"""
from types import SimpleNamespace

import pytest

from api.worker import (
    _PLAYOFF_MATCH_COUNTS,
    _TEST_OVERS_ESTIMATE,
    _TOURNAMENT_PROGRESS,
    _PersistingTournamentEngine,
    _estimate_total_deliveries,
    get_tournament_progress,
)
from simulator.tournament.config import (
    PlayoffConfig, ScheduleConfig, TeamConfig, TournamentConfig, VenueConfig,
)
from simulator.tournament.scheduler import generate_fixtures, generate_playoffs


def _make_config(num_teams: int = 4, playoff_format: str = "none") -> TournamentConfig:
    teams = [
        TeamConfig(name=f"Team {i}", short_name=f"T{i}", players=[])
        for i in range(num_teams)
    ]
    return TournamentConfig(
        tournament_name="Test Cup",
        format="T20",
        gender="male",
        season="2025",
        venues=[VenueConfig(name="Ground A")],
        teams=teams,
        schedule=ScheduleConfig(type="round_robin"),
        playoffs=PlayoffConfig(format=playoff_format, top_n=4),
    )


class TestPlayoffMatchCounts:
    """_PLAYOFF_MATCH_COUNTS must match generate_playoffs' actual fixture
    count for every format it supports — this is what would have caught the
    missing 'quarters_semis_final' entry."""

    @pytest.mark.parametrize("fmt", ["none", "two_teams", "semis_final", "ipl", "quarters_semis_final"])
    def test_matches_real_generate_playoffs_output(self, fmt):
        cfg = _make_config(num_teams=8, playoff_format=fmt)
        standings = [t.name for t in cfg.teams]
        fixtures = generate_playoffs(cfg, standings, start_match_number=1)
        assert len(fixtures) == _PLAYOFF_MATCH_COUNTS[fmt]

    def test_unrecognized_format_defaults_to_zero_like_generate_playoffs_does(self):
        cfg = _make_config(num_teams=8, playoff_format="made_up_format")
        standings = [t.name for t in cfg.teams]
        assert generate_playoffs(cfg, standings, start_match_number=1) == []
        assert _PLAYOFF_MATCH_COUNTS.get("made_up_format", 0) == 0


class TestTotalMatchesFormula:

    def test_round_robin_plus_ipl_playoffs(self):
        cfg = _make_config(num_teams=4, playoff_format="ipl")
        total = len(generate_fixtures(cfg)) + _PLAYOFF_MATCH_COUNTS.get(cfg.playoffs.format, 0)
        # 4 teams round robin = 6 group matches + 4 IPL-style playoff matches
        assert total == 6 + 4

    def test_no_playoffs(self):
        cfg = _make_config(num_teams=4, playoff_format="none")
        total = len(generate_fixtures(cfg)) + _PLAYOFF_MATCH_COUNTS.get(cfg.playoffs.format, 0)
        assert total == 6


class TestEstimateTotalDeliveries:

    def test_t20_is_exact(self):
        # 20 overs x 2 innings x 6 balls x 3 matches
        assert _estimate_total_deliveries("T20", total_matches=3) == 20 * 2 * 6 * 3

    def test_odi_is_exact(self):
        assert _estimate_total_deliveries("ODI", total_matches=2) == 50 * 2 * 6 * 2

    def test_test_format_uses_labeled_rough_estimate(self):
        # No fixed overs_per_innings for Test — days x overs/day, spanning all innings.
        assert _estimate_total_deliveries("Test", total_matches=1) == _TEST_OVERS_ESTIMATE * 6
        assert _TEST_OVERS_ESTIMATE == 5 * 90


class TestGetTournamentProgress:

    def teardown_method(self):
        _TOURNAMENT_PROGRESS.clear()

    def test_returns_none_for_unknown_sim_id(self):
        assert get_tournament_progress("does-not-exist") is None

    def test_returns_current_snapshot_for_known_sim_id(self):
        snapshot = {"completed": 3, "total": 10, "teams": 8, "total_deliveries": 2400, "results": []}
        _TOURNAMENT_PROGRESS["sim-1"] = snapshot
        assert get_tournament_progress("sim-1") == snapshot

    def test_none_again_after_cleanup(self):
        _TOURNAMENT_PROGRESS["sim-1"] = {"completed": 10, "total": 10, "teams": 8, "total_deliveries": 2400, "results": []}
        _TOURNAMENT_PROGRESS.pop("sim-1", None)
        assert get_tournament_progress("sim-1") is None


class TestOnFixtureCompleteIncrementsProgress:

    def teardown_method(self):
        _TOURNAMENT_PROGRESS.clear()

    def _make_engine(self, sim_id: str, team_id_map: dict) -> _PersistingTournamentEngine:
        engine = _PersistingTournamentEngine.__new__(_PersistingTournamentEngine)
        engine._sim_id = sim_id
        engine._team_id_map = team_id_map
        engine._match_counter = 1
        engine._pending_commits = 0
        engine._sim_repo = None  # unused on the TBD early-return path exercised here
        engine._tournament_id = 1
        return engine

    def _make_match(self, description: str = "Team A won by 5 wickets"):
        return SimpleNamespace(result=SimpleNamespace(description=description))

    def test_increments_even_when_teams_not_yet_known(self):
        """Increment happens before the persistence-layer TBD check — progress
        should reflect matches actually simulated, not matches persisted."""
        _TOURNAMENT_PROGRESS["sim-1"] = {"completed": 0, "total": 5, "teams": 4, "total_deliveries": 1000, "results": []}
        engine = self._make_engine("sim-1", team_id_map={})  # no teams known -> TBD early return
        fixture = SimpleNamespace(home="Team A", away="Team B")

        engine._on_fixture_complete(match=self._make_match(), fixture=fixture, stage="group")

        assert _TOURNAMENT_PROGRESS["sim-1"]["completed"] == 1

    def test_increments_once_per_call(self):
        _TOURNAMENT_PROGRESS["sim-1"] = {"completed": 0, "total": 5, "teams": 4, "total_deliveries": 1000, "results": []}
        engine = self._make_engine("sim-1", team_id_map={})
        fixture = SimpleNamespace(home="Team A", away="Team B")

        for _ in range(3):
            engine._on_fixture_complete(match=self._make_match(), fixture=fixture, stage="group")

        assert _TOURNAMENT_PROGRESS["sim-1"]["completed"] == 3

    def test_no_error_when_sim_id_not_tracked(self):
        engine = self._make_engine("untracked-sim", team_id_map={})
        fixture = SimpleNamespace(home="Team A", away="Team B")

        engine._on_fixture_complete(match=self._make_match(), fixture=fixture, stage="group")  # must not raise

        assert get_tournament_progress("untracked-sim") is None

    def test_appends_result_entry_naming_both_teams(self):
        """The mockup names both sides ('IND beat AUS by 5 wkts.') but
        match.result.description only names the winner — so the text must be
        built from fixture.home/away plus the description, not the
        description alone. Structured {label, text, home, away} rather than
        one pre-formatted string so the frontend can style the label (and
        highlight the user's own matches) without parsing it back out."""
        _TOURNAMENT_PROGRESS["sim-1"] = {"completed": 0, "total": 5, "teams": 4, "total_deliveries": 1000, "results": []}
        engine = self._make_engine("sim-1", team_id_map={})
        fixture = SimpleNamespace(home="Mumbai Indians", away="Chennai Super Kings", match_label="Match 1")

        engine._on_fixture_complete(
            match=self._make_match("Mumbai Indians won by 2 wickets"), fixture=fixture, stage="group",
        )

        [entry] = _TOURNAMENT_PROGRESS["sim-1"]["results"]
        assert entry["label"] == "Match 1"
        assert entry["text"] == "Mumbai Indians vs Chennai Super Kings — Mumbai Indians won by 2 wickets"
        assert entry["home"] == "Mumbai Indians"
        assert entry["away"] == "Chennai Super Kings"

    def test_no_result_line_when_match_result_missing(self):
        _TOURNAMENT_PROGRESS["sim-1"] = {"completed": 0, "total": 5, "teams": 4, "total_deliveries": 1000, "results": []}
        engine = self._make_engine("sim-1", team_id_map={})
        fixture = SimpleNamespace(home="Team A", away="Team B")

        engine._on_fixture_complete(match=SimpleNamespace(result=None), fixture=fixture, stage="group")

        assert _TOURNAMENT_PROGRESS["sim-1"]["completed"] == 1
        assert _TOURNAMENT_PROGRESS["sim-1"]["results"] == []
