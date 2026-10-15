"""
IdentityRepository.sync_anonymous against real Postgres (DB tier). The
DB-free tests in test_identity_repository.py use a fake cursor that re-states
the SQL's behaviour in Python; these run the actual statement, so a change to
the SQL can't pass while the fake still agrees. Skipped without a local Postgres.
"""
import pytest

from db.identity_repository import IdentityRepository


@pytest.fixture
def identity_db(make_db, app_db):
    db = make_db()
    app_db(db)
    return db


def _row(db, ident):
    conn = db.connect("test:read")
    with conn.cursor() as cur:
        cur.execute("SELECT username, is_anonymous, linked_auth_id, updated_by FROM simulation.identity_links WHERE id = %s", (ident,))
        row = cur.fetchone()
    conn.close()
    return row


def _sync(anon_id, name):
    repo = IdentityRepository()
    try:
        repo.sync_anonymous(anon_id, name)
    finally:
        repo.close()


class TestSyncAnonymousRealSql:
    def test_creates_then_renames_an_anonymous_identity(self, identity_db):
        _sync("anon-1", "SwiftYorker_1111")
        _sync("anon-1", "DeepCover_2222")
        assert _row(identity_db, "anon-1")[:3] == ("DeepCover_2222", True, None)

    def test_does_not_rename_an_account_linked_from_that_anon_id(self, identity_db):
        _sync("anon-1", "SwiftYorker_1111")
        conn = identity_db.connect("test:link")
        with conn.cursor() as cur:
            cur.execute("""UPDATE simulation.identity_links
                           SET username = 'Vinay', is_anonymous = FALSE, linked_auth_id = 'auth-1'
                           WHERE id = 'anon-1'""")
        conn.close()
        _sync("anon-1", "SwiftPoint_2424")
        assert _row(identity_db, "anon-1")[:3] == ("Vinay", False, "auth-1")

    def test_linked_account_sync_does_not_hit_username_uniqueness(self, identity_db):
        _sync("anon-2", "SwiftPoint_2424")
        _sync("anon-1", "Other_0001")
        conn = identity_db.connect("test:link")
        with conn.cursor() as cur:
            cur.execute("""UPDATE simulation.identity_links SET username = 'Vinay', is_anonymous = FALSE,
                           linked_auth_id = 'auth-1' WHERE id = 'anon-1'""")
        conn.close()
        _sync("anon-1", "SwiftPoint_2424")   # name held by anon-2: still a no-op, not an error
        assert _row(identity_db, "anon-1")[0] == "Vinay"
