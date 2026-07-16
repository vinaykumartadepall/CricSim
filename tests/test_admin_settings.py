"""
Tests for:
  - OutcomeStrategyFactory.available_names() / BowlingStrategyFactory.available_names()
  - simulator.admin_settings (in-memory admin-configurable simulation defaults)
  - match_runner.py / worker.py falling back to the admin default when a
    simulation request doesn't specify its own strategy

No live DB connection required anywhere in this file.
"""
import pytest

from simulator.admin_settings import (
    AdminSettings,
    get_admin_settings,
    set_default_bowling_strategy,
    set_default_outcome_strategy,
    set_leaderboards_enabled,
)
from simulator.predictors.factory import BowlingStrategyFactory, OutcomeStrategyFactory


class TestFactoryAvailableNames:

    def test_outcome_strategy_names(self):
        assert OutcomeStrategyFactory.available_names() == ['enhanced', 'historical']

    def test_bowling_strategy_names(self):
        assert BowlingStrategyFactory.available_names() == ['historical', 'smart']


class TestAdminSettings:

    def setup_method(self):
        s = get_admin_settings()
        self._original_outcome = s.default_outcome_strategy
        self._original_bowling = s.default_bowling_strategy

    def teardown_method(self):
        s = get_admin_settings()
        s.default_outcome_strategy = self._original_outcome
        s.default_bowling_strategy = self._original_bowling

    def test_defaults_are_valid_registered_strategies(self):
        s = get_admin_settings()
        assert s.default_outcome_strategy in OutcomeStrategyFactory.available_names()
        assert s.default_bowling_strategy in BowlingStrategyFactory.available_names()

    def test_set_default_outcome_strategy(self):
        set_default_outcome_strategy('historical')
        assert get_admin_settings().default_outcome_strategy == 'historical'

    def test_set_default_bowling_strategy(self):
        set_default_bowling_strategy('smart')
        assert get_admin_settings().default_bowling_strategy == 'smart'

    def test_set_default_outcome_strategy_rejects_unknown(self):
        with pytest.raises(ValueError, match="Unknown outcome strategy"):
            set_default_outcome_strategy('not-a-real-strategy')

    def test_set_default_bowling_strategy_rejects_unknown(self):
        with pytest.raises(ValueError, match="Unknown bowling strategy"):
            set_default_bowling_strategy('not-a-real-strategy')

    def test_get_admin_settings_returns_same_singleton(self):
        assert get_admin_settings() is get_admin_settings()


class TestLeaderboardsEnabledSetting:

    def setup_method(self):
        self._original = get_admin_settings().leaderboards_enabled

    def teardown_method(self):
        get_admin_settings().leaderboards_enabled = self._original

    def test_defaults_to_false(self, monkeypatch):
        monkeypatch.delenv("LEADERBOARDS_ENABLED", raising=False)
        assert AdminSettings().leaderboards_enabled is False

    def test_set_leaderboards_enabled_false(self):
        set_leaderboards_enabled(False)
        assert get_admin_settings().leaderboards_enabled is False

    def test_set_leaderboards_enabled_true(self):
        set_leaderboards_enabled(False)
        set_leaderboards_enabled(True)
        assert get_admin_settings().leaderboards_enabled is True


class TestLeaderboardsEnabledEnvDefault:

    def test_uses_env_var_when_truthy(self, monkeypatch):
        for value in ("1", "true", "True", "yes", "on"):
            monkeypatch.setenv("LEADERBOARDS_ENABLED", value)
            assert AdminSettings().leaderboards_enabled is True

    def test_uses_env_var_when_falsy(self, monkeypatch):
        for value in ("0", "false", "False", "no", "off"):
            monkeypatch.setenv("LEADERBOARDS_ENABLED", value)
            assert AdminSettings().leaderboards_enabled is False

    def test_falls_back_to_false_when_unset(self, monkeypatch):
        monkeypatch.delenv("LEADERBOARDS_ENABLED", raising=False)
        assert AdminSettings().leaderboards_enabled is False


class TestAdminSettingsEnvDefaults:
    """AdminSettings() reads DEFAULT_OUTCOME_STRATEGY / DEFAULT_BOWLING_STRATEGY
    at construction time - this is only the *startup* default (the module-level
    singleton is built once at import), not a live runtime read. Constructing a
    fresh instance here is how we test the field(default_factory=...) behavior
    in isolation from the process-wide singleton."""

    def test_uses_env_var_when_valid(self, monkeypatch):
        monkeypatch.setenv('DEFAULT_OUTCOME_STRATEGY', 'historical')
        monkeypatch.setenv('DEFAULT_BOWLING_STRATEGY', 'smart')
        s = AdminSettings()
        assert s.default_outcome_strategy == 'historical'
        assert s.default_bowling_strategy == 'smart'

    def test_falls_back_when_env_var_unset(self, monkeypatch):
        monkeypatch.delenv('DEFAULT_OUTCOME_STRATEGY', raising=False)
        monkeypatch.delenv('DEFAULT_BOWLING_STRATEGY', raising=False)
        s = AdminSettings()
        assert s.default_outcome_strategy == 'enhanced'
        assert s.default_bowling_strategy == 'historical'

    def test_falls_back_when_env_var_invalid(self, monkeypatch):
        monkeypatch.setenv('DEFAULT_OUTCOME_STRATEGY', 'not-a-real-strategy')
        monkeypatch.setenv('DEFAULT_BOWLING_STRATEGY', 'also-not-real')
        s = AdminSettings()
        assert s.default_outcome_strategy == 'enhanced'
        assert s.default_bowling_strategy == 'historical'


class TestMatchRunnerUsesAdminDefault:

    def setup_method(self):
        self._original_outcome = get_admin_settings().default_outcome_strategy
        self._original_bowling = get_admin_settings().default_bowling_strategy

    def teardown_method(self):
        get_admin_settings().default_outcome_strategy = self._original_outcome
        get_admin_settings().default_bowling_strategy = self._original_bowling

    def _make_runner(self, config):
        from simulator.match_runner import MatchRunner
        from db.stats_repository import StatsRepository
        repo = StatsRepository.__new__(StatsRepository)
        repo.conn = None
        return MatchRunner(config, repo=repo, silent=True)

    def test_uses_admin_default_when_config_omits_strategy(self):
        set_default_outcome_strategy('historical')
        set_default_bowling_strategy('smart')
        runner = self._make_runner({"match_format": "T20"})
        # Strategy factories return concrete strategy instances - check the
        # class name matches what 'historical'/'smart' resolve to, since the
        # runner only stores the built strategy object, not the name string.
        from simulator.predictors.factory import OutcomeStrategyFactory, BowlingStrategyFactory
        expected_outcome = type(OutcomeStrategyFactory.for_name('historical', 'T20'))
        expected_bowling = type(BowlingStrategyFactory.for_name('smart', 'T20'))
        assert isinstance(runner._outcome_strat, expected_outcome)
        assert isinstance(runner._bowling_strat, expected_bowling)

    def test_explicit_config_value_overrides_admin_default(self):
        set_default_outcome_strategy('historical')
        runner = self._make_runner({
            "match_format": "T20",
            "ball_outcome_strategy": "enhanced",
        })
        from simulator.predictors.factory import OutcomeStrategyFactory
        expected = type(OutcomeStrategyFactory.for_name('enhanced', 'T20'))
        assert isinstance(runner._outcome_strat, expected)
