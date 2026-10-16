"""
/cricsimapi/identity routes (api/routes/identity.py) - the HTTP surface over
IdentityRepository (simulation.identity_links, migration 031). No live DB:
IdentityRepository is monkeypatched with a fake per test.
"""
import pytest
from fastapi.testclient import TestClient

import api.routes.identity as identity_mod
from api.identity_auth import IdentityError
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

    def is_auth_linked(self, auth_id):
        self.calls.append(("is_auth_linked", auth_id))
        return getattr(self, "_auth_linked", False)

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
    def test_syncs_the_verified_identity(self, client, fake_repo, as_identity):
        resp = client.post("/cricsimapi/identity/sync-anonymous",
                            json={"username": "SwiftYorker_1234"}, headers=as_identity("A1"))
        assert resp.status_code == 204
        assert fake_repo.calls == [("sync_anonymous", "A1", "SwiftYorker_1234")]
        assert fake_repo.closed

    def test_username_is_stripped(self, client, fake_repo, as_identity):
        client.post("/cricsimapi/identity/sync-anonymous",
                    json={"username": "  Foo  "}, headers=as_identity("A1"))
        assert fake_repo.calls == [("sync_anonymous", "A1", "Foo")]

    def test_client_id_in_body_is_ignored(self, client, fake_repo, as_identity):
        client.post("/cricsimapi/identity/sync-anonymous",
                    json={"client_id": "VICTIM", "username": "x"}, headers=as_identity("A1"))
        assert fake_repo.calls == [("sync_anonymous", "A1", "x")]

    def test_no_credentials_is_401(self, client, fake_repo, as_identity):
        resp = client.post("/cricsimapi/identity/sync-anonymous", json={"client_id": "A1", "username": "x"})
        assert resp.status_code == 401
        assert fake_repo.calls == []


class TestLink:
    @pytest.fixture
    def browser(self, monkeypatch):
        """Stub the browser-credential check: maps (client_id, secret) to an
        outcome. Default: the secret 'good' proves the id."""
        seen = []

        def _verify(client_id, secret):
            seen.append((client_id, secret))
            if client_id == "LINKED":
                raise IdentityError(403, "identity_linked", "linked")
            if secret != "good":
                raise IdentityError(401, "credential_mismatch", "mismatch")
            return client_id

        monkeypatch.setattr(identity_mod, "verify_browser_credential", _verify)
        return seen

    def _headers(self, client_id, secret="good"):
        return {"X-Client-Id": client_id, "X-Client-Secret": secret}

    def test_requires_auth(self, client, fake_repo, browser):
        resp = client.post("/cricsimapi/identity/link", json={"fallback_username": "Foo"},
                            headers=self._headers("A1"))
        assert resp.status_code == 401

    def test_first_sign_in_links_the_proven_browser_identity(self, client, fake_repo, browser):
        app.dependency_overrides[get_current_user_id] = lambda: "G1"
        fake_repo._canonical_id = "A1"
        fake_repo._username = "Alice"
        resp = client.post("/cricsimapi/identity/link", json={"fallback_username": "Alice"},
                            headers=self._headers("A1"))
        assert resp.status_code == 200
        assert resp.json() == {"canonical_id": "A1", "username": "Alice"}
        assert ("link_account", "G1", "A1", "Alice") in fake_repo.calls
        assert browser == [("A1", "good")]

    def test_first_sign_in_with_a_wrong_secret_links_nothing(self, client, fake_repo, browser):
        """Someone who only knows a victim's client_id can't pull the victim's
        anonymous history into their own account."""
        app.dependency_overrides[get_current_user_id] = lambda: "G1"
        resp = client.post("/cricsimapi/identity/link", json={"fallback_username": "x"},
                            headers=self._headers("VICTIM", secret="guess"))
        assert resp.status_code == 401
        assert not [c for c in fake_repo.calls if c[0] == "link_account"]

    def test_client_id_in_body_is_ignored(self, client, fake_repo, browser):
        app.dependency_overrides[get_current_user_id] = lambda: "G1"
        client.post("/cricsimapi/identity/link", json={"client_id": "VICTIM", "fallback_username": "x"},
                    headers=self._headers("A1"))
        assert ("link_account", "G1", "A1", "x") in fake_repo.calls

    def test_first_sign_in_without_browser_credentials_starts_fresh(self, client, fake_repo, browser):
        app.dependency_overrides[get_current_user_id] = lambda: "G1"
        client.post("/cricsimapi/identity/link", json={"fallback_username": "x"})
        assert ("link_account", "G1", "G1", "x") in fake_repo.calls

    def test_browser_identity_owned_by_another_account_is_never_handed_over(self, client, fake_repo, browser):
        app.dependency_overrides[get_current_user_id] = lambda: "G2"
        resp = client.post("/cricsimapi/identity/link", json={"fallback_username": "x"},
                            headers=self._headers("LINKED"))
        assert resp.status_code == 200
        assert ("link_account", "G2", "G2", "x") in fake_repo.calls

    def test_returning_sign_in_skips_the_browser_check(self, client, fake_repo, browser):
        """Second sign-in: the account is already linked, so the browser's
        (possibly fresh post-logout) identity doesn't matter - the repo's no-op
        path returns the ORIGINAL canonical id."""
        app.dependency_overrides[get_current_user_id] = lambda: "G1"
        fake_repo._auth_linked = True
        fake_repo._canonical_id = "A1"
        resp = client.post("/cricsimapi/identity/link", json={"fallback_username": "ignored"},
                            headers=self._headers("A2", secret="anything"))
        assert resp.status_code == 200
        assert resp.json()["canonical_id"] == "A1"
        assert browser == []

    def test_username_collision_is_409(self, client, fake_repo, browser):
        app.dependency_overrides[get_current_user_id] = lambda: "G1"
        fake_repo._link_raises = UsernameTakenError("Taken")
        resp = client.post("/cricsimapi/identity/link", json={"fallback_username": "Taken"},
                            headers=self._headers("A1"))
        assert resp.status_code == 409
        assert fake_repo.closed


class TestSetUsername:
    def test_renames_the_verified_identity(self, client, fake_repo, as_identity):
        resp = client.put("/cricsimapi/identity/username",
                           json={"username": "NewName"}, headers=as_identity("A1"))
        assert resp.status_code == 200
        assert resp.json() == {"canonical_id": "A1", "username": "NewName"}
        assert ("set_username", "A1", "NewName") in fake_repo.calls

    def test_cannot_rename_someone_else_by_naming_their_client_id(self, client, fake_repo, as_identity):
        """The old hole: PUT {client_id: <victim>} renamed the victim. The body's
        client_id is now ignored - only the caller's own identity is renamed."""
        client.put("/cricsimapi/identity/username",
                   json={"client_id": "VICTIM", "username": "pwned"}, headers=as_identity("A1"))
        assert ("set_username", "A1", "pwned") in fake_repo.calls
        assert not [c for c in fake_repo.calls if "VICTIM" in c]

    def test_no_credentials_is_401(self, client, fake_repo, as_identity):
        resp = client.put("/cricsimapi/identity/username", json={"client_id": "A1", "username": "x"})
        assert resp.status_code == 401
        assert fake_repo.calls == []

    def test_collision_is_409(self, client, fake_repo, as_identity):
        fake_repo._set_username_raises = UsernameTakenError("Taken")
        resp = client.put("/cricsimapi/identity/username",
                           json={"username": "Taken"}, headers=as_identity("A1"))
        assert resp.status_code == 409
