"""
IdentityRepository (db/identity_repository.py) - the single resolution point
for anonymous and authenticated identity (simulation.identity_links,
migration 031). No live DB - a fake cursor simulates the table with a plain
dict, since these tests need real INSERT/UPDATE/conflict semantics rather
than just asserting SQL text.
"""
import pytest

from db.identity_repository import IdentityRepository, UsernameTakenError


class _FakeUniqueViolation(Exception):
    pass


class _FakeCursor:
    """Simulates simulation.identity_links as an in-memory dict of rows,
    keyed by id, with the same uniqueness rules (id PK, linked_auth_id
    UNIQUE, lower(username) UNIQUE) the real table enforces."""

    def __init__(self, rows=None):
        self.rows: dict[str, dict] = rows or {}
        self._result = None

    def _find_by_linked_auth_id(self, auth_id):
        return next((r for r in self.rows.values() if r.get("linked_auth_id") == auth_id), None)

    def _find_by_username(self, username, exclude_id=None):
        return next(
            (r for r in self.rows.values()
             if r["username"].lower() == username.lower() and r["id"] != exclude_id),
            None,
        )

    def execute(self, query, params=()):
        q = " ".join(query.split())

        if q.startswith("SELECT id FROM simulation.identity_links WHERE id = %s OR linked_auth_id = %s"):
            raw_id = params[0]
            row = self.rows.get(raw_id) or self._find_by_linked_auth_id(raw_id)
            self._result = row

        elif q.startswith("SELECT id FROM simulation.identity_links WHERE linked_auth_id = %s"):
            self._result = self._find_by_linked_auth_id(params[0])

        elif q.startswith("SELECT id FROM simulation.identity_links WHERE id = %s"):
            self._result = self.rows.get(params[0])

        elif q.startswith("SELECT username FROM simulation.identity_links WHERE id = %s"):
            self._result = self.rows.get(params[0])

        elif q.startswith("INSERT INTO simulation.identity_links (id, username, is_anonymous)"):
            anon_id, username = params
            if self._find_by_username(username, exclude_id=anon_id):
                raise _FakeUniqueViolation()
            existing = self.rows.get(anon_id)
            if existing:
                existing["username"] = username
            else:
                self.rows[anon_id] = {"id": anon_id, "username": username,
                                      "is_anonymous": True, "linked_auth_id": None}
            self._result = None

        elif "SET linked_auth_id = %s, is_anonymous = FALSE" in q:
            auth_id, row_id = params
            if self._find_by_linked_auth_id(auth_id):
                raise _FakeUniqueViolation()
            self.rows[row_id]["linked_auth_id"] = auth_id
            self.rows[row_id]["is_anonymous"] = False
            self._result = None

        elif q.startswith("INSERT INTO simulation.identity_links (id, username, is_anonymous, linked_auth_id)"):
            row_id, username, auth_id = params
            if self._find_by_username(username, exclude_id=row_id) or self._find_by_linked_auth_id(auth_id):
                raise _FakeUniqueViolation()
            self.rows[row_id] = {"id": row_id, "username": username,
                                 "is_anonymous": False, "linked_auth_id": auth_id}
            self._result = None

        elif q.startswith("UPDATE simulation.identity_links SET username = %s"):
            username, row_id = params
            if self._find_by_username(username, exclude_id=row_id):
                raise _FakeUniqueViolation()
            self.rows[row_id]["username"] = username
            self._result = None

        else:
            raise AssertionError(f"unexpected query in fake cursor: {q}")

    def fetchone(self):
        return self._result


def _repo(rows=None) -> IdentityRepository:
    repo = IdentityRepository.__new__(IdentityRepository)
    repo._cur = _FakeCursor(rows)
    repo._conn = type("C", (), {"commit": lambda self: None, "rollback": lambda self: None})()
    # Route the fake UniqueViolation through the same except clause the real
    # code catches (psycopg2.errors.UniqueViolation) by monkeypatching the
    # module-level name the repository imports.
    import db.identity_repository as mod
    mod.psycopg2.errors.UniqueViolation = _FakeUniqueViolation
    return repo


class TestResolveClientId:
    def test_none_passthrough(self):
        assert _repo().resolve_client_id(None) is None

    def test_unlinked_anon_id_resolves_to_itself(self):
        repo = _repo({"A1": {"id": "A1", "username": "Foo", "is_anonymous": True, "linked_auth_id": None}})
        assert repo.resolve_client_id("A1") == "A1"

    def test_never_seen_id_resolves_to_itself(self):
        assert _repo().resolve_client_id("brand-new-uuid") == "brand-new-uuid"

    def test_auth_id_resolves_to_canonical_anon_id(self):
        repo = _repo({"A1": {"id": "A1", "username": "Foo", "is_anonymous": False, "linked_auth_id": "G1"}})
        assert repo.resolve_client_id("G1") == "A1"
        assert repo.resolve_client_id("A1") == "A1"


class TestSyncAnonymous:
    def test_creates_a_new_anonymous_row(self):
        repo = _repo()
        repo.sync_anonymous("A1", "SwiftYorker_1234")
        assert repo._cur.rows["A1"]["username"] == "SwiftYorker_1234"
        assert repo._cur.rows["A1"]["is_anonymous"] is True

    def test_upserts_on_rename(self):
        repo = _repo({"A1": {"id": "A1", "username": "Old", "is_anonymous": True, "linked_auth_id": None}})
        repo.sync_anonymous("A1", "New")
        assert repo._cur.rows["A1"]["username"] == "New"

    def test_username_collision_is_swallowed_not_raised(self):
        repo = _repo({"A1": {"id": "A1", "username": "Taken", "is_anonymous": True, "linked_auth_id": None}})
        repo.sync_anonymous("A2", "Taken")  # must not raise
        assert "A2" not in repo._cur.rows


class TestLinkAccount:
    def test_first_ever_sign_in_links_current_anon_row(self):
        repo = _repo({"A1": {"id": "A1", "username": "Foo", "is_anonymous": True, "linked_auth_id": None}})
        canonical = repo.link_account(auth_id="G1", current_client_id="A1", fallback_username="Foo")
        assert canonical == "A1"
        assert repo._cur.rows["A1"]["linked_auth_id"] == "G1"
        assert repo._cur.rows["A1"]["is_anonymous"] is False

    def test_first_ever_sign_in_with_no_existing_row_creates_self_referential_one(self):
        repo = _repo()
        canonical = repo.link_account(auth_id="G1", current_client_id="A1", fallback_username="Alice")
        assert canonical == "A1"
        assert repo._cur.rows["A1"] == {
            "id": "A1", "username": "Alice", "is_anonymous": False, "linked_auth_id": "G1",
        }

    def test_returning_sign_in_does_not_merge_current_anon_session(self):
        """The exact scenario: anon -> sign in (G1, links A1) -> sign out
        (fresh A2) -> anon play as A2 -> sign in again as G1. Must resolve to
        the ORIGINAL A1 history and leave A2 completely untouched."""
        repo = _repo({
            "A1": {"id": "A1", "username": "Alice", "is_anonymous": False, "linked_auth_id": "G1"},
            "A2": {"id": "A2", "username": "GuestName", "is_anonymous": True, "linked_auth_id": None},
        })
        canonical = repo.link_account(auth_id="G1", current_client_id="A2", fallback_username="ignored")
        assert canonical == "A1"
        # A2 is untouched - still anonymous, still its own separate identity
        assert repo._cur.rows["A2"] == {
            "id": "A2", "username": "GuestName", "is_anonymous": True, "linked_auth_id": None,
        }

    def test_different_email_creates_a_second_independent_identity(self):
        repo = _repo({
            "A1": {"id": "A1", "username": "Alice", "is_anonymous": False, "linked_auth_id": "G1"},
            "A2": {"id": "A2", "username": "Bob", "is_anonymous": True, "linked_auth_id": None},
        })
        canonical = repo.link_account(auth_id="G2", current_client_id="A2", fallback_username="Bob")
        assert canonical == "A2"
        assert repo._cur.rows["A2"]["linked_auth_id"] == "G2"
        # G1/A1 fully unaffected
        assert repo._cur.rows["A1"]["linked_auth_id"] == "G1"

    def test_fallback_username_collision_raises(self):
        repo = _repo({"A1": {"id": "A1", "username": "Taken", "is_anonymous": True, "linked_auth_id": None}})
        with pytest.raises(UsernameTakenError):
            repo.link_account(auth_id="G1", current_client_id="A2", fallback_username="Taken")


class TestUsername:
    def test_get_returns_none_for_unknown_id(self):
        assert _repo().get_username("nope") is None

    def test_set_then_get(self):
        repo = _repo({"A1": {"id": "A1", "username": "Old", "is_anonymous": True, "linked_auth_id": None}})
        repo.set_username("A1", "New")
        assert repo.get_username("A1") == "New"

    def test_set_raises_on_collision(self):
        repo = _repo({
            "A1": {"id": "A1", "username": "Taken", "is_anonymous": True, "linked_auth_id": None},
            "A2": {"id": "A2", "username": "Mine", "is_anonymous": True, "linked_auth_id": None},
        })
        with pytest.raises(UsernameTakenError):
            repo.set_username("A2", "Taken")

    def test_set_is_case_insensitive_against_existing_usernames(self):
        repo = _repo({
            "A1": {"id": "A1", "username": "Rahul", "is_anonymous": True, "linked_auth_id": None},
            "A2": {"id": "A2", "username": "Mine", "is_anonymous": True, "linked_auth_id": None},
        })
        with pytest.raises(UsernameTakenError):
            repo.set_username("A2", "rahul")
