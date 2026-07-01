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


def _phase_freq_rows():
    """Minimal mock rows: (player_id, probs_jsonb_dict)."""
    return [
        (
            42,
            {
                "n": 30,
                "buckets": {
                    "1": {"0": 0.9, "1": 0.7, "2": 0.5},
                    "2": {"0": 0.4, "1": 0.3},
                },
            },
        ),
        (
            99,
            {
                "n": 10,
                "buckets": {
                    "1": {"3": 0.6},
                },
            },
        ),
    ]


class TestLoadTestPhaseFreqCache:

    def setup_method(self):
        _PRECOMPUTED_CACHE.pop(('test_phase_freq_pc',), None)

    def teardown_method(self):
        _PRECOMPUTED_CACHE.pop(('test_phase_freq_pc',), None)

    def test_returns_empty_dict_when_no_conn(self):
        repo = _make_repo_no_db()
        result = repo._load_test_phase_freq_cache()
        assert result == {}
        assert _PRECOMPUTED_CACHE[('test_phase_freq_pc',)] == {}

    def test_parses_rows_into_expected_structure(self):
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query', return_value=_phase_freq_rows()):
            result = repo._load_test_phase_freq_cache()

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
        with patch.object(repo, '_run_query', return_value=_phase_freq_rows()):
            result = repo._load_test_phase_freq_cache()
        buckets = result[42]['buckets']
        assert all(isinstance(k, int) for k in buckets)
        for phases in buckets.values():
            assert all(isinstance(k, int) for k in phases)

    def test_cached_on_second_call(self):
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query', return_value=_phase_freq_rows()) as mock_q:
            repo._load_test_phase_freq_cache()
            repo._load_test_phase_freq_cache()
        assert mock_q.call_count == 1


class TestGetBowlerTestPhaseFrequencyPrecomputed:

    def setup_method(self):
        _PRECOMPUTED_CACHE.pop(('test_phase_freq_pc',), None)

    def teardown_method(self):
        _PRECOMPUTED_CACHE.pop(('test_phase_freq_pc',), None)

    def test_filters_by_player_ids(self):
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query', return_value=_phase_freq_rows()):
            result = repo.get_bowler_test_phase_frequency_precomputed([42])
        assert 42 in result
        assert 99 not in result

    def test_returns_empty_for_unknown_players(self):
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query', return_value=_phase_freq_rows()):
            result = repo.get_bowler_test_phase_frequency_precomputed([999])
        assert result == {}

    def test_returns_all_when_all_ids_present(self):
        repo = _make_repo_no_db()
        repo.conn = MagicMock()
        with patch.object(repo, '_run_query', return_value=_phase_freq_rows()):
            result = repo.get_bowler_test_phase_frequency_precomputed([42, 99])
        assert set(result.keys()) == {42, 99}
