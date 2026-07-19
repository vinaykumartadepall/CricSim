"""
Unit tests for SimulationRepository.get_challenge_leaderboard.

Regression-guards the query shape: must span ALL users for a given
tournament+team+mode (not just the caller), dedupe to one row per user via
their best attempt (placement -> fewest swaps -> highest win%), and expose
ties via RANK() so equal finishers share a rank.

Also covers the paginated shape: three separate statements per call (total
count, the requested page, the caller's own row) - the caller's row must be
returned regardless of whether it falls inside the requested page, and
total_entrants must reflect the true count, not just the page size. No live
DB - cursor is mocked per this project's convention.
"""
from unittest.mock import MagicMock

from db.simulation_repository import SimulationRepository


def _make_repo(*, total, page_rows, you_row):
    """
    Mocks the three sequential execute()/fetchone()/fetchall() calls the
    method makes, in order: COUNT(*), the page, and the caller's own row.
    """
    repo = SimulationRepository.__new__(SimulationRepository)
    repo._dict_cur = MagicMock()
    repo._dict_cur.fetchone.side_effect = [{"total": total}, you_row]
    repo._dict_cur.fetchall.side_effect = [page_rows]
    repo.cur = MagicMock()
    repo.cur.fetchone.return_value = None  # no identity_links row -> client_id resolves to itself
    return repo


class TestChallengeLeaderboardQueryShape:
    def test_spans_all_users_not_just_caller(self):
        repo = _make_repo(total=0, page_rows=[], you_row=None)
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        for call in repo._dict_cur.execute.call_args_list:
            assert "s.client_id = %s" not in call[0][0]

    def test_filters_on_team_name_and_mode(self):
        repo = _make_repo(total=0, page_rows=[], you_row=None)
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        query = repo._dict_cur.execute.call_args_list[0][0][0]
        assert "st.name = %s" in query
        assert "gs.mode = %s" in query

    def test_dedupes_one_row_per_user(self):
        repo = _make_repo(total=0, page_rows=[], you_row=None)
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        query = repo._dict_cur.execute.call_args_list[0][0][0]
        assert "DISTINCT ON (client_id)" in query

    def test_tiebreak_chain_is_placement_then_swaps_then_win_pct(self):
        repo = _make_repo(total=0, page_rows=[], you_row=None)
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        query = repo._dict_cur.execute.call_args_list[0][0][0]
        # Both the per-user dedup and the RANK() window must use the full chain.
        assert query.count("placement_rank ASC, swap_count ASC, win_pct DESC") == 2

    def test_uses_rank_not_dense_rank_or_row_number(self):
        repo = _make_repo(total=0, page_rows=[], you_row=None)
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        query = repo._dict_cur.execute.call_args_list[0][0][0]
        assert "RANK() OVER" in query
        assert "DENSE_RANK()" not in query
        assert "ROW_NUMBER()" not in query

    def test_win_pct_lateral_joined(self):
        repo = _make_repo(total=0, page_rows=[], you_row=None)
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        query = repo._dict_cur.execute.call_args_list[0][0][0]
        assert "wp.wins" in query and "wp.played" in query

    def test_resolves_caller_client_id_via_identity_links(self):
        repo = _make_repo(total=0, page_rows=[], you_row=None)
        repo.cur.fetchone.return_value = ("canonical-1",)
        repo.get_challenge_leaderboard("old-anon-id", 3039, "Mumbai Indians", "challenge")
        # The "you" lookup (last execute call) filters by the resolved id.
        params = repo._dict_cur.execute.call_args_list[-1][0][1]
        assert params[-1] == "canonical-1"


class TestChallengeLeaderboardPagination:
    def test_three_queries_count_page_you(self):
        repo = _make_repo(total=0, page_rows=[], you_row=None)
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        assert repo._dict_cur.execute.call_count == 3

    def test_page_query_uses_limit_and_offset(self):
        repo = _make_repo(total=0, page_rows=[], you_row=None)
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge", limit=10, offset=20)
        page_query, page_params = repo._dict_cur.execute.call_args_list[1][0]
        assert "LIMIT %s OFFSET %s" in page_query
        assert page_params[-2:] == (10, 20)

    def test_default_limit_and_offset(self):
        repo = _make_repo(total=0, page_rows=[], you_row=None)
        repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        page_params = repo._dict_cur.execute.call_args_list[1][0][1]
        assert page_params[-2:] == (10, 0)

    def test_total_entrants_reflects_full_count_not_page_size(self):
        repo = _make_repo(
            total=142,
            page_rows=[{"client_id": "a", "best_placement": "Winner", "swap_count": 0, "win_pct": 1.0, "sim_id": "s1", "rank": 1}],
            you_row=None,
        )
        result = repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge", limit=1, offset=0)
        assert result["total_entrants"] == 142
        assert len(result["entries"]) == 1

    def test_you_returned_even_when_outside_requested_page(self):
        """Caller ranked #47, but only the top-10 page was requested - `you` must still come back."""
        you_row = {"client_id": "client-1", "best_placement": "Group stage", "swap_count": 2, "win_pct": 0.36, "sim_id": "s99", "rank": 47}
        repo = _make_repo(total=200, page_rows=[], you_row=you_row)
        result = repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge", limit=10, offset=0)
        assert result["you"]["rank"] == 47
        assert result["you"]["is_you"] is True

    def test_you_is_none_when_caller_has_no_attempt(self):
        repo = _make_repo(total=5, page_rows=[], you_row=None)
        result = repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        assert result["you"] is None

    def test_entries_have_is_you_computed_per_row(self):
        page_rows = [
            {"client_id": "client-1", "best_placement": "Winner", "swap_count": 0, "win_pct": 1.0, "sim_id": "s1", "rank": 1},
            {"client_id": "someone-else", "best_placement": "Runner-up", "swap_count": 1, "win_pct": 0.5, "sim_id": "s2", "rank": 2},
        ]
        repo = _make_repo(total=2, page_rows=page_rows, you_row=None)
        result = repo.get_challenge_leaderboard("client-1", 3039, "Mumbai Indians", "challenge")
        assert result["entries"][0]["is_you"] is True
        assert result["entries"][1]["is_you"] is False
