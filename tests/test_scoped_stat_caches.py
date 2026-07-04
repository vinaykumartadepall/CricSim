"""
Tests for the per-player-scoped cache loaders fixed this session — each of
these used to bulk-load the ENTIRE table (all players who've ever played,
not just the ones actually needed) into _PRECOMPUTED_CACHE:

  - _ensure_in_roles_cache            (was _load_roles_cache)
  - _ensure_in_workload_cache         (was _load_workload_cache)
  - _ensure_in_bowler_order_cache     (was _load_bowler_order_cache)
  - _ensure_in_country_stats_cache    (was _load_player_country_stats_cache,
                                        measured at 854MB / 8,592 players for
                                        a single format — the dominant
                                        contributor to production swap
                                        thrashing)
  - get_batter_death_stats / get_bowler_phase_stats (measured at 1.24GB via
    the unscoped _load_player_stat_cache — the single largest contributor
    found)

Each test class verifies two things per method:
  1. The DB query is actually scoped to the requested player_ids (not the
     whole table) — the actual bug being fixed.
  2. Calling it twice with different, non-overlapping player sets merges
     into the same cache rather than losing the first batch — the
     regression this incremental-loading pattern must not introduce.

All tests run without a live DB connection.
"""
from unittest.mock import MagicMock, patch

from db.stats_repository import StatsRepository, _PRECOMPUTED_CACHE


def _make_repo():
    repo = StatsRepository.__new__(StatsRepository)
    repo.conn = MagicMock()
    return repo


class TestEnsureInRolesCache:

    def setup_method(self):
        _PRECOMPUTED_CACHE.pop(('roles',), None)
        _PRECOMPUTED_CACHE.pop(('roles_loaded_pids',), None)

    teardown_method = setup_method

    def test_no_conn_returns_empty(self):
        repo = StatsRepository.__new__(StatsRepository)
        repo.conn = None
        assert repo._ensure_in_roles_cache([1]) == {}

    def test_queries_only_requested_players(self):
        repo = _make_repo()
        with patch.object(repo, '_run_query', return_value=[(1, {'is_keeper': True})]) as mock_q:
            repo._ensure_in_roles_cache([1])
        _, params = mock_q.call_args[0]
        assert params == ([1],)

    def test_merges_across_calls_without_losing_first_batch(self):
        repo = _make_repo()
        with patch.object(repo, '_run_query') as mock_q:
            mock_q.return_value = [(1, {'is_keeper': True})]
            repo._ensure_in_roles_cache([1])
            mock_q.return_value = [(2, {'is_spinner': True})]
            result = repo._ensure_in_roles_cache([2])
        assert 1 in result and 2 in result
        assert mock_q.call_count == 2

    def test_second_call_same_player_does_not_requery(self):
        repo = _make_repo()
        with patch.object(repo, '_run_query', return_value=[(1, {'is_keeper': True})]) as mock_q:
            repo._ensure_in_roles_cache([1])
            repo._ensure_in_roles_cache([1])
        assert mock_q.call_count == 1

    def test_get_wicket_keepers_uses_scoped_cache(self):
        repo = _make_repo()
        with patch.object(repo, '_run_query', return_value=[(1, {'is_keeper': True}), (2, {'is_keeper': False})]):
            result = repo.get_wicket_keepers([1, 2])
        assert result == {1}


class TestEnsureInWorkloadCache:

    def setup_method(self):
        _PRECOMPUTED_CACHE.pop(('workload_pc', 'T20'), None)
        _PRECOMPUTED_CACHE.pop(('workload_pc_loaded_pids', 'T20'), None)

    teardown_method = setup_method

    def test_queries_only_requested_players(self):
        repo = _make_repo()
        with patch.object(repo, '_run_query', return_value=[(1, {'avg_overs': 3.5})]) as mock_q:
            repo._ensure_in_workload_cache([1], 'T20')
        _, params = mock_q.call_args[0]
        assert params == ('T20', [1])

    def test_merges_across_calls(self):
        repo = _make_repo()
        with patch.object(repo, '_run_query') as mock_q:
            mock_q.return_value = [(1, {'avg_overs': 3.5})]
            repo._ensure_in_workload_cache([1], 'T20')
            mock_q.return_value = [(2, {'avg_overs': 4.0})]
            result = repo._ensure_in_workload_cache([2], 'T20')
        assert 1 in result and 2 in result

    def test_get_bowler_workload_precomputed_filters_to_requested(self):
        repo = _make_repo()
        with patch.object(repo, '_run_query', return_value=[(1, {'avg_overs': 3.5})]):
            result = repo.get_bowler_workload_precomputed([1], 'T20')
        assert set(result.keys()) == {1}


class TestEnsureInBowlerOrderCache:

    def setup_method(self):
        for k in [('bowler_order_pc', 'T20', 'over_freq'), ('bowler_order_pc_loaded_pids', 'T20', 'over_freq')]:
            _PRECOMPUTED_CACHE.pop(k, None)

    teardown_method = setup_method

    def test_queries_only_requested_players(self):
        repo = _make_repo()
        with patch.object(repo, '_run_query', return_value=[(1, 'all', 0, {'0': 0.1})]) as mock_q:
            repo._ensure_in_bowler_order_cache([1], 'T20', 'over_freq')
        _, params = mock_q.call_args[0]
        assert params == ('T20', 'over_freq', [1])

    def test_merges_across_calls_preserving_nested_structure(self):
        repo = _make_repo()
        with patch.object(repo, '_run_query') as mock_q:
            mock_q.return_value = [(1, 'all', 0, {'0': 0.1})]
            repo._ensure_in_bowler_order_cache([1], 'T20', 'over_freq')
            mock_q.return_value = [(2, 'all', 0, {'0': 0.2})]
            result = repo._ensure_in_bowler_order_cache([2], 'T20', 'over_freq')
        slot = result[('all', 0)]
        assert 1 in slot and 2 in slot

    def test_get_bowler_over_frequency_precomputed_filters_to_requested(self):
        repo = _make_repo()
        with patch.object(repo, '_run_query', return_value=[(1, 'all', 0, {'0': 0.1}), (2, 'all', 0, {'0': 0.2})]):
            result = repo.get_bowler_over_frequency_precomputed([1], 'T20')
        assert set(result.keys()) == {1}


class TestEnsureInCountryStatsCache:

    def setup_method(self):
        _PRECOMPUTED_CACHE.pop(('pcs_country', 'T20'), None)
        _PRECOMPUTED_CACHE.pop(('pcs_country_loaded_pids', 'T20'), None)

    teardown_method = setup_method

    def test_queries_only_requested_players(self):
        repo = _make_repo()
        rows = [(1, 'India', {'0|0|Dot|': 0.5}, None, 20)]
        with patch.object(repo, '_run_query', return_value=rows) as mock_q:
            repo._ensure_in_country_stats_cache([1], 'T20')
        _, params = mock_q.call_args[0]
        assert params == ('T20', [1])

    def test_merges_across_calls_without_losing_first_batch(self):
        repo = _make_repo()
        with patch.object(repo, '_run_query') as mock_q:
            mock_q.return_value = [(1, 'India', {'0|0|Dot|': 0.5}, None, 20)]
            repo._ensure_in_country_stats_cache([1], 'T20')
            mock_q.return_value = [(2, 'Australia', {'0|0|Dot|': 0.4}, None, 15)]
            result = repo._ensure_in_country_stats_cache([2], 'T20')
        assert (1, 'India') in result
        assert (2, 'Australia') in result

    def test_get_player_country_distribution_uses_scoped_cache(self):
        repo = _make_repo()
        rows = [(1, 'India', {'0|0|Dot|': 1.0}, None, 20)]
        with patch.object(repo, '_run_query', return_value=rows) as mock_q:
            result = repo.get_player_country_distribution([1], 'India', 'T20')
        assert 1 in result
        # confirms the query itself was scoped to player 1, not the whole table
        _, params = mock_q.call_args[0]
        assert params == ('T20', [1])


class TestDeathAndPhaseStatsUseScopedSource:
    """get_batter_death_stats / get_bowler_phase_stats derive from
    player_outcome_stats — verify they now go through the already-scoped
    _ensure_in_stat_cache instead of the unscoped bulk _load_player_stat_cache."""

    def setup_method(self):
        for key_prefix in ('batter_death_stats', 'batter_death_stats_loaded_pids',
                           'bowler_phase_stats', 'bowler_phase_stats_loaded_pids'):
            for k in list(_PRECOMPUTED_CACHE.keys()):
                if k[0] == key_prefix:
                    del _PRECOMPUTED_CACHE[k]
        for k in list(_PRECOMPUTED_CACHE.keys()):
            if k[0] in ('pos', 'pos_loaded_pids', 'pos_all_loaded'):
                del _PRECOMPUTED_CACHE[k]

    teardown_method = setup_method

    def test_batter_death_stats_queries_only_requested_players(self):
        repo = _make_repo()
        # raw row format: probs_raw is JSON with 'rb|re|ot|ok' string keys, as
        # returned by the real DB — _ensure_in_stat_cache decodes it internally.
        raw_json = {'4|0|Runs|': 1.0}
        with patch.object(repo, '_run_query', return_value=[(1, raw_json, None, 10)]) as mock_q:
            repo.get_batter_death_stats([1], 'T20')
        # every _run_query call must have been scoped by player_id = ANY([1])
        for call in mock_q.call_args_list:
            _, params = call[0]
            assert 1 in params[-1]
            assert len(params[-1]) == 1

    def test_bowler_phase_stats_queries_only_requested_players(self):
        repo = _make_repo()
        raw_json = {'0|0|Dot|': 1.0}
        with patch.object(repo, '_run_query', return_value=[(5, raw_json, None, 10)]) as mock_q:
            repo.get_bowler_phase_stats([5], 'T20')
        for call in mock_q.call_args_list:
            _, params = call[0]
            assert 5 in params[-1]
            assert len(params[-1]) == 1

    def test_second_call_with_different_players_merges(self):
        repo = _make_repo()
        raw_json = {'4|0|Runs|': 1.0}
        with patch.object(repo, '_run_query') as mock_q:
            mock_q.return_value = [(1, raw_json, None, 10)]
            first = repo.get_batter_death_stats([1], 'T20')
            mock_q.return_value = [(2, raw_json, None, 10)]
            second = repo.get_batter_death_stats([2], 'T20')
        assert 1 in first
        assert 2 in second
        # first player's derived stats must still be retrievable afterward
        both = repo.get_batter_death_stats([1, 2], 'T20')
        assert 1 in both and 2 in both
