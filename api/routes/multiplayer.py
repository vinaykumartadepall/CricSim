from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from api.multiplayer.manager import SQUAD_SIZE, RoomState, draft_manager
from db.database import get_db_connection

router = APIRouter(prefix="/cricsimapi/multiplayer", tags=["multiplayer"])

_KEEPER_ROLE = "Keeper"


# ── player search ──────────────────────────────────────────────────────────────

@router.get("/players")
def search_players(
    q: str = Query("", description="Search by name"),
    keeper_only: bool = Query(False),
    limit: int = Query(30, le=50),
):
    conn = get_db_connection(); cur = conn.cursor()
    try:
        if keeper_only:
            cur.execute(
                """
                SELECT player_id, display_name, player_role, batting_style, bowling_style,
                       cricinfo_id, player_role = 'Keeper' AS is_keeper
                FROM history.players
                WHERE gender = 'male' AND player_role = 'Keeper'
                  AND (display_name ILIKE %s OR name ILIKE %s)
                ORDER BY display_name LIMIT %s
                """,
                (f"%{q}%", f"%{q}%", limit),
            )
        else:
            cur.execute(
                """
                SELECT player_id, display_name, player_role, batting_style, bowling_style,
                       cricinfo_id, player_role = 'Keeper' AS is_keeper
                FROM history.players
                WHERE gender = 'male'
                  AND (display_name ILIKE %s OR name ILIKE %s)
                ORDER BY display_name LIMIT %s
                """,
                (f"%{q}%", f"%{q}%", limit),
            )
        rows = cur.fetchall()
    finally:
        cur.close(); conn.close()

    return [
        {
            "player_id": r[0],
            "name": r[1],
            "role": r[2],
            "batting_style": r[3],
            "bowling_style": r[4],
            "headshot_url": _headshot(r[5]),
            "is_keeper": r[6],
        }
        for r in rows
    ]


# ── room create/join ───────────────────────────────────────────────────────────

class CreateRoomRequest(BaseModel):
    client_id: str
    display_name: str = Field(..., min_length=1, max_length=32)
    mode: str = Field("1v1", pattern="^(1v1|tournament)$")
    tournament_name: str = Field("", max_length=64)
    player_count: int = Field(2, ge=2, le=10)


class JoinRoomRequest(BaseModel):
    client_id: str
    display_name: str = Field(..., min_length=1, max_length=32)


@router.post("/rooms")
def create_room(body: CreateRoomRequest):
    if body.mode == "1v1" and body.player_count != 2:
        raise HTTPException(status_code=422, detail="1v1 mode requires exactly 2 players")
    if body.mode == "tournament" and body.player_count < 4:
        raise HTTPException(status_code=422, detail="Tournament mode requires at least 4 players")

    name = body.tournament_name.strip() or _random_tournament_name()
    room = draft_manager.create_room(
        host_id=body.client_id,
        display_name=body.display_name,
        mode=body.mode,
        tournament_name=name,
        player_count=body.player_count,
    )
    _persist_room(room)
    return {"room_id": room.room_id, "tournament_name": room.tournament_name, **room.to_dict()}


@router.post("/rooms/{room_id}/join")
def join_room(room_id: str, body: JoinRoomRequest):
    try:
        room = draft_manager.join_room(room_id, body.client_id, body.display_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _persist_member(room.room_id, body.client_id, body.display_name)
    return room.to_dict()


@router.get("/rooms/{room_id}")
def get_room(room_id: str):
    room = draft_manager.get_room(room_id)
    if not room:
        # Try to load from DB for rooms whose host hasn't connected yet
        raise HTTPException(status_code=404, detail="Room not found")
    return room.to_dict()


# ── WebSocket ──────────────────────────────────────────────────────────────────

@router.websocket("/ws/{room_id}")
async def room_ws(ws: WebSocket, room_id: str, client_id: str = Query(...)):
    room = draft_manager.get_room(room_id)
    if not room or client_id not in room.members:
        await ws.close(code=4004)
        return

    await ws.accept()
    draft_manager.connect(room, client_id, ws)
    await draft_manager.send(ws, {"type": "room_state", "data": room.to_dict()})
    await draft_manager.broadcast(room, {"type": "member_connected", "data": {"client_id": client_id}})

    try:
        async for raw in ws.iter_text():
            try:
                msg = __import__("json").loads(raw)
            except Exception:
                continue
            await _handle_message(room, client_id, ws, msg)
    except WebSocketDisconnect:
        pass
    finally:
        draft_manager.disconnect(room, client_id)
        await draft_manager.broadcast(room, {"type": "member_disconnected", "data": {"client_id": client_id}})


# ── message handler ────────────────────────────────────────────────────────────

async def _handle_message(room: RoomState, client_id: str, ws: WebSocket, msg: dict):
    t = msg.get("type")

    if t == "start_draft":
        if client_id != room.host_id:
            await draft_manager.send(ws, {"type": "error", "data": {"message": "Only the host can start the draft"}})
            return
        if len(room.members) < 2:
            await draft_manager.send(ws, {"type": "error", "data": {"message": "Need at least 2 players"}})
            return
        keeper_ids = _load_keeper_ids()
        try:
            draft_manager.start_draft(room, keeper_ids)
        except ValueError as e:
            await draft_manager.send(ws, {"type": "error", "data": {"message": str(e)}})
            return
        all_pids = _load_all_player_ids()
        await draft_manager.broadcast(room, {"type": "draft_started", "data": room.to_dict()})
        _start_pick_timer(room, all_pids)

    elif t == "pick_player":
        player_id = msg.get("player_id")
        if not isinstance(player_id, int):
            await draft_manager.send(ws, {"type": "error", "data": {"message": "Invalid player_id"}})
            return
        try:
            result = draft_manager.make_pick(room, client_id, player_id)
        except ValueError as e:
            await draft_manager.send(ws, {"type": "error", "data": {"message": str(e)}})
            return

        draft_manager.cancel_timer(room)
        player_info = _player_info(player_id)
        await draft_manager.broadcast(room, {
            "type": "pick_made",
            "data": {**result, "player": player_info, "room": room.to_dict()},
        })

        if room.draft_complete():
            await _finish_draft(room)
        else:
            all_pids = _load_all_player_ids()
            _start_pick_timer(room, all_pids)

    elif t == "reorder_squad":
        order = msg.get("order", [])
        try:
            draft_manager.reorder_squad(room, client_id, order)
        except ValueError as e:
            await draft_manager.send(ws, {"type": "error", "data": {"message": str(e)}})
            return
        await draft_manager.broadcast(room, {
            "type": "squad_reordered",
            "data": {"client_id": client_id, "squad": order},
        })

    elif t == "ping":
        await draft_manager.send(ws, {"type": "pong"})


# ── auto-pick on timeout ───────────────────────────────────────────────────────

async def _on_timeout(room: RoomState, all_player_ids: list):
    result = draft_manager.auto_pick(room, all_player_ids)
    if not result:
        return
    player_info = _player_info(result["player_id"])
    await draft_manager.broadcast(room, {
        "type": "pick_made",
        "data": {**result, "player": player_info, "auto_picked": True, "room": room.to_dict()},
    })
    if room.draft_complete():
        await _finish_draft(room)
    else:
        _start_pick_timer(room, all_player_ids)


def _start_pick_timer(room: RoomState, all_pids: list):
    loop = asyncio.get_event_loop()
    draft_manager.start_timer(room, loop, _on_timeout, all_pids)


# ── simulation trigger ─────────────────────────────────────────────────────────

async def _finish_draft(room: RoomState):
    room.status = "simulating"
    await draft_manager.broadcast(room, {"type": "draft_complete", "data": room.to_dict()})

    try:
        sim_id = await asyncio.get_event_loop().run_in_executor(None, _run_simulation, room)
        room.sim_id = sim_id
        room.status = "completed"
        await draft_manager.broadcast(room, {
            "type": "sim_result",
            "data": {"sim_id": sim_id},
        })
    except Exception as e:
        room.status = "waiting"
        await draft_manager.broadcast(room, {"type": "error", "data": {"message": f"Simulation failed: {e}"}})
    finally:
        _cleanup_room_db(room.room_id)
        draft_manager.remove_room(room.room_id)


def _run_simulation(room: RoomState) -> str:
    """Build a tournament/match config and kick off the simulation synchronously."""
    from api.worker import run_tournament_job, run_match_job
    from db.simulation_repository import SimulationRepository
    import uuid

    members = sorted(room.members.values(), key=lambda m: m.draft_order)
    conn = get_db_connection(); cur = conn.cursor()

    # Fetch player details for all squad members
    all_ids = list({pid for m in members for pid in m.squad})
    cur.execute(
        "SELECT player_id, display_name, player_role, batting_style, bowling_style "
        "FROM history.players WHERE player_id = ANY(%s)",
        (all_ids,),
    )
    player_map = {r[0]: {"name": r[1], "role": r[2], "bat": r[3], "bowl": r[4]} for r in cur.fetchall()}
    cur.close(); conn.close()

    def _team_cfg(member: "Member") -> dict:
        return {
            "name": member.display_name,
            "players": member.squad,
            "primary_color": "#1a1a2e",
            "secondary_color": "#16213e",
        }

    repo = SimulationRepository()
    try:
        if room.mode == "1v1":
            home, away = members[0], members[1]
            config = {
                "simulation_type": "match",
                "match_format": "T20",
                "home_team": _team_cfg(home),
                "away_team": _team_cfg(away),
                "venue": None,
            }
            sim_id = repo.create_simulation("match", config, client_id=None, mode="multiplayer")
            repo.commit()
            run_match_job(sim_id, config)
        else:
            teams = [_team_cfg(m) for m in members]
            config = {
                "simulation_type": "tournament",
                "tournament_name": room.tournament_name,
                "season": "2025",
                "format": "T20",
                "gender": "male",
                "teams": teams,
                "outcome_strategy": "enhanced_historical_stats",
                "bowling_strategy": "historical",
            }
            sim_id = repo.create_simulation("tournament", config, client_id=None, mode="multiplayer")
            repo.commit()
            run_tournament_job(sim_id, config, user_team_name=None)
        return sim_id
    finally:
        repo.close()


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _persist_room(room: RoomState) -> None:
    conn = get_db_connection(autocommit=True); cur = conn.cursor()
    cur.execute(
        """INSERT INTO simulation.rooms (room_id, host_id, mode, status, tournament_name, player_count)
           VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        (room.room_id, room.host_id, room.mode, room.status, room.tournament_name, room.player_count),
    )
    cur.execute(
        """INSERT INTO simulation.room_members (room_id, client_id, display_name, squad)
           VALUES (%s, %s, %s, '[]') ON CONFLICT DO NOTHING""",
        (room.room_id, room.host_id, room.members[room.host_id].display_name),
    )
    cur.close(); conn.close()


def _persist_member(room_id: str, client_id: str, display_name: str) -> None:
    conn = get_db_connection(autocommit=True); cur = conn.cursor()
    cur.execute(
        """INSERT INTO simulation.room_members (room_id, client_id, display_name, squad)
           VALUES (%s, %s, %s, '[]') ON CONFLICT DO NOTHING""",
        (room_id, client_id, display_name),
    )
    cur.close(); conn.close()


def _cleanup_room_db(room_id: str) -> None:
    conn = get_db_connection(autocommit=True); cur = conn.cursor()
    cur.execute("DELETE FROM simulation.rooms WHERE room_id = %s", (room_id,))
    cur.close(); conn.close()


def _load_keeper_ids() -> set:
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT player_id FROM history.players WHERE gender='male' AND player_role='Keeper'")
    ids = {r[0] for r in cur.fetchall()}
    cur.close(); conn.close()
    return ids


def _load_all_player_ids() -> list:
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT player_id FROM history.players WHERE gender='male' ORDER BY player_id")
    ids = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()
    return ids


def _player_info(player_id: int) -> dict:
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute(
        "SELECT display_name, player_role, cricinfo_id FROM history.players WHERE player_id=%s",
        (player_id,),
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return {"player_id": player_id, "name": "Unknown", "role": "", "headshot_url": None}
    return {
        "player_id": player_id,
        "name": row[0],
        "role": row[1],
        "headshot_url": _headshot(row[2]),
        "is_keeper": row[1] == _KEEPER_ROLE,
    }


def _headshot(cricinfo_id) -> Optional[str]:
    if not cricinfo_id:
        return None
    return f"https://img1.hscicdn.com/image/upload/f_auto,t_h_100_2x/lsci/db/PICTURES/CMS/316600/{cricinfo_id}.png"


def _random_tournament_name() -> str:
    import random
    adjectives = ["Blitz", "Thunder", "Storm", "Clash", "Rumble", "Duel", "Battle", "Showdown"]
    nouns = ["Cup", "Trophy", "Championship", "Invitational", "Series", "League", "Open"]
    return f"{random.choice(adjectives)} {random.choice(nouns)} 2025"
