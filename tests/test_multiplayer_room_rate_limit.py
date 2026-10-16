import pytest
"""
Tests for the multiplayer room-creation rate limit (api/routes/multiplayer.py)
- GET /multiplayer/rooms/active-count and the 429 enforced inside
POST /multiplayer/rooms. Mirrors the single-player "max 2 concurrent
simulations per client" cap (api/routes/simulations.py).

Reads/writes draft_manager._rooms directly (in-memory, same source of truth
list_public_rooms already uses) rather than mocking db_cursor for the count
check itself - matches the pattern in test_api_multiplayer_public_rooms.py.
No live DB connection required.
"""
from contextlib import contextmanager

from fastapi.testclient import TestClient

import api.routes.multiplayer as mp_routes
from api.main import app
from api.multiplayer.manager import Member, RoomState, draft_manager
from api.routes.multiplayer import MAX_ACTIVE_HOSTED_ROOMS, _active_hosted_room_count


class _FakeCursor:
    def execute(self, query, params=None):
        pass

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


def _fake_db_cursor():
    @contextmanager
    def _cm(*args, **kwargs):
        yield _FakeCursor()
    return _cm


def _room(room_id, *, host_id="host", status="waiting", mode="tournament",
          player_count=4):
    room = RoomState(
        room_id=room_id, host_id=host_id, mode=mode, tournament_name=f"Cup {room_id}",
        player_count=player_count, match_format="T20", status=status,
    )
    room.members[host_id] = Member(client_id=host_id, display_name="Host")
    return room


class _RoomsFixture:
    def setup_method(self):
        self._orig_rooms = dict(draft_manager._rooms)
        draft_manager._rooms.clear()

    def teardown_method(self):
        draft_manager._rooms.clear()
        draft_manager._rooms.update(self._orig_rooms)


class TestActiveHostedRoomCount(_RoomsFixture):
    def test_counts_only_rooms_hosted_by_this_client(self):
        draft_manager._rooms["R1"] = _room("R1", host_id="alice")
        draft_manager._rooms["R2"] = _room("R2", host_id="bob")

        assert _active_hosted_room_count("alice") == 1
        assert _active_hosted_room_count("bob") == 1
        assert _active_hosted_room_count("carol") == 0

    def test_excludes_completed_rooms(self):
        draft_manager._rooms["R1"] = _room("R1", host_id="alice", status="completed")
        draft_manager._rooms["R2"] = _room("R2", host_id="alice", status="waiting")

        assert _active_hosted_room_count("alice") == 1

    def test_counts_every_non_completed_status(self):
        for i, status in enumerate(["waiting", "drafting", "reordering", "simulating"]):
            draft_manager._rooms[f"R{i}"] = _room(f"R{i}", host_id="alice", status=status)

        assert _active_hosted_room_count("alice") == 4


@pytest.mark.usefixtures("as_identity")
class TestActiveCountEndpoint(_RoomsFixture):
    def _get(self, client_id):
        return TestClient(app).get(
            "/cricsimapi/multiplayer/rooms/active-count", headers={"X-Test-Identity": client_id}
        )

    def test_returns_count_and_limit(self):
        draft_manager._rooms["R1"] = _room("R1", host_id="alice")

        resp = self._get("alice")

        assert resp.status_code == 200
        assert resp.json() == {"count": 1, "limit": MAX_ACTIVE_HOSTED_ROOMS}

    def test_zero_for_client_with_no_rooms(self):
        resp = self._get("nobody")

        assert resp.json() == {"count": 0, "limit": MAX_ACTIVE_HOSTED_ROOMS}


@pytest.mark.usefixtures("as_identity")
class TestCreateRoomRateLimit(_RoomsFixture):
    def _create(self, client_id, monkeypatch):
        monkeypatch.setattr(mp_routes, "db_cursor", _fake_db_cursor())
        return TestClient(app).post(
            "/cricsimapi/multiplayer/rooms",
            headers={"X-Test-Identity": client_id},
            json={
                "display_name": "Alice",
                "mode": "tournament",
                "tournament_name": "Test Cup",
                "player_count": 4,
                "match_format": "T20",
            },
        )

    def test_succeeds_under_the_cap(self, monkeypatch):
        draft_manager._rooms["R1"] = _room("R1", host_id="alice")  # 1 active, cap is 2

        resp = self._create("alice", monkeypatch)

        assert resp.status_code == 200
        assert _active_hosted_room_count("alice") == 2

    def test_rejects_at_the_cap(self, monkeypatch):
        draft_manager._rooms["R1"] = _room("R1", host_id="alice")
        draft_manager._rooms["R2"] = _room("R2", host_id="alice")

        resp = self._create("alice", monkeypatch)

        assert resp.status_code == 429
        assert "Too many active rooms" in resp.json()["detail"]
        # The rejected attempt must not have created a third room.
        assert _active_hosted_room_count("alice") == 2

    def test_completed_rooms_dont_count_against_the_cap(self, monkeypatch):
        draft_manager._rooms["R1"] = _room("R1", host_id="alice", status="completed")
        draft_manager._rooms["R2"] = _room("R2", host_id="alice", status="completed")

        resp = self._create("alice", monkeypatch)

        assert resp.status_code == 200

    def test_cap_is_per_client_not_global(self, monkeypatch):
        draft_manager._rooms["R1"] = _room("R1", host_id="alice")
        draft_manager._rooms["R2"] = _room("R2", host_id="alice")

        resp = self._create("bob", monkeypatch)

        assert resp.status_code == 200
