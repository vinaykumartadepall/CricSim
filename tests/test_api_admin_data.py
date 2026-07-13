"""
Admin data views (api/routes/admin_data.py) - cross-user, unfiltered queries
behind the require_admin_user guard - plus the repo-level admin_view flag and
the public list route's now-required client_id.

No live DB: the route's SimulationRepository is monkeypatched with a fake, and
the repo SQL-construction tests drive list_simulations through a fake cursor.
"""
import os
from datetime import datetime, timezone

import pytest

from fastapi.testclient import TestClient

import api.routes.admin_data as admin_data_mod
from api.deps import get_current_user_id
from api.main import app
from db.simulation_repository import SimulationRepository

_TEST_ADMIN_ID = "test-admin-uuid"

_ROWS = [
    {
        "sim_id": "11111111-aaaa-bbbb-cccc-000000000001",
        "simulation_type": "tournament",
        "status": "completed",
        "created_at": datetime(2026, 7, 13, 9, 55, tzinfo=timezone.utc),
        "completed_at": None,
        "mode": "fun",
        "tournament_name": "IPL",
        "season": "2024",
        "user_team_name": "CSK",
        "swap_count": 2,
        "winner_name": "CSK",
        "user_team_placement": "winner",
        "match_id": None,
        "match_format": "T20",
        "client_id": "someone-else",
        "error_message": None,
        "total_count": 7,
    },
    {
        "sim_id": "11111111-aaaa-bbbb-cccc-000000000002",
        "simulation_type": "match",
        "status": "failed",
        "created_at": datetime(2026, 7, 13, 9, 50, tzinfo=timezone.utc),
        "completed_at": None,
        "mode": "multiplayer",
        "tournament_name": "A vs B",
        "season": None,
        "user_team_name": None,
        "swap_count": None,
        "winner_name": None,
        "user_team_placement": None,
        "match_id": 42,
        "match_format": "Test",
        "client_id": "another-user",
        "error_message": "boom",
        "total_count": 7,
    },
]


class _FakeRepo:
    def list_simulations(self, limit=50, offset=0, client_id=None, admin_view=False):
        assert admin_view is True
        assert client_id is None
        return [dict(r) for r in _ROWS]

    def close(self):
        pass


class _FakeProfileRepo:
    """Profiles live in the Supabase DB; only signed-in users have a row."""

    def get_display_names(self, user_ids):
        assert set(user_ids) == {"someone-else", "another-user"}
        return {"someone-else": "Ravi"}  # 'another-user' is anonymous - no row

    def close(self):
        pass


class _ExplodingProfileRepo:
    def __init__(self):
        raise RuntimeError("supabase unreachable")


@pytest.fixture(scope="module")
def client():
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


class TestAdminSimulationsList:

    def test_returns_all_rows_with_owner_fields_and_total(self, client, monkeypatch):
        monkeypatch.setattr(admin_data_mod, "SimulationRepository", _FakeRepo)
        monkeypatch.setattr(admin_data_mod, "ProfileRepository", _FakeProfileRepo)
        resp = client.get("/cricsimapi/admin/data/simulations")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 7
        assert len(body["simulations"]) == 2
        first, second = body["simulations"]
        assert first["client_id"] == "someone-else"
        assert first["display_name"] == "Ravi"       # signed-in: profile merged in
        assert second["display_name"] is None        # anonymous: no profile row
        assert second["status"] == "failed"
        assert second["error_message"] == "boom"
        # window-count column must not leak into the response rows
        assert "total_count" not in first

    def test_reachable_on_bare_mount_too(self, client, monkeypatch):
        monkeypatch.setattr(admin_data_mod, "SimulationRepository", _FakeRepo)
        monkeypatch.setattr(admin_data_mod, "ProfileRepository", _FakeProfileRepo)
        assert client.get("/admin/data/simulations").status_code == 200

    def test_supabase_outage_degrades_to_ids_only(self, client, monkeypatch):
        # Best effort: the list must still render if the profiles DB is down.
        monkeypatch.setattr(admin_data_mod, "SimulationRepository", _FakeRepo)
        monkeypatch.setattr(admin_data_mod, "ProfileRepository", _ExplodingProfileRepo)
        resp = client.get("/cricsimapi/admin/data/simulations")
        assert resp.status_code == 200
        assert all(r["display_name"] is None for r in resp.json()["simulations"])

    def test_non_admin_is_403(self, client):
        app.dependency_overrides[get_current_user_id] = lambda: "not-the-admin"
        try:
            assert client.get("/cricsimapi/admin/data/simulations").status_code == 403
        finally:
            app.dependency_overrides[get_current_user_id] = lambda: _TEST_ADMIN_ID

    def test_no_token_is_401(self, client):
        saved = app.dependency_overrides.pop(get_current_user_id)
        try:
            assert client.get("/cricsimapi/admin/data/simulations").status_code == 401
        finally:
            app.dependency_overrides[get_current_user_id] = saved


class TestPublicListRequiresClientId:
    """The repo treats client_id=None as 'all users' - reserved for the guarded
    admin view. The public route must therefore reject a missing client_id
    (which previously listed every user's simulations to anyone)."""

    def test_missing_client_id_is_422(self, client):
        assert client.get("/cricsimapi/simulations").status_code == 422


class _FakeCursor:
    def __init__(self):
        self.last_query = None
        self.last_params = None

    def execute(self, query, params=None):
        self.last_query = query
        self.last_params = params

    def fetchall(self):
        return []


class TestRepoAdminViewSql:
    """list_simulations builds one shared query; admin_view only widens it."""

    def _repo_with_fake_cursor(self):
        repo = SimulationRepository.__new__(SimulationRepository)
        repo._dict_cur = _FakeCursor()
        return repo

    def test_admin_view_adds_owner_columns_and_keeps_failed(self):
        repo = self._repo_with_fake_cursor()
        repo.list_simulations(client_id=None, admin_view=True)
        sql = repo._dict_cur.last_query
        assert "s.client_id" in sql
        assert "s.error_message" in sql
        assert "COUNT(*) OVER() AS total_count" in sql
        assert "!= 'failed'" not in sql

    def test_default_view_filters_failed_and_omits_owner_columns(self):
        repo = self._repo_with_fake_cursor()
        repo.list_simulations(client_id="someone")
        sql = repo._dict_cur.last_query
        assert "!= 'failed'" in sql
        assert "s.error_message" not in sql
        assert "total_count" not in sql

    def test_session_join_falls_back_to_sim_owner(self):
        repo = self._repo_with_fake_cursor()
        repo.list_simulations(client_id=None, admin_view=True)
        assert "COALESCE(%s, s.client_id)" in repo._dict_cur.last_query
