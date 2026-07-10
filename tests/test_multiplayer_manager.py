"""
Tests for DraftManager (api/multiplayer/manager.py):
  - kick_member: host-only, pre-draft only, cannot self-kick, clears ready state
  - start_draft: resets ready_members (waiting-room ready no longer means
    anything once drafting actually starts)

No live DB / WebSocket connection required - RoomState/Member are plain
dataclasses, no FastAPI machinery needed to exercise this logic.
"""
import pytest

from api.multiplayer.manager import DraftManager, Member, RoomState, SQUAD_SIZE


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


class TestBattingOrderReservedGaps:
    """
    squad (pick order, drives turn-tracking) and batting_order (display/
    lineup order, SQUAD_SIZE slots with None gaps) are deliberately separate
    fields - reordering must never disturb whose turn it is, and a drafted
    player must be movable past not-yet-picked slots to reserve a later
    batting position.
    """

    def _drafting_room(self):
        room = _make_room(num_members=2)
        room.status = "drafting"
        room.pick_sequence = ["host"] * SQUAD_SIZE + ["p1"] * SQUAD_SIZE
        room.current_pick_idx = 0
        return room

    def test_first_pick_lands_in_first_batting_order_slot(self):
        room = self._drafting_room()
        manager = DraftManager()

        manager.make_pick(room, "host", player_id=101)

        assert room.members["host"].squad == [101]
        assert room.members["host"].batting_order == [101] + [None] * (SQUAD_SIZE - 1)

    def test_reorder_can_move_a_pick_past_open_slots(self):
        room = self._drafting_room()
        manager = DraftManager()
        manager.make_pick(room, "host", player_id=1)
        manager.make_pick(room, "host", player_id=2)

        new_order = [None, 2, None, None, 1] + [None] * (SQUAD_SIZE - 5)
        manager.reorder_squad(room, "host", new_order)

        assert room.members["host"].batting_order == new_order
        assert room.members["host"].squad == [1, 2]  # pick order untouched by reordering

    def test_new_pick_fills_earliest_reserved_gap_not_appended_at_end(self):
        room = self._drafting_room()
        manager = DraftManager()
        manager.make_pick(room, "host", player_id=1)
        manager.make_pick(room, "host", player_id=2)
        # Reserve slot 0 for a future pick by moving player 1 down to slot 4.
        manager.reorder_squad(room, "host", [None, 2, None, None, 1] + [None] * (SQUAD_SIZE - 5))

        manager.make_pick(room, "host", player_id=3)

        bo = room.members["host"].batting_order
        assert bo[0] == 3   # new pick filled the reserved gap, not appended at the end
        assert bo[1] == 2
        assert bo[4] == 1
        assert room.members["host"].squad == [1, 2, 3]

    def test_reorder_rejects_wrong_length(self):
        room = self._drafting_room()
        manager = DraftManager()
        manager.make_pick(room, "host", player_id=1)

        with pytest.raises(ValueError, match=f"exactly {SQUAD_SIZE} slots"):
            manager.reorder_squad(room, "host", [1, None])

    def test_reorder_rejects_player_id_not_in_squad(self):
        room = self._drafting_room()
        manager = DraftManager()
        manager.make_pick(room, "host", player_id=1)

        bogus = [999] + [None] * (SQUAD_SIZE - 1)
        with pytest.raises(ValueError, match="exactly the drafted player IDs"):
            manager.reorder_squad(room, "host", bogus)

    def test_reorder_rejects_dropping_a_drafted_player(self):
        room = self._drafting_room()
        manager = DraftManager()
        manager.make_pick(room, "host", player_id=1)
        manager.make_pick(room, "host", player_id=2)

        missing_one = [1, None] + [None] * (SQUAD_SIZE - 2)  # player 2 silently dropped
        with pytest.raises(ValueError, match="exactly the drafted player IDs"):
            manager.reorder_squad(room, "host", missing_one)

    def test_reorder_by_unknown_member_raises(self):
        room = self._drafting_room()
        manager = DraftManager()

        with pytest.raises(ValueError, match="Not a member"):
            manager.reorder_squad(room, "ghost", [None] * SQUAD_SIZE)
        assert room.status == "drafting"
