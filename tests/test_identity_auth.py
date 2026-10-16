"""
api/identity_auth.py - proving who a request comes from, against a real
throwaway database (DB tier; skipped without a local Postgres).

The guarantees that matter most:
- the first request for a client_id records its secret; every later request
  must present the same one - a recorded secret is never replaced
  ("re-issued"), not by the code and not by a direct UPDATE (trigger);
- two first requests racing with different secrets: exactly one wins;
- a client_id alone (query/body) proves nothing;
- identities linked to an account refuse browser credentials.
"""
import hashlib
import threading
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import api.identity_auth as auth
from api.identity_auth import IdentityError, identity_from_credentials, verify_browser_credential
from api.main import app
from api.multiplayer.manager import Member, RoomState, draft_manager

SECRET_A = "a" * 64
SECRET_B = "b" * 64


@pytest.fixture
def db(make_db, app_db):
    d = make_db()
    app_db(d)
    return d


def _new_id() -> str:
    return str(uuid.uuid4())


def _stored_hash(db, client_id):
    conn = db.connect("test:read")
    with conn.cursor() as cur:
        cur.execute("SELECT secret_hash FROM simulation.client_credentials WHERE client_id = %s", (client_id,))
        row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def _link(db, client_id, auth_id):
    conn = db.connect("test:link")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO simulation.identity_links (id, username, is_anonymous, linked_auth_id) "
                    "VALUES (%s, %s, FALSE, %s)", (client_id, f"user-{client_id[:8]}", auth_id))
    conn.close()


class TestWriteOnce:
    def test_first_use_records_the_secret(self, db):
        cid = _new_id()
        assert verify_browser_credential(cid, SECRET_A) == cid
        assert _stored_hash(db, cid) == hashlib.sha256(SECRET_A.encode()).hexdigest()

    def test_same_secret_keeps_working(self, db):
        cid = _new_id()
        verify_browser_credential(cid, SECRET_A)
        assert verify_browser_credential(cid, SECRET_A) == cid
        assert verify_browser_credential(cid, SECRET_A) == cid

    def test_a_different_secret_is_refused_and_never_replaces_the_first(self, db):
        cid = _new_id()
        verify_browser_credential(cid, SECRET_A)
        first = _stored_hash(db, cid)
        with pytest.raises(IdentityError) as e:
            verify_browser_credential(cid, SECRET_B)
        assert (e.value.status_code, e.value.code) == (401, "credential_mismatch")
        assert _stored_hash(db, cid) == first
        assert verify_browser_credential(cid, SECRET_A) == cid      # the owner is unaffected

    def test_database_refuses_to_replace_a_secret_even_directly(self, db):
        cid = _new_id()
        verify_browser_credential(cid, SECRET_A)
        conn = db.connect("test:tamper")
        with conn.cursor() as cur, pytest.raises(psycopg2.errors.RaiseException, match="write-once"):
            cur.execute("UPDATE simulation.client_credentials SET secret_hash = %s WHERE client_id = %s",
                        (hashlib.sha256(SECRET_B.encode()).hexdigest(), cid))
        conn.close()
        assert _stored_hash(db, cid) == hashlib.sha256(SECRET_A.encode()).hexdigest()

    def test_deleting_a_row_allows_a_fresh_claim(self, db):
        """Manual admin recovery path - documented in migration 038."""
        cid = _new_id()
        verify_browser_credential(cid, SECRET_A)
        conn = db.connect("test:admin")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM simulation.client_credentials WHERE client_id = %s", (cid,))
        conn.close()
        assert verify_browser_credential(cid, SECRET_B) == cid


class TestConcurrentFirstUse:
    def _race(self, cid, secrets):
        results, barrier = [None] * len(secrets), threading.Barrier(len(secrets))

        def run(i, secret):
            barrier.wait()
            try:
                results[i] = verify_browser_credential(cid, secret)
            except IdentityError as e:
                results[i] = e.code

        threads = [threading.Thread(target=run, args=(i, s)) for i, s in enumerate(secrets)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def test_tabs_sharing_one_secret_all_succeed(self, db):
        cid = _new_id()
        assert self._race(cid, [SECRET_A] * 6) == [cid] * 6

    def test_different_secrets_exactly_one_wins(self, db):
        cid = _new_id()
        results = self._race(cid, [SECRET_A, SECRET_B] * 3)
        winners = {s for s, r in zip([SECRET_A, SECRET_B] * 3, results) if r == cid}
        assert len(winners) == 1
        assert all(r in (cid, "credential_mismatch") for r in results)
        assert _stored_hash(db, cid) == hashlib.sha256(winners.pop().encode()).hexdigest()


class TestRejections:
    @pytest.mark.parametrize("cid, secret", [
        ("", SECRET_A), ("short", SECRET_A), ("x" * 65, SECRET_A), ("bad id!", SECRET_A),
        ("valid-client-id", ""), ("valid-client-id", "tooshort"), ("valid-client-id", "s p a c e" * 8),
    ])
    def test_malformed_credentials(self, db, cid, secret):
        with pytest.raises(IdentityError) as e:
            verify_browser_credential(cid, secret)
        assert e.value.code == "invalid_credential"
        assert _stored_hash(db, cid) is None

    def test_identity_linked_to_an_account_refuses_browser_credentials(self, db):
        cid = _new_id()
        _link(db, cid, auth_id="G1")
        with pytest.raises(IdentityError) as e:
            verify_browser_credential(cid, SECRET_A)
        assert (e.value.status_code, e.value.code) == (403, "identity_linked")
        assert _stored_hash(db, cid) is None

    def test_the_account_id_itself_is_refused_too(self, db):
        _link(db, _new_id(), auth_id="auth-user-1234")
        with pytest.raises(IdentityError):
            verify_browser_credential("auth-user-1234", SECRET_A)

    def test_no_credentials_is_no_identity(self, db):
        assert identity_from_credentials(None, None, None) is None


class TestAccountPath:
    def test_jwt_resolves_to_the_linked_canonical_identity(self, db, monkeypatch):
        cid = _new_id()
        _link(db, cid, auth_id="G1")
        monkeypatch.setattr(auth, "get_current_user_id", lambda authorization: "G1")
        ident = identity_from_credentials("Bearer x", None, None)
        assert (ident.id, ident.actor) == (cid, "user:G1")

    def test_jwt_wins_over_browser_credentials(self, db, monkeypatch):
        cid = _new_id()
        _link(db, cid, auth_id="G1")
        monkeypatch.setattr(auth, "get_current_user_id", lambda authorization: "G1")
        ident = identity_from_credentials("Bearer x", "someone-else-id", "wrong-secret-but-ignored-xxxxxxxxxxxx")
        assert ident.id == cid
        assert _stored_hash(db, "someone-else-id") is None

    def test_unlinked_account_is_its_own_identity(self, db, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_id", lambda authorization: "G-new")
        assert identity_from_credentials("Bearer x", None, None).id == "G-new"


class TestThroughTheApi:
    """The real dependency chain - headers in, verified identity out."""

    def test_headers_identify_the_caller(self, db):
        cid = _new_id()
        r = TestClient(app).get("/cricsimapi/simulations",
                                headers={"X-Client-Id": cid, "X-Client-Secret": SECRET_A})
        assert r.status_code == 200
        assert _stored_hash(db, cid) is not None

    def test_wrong_secret_is_401_with_a_reason_and_a_readable_message(self, db):
        cid = _new_id()
        verify_browser_credential(cid, SECRET_A)
        r = TestClient(app).get("/cricsimapi/simulations",
                                headers={"X-Client-Id": cid, "X-Client-Secret": SECRET_B})
        assert r.status_code == 401
        assert r.headers["X-Identity-Error"] == "credential_mismatch"
        assert "refresh" in r.json()["detail"]

    def test_a_bare_client_id_is_not_enough(self, db):
        """What an old tab (or someone who copied an id) sends."""
        cid = _new_id()
        verify_browser_credential(cid, SECRET_A)
        r = TestClient(app).get("/cricsimapi/simulations", params={"client_id": cid})
        assert r.status_code == 401
        assert r.headers["X-Identity-Error"] == "missing_credential"


class TestRoomWebSocket:
    @pytest.fixture
    def room(self, db):
        host = _new_id()
        verify_browser_credential(host, SECRET_A)
        room = RoomState(room_id="WSTEST", host_id=host, mode="1v1", tournament_name="Cup",
                         player_count=2, match_format="T20")
        room.members[host] = Member(client_id=host, display_name="Host")
        draft_manager._rooms["WSTEST"] = room
        yield host
        draft_manager._rooms.pop("WSTEST", None)

    def test_member_with_valid_credentials_gets_the_room(self, room):
        with TestClient(app).websocket_connect("/cricsimapi/multiplayer/ws/WSTEST") as ws:
            ws.send_json({"type": "auth", "client_id": room, "secret": SECRET_A})
            assert ws.receive_json()["type"] == "room_state"

    def test_wrong_secret_is_closed(self, room):
        with TestClient(app).websocket_connect("/cricsimapi/multiplayer/ws/WSTEST") as ws:
            ws.send_json({"type": "auth", "client_id": room, "secret": SECRET_B})
            with pytest.raises(WebSocketDisconnect) as e:
                ws.receive_json()
        assert e.value.code == 4401

    def test_old_style_query_param_without_auth_message_is_closed(self, room, monkeypatch):
        monkeypatch.setattr("api.routes.multiplayer.WS_AUTH_TIMEOUT_S", 0.2)
        with TestClient(app).websocket_connect(f"/cricsimapi/multiplayer/ws/WSTEST?client_id={room}") as ws:
            with pytest.raises(WebSocketDisconnect) as e:
                ws.receive_json()
        assert e.value.code == 4401
