from __future__ import annotations

import asyncio
import json
import random
import string
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from fastapi import WebSocket

from simulator.logger import get_logger

SQUAD_SIZE = 11
PICK_TIMEOUT_S = 60


@dataclass
class Member:
    client_id: str
    display_name: str
    draft_order: int = 0
    squad: List[int] = field(default_factory=list)      # player_ids in batting order
    ws: Optional[WebSocket] = field(default=None, repr=False)

    def has_keeper(self, keeper_ids: Set[int]) -> bool:
        return any(pid in keeper_ids for pid in self.squad)

    def needs_keeper(self, keeper_ids: Set[int]) -> bool:
        """True when this is the last pick and no keeper has been chosen yet."""
        return len(self.squad) == SQUAD_SIZE - 1 and not self.has_keeper(keeper_ids)


@dataclass
class RoomState:
    room_id: str
    host_id: str
    mode: str                           # '1v1' or 'tournament'
    tournament_name: str
    player_count: int
    match_format: str = 'T20'           # 'T20' | 'ODI' | 'Test'
    status: str = 'waiting'             # waiting | drafting | reordering | simulating | completed
    members: Dict[str, Member] = field(default_factory=dict)   # client_id → Member
    pick_sequence: List[str] = field(default_factory=list)     # client_ids in pick order
    current_pick_idx: int = 0
    drafted_ids: Set[int] = field(default_factory=set)
    keeper_ids: Set[int] = field(default_factory=set)          # populated on draft start
    ready_members: Set[str] = field(default_factory=set)       # client_ids who clicked ready
    _timer_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _reorder_task: Optional[asyncio.Task] = field(default=None, repr=False)
    sim_id: Optional[str] = None

    # ── helpers ───────────────────────────────────────────────────────────────

    @property
    def current_picker_id(self) -> Optional[str]:
        if not self.pick_sequence or self.status != 'drafting':
            return None
        return self.pick_sequence[self.current_pick_idx % len(self.pick_sequence)]

    @property
    def total_picks(self) -> int:
        return SQUAD_SIZE * len(self.members)

    @property
    def picks_made(self) -> int:
        return sum(len(m.squad) for m in self.members.values())

    def draft_complete(self) -> bool:
        return all(len(m.squad) == SQUAD_SIZE for m in self.members.values())

    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "host_id": self.host_id,
            "mode": self.mode,
            "tournament_name": self.tournament_name,
            "player_count": self.player_count,
            "match_format": self.match_format,
            "status": self.status,
            "ready_members": list(self.ready_members),
            "current_picker": self.current_picker_id,
            "picks_made": self.picks_made,
            "total_picks": self.total_picks,
            "members": [
                {
                    "client_id": m.client_id,
                    "display_name": m.display_name,
                    "team_name": m.display_name,
                    "draft_order": m.draft_order,
                    "squad": m.squad,
                    "connected": m.ws is not None,
                }
                for m in sorted(self.members.values(), key=lambda x: x.draft_order)
            ],
        }


class DraftManager:
    """Process-level singleton managing all active multiplayer rooms."""

    def __init__(self):
        self._rooms: Dict[str, RoomState] = {}

    # ── room lifecycle ─────────────────────────────────────────────────────────

    def create_room(self, host_id: str, display_name: str, mode: str,
                    tournament_name: str, player_count: int,
                    match_format: str = 'T20') -> RoomState:
        room_id = self._unique_code()
        room = RoomState(
            room_id=room_id,
            host_id=host_id,
            mode=mode,
            tournament_name=tournament_name,
            player_count=player_count,
            match_format=match_format,
        )
        host = Member(client_id=host_id, display_name=display_name)
        room.members[host_id] = host
        self._rooms[room_id] = room
        return room

    def get_room(self, room_id: str) -> Optional[RoomState]:
        return self._rooms.get(room_id.upper())

    def join_room(self, room_id: str, client_id: str, display_name: str) -> RoomState:
        room = self._rooms.get(room_id.upper())
        if not room:
            raise ValueError("Room not found")
        if room.status != 'waiting':
            raise ValueError("Draft has already started")
        if len(room.members) >= room.player_count:
            raise ValueError("Room is full")
        if client_id not in room.members:
            room.members[client_id] = Member(client_id=client_id, display_name=display_name)
        return room

    def remove_room(self, room_id: str) -> None:
        self._rooms.pop(room_id, None)

    def kick_member(self, room: RoomState, host_id: str, target_id: str) -> Member:
        """Remove a player from the waiting room. Host-only, pre-draft only —
        once picks are underway a member's squad/pick order is already woven
        into room state, so removal isn't well-defined there."""
        if host_id != room.host_id:
            raise ValueError("Only the host can kick players")
        if room.status != 'waiting':
            raise ValueError("Can only kick players before the draft starts")
        if target_id == room.host_id:
            raise ValueError("Host cannot kick themselves")
        member = room.members.pop(target_id, None)
        if member is None:
            raise ValueError("Player not in this room")
        room.ready_members.discard(target_id)
        return member

    # ── WebSocket connect/disconnect ───────────────────────────────────────────

    def connect(self, room: RoomState, client_id: str, ws: WebSocket) -> None:
        if client_id in room.members:
            room.members[client_id].ws = ws

    def disconnect(self, room: RoomState, client_id: str) -> None:
        if client_id in room.members:
            room.members[client_id].ws = None

    def transfer_host(self, room: RoomState, leaving_client_id: str) -> bool:
        """Pass host to the next joined member when the current host leaves. Returns True if transferred."""
        if room.host_id != leaving_client_id:
            return False
        remaining = [cid for cid in room.members if cid != leaving_client_id]
        if not remaining:
            return False
        room.host_id = remaining[0]
        return True

    # ── draft start ────────────────────────────────────────────────────────────

    def start_draft(self, room: RoomState, keeper_ids: Set[int]) -> None:
        if room.status != 'waiting':
            raise ValueError("Draft already started")
        if len(room.members) < 2:
            raise ValueError("Need at least 2 players to start")
        if room.mode == 'tournament' and len(room.members) < 4:
            raise ValueError("Tournament mode requires at least 4 players")
        if len(room.ready_members) < len(room.members):
            raise ValueError("All players must be ready before the draft can start")

        room.keeper_ids = keeper_ids
        order = list(room.members.keys())
        random.shuffle(order)

        for i, cid in enumerate(order):
            room.members[cid].draft_order = i

        room.pick_sequence = _snake_sequence(order, SQUAD_SIZE)

        room.status = 'drafting'
        room.current_pick_idx = 0
        room.ready_members = set()  # waiting-room ready state no longer means anything once drafting starts

    # ── picking ────────────────────────────────────────────────────────────────

    def make_pick(self, room: RoomState, client_id: str, player_id: int) -> dict:
        if room.status != 'drafting':
            raise ValueError("Draft is not active")
        if room.current_picker_id != client_id:
            raise ValueError("It's not your turn")
        if player_id in room.drafted_ids:
            raise ValueError("Player already drafted")

        member = room.members[client_id]

        # Enforce keeper on last pick
        if member.needs_keeper(room.keeper_ids) and player_id not in room.keeper_ids:
            raise ValueError("Your last pick must be a wicket-keeper")

        member.squad.append(player_id)
        room.drafted_ids.add(player_id)
        room.current_pick_idx += 1
        return {"picker": client_id, "player_id": player_id, "squad_size": len(member.squad)}

    def auto_pick(self, room: RoomState, all_player_ids: List[int]) -> Optional[dict]:
        """Pick a random valid player for the current picker (called on timeout)."""
        if room.status != 'drafting' or not room.current_picker_id:
            return None
        client_id = room.current_picker_id
        member = room.members[client_id]
        available = [pid for pid in all_player_ids if pid not in room.drafted_ids]
        if member.needs_keeper(room.keeper_ids):
            keepers = [pid for pid in available if pid in room.keeper_ids]
            pool = keepers if keepers else available
        else:
            pool = available
        if not pool:
            return None
        player_id = random.choice(pool)
        return self.make_pick(room, client_id, player_id)

    def reorder_squad(self, room: RoomState, client_id: str, order: List[int]) -> None:
        member = room.members.get(client_id)
        if not member:
            raise ValueError("Not a member of this room")
        if set(order) != set(member.squad) or len(order) != len(member.squad):
            raise ValueError("Invalid reorder: must contain same player IDs")
        member.squad = order

    # ── broadcast ──────────────────────────────────────────────────────────────

    async def broadcast(self, room: RoomState, message: dict) -> None:
        data = json.dumps(message)
        dead = []
        for member in room.members.values():
            if member.ws:
                try:
                    await member.ws.send_text(data)
                except Exception as e:
                    get_logger().warning(
                        "Broadcast send failed for room %s, client %s: %s",
                        room.room_id, member.client_id, e,
                    )
                    dead.append(member.client_id)
        for cid in dead:
            room.members[cid].ws = None

    async def send(self, ws: WebSocket, message: dict) -> None:
        await ws.send_text(json.dumps(message))

    # ── timer ──────────────────────────────────────────────────────────────────

    def cancel_timer(self, room: RoomState) -> None:
        if room._timer_task and not room._timer_task.done():
            room._timer_task.cancel()
        room._timer_task = None

    def cancel_reorder_timer(self, room: RoomState) -> None:
        if room._reorder_task and not room._reorder_task.done():
            room._reorder_task.cancel()
        room._reorder_task = None

    def start_timer(self, room: RoomState, loop: asyncio.AbstractEventLoop,
                    on_timeout, all_player_ids: List[int]) -> None:
        self.cancel_timer(room)
        room._timer_task = loop.create_task(
            self._run_timer(room, on_timeout, all_player_ids)
        )

    async def _run_timer(self, room: RoomState, on_timeout, all_player_ids: List[int]) -> None:
        for remaining in range(PICK_TIMEOUT_S, 0, -1):
            await asyncio.sleep(1)
            await self.broadcast(room, {
                "type": "timer_tick",
                "data": {"seconds_remaining": remaining - 1, "picker": room.current_picker_id},
            })
        await on_timeout(room, all_player_ids)

    # ── utils ──────────────────────────────────────────────────────────────────

    def _unique_code(self, length: int = 6) -> str:
        chars = string.ascii_uppercase + string.digits
        for _ in range(100):
            code = ''.join(random.choices(chars, k=length))
            if code not in self._rooms:
                return code
        raise RuntimeError("Could not generate unique room code")


# ── draft sequence helpers ─────────────────────────────────────────────────────

def _snake_sequence(players: List[str], picks_each: int) -> List[str]:
    """Snake draft: A B B A A B B … for 2 players."""
    seq = []
    for round_ in range(picks_each):
        seq.extend(players if round_ % 2 == 0 else reversed(players))
    return seq


def _roundrobin_sequence(players: List[str], picks_each: int) -> List[str]:
    return players * picks_each


# Process-level singleton
draft_manager = DraftManager()
