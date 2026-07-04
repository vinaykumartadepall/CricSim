"""
Tests for Test-format bowler phase-frequency precomputation and cache loading.
All tests run without a live DB connection.
"""

import json
from unittest.mock import MagicMock, patch

import db.stats_repository as sr_mod
from db.stats_repository import StatsRepository, _PRECOMPUTED_CACHE


def _make_repo_no_db():
    repo = StatsRepository.__new__(StatsRepository)
    repo.conn = None
    return repo


def _phase_freq_rows(pids=(42, 99)):
    """Minimal mock rows: (player_id, probs_jsonb_dict)."""
    rows = {
        42: (
            42,
            {
                "n": 30,
                "buckets": {
                    "1": {"0": 0.9, "1": 0.7, "2": 0.5},
                    "2": {"0": 0.4, "1": 0.3},
                },
            },
        ),
        99: (
            99,
            {
                "n": 10,
                "buckets": {
                    "1": {"3": 0.6},
                },
            },
        ),
    }
    return [rows[p] for p in pids if p in rows]


class TestEnsureInTestPhaseFreqCache:

    def setup_method(self):
        _PRECOMPUTED_CACHE.pop(('test_phase_freq_pc',), None)
        _PRECOMPUTED_CACHE.pop(('test_phase_freq_pc_loaded_pids',), None)

    def teardown_method(self):
        _PRECOMPUTED_CACHE.pop(('test_phase_freq_pc',), None)
        _PRECOMPUTED_CACHE.pop(('test_phase_freq_pc_loaded_pids',), None)

    def test_returns_empty_dict_when_no_conn(self):
        repo = _make_repo_no_db()
        result = repo._ensure_in_test_phase_freq_cache([42])
        assert result == {}

    def test_returns_empty_dict_when_no_player_ids(self):
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        result = repo._ensure_in_test_phase_freq_cache([])
        assert result == {}

    def test_parses_rows_into_expected_structure(self):
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query', return_value=_phase_freq_rows([42, 99])):
            result = repo._ensure_in_test_phase_freq_cache([42, 99])

        assert 42 in result
        assert 99 in result

        e42 = result[42]
        assert e42['n'] == 30
        assert e42['buckets'][1][0] == 0.9
        assert e42['buckets'][1][2] == 0.5
        assert e42['buckets'][2][0] == 0.4

        e99 = result[99]
        assert e99['n'] == 10
        assert e99['buckets'][1][3] == 0.6

    def test_string_keys_converted_to_int(self):
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query', return_value=_phase_freq_rows([42])):
            result = repo._ensure_in_test_phase_freq_cache([42])
        buckets = result[42]['buckets']
        assert all(isinstance(k, int) for k in buckets)
        for phases in buckets.values():
            assert all(isinstance(k, int) for k in phases)

    def test_only_queries_for_requested_players_not_everyone(self):
        """The whole point of this fix: must not bulk-load the full table."""
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query', return_value=_phase_freq_rows([42])) as mock_q:
            repo._ensure_in_test_phase_freq_cache([42])
        query, params = mock_q.call_args[0]
        assert params == ([42],)

    def test_second_call_with_same_players_does_not_requery(self):
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query', return_value=_phase_freq_rows([42])) as mock_q:
            repo._ensure_in_test_phase_freq_cache([42])
            repo._ensure_in_test_phase_freq_cache([42])
        assert mock_q.call_count == 1

    def test_second_call_with_new_players_only_queries_the_new_ones(self):
        """Regression guard: must merge, not overwrite/lose the first batch."""
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query') as mock_q:
            mock_q.return_value = _phase_freq_rows([42])
            first = repo._ensure_in_test_phase_freq_cache([42])
            mock_q.return_value = _phase_freq_rows([99])
            second = repo._ensure_in_test_phase_freq_cache([99])

        assert mock_q.call_count == 2
        second_call_params = mock_q.call_args_list[1][0][1]
        assert second_call_params == ([99],)
        # both players' data must still be present after the second call
        assert 42 in second and 99 in second
        assert first is second  # same underlying merged dict object


class TestGetBowlerTestPhaseFrequencyPrecomputed:

    def setup_method(self):
        _PRECOMPUTED_CACHE.pop(('test_phase_freq_pc',), None)
        _PRECOMPUTED_CACHE.pop(('test_phase_freq_pc_loaded_pids',), None)

    def teardown_method(self):
        _PRECOMPUTED_CACHE.pop(('test_phase_freq_pc',), None)
        _PRECOMPUTED_CACHE.pop(('test_phase_freq_pc_loaded_pids',), None)

    def test_filters_by_player_ids(self):
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query', return_value=_phase_freq_rows([42])):
            result = repo.get_bowler_test_phase_frequency_precomputed([42])
        assert 42 in result
        assert 99 not in result

    def test_returns_empty_for_unknown_players(self):
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query', return_value=[]):
            result = repo.get_bowler_test_phase_frequency_precomputed([999])
        assert result == {}

    def test_returns_all_when_all_ids_present(self):
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query', return_value=_phase_freq_rows([42, 99])):
            result = repo.get_bowler_test_phase_frequency_precomputed([42, 99])
        assert set(result.keys()) == {42, 99}
