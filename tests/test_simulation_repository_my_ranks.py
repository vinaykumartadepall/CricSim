"""
Unit tests for SimulationRepository.get_my_challenge_ranks.

The batched, per-tournament sibling of get_challenge_leaderboard: for every
team the caller has attempted, their rank within THAT team's own (all-users)
leaderboard - powers the team-selection screens showing "your rank" per team
in one round trip instead of one call per team. No live DB.
"""
from unittest.mock import MagicMock

from db.simulation_repository import SimulationRepository


def _make_repo(rows):
    repo = SimulationRepository.__new__(SimulationRepository)
    repo._dict_cur = MagicMock()
    repo._dict_cur.fetchall.return_value = rows
    repo.cur = MagicMock()
    repo.cur.fetchone.return_value = None
    return repo


class TestMyChallengeRanksQueryShape:
    def test_spans_all_teams_not_filtered_to_one(self):
        repo = _make_repo([])
        repo.get_my_challenge_ranks("client-1", 3039, "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        assert "st.name = %s" not in query

    def test_ranks_are_partitioned_per_team(self):
        repo = _make_repo([])
        repo.get_my_challenge_ranks("client-1", 3039, "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        assert query.count("PARTITION BY team_name") == 2  # rank + total_entrants windows

    def test_dedupes_one_row_per_team_per_user(self):
        repo = _make_repo([])
        repo.get_my_challenge_ranks("client-1", 3039, "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        assert "DISTINCT ON (team_name, client_id)" in query

    def test_final_select_scoped_to_caller(self):
        repo = _make_repo([])
        repo.get_my_challenge_ranks("client-1", 3039, "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        assert "WHERE client_id = %s" in query

    def test_uses_rank_not_dense_rank(self):
        repo = _make_repo([])
        repo.get_my_challenge_ranks("client-1", 3039, "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        assert "RANK()" in query
        assert "DENSE_RANK()" not in query

    def test_params_order(self):
        repo = _make_repo([])
        repo.get_my_challenge_ranks("client-1", 3039, "challenge")
        params = repo._dict_cur.execute.call_args[0][1]
        assert params == (3039, "challenge", "client-1")

    def test_returns_rows_as_is(self):
        rows = [{"team_name": "CSK", "rank": 2, "total_entrants": 5,
                  "best_placement": "Runner-up", "swap_count": 1, "win_pct": 0.6}]
        repo = _make_repo(rows)
        result = repo.get_my_challenge_ranks("client-1", 3039, "challenge")
        assert result == rows
