"""
Unit tests for SimulationRepository.save_match_potm / save_final_standings —
the persistence half of moving POTM and NRR/points-table off of recomputed-
on-every-request logic and onto values the live simulation already computed
once, correctly. No live DB connection — cursor is mocked per this project's
convention (see tests/test_simulation_repository_sim_history.py).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from db.simulation_repository import SimulationRepository
from simulator.awards.mvp_strategy import PlayerAward


def _make_repo():
    repo = SimulationRepository.__new__(SimulationRepository)
    repo.cur = MagicMock()
    return repo


class TestSaveMatchPotm:
    def test_writes_player_id_name_team_points(self):
        repo = _make_repo()
        potm = SimpleNamespace(player_id=42, player_name="Virat Kohli", team="RCB", total=87.456)

        repo.save_match_potm(123, potm)

        query, params = repo.cur.execute.call_args[0]
        assert "UPDATE simulation.matches" in query
        assert "player_of_match_id" in query
        assert "potm_player_name" in query
        assert "potm_team_name" in query
        assert "potm_points" in query
        assert params == (42, "Virat Kohli", "RCB", 87.46, 123)  # points rounded to 2dp

    def test_none_potm_is_a_noop(self):
        repo = _make_repo()
        repo.save_match_potm(123, None)
        repo.cur.execute.assert_not_called()


class TestSavePlayerAwards:
    """
    save_player_awards reads batting_pts/bowling_pts/fielding_pts out of each
    PlayerAward.breakdown by convention (that's what StatisticalAwardsStrategy
    reports) rather than off fixed attributes — this pins that contract down
    so a future MvpStrategy's differently-shaped breakdown doesn't silently
    break persistence (it'll just persist zeros for the categories it doesn't
    report, per simulator/awards/mvp_strategy.py's documented convention).
    """

    def test_reads_breakdown_categories_into_fixed_columns(self):
        repo = _make_repo()
        awards = [
            PlayerAward(1, "Alice", team="A", total=42.5,
                        breakdown={"batting_pts": 30.0, "bowling_pts": 12.5}),
        ]

        with patch("psycopg2.extras.execute_batch") as mock_batch:
            repo.save_player_awards("sim-1", awards)

        rows = mock_batch.call_args[0][2]
        assert rows == [("sim-1", 1, "Alice", "A", 30.0, 12.5, 0.0)]  # fielding_pts absent -> 0.0

    def test_missing_breakdown_entirely_defaults_all_categories_to_zero(self):
        repo = _make_repo()
        awards = [PlayerAward(2, "Bob", team="B", total=10.0, breakdown={})]

        with patch("psycopg2.extras.execute_batch") as mock_batch:
            repo.save_player_awards("sim-1", awards)

        rows = mock_batch.call_args[0][2]
        assert rows == [("sim-1", 2, "Bob", "B", 0.0, 0.0, 0.0)]

    def test_inserts_into_player_awards_table(self):
        repo = _make_repo()
        with patch("psycopg2.extras.execute_batch") as mock_batch:
            repo.save_player_awards("sim-1", [PlayerAward(1, "Alice", total=0.0)])

        query = mock_batch.call_args[0][1]
        assert "INSERT INTO simulation.player_awards" in query


class TestSaveFinalStandings:
    def test_writes_standings_as_json_for_sim_id(self):
        repo = _make_repo()
        standings = [
            {"team": "Alpha", "played": 14, "won": 9, "lost": 5, "tied": 0,
             "no_result": 0, "points": 18, "nrr": 0.390},
        ]

        repo.save_final_standings("sim-1", standings)

        query, params = repo.cur.execute.call_args[0]
        assert "UPDATE simulation.tournaments" in query
        assert "final_standings" in query
        assert params[1] == "sim-1"
        # psycopg2.extras.Json wraps the payload — check it round-trips the data, not the wrapper type.
        assert params[0].adapted == standings
