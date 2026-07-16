"""
Unit tests for SimulationRepository.get_challenge_leaderboard.

Regression-guards the query shape: must span ALL users for a given
tournament+team+mode (not just the caller), dedupe to one row per user via
their best attempt (placement -> fewest swaps -> highest win%), and expose
ties via RANK() so equal finishers share a rank. No live DB - cursor is
mocked per this project's convention.
"""
from unittest.mock import MagicMock

from db.simulation_repository import SimulationRepository


def _make_repo(rows):
    repo = SimulationRepository.__new__(SimulationRepository)
    repo._dict_cur = MagicMock()
    repo._dict_cur.fetchall.return_value = rows
    repo.cur = MagicMock()
    repo.cur.fetchone.return_value = None  # no identity_links row -> client_id resolves to itself
    return repo


class TestChallengeLeaderboardQueryShape:
    def test_spans_all_users_not_just_caller(self):
        repo = _make_repo([])
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        assert "s.client_id = %s" not in query

    def test_filters_on_team_name_and_mode(self):
        repo = _make_repo([])
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        assert "st.name = %s" in query
        assert "gs.mode = %s" in query

    def test_dedupes_one_row_per_user(self):
        repo = _make_repo([])
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        assert "DISTINCT ON (client_id)" in query

    def test_tiebreak_chain_is_placement_then_swaps_then_win_pct(self):
        repo = _make_repo([])
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        # Both the per-user dedup and the outer RANK() must use the full chain.
        assert query.count("placement_rank ASC, swap_count ASC, win_pct DESC") == 2

    def test_uses_rank_not_dense_rank_or_row_number(self):
        repo = _make_repo([])
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        assert "RANK() OVER" in query
        assert "DENSE_RANK()" not in query
        assert "ROW_NUMBER()" not in query

    def test_win_pct_lateral_joined(self):
        repo = _make_repo([])
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        assert "wp.wins" in query and "wp.played" in query

    def test_params_order(self):
        repo = _make_repo([])
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        params = repo._dict_cur.execute.call_args[0][1]
        assert params == (3039, "Mumbai Indians", "challenge", "client-1")

    def test_resolves_caller_client_id_via_identity_links(self):
        repo = _make_repo([])
        repo.cur.fetchone.return_value = ("canonical-1",)
        repo.get_challenge_leaderboard("old-anon-id", 3039, "Mumbai Indians", "challenge")
        params = repo._dict_cur.execute.call_args[0][1]
        assert params[-1] == "canonical-1"

    def test_returns_rows_as_is(self):
        rows = [{"client_id": "a", "best_placement": "Winner", "swap_count": 0,
                  "win_pct": 1.0, "sim_id": "s1", "is_you": True, "rank": 1}]
        repo = _make_repo(rows)
        result = repo.get_challenge_leaderboard("a", 3039, "Mumbai Indians", "challenge")
        assert result == rows
