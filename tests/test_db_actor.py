"""
Audit actor plumbing (db/database.py): every connection carries the Postgres
setting app.actor, which the audit columns' defaults and the audit_touch
trigger write into updated_by. These tests pin where the actor comes from.
No live DB connection required - psycopg2.connect is replaced.
"""
import pytest
from fastapi.testclient import TestClient

import api.routes.identity as identity_mod
import api.worker as worker_mod
import db.database as database
from api.deps import get_current_user_id
from api.main import app


@pytest.fixture
def captured_connects(monkeypatch):
    calls = []

    class _Conn:
        autocommit = False

    def fake_connect(*args, **kwargs):
        calls.append((args, kwargs))
        return _Conn()

    monkeypatch.setattr(database.psycopg2, "connect", fake_connect)
    monkeypatch.setattr(database, "_DATABASE_URL", None)
    return calls


def _actor_of(call):
    options = call[1]["options"]
    assert options.startswith("-c app.actor=") or " -c app.actor=" in options
    return options.rsplit("app.actor=", 1)[1]


class TestActorSelection:
    def test_default_actor_is_used_outside_any_block(self, captured_connects, monkeypatch):
        monkeypatch.setattr(database, "_default_actor", "script:precompute")
        database.get_db_connection()
        assert _actor_of(captured_connects[-1]) == "script:precompute"

    def test_db_actor_overrides_and_restores(self, captured_connects, monkeypatch):
        monkeypatch.setattr(database, "_default_actor", "api")
        with database.db_actor("worker:sim:abc"):
            database.get_db_connection()
            with database.db_actor("user:42"):
                database.get_db_connection()
            database.get_db_connection()
        database.get_db_connection()
        assert [_actor_of(c) for c in captured_connects] == ["worker:sim:abc", "user:42", "worker:sim:abc", "api"]

    def test_set_default_actor(self, captured_connects, monkeypatch):
        monkeypatch.setattr(database, "_default_actor", "script:x")
        database.set_default_actor("api")
        database.get_db_connection()
        assert _actor_of(captured_connects[-1]) == "api"

    @pytest.mark.parametrize("raw, clean", [
        ("user:9f1 x;drop", "user:9f1_x_drop"),
        ("client:a'b\\c", "client:a_b_c"),
        ("", "unknown"),
        (None, "unknown"),
        ("x" * 300, "x" * 100),
    ])
    def test_actor_is_sanitised_for_libpq_options(self, raw, clean):
        assert database._sanitize_actor(raw) == clean


class TestConnectOptions:
    def test_keyword_connection_gets_options(self, captured_connects):
        database.get_db_connection()
        args, kwargs = captured_connects[-1]
        assert args == ()
        assert kwargs["options"].startswith("-c app.actor=")
        assert kwargs["dbname"] == database.DB_NAME

    def test_url_connection_keeps_its_own_options(self, captured_connects, monkeypatch):
        url = "postgresql://u:p@h:5432/db?options=-c%20search_path%3Dfoo"
        monkeypatch.setattr(database, "_DATABASE_URL", url)
        database.get_db_connection()
        args, kwargs = captured_connects[-1]
        assert args == (url,)
        assert kwargs["options"].startswith("-c search_path=foo -c app.actor=")


class TestWorkerAttribution:
    def test_match_job_connections_are_attributed_to_the_sim(self, monkeypatch):
        seen = []

        class _Repo:
            def __init__(self):
                seen.append(database.current_actor())
                raise RuntimeError("stop after the first connection")

        monkeypatch.setattr(worker_mod, "SimulationRepository", _Repo)
        with pytest.raises(RuntimeError):
            worker_mod.run_match_job("sim-123", {})
        assert seen == ["worker:sim:sim-123"]
        assert database.current_actor() != "worker:sim:sim-123"

    def test_tournament_job_connections_are_attributed_to_the_sim(self, monkeypatch):
        seen = []

        class _Repo:
            def __init__(self):
                seen.append(database.current_actor())
                raise RuntimeError("stop after the first connection")

        monkeypatch.setattr(worker_mod, "SimulationRepository", _Repo)
        with pytest.raises(RuntimeError):
            worker_mod.run_tournament_job("sim-456", {})
        assert seen == ["worker:sim:sim-456"]


class TestApiAttribution:
    """No `with TestClient(...)`: the lifespan (startup sweep) isn't needed here."""

    @pytest.fixture
    def recording_identity_repo(self, monkeypatch):
        seen = []

        class _Repo:
            def __init__(self):
                seen.append(database.current_actor())

            def sync_anonymous(self, *a):
                pass

            def link_account(self, auth_id, current_client_id, fallback_username):
                return auth_id

            def get_username(self, canonical_id):
                return "name"

            def close(self):
                pass

        monkeypatch.setattr(identity_mod, "IdentityRepository", _Repo)
        return seen

    def test_anonymous_write_is_attributed_to_the_client(self, recording_identity_repo):
        r = TestClient(app).post("/cricsimapi/identity/sync-anonymous", json={"client_id": "anon-1", "username": "x"})
        assert r.status_code == 204
        assert recording_identity_repo == ["client:anon-1"]

    def test_signed_in_write_is_attributed_to_the_user(self, recording_identity_repo):
        app.dependency_overrides[get_current_user_id] = lambda: "user-uuid-1"
        try:
            r = TestClient(app).post("/cricsimapi/identity/link", json={"client_id": "anon-1", "fallback_username": "x"})
        finally:
            app.dependency_overrides.pop(get_current_user_id, None)
        assert r.status_code == 200
        assert recording_identity_repo == ["user:user-uuid-1"]

    def test_actor_does_not_leak_into_the_next_request(self, recording_identity_repo):
        client = TestClient(app)
        client.post("/cricsimapi/identity/sync-anonymous", json={"client_id": "anon-1", "username": "x"})
        assert database.current_actor() == database._default_actor
        client.post("/cricsimapi/identity/sync-anonymous", json={"client_id": "anon-2", "username": "y"})
        assert recording_identity_repo == ["client:anon-1", "client:anon-2"]
