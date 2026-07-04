"""
Tests for the pluggable _PRECOMPUTED_CACHE retention strategies:
  - PersistentCacheStrategy (default) — entries survive on_job_end()
  - PerJobCacheStrategy — on_job_end() wipes the cache
  - Strategy selection via the STATS_CACHE_STRATEGY env var
  - StatsRepository.on_job_end() / clear_cache() delegate to the active strategy

No live DB connection required anywhere in this file.
"""
from unittest.mock import patch

import db.stats_repository as sr_mod
import api.worker as worker_mod
from db.stats_repository import (
    StatsRepository,
    PersistentCacheStrategy,
    PerJobCacheStrategy,
    _make_cache_strategy,
)


class TestPersistentCacheStrategy:

    def test_behaves_like_a_dict(self):
        cache = PersistentCacheStrategy()
        cache[('pos', 'T20', 'batting')] = {1: 'x'}
        assert ('pos', 'T20', 'batting') in cache
        assert cache[('pos', 'T20', 'batting')] == {1: 'x'}
        assert cache.get(('missing',)) is None
        assert len(cache) == 1

    def test_on_job_end_does_not_clear(self):
        cache = PersistentCacheStrategy()
        cache[('pos', 'T20', 'batting')] = {1: 'x'}
        cache.on_job_end()
        assert len(cache) == 1
        assert cache[('pos', 'T20', 'batting')] == {1: 'x'}


class TestPerJobCacheStrategy:

    def test_behaves_like_a_dict(self):
        cache = PerJobCacheStrategy()
        cache[('pos', 'T20', 'batting')] = {1: 'x'}
        assert ('pos', 'T20', 'batting') in cache
        assert cache[('pos', 'T20', 'batting')] == {1: 'x'}

    def test_on_job_end_clears_everything(self):
        cache = PerJobCacheStrategy()
        cache[('pos', 'T20', 'batting')] = {1: 'x'}
        cache[('agg', 'T20', 'male')] = {2: 'y'}
        cache.on_job_end()
        assert len(cache) == 0

    def test_reuse_within_same_job_survives_until_end(self):
        # Simulates several matches within one tournament job reusing the
        # same cached entries — nothing resets mid-job, only on_job_end()
        # (called once the whole job finishes) wipes it.
        cache = PerJobCacheStrategy()
        cache[('pos', 'T20', 'batting')] = {1: 'x'}
        cache[('pos', 'T20', 'bowling')] = {2: 'y'}  # a "later match" reusing the cache
        assert cache[('pos', 'T20', 'batting')] == {1: 'x'}
        assert len(cache) == 2
        cache.on_job_end()
        assert len(cache) == 0


class TestStrategySelection:

    def _reload_with_env(self, monkeypatch, value):
        if value is None:
            monkeypatch.delenv('STATS_CACHE_STRATEGY', raising=False)
        else:
            monkeypatch.setenv('STATS_CACHE_STRATEGY', value)

    def test_defaults_to_persistent(self, monkeypatch):
        self._reload_with_env(monkeypatch, None)
        assert isinstance(_make_cache_strategy(), PersistentCacheStrategy)

    def test_selects_per_job(self, monkeypatch):
        self._reload_with_env(monkeypatch, 'per_job')
        assert isinstance(_make_cache_strategy(), PerJobCacheStrategy)

    def test_unknown_value_falls_back_to_persistent(self, monkeypatch):
        self._reload_with_env(monkeypatch, 'not-a-real-strategy')
        assert isinstance(_make_cache_strategy(), PersistentCacheStrategy)

    def test_case_insensitive(self, monkeypatch):
        self._reload_with_env(monkeypatch, 'PER_JOB')
        assert isinstance(_make_cache_strategy(), PerJobCacheStrategy)


class TestStatsRepositoryDelegation:

    def setup_method(self):
        self._original_cache = sr_mod._PRECOMPUTED_CACHE

    def teardown_method(self):
        sr_mod._PRECOMPUTED_CACHE = self._original_cache

    def test_on_job_end_delegates_to_active_strategy(self):
        fake = PerJobCacheStrategy()
        fake[('pos', 'T20', 'batting')] = {1: 'x'}
        sr_mod._PRECOMPUTED_CACHE = fake

        StatsRepository.on_job_end()

        assert len(fake) == 0

    def test_on_job_end_is_noop_under_persistent(self):
        fake = PersistentCacheStrategy()
        fake[('pos', 'T20', 'batting')] = {1: 'x'}
        sr_mod._PRECOMPUTED_CACHE = fake

        StatsRepository.on_job_end()

        assert len(fake) == 1

    def test_clear_cache_still_works_regardless_of_strategy(self):
        fake = PersistentCacheStrategy()
        fake[('pos', 'T20', 'batting')] = {1: 'x'}
        sr_mod._PRECOMPUTED_CACHE = fake

        removed = StatsRepository.clear_cache()

        assert removed == 1
        assert len(fake) == 0


# ---------------------------------------------------------------------------
# Runtime hot-swap — StatsRepository.set_cache_strategy() (admin page control)
# ---------------------------------------------------------------------------

class TestSetCacheStrategy:

    def setup_method(self):
        self._original_cache = sr_mod._PRECOMPUTED_CACHE

    def teardown_method(self):
        sr_mod._PRECOMPUTED_CACHE = self._original_cache

    def test_available_cache_strategies(self):
        assert StatsRepository.available_cache_strategies() == ['per_job', 'persistent']

    def test_get_cache_strategy_name_reflects_current_object(self):
        sr_mod._PRECOMPUTED_CACHE = PersistentCacheStrategy()
        assert StatsRepository.get_cache_strategy_name() == 'persistent'
        sr_mod._PRECOMPUTED_CACHE = PerJobCacheStrategy()
        assert StatsRepository.get_cache_strategy_name() == 'per_job'

    def test_set_cache_strategy_swaps_the_active_object(self):
        sr_mod._PRECOMPUTED_CACHE = PersistentCacheStrategy()
        StatsRepository.set_cache_strategy('per_job')
        assert isinstance(sr_mod._PRECOMPUTED_CACHE, PerJobCacheStrategy)

    def test_set_cache_strategy_starts_empty_even_if_old_had_entries(self):
        old = PersistentCacheStrategy()
        old[('pos', 'T20', 'batting')] = {1: 'x'}
        sr_mod._PRECOMPUTED_CACHE = old

        StatsRepository.set_cache_strategy('per_job')

        assert len(sr_mod._PRECOMPUTED_CACHE) == 0
        # old object itself is untouched — just no longer referenced
        assert len(old) == 1

    def test_set_cache_strategy_rejects_unknown_name(self):
        import pytest
        with pytest.raises(ValueError, match="Unknown cache strategy"):
            StatsRepository.set_cache_strategy('not-a-real-strategy')

    def test_on_job_end_after_hot_swap_uses_new_strategy(self):
        # Regression guard: on_job_end() must look up _PRECOMPUTED_CACHE by
        # module-global name at call time, not a stale captured reference.
        sr_mod._PRECOMPUTED_CACHE = PersistentCacheStrategy()
        StatsRepository.set_cache_strategy('per_job')
        sr_mod._PRECOMPUTED_CACHE[('pos', 'T20', 'batting')] = {1: 'x'}

        StatsRepository.on_job_end()

        assert len(sr_mod._PRECOMPUTED_CACHE) == 0


# ---------------------------------------------------------------------------
# Jobs must release the cache on both success AND failure — on_job_end() is
# called from a `finally` block precisely so a crashed job doesn't leave its
# entries lingering until whenever the next job happens to start.
# ---------------------------------------------------------------------------

class TestJobsCallOnJobEndFromFinally:

    def test_run_match_job_calls_on_job_end_even_when_it_raises(self):
        with patch.object(worker_mod, 'SimulationRepository') as MockSimRepo, \
             patch.object(worker_mod, 'StatsRepository') as MockStatsRepo, \
             patch.object(worker_mod, 'MatchRunner') as MockRunner:
            MockRunner.return_value.run.side_effect = RuntimeError("boom")

            worker_mod.run_match_job("sim-1", {})

            MockStatsRepo.on_job_end.assert_called_once()
            MockSimRepo.return_value.update_status.assert_any_call(
                "sim-1", "failed", error="boom"
            )

    def test_run_tournament_job_calls_on_job_end_even_when_it_raises(self):
        with patch.object(worker_mod, 'SimulationRepository') as MockSimRepo, \
             patch.object(worker_mod, 'StatsRepository') as MockStatsRepo, \
             patch.object(worker_mod, '_build_tournament_config') as mock_build:
            mock_build.side_effect = RuntimeError("boom")

            worker_mod.run_tournament_job("sim-2", {})

            MockStatsRepo.on_job_end.assert_called_once()
            MockSimRepo.return_value.update_status.assert_any_call(
                "sim-2", "failed", error="boom"
            )

    def test_run_match_job_calls_on_job_end_on_success_too(self):
        with patch.object(worker_mod, 'SimulationRepository') as MockSimRepo, \
             patch.object(worker_mod, 'StatsRepository') as MockStatsRepo, \
             patch.object(worker_mod, 'MatchRunner') as MockRunner:
            match = MockRunner.return_value.run.return_value
            match.innings = []

            worker_mod.run_match_job("sim-3", {})

            MockStatsRepo.on_job_end.assert_called_once()
            MockSimRepo.return_value.update_status.assert_any_call("sim-3", "completed")
