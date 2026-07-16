"""
Tests for api/routes/admin.py using FastAPI's TestClient.

No live DB connection required - these routes only touch in-process state
(simulator.logger's level, db.stats_repository's cache strategy,
simulator.admin_settings' simulation defaults), none of which need Postgres.

Admin routes require a verified Supabase JWT belonging to a user listed in
ADMIN_USER_IDS (api/deps.py::require_admin_user). The client fixture bypasses
the JWT-verification step via dependency_overrides and grants the test user
admin rights through the env var, which the guard reads per-request.
"""
import os

import pytest

import db.stats_repository as sr_mod
from db.stats_repository import PersistentCacheStrategy, StatsRepository
from fastapi.testclient import TestClient
from simulator.admin_settings import get_admin_settings
from simulator.logger import get_current_log_level, set_log_level

from api.deps import get_current_user_id
from api.main import app

_TEST_ADMIN_ID = "test-admin-uuid"


@pytest.fixture(scope="module")
def client():
    # Use as a context manager so FastAPI's lifespan (configure_logger, which
    # attaches the RotatingFileHandler that /admin/log-level reads/writes) runs.
    prev_env = os.environ.get("ADMIN_USER_IDS")
    os.environ["ADMIN_USER_IDS"] = _TEST_ADMIN_ID
    app.dependency_overrides[get_current_user_id] = lambda: _TEST_ADMIN_ID
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
        if prev_env is None:
            os.environ.pop("ADMIN_USER_IDS", None)
        else:
            os.environ["ADMIN_USER_IDS"] = prev_env


class TestLogLevelRoute:

    def setup_method(self):
        self._original = get_current_log_level()

    def teardown_method(self):
        set_log_level(self._original)

    def test_get_returns_current_level(self, client):
        set_log_level("WARNING")
        resp = client.get("/admin/log-level")
        assert resp.status_code == 200
        assert resp.json() == {"level": "WARNING"}

    def test_put_changes_level(self, client):
        resp = client.put("/admin/log-level", json={"level": "debug"})
        assert resp.status_code == 200
        assert resp.json() == {"level": "DEBUG"}
        assert get_current_log_level() == "DEBUG"

    def test_put_rejects_invalid_level(self, client):
        resp = client.put("/admin/log-level", json={"level": "NOT_A_LEVEL"})
        assert resp.status_code == 422


class TestCacheStrategyRoute:

    def setup_method(self):
        self._original_cache = sr_mod._PRECOMPUTED_CACHE

    def teardown_method(self):
        sr_mod._PRECOMPUTED_CACHE = self._original_cache

    def test_get_returns_current_strategy_and_options(self, client):
        sr_mod._PRECOMPUTED_CACHE = PersistentCacheStrategy()
        resp = client.get("/admin/cache-strategy")
        assert resp.status_code == 200
        body = resp.json()
        assert body["strategy"] == "persistent"
        assert set(body["available"]) == {"persistent", "per_job"}

    def test_put_switches_strategy(self, client):
        resp = client.put("/admin/cache-strategy", json={"strategy": "per_job"})
        assert resp.status_code == 200
        assert resp.json()["strategy"] == "per_job"
        assert StatsRepository.get_cache_strategy_name() == "per_job"

    def test_put_rejects_unknown_strategy(self, client):
        resp = client.put("/admin/cache-strategy", json={"strategy": "bogus"})
        assert resp.status_code == 422


class TestSimulationDefaultsRoute:

    def setup_method(self):
        s = get_admin_settings()
        self._original_outcome = s.default_outcome_strategy
        self._original_bowling = s.default_bowling_strategy

    def teardown_method(self):
        s = get_admin_settings()
        s.default_outcome_strategy = self._original_outcome
        s.default_bowling_strategy = self._original_bowling

    def test_get_returns_current_defaults_and_options(self, client):
        resp = client.get("/admin/simulation-defaults")
        assert resp.status_code == 200
        body = resp.json()
        assert "outcome_strategy" in body
        assert "bowling_strategy" in body
        assert set(body["available_outcome_strategies"]) == {"enhanced", "historical"}
        assert set(body["available_bowling_strategies"]) == {"historical", "smart"}

    def test_put_updates_only_provided_field(self, client):
        resp = client.put("/admin/simulation-defaults", json={"bowling_strategy": "smart"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["bowling_strategy"] == "smart"
        assert body["outcome_strategy"] == self._original_outcome

    def test_put_rejects_unknown_strategy(self, client):
        resp = client.put("/admin/simulation-defaults", json={"outcome_strategy": "bogus"})
        assert resp.status_code == 422


class TestLeaderboardsEnabledRoute:

    def setup_method(self):
        self._original = get_admin_settings().leaderboards_enabled

    def teardown_method(self):
        get_admin_settings().leaderboards_enabled = self._original

    def test_get_returns_current_state(self, client):
        get_admin_settings().leaderboards_enabled = True
        resp = client.get("/admin/leaderboards-enabled")
        assert resp.status_code == 200
        assert resp.json() == {"enabled": True}

    def test_put_disables(self, client):
        resp = client.put("/admin/leaderboards-enabled", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json() == {"enabled": False}
        assert get_admin_settings().leaderboards_enabled is False

    def test_put_re_enables(self, client):
        client.put("/admin/leaderboards-enabled", json={"enabled": False})
        resp = client.put("/admin/leaderboards-enabled", json={"enabled": True})
        assert resp.status_code == 200
        assert resp.json() == {"enabled": True}
        assert get_admin_settings().leaderboards_enabled is True


class TestConsolidatedSettingsRoute:

    def test_get_settings_includes_everything(self, client):
        resp = client.get("/admin/settings")
        assert resp.status_code == 200
        body = resp.json()
        for key in (
            "log_level", "cache_strategy", "available_cache_strategies",
            "outcome_strategy", "bowling_strategy",
            "available_outcome_strategies", "available_bowling_strategies",
            "leaderboards_enabled",
        ):
            assert key in body


class TestDualMount:
    """admin routes are mounted at both /admin/* (direct ops access) and
    /cricsimapi/admin/* (what the browser-facing Admin page actually calls,
    since nginx only proxies the /cricsimapi prefix in production)."""

    def test_settings_reachable_under_both_prefixes(self, client):
        bare = client.get("/admin/settings")
        prefixed = client.get("/cricsimapi/admin/settings")
        assert bare.status_code == 200
        assert prefixed.status_code == 200
        assert bare.json() == prefixed.json()


class TestAdminGuard:
    """require_admin_user (api/deps.py): a verified JWT alone is not enough -
    the user must be listed in ADMIN_USER_IDS, and an unset env var locks
    everyone out (fail closed) rather than opening the routes."""

    def test_no_token_is_401(self, client):
        # Remove the override so the real JWT dependency runs; without an
        # Authorization header it must 401 before any admin check.
        saved = app.dependency_overrides.pop(get_current_user_id)
        try:
            assert client.get("/admin/settings").status_code == 401
        finally:
            app.dependency_overrides[get_current_user_id] = saved

    def test_non_admin_user_is_403_on_all_mounts(self, client):
        app.dependency_overrides[get_current_user_id] = lambda: "not-the-admin"
        try:
            assert client.get("/admin/settings").status_code == 403
            assert client.get("/cricsimapi/admin/settings").status_code == 403
            # admin_squads router is guarded too (it has a destructive DELETE);
            # the 403 fires in the dependency, before the route touches the DB.
            assert client.get("/admin/squads/tournaments").status_code == 403
        finally:
            app.dependency_overrides[get_current_user_id] = lambda: _TEST_ADMIN_ID

    def test_admin_user_is_allowed(self, client):
        assert client.get("/admin/settings").status_code == 200

    def test_unset_env_fails_closed_even_for_valid_user(self, client):
        prev = os.environ.pop("ADMIN_USER_IDS")
        try:
            assert client.get("/admin/settings").status_code == 403
        finally:
            os.environ["ADMIN_USER_IDS"] = prev

    def test_non_admin_cannot_mutate_settings(self, client):
        app.dependency_overrides[get_current_user_id] = lambda: "not-the-admin"
        try:
            before = get_current_log_level()
            resp = client.put("/admin/log-level", json={"level": "ERROR"})
            assert resp.status_code == 403
            assert get_current_log_level() == before
        finally:
            app.dependency_overrides[get_current_user_id] = lambda: _TEST_ADMIN_ID
