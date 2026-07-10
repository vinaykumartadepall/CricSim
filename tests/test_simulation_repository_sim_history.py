"""
Unit tests for SimulationRepository.get_sim_history_counts.

Covers the fix where "completed" was counting any finished simulation run
regardless of outcome; it must now only count tournament sims where the
user's team actually won the final (via the _FINAL_LATERAL fragment).
No live DB connection - cursor is mocked per this project's convention.
"""
from unittest.mock import MagicMock

from db.simulation_repository import SimulationRepository


def _make_repo(rows):
    repo = SimulationRepository.__new__(SimulationRepository)
    repo._dict_cur = MagicMock()
    repo._dict_cur.fetchall.return_value = rows
    return repo


class TestSimHistoryCountsRequiresWin:
    def test_step1_no_mode_filters_on_winner(self):
        repo = _make_repo([{"name": "IPL", "tournament_ids": [1, 2], "total": 5, "completed": 1}])
        result = repo.get_sim_history_counts("client-1", None, None)

        query = repo._dict_cur.execute.call_args[0][0]
        assert "mf.winner_id = gs.user_team_id" in query
        assert "_FINAL_LATERAL" not in query  # fragment must be interpolated, not left as literal text
        assert result == [{"name": "IPL", "tournament_ids": [1, 2], "total": 5, "completed": 1}]

    def test_step1_challenge_mode_filters_on_winner(self):
        repo = _make_repo([])
        repo.get_sim_history_counts("client-1", None, "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        assert "mf.winner_id = gs.user_team_id" in query
        assert "gs.mode = 'challenge'" in query

    def test_step2_no_mode_filters_on_winner(self):
        repo = _make_repo([{"tournament_id": 3039, "total": 10, "completed": 2}])
        result = repo.get_sim_history_counts("client-1", [3039], None)
        query = repo._dict_cur.execute.call_args[0][0]
        assert "mf.winner_id = gs.user_team_id" in query
        assert result == [{"tournament_id": 3039, "total": 10, "completed": 2}]

    def test_step2_challenge_mode_filters_on_winner(self):
        repo = _make_repo([])
        repo.get_sim_history_counts("client-1", [3039], "challenge")
        query = repo._dict_cur.execute.call_args[0][0]
        assert "mf.winner_id = gs.user_team_id" in query
        assert "gs.mode = 'challenge'" in query

    def test_all_four_branches_reference_final_match_lateral(self):
        """The 'done' CTE must join the final-match lateral so winner_id is available at all."""
        for tournament_ids, mode in [(None, None), (None, "challenge"), ([1], None), ([1], "challenge")]:
            repo = _make_repo([])
            repo.get_sim_history_counts("client-1", tournament_ids, mode)
            query = repo._dict_cur.execute.call_args[0][0]
            assert "match_label ILIKE" in query, f"missing final-match lookup for tournament_ids={tournament_ids}, mode={mode}"
