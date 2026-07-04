"""
Tests for DraftManager (api/multiplayer/manager.py):
  - kick_member: host-only, pre-draft only, cannot self-kick, clears ready state
  - start_draft: resets ready_members (waiting-room ready no longer means
    anything once drafting actually starts)

No live DB / WebSocket connection required — RoomState/Member are plain
dataclasses, no FastAPI machinery needed to exercise this logic.
"""
import pytest

from api.multiplayer.manager import DraftManager, Member, RoomState


def _make_room(num_members: int = 4, mode: str = "tournament") -> RoomState:
    room = RoomState(
        room_id="ABC123",
        host_id="host",
        mode=mode,
        tournament_name="Test Cup",
        player_count=num_members,
    )
    room.members["host"] = Member(client_id="host", display_name="Host")
    for i in range(1, num_members):
        cid = f"p{i}"
        room.members[cid] = Member(client_id=cid, display_name=f"Player {i}")
    return room


class TestKickMember:

    def test_host_can_kick_a_player(self):
        room = _make_room()
        manager = DraftManager()

        kicked = manager.kick_member(room, host_id="host", target_id="p1")

        assert kicked.client_id == "p1"
        assert "p1" not in room.members

    def test_non_host_cannot_kick(self):
        room = _make_room()
        manager = DraftManager()

        with pytest.raises(ValueError, match="Only the host"):
            manager.kick_member(room, host_id="p1", target_id="p2")
        assert "p2" in room.members

    def test_host_cannot_kick_self(self):
        room = _make_room()
        manager = DraftManager()

        with pytest.raises(ValueError, match="cannot kick themselves"):
            manager.kick_member(room, host_id="host", target_id="host")
        assert "host" in room.members

    def test_cannot_kick_once_drafting(self):
        room = _make_room()
        room.status = "drafting"
        manager = DraftManager()

        with pytest.raises(ValueError, match="before the draft starts"):
            manager.kick_member(room, host_id="host", target_id="p1")
        assert "p1" in room.members

    def test_kicking_unknown_player_raises(self):
        room = _make_room()
        manager = DraftManager()

        with pytest.raises(ValueError, match="not in this room"):
            manager.kick_member(room, host_id="host", target_id="does-not-exist")

    def test_kick_clears_ready_state(self):
        room = _make_room()
        room.ready_members.add("p1")
        manager = DraftManager()

        manager.kick_member(room, host_id="host", target_id="p1")

        assert "p1" not in room.ready_members


class TestStartDraftRequiresEveryoneReady:

    def test_raises_if_not_everyone_ready(self):
        room = _make_room()
        room.ready_members = {"host", "p1"}  # 2 of 4 members
        manager = DraftManager()

        with pytest.raises(ValueError, match="must be ready"):
            manager.start_draft(room, keeper_ids=set())
        assert room.status == "waiting"

    def test_succeeds_and_resets_ready_members_once_everyone_ready(self):
        room = _make_room()
        room.ready_members = set(room.members.keys())  # everyone ready
        manager = DraftManager()

        manager.start_draft(room, keeper_ids=set())

        assert room.ready_members == set()
        assert room.status == "drafting"
