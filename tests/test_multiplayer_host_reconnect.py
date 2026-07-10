"""
Tests for _transfer_host_after_grace_period (api/routes/multiplayer.py) - a
host disconnect (most commonly just a page reload) no longer transfers host
instantly; it waits HOST_RECONNECT_GRACE_S seconds and only transfers if the
host is still disconnected by then.

No live WebSocket/DB required - RoomState/Member are plain dataclasses, and
asyncio.sleep is monkeypatched to be instant so the grace period doesn't
actually slow the test down.
"""
import asyncio

from unittest.mock import AsyncMock

import api.routes.multiplayer as mp
from api.multiplayer.manager import Member, RoomState


def _room():
    room = RoomState(room_id="ABC123", host_id="host", mode="tournament",
                      tournament_name="Test Cup", player_count=4, status="waiting")
    room.members["host"] = Member(client_id="host", display_name="Host")
    room.members["p1"] = Member(client_id="p1", display_name="Player 1")
    return room


class TestHostReconnectGracePeriod:
    def test_transfers_host_if_still_disconnected_after_grace_period(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        room = _room()
        room.members["host"].ws = None  # still disconnected

        asyncio.run(mp._transfer_host_after_grace_period(room, "host"))

        assert room.host_id == "p1"

    def test_does_not_transfer_if_reconnected_within_grace_period(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        room = _room()
        room.members["host"].ws = object()  # reconnected - has a live websocket again

        asyncio.run(mp._transfer_host_after_grace_period(room, "host"))

        assert room.host_id == "host"

    def test_does_not_transfer_if_draft_already_started(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        room = _room()
        room.members["host"].ws = None
        room.status = "drafting"  # moved on while we were waiting out the grace period

        asyncio.run(mp._transfer_host_after_grace_period(room, "host"))

        assert room.host_id == "host"

    def test_does_not_transfer_if_someone_else_already_became_host(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        room = _room()
        room.members["host"].ws = None
        room.host_id = "p1"  # host changed by some other path while waiting

        asyncio.run(mp._transfer_host_after_grace_period(room, "host"))

        assert room.host_id == "p1"

    def test_transfers_even_if_member_was_fully_removed(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        room = _room()
        del room.members["host"]  # e.g. kicked while disconnected

        asyncio.run(mp._transfer_host_after_grace_period(room, "host"))

        assert room.host_id == "p1"
