"""
/cricsimapi/identity routes (api/routes/identity.py) - the HTTP surface over
IdentityRepository (simulation.identity_links, migration 031). No live DB:
IdentityRepository is monkeypatched with a fake per test.
"""
import pytest
from fastapi.testclient import TestClient

import api.routes.identity as identity_mod
from api.deps import get_current_user_id
from api.main import app
from db.identity_repository import UsernameTakenError


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_current_user_id, None)


class _FakeRepo:
    """Records calls; lets each test script return values / raise."""

    calls: list

    def __init__(self):
        self.calls = []
        self.closed = False

    def sync_anonymous(self, anon_id, username):
        self.calls.append(("sync_anonymous", anon_id, username))

    def link_account(self, auth_id, current_client_id, fallback_username):
        self.calls.append(("link_account", auth_id, current_client_id, fallback_username))
        if getattr(self, "_link_raises", None):
            raise self._link_raises
        return getattr(self, "_canonical_id", current_client_id)

    def get_username(self, canonical_id):
        self.calls.append(("get_username", canonical_id))
        return getattr(self, "_username", "SomeName")

    def resolve_client_id(self, raw_id):
        self.calls.append(("resolve_client_id", raw_id))
        return getattr(self, "_resolved_id", raw_id)

    def set_username(self, canonical_id, username):
        self.calls.append(("set_username", canonical_id, username))
        if getattr(self, "_set_username_raises", None):
            raise self._set_username_raises

    def rollback(self):
        self.calls.append(("rollback",))

    def close(self):
        self.closed = True


@pytest.fixture
def fake_repo(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(identity_mod, "IdentityRepository", lambda: repo)
    return repo


class TestSyncAnonymous:
    def test_calls_repo_and_returns_204(self, client, fake_repo):
        resp = client.post("/cricsimapi/identity/sync-anonymous",
                            json={"client_id": "A1", "username": "SwiftYorker_1234"})
        assert resp.status_code == 204
        assert fake_repo.calls == [("sync_anonymous", "A1", "SwiftYorker_1234")]
        assert fake_repo.closed

    def test_username_is_stripped(self, client, fake_repo):
        client.post("/cricsimapi/identity/sync-anonymous",
                    json={"client_id": "A1", "username": "  Foo  "})
        assert fake_repo.calls == [("sync_anonymous", "A1", "Foo")]


class TestLink:
    def test_requires_auth(self, client, fake_repo):
        resp = client.post("/cricsimapi/identity/link",
                            json={"client_id": "A1", "fallback_username": "Foo"})
        assert resp.status_code == 401

    def test_first_sign_in_links_and_returns_canonical_plus_username(self, client, fake_repo):
        app.dependency_overrides[get_current_user_id] = lambda: "G1"
        fake_repo._canonical_id = "A1"
        fake_repo._username = "Alice"
        resp = client.post("/cricsimapi/identity/link",
                            json={"client_id": "A1", "fallback_username": "Alice"})
        assert resp.status_code == 200
        assert resp.json() == {"canonical_id": "A1", "username": "Alice"}
        assert ("link_account", "G1", "A1", "Alice") in fake_repo.calls

    def test_returning_sign_in_resolves_to_existing_canonical(self, client, fake_repo):
        """Second sign-in for the same account: current_client_id may be a
        fresh post-logout anon id, but the repo's no-op path returns the
        ORIGINAL canonical id regardless - the route just passes it through."""
        app.dependency_overrides[get_current_user_id] = lambda: "G1"
        fake_repo._canonical_id = "A1"  # original identity, not the fresh A2 sent
        fake_repo._username = "Alice"
        resp = client.post("/cricsimapi/identity/link",
                            json={"client_id": "A2", "fallback_username": "ignored"})
        assert resp.status_code == 200
        assert resp.json()["canonical_id"] == "A1"

    def test_username_collision_is_409(self, client, fake_repo):
        app.dependency_overrides[get_current_user_id] = lambda: "G1"
        fake_repo._link_raises = UsernameTakenError("Taken")
        resp = client.post("/cricsimapi/identity/link",
                            json={"client_id": "A1", "fallback_username": "Taken"})
        assert resp.status_code == 409
        assert fake_repo.closed


class TestSetUsername:
    def test_resolves_then_sets(self, client, fake_repo):
        fake_repo._resolved_id = "A1"
        resp = client.put("/cricsimapi/identity/username",
                           json={"client_id": "G1", "username": "NewName"})
        assert resp.status_code == 200
        assert resp.json() == {"canonical_id": "A1", "username": "NewName"}
        assert ("resolve_client_id", "G1") in fake_repo.calls
        assert ("set_username", "A1", "NewName") in fake_repo.calls

    def test_collision_is_409(self, client, fake_repo):
        fake_repo._resolved_id = "A1"
        fake_repo._set_username_raises = UsernameTakenError("Taken")
        resp = client.put("/cricsimapi/identity/username",
                           json={"client_id": "A1", "username": "Taken"})
        assert resp.status_code == 409

    def test_no_auth_required(self, client, fake_repo):
        """Anonymous identities can rename themselves too - no JWT needed,
        client_id is the trust boundary here (same as the rest of the app)."""
        fake_repo._resolved_id = "A1"
        resp = client.put("/cricsimapi/identity/username",
                           json={"client_id": "A1", "username": "NewName"})
        assert resp.status_code == 200
