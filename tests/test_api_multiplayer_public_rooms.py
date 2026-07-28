"""
Tests for GET /multiplayer/rooms/public (api/routes/multiplayer.py) - the
public rooms browse list - and _persist_room's is_public column.

The endpoint reads directly from draft_manager._rooms (in-memory, the same
source of truth get_room/the idle reaper already use) rather than the DB, so
these tests populate that dict directly rather than mocking db_cursor.

No live DB connection required.
"""
from contextlib import contextmanager

from fastapi.testclient import TestClient

import api.routes.multiplayer as mp_routes
from api.main import app
from api.multiplayer.manager import Member, RoomState, draft_manager


class _FakeCursor:
    def __init__(self):
        self.calls = []  # [(query, params), ...] - _persist_room issues 2 executes

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


def _fake_db_cursor(cur):
    @contextmanager
    def _cm(*args, **kwargs):
        yield cur
    return _cm


def _room(room_id, *, is_public=True, status="waiting", mode="tournament",
          match_format="T20", player_count=4, num_members=1, host_id="host"):
    room = RoomState(
        room_id=room_id, host_id=host_id, mode=mode, tournament_name=f"Cup {room_id}",
        player_count=player_count, match_format=match_format, status=status, is_public=is_public,
    )
    room.members[host_id] = Member(client_id=host_id, display_name="Host")
    for i in range(1, num_members):
        cid = f"p{i}-{room_id}"
        room.members[cid] = Member(client_id=cid, display_name=f"Player {i}")
    return room


class TestListPublicRooms:
    def setup_method(self):
        self._orig_rooms = dict(draft_manager._rooms)
        draft_manager._rooms.clear()

    def teardown_method(self):
        draft_manager._rooms.clear()
        draft_manager._rooms.update(self._orig_rooms)

    def _get(self, **params):
        return TestClient(app).get("/cricsimapi/multiplayer/rooms/public", params=params)

    def test_excludes_private_rooms(self):
        draft_manager._rooms["PRIV01"] = _room("PRIV01", is_public=False)
        draft_manager._rooms["PUB001"] = _room("PUB001", is_public=True)

        resp = self._get()

        assert resp.status_code == 200
        ids = [r["room_id"] for r in resp.json()]
        assert ids == ["PUB001"]

    def test_excludes_full_rooms(self):
        draft_manager._rooms["FULL01"] = _room("FULL01", player_count=2, num_members=2)
        draft_manager._rooms["OPEN01"] = _room("OPEN01", player_count=2, num_members=1)

        resp = self._get()

        ids = [r["room_id"] for r in resp.json()]
        assert ids == ["OPEN01"]

    def test_excludes_non_waiting_rooms(self):
        draft_manager._rooms["DRAFT1"] = _room("DRAFT1", status="drafting")
        draft_manager._rooms["WAIT01"] = _room("WAIT01", status="waiting")

        resp = self._get()

        ids = [r["room_id"] for r in resp.json()]
        assert ids == ["WAIT01"]

    def test_filters_by_mode(self):
        draft_manager._rooms["T1"] = _room("T1", mode="tournament")
        draft_manager._rooms["O1"] = _room("O1", mode="1v1", player_count=2)

        resp = self._get(mode="1v1")

        ids = [r["room_id"] for r in resp.json()]
        assert ids == ["O1"]

    def test_filters_by_match_format(self):
        draft_manager._rooms["A1"] = _room("A1", match_format="T20")
        draft_manager._rooms["B1"] = _room("B1", match_format="ODI")

        resp = self._get(match_format="ODI")

        ids = [r["room_id"] for r in resp.json()]
        assert ids == ["B1"]

    def test_sorted_by_spots_remaining_ascending(self):
        draft_manager._rooms["MANY"] = _room("MANY", player_count=8, num_members=1)   # 7 left
        draft_manager._rooms["FEW"]  = _room("FEW", player_count=4, num_members=3)    # 1 left
        draft_manager._rooms["MID"]  = _room("MID", player_count=4, num_members=1)    # 3 left

        resp = self._get()

        ids = [r["room_id"] for r in resp.json()]
        assert ids == ["FEW", "MID", "MANY"]

    def test_response_shape(self):
        draft_manager._rooms["ABC123"] = _room("ABC123", player_count=4, num_members=1)

        resp = self._get()

        row = resp.json()[0]
        assert row == {
            "room_id": "ABC123",
            "tournament_name": "Cup ABC123",
            "mode": "tournament",
            "match_format": "T20",
            "player_count": 4,
            "members_joined": 1,
            "spots_remaining": 3,
            "host_name": "Host",
        }

    def test_empty_when_no_public_rooms(self):
        draft_manager._rooms["PRIV01"] = _room("PRIV01", is_public=False)

        resp = self._get()

        assert resp.json() == []


class TestPersistRoomIncludesVisibility:
    def test_insert_includes_is_public(self, monkeypatch):
        cur = _FakeCursor()
        monkeypatch.setattr(mp_routes, "db_cursor", _fake_db_cursor(cur))
        room = _room("XYZ999", is_public=True)

        mp_routes._persist_room(room)

        rooms_insert_query, rooms_insert_params = cur.calls[0]
        assert "INSERT INTO simulation.rooms" in rooms_insert_query
        assert "is_public" in rooms_insert_query
        # is_public is the 8th positional param (room_id, host_id, mode, status,
        # tournament_name, player_count, match_format, is_public, ...advanced settings).
        assert rooms_insert_params[7] is True
