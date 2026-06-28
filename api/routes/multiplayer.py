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
        role_filter = "AND player_role = 'Keeper'" if keeper_only else ""
        cur.execute(
            f"""
            SELECT p.player_id, p.display_name, p.player_role, p.batting_style, p.bowling_style,
                   p.cricinfo_id, p.player_role = 'Keeper' AS is_keeper
            FROM history.players p
            LEFT JOIN (
                SELECT player_id, COUNT(*) AS matches_played
                FROM history.match_players
                GROUP BY player_id
            ) mp ON mp.player_id = p.player_id
            WHERE p.gender = 'male' {role_filter}
              AND (p.display_name ILIKE %s OR p.name ILIKE %s)
            ORDER BY COALESCE(mp.matches_played, 0) DESC LIMIT %s
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
    team_name: str = Field("", max_length=32)
    mode: str = Field("1v1", pattern="^(1v1|tournament)$")
    tournament_name: str = Field("", max_length=64)
    player_count: int = Field(2, ge=2, le=10)
    match_format: str = Field("T20", pattern="^(T20|ODI|Test)$")


class JoinRoomRequest(BaseModel):
    client_id: str
    display_name: str = Field(..., min_length=1, max_length=32)
    team_name: str = Field("", max_length=32)


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
        team_name=body.team_name.strip(),
        mode=body.mode,
        tournament_name=name,
        player_count=body.player_count,
        match_format=body.match_format,
    )
    _persist_room(room)
    return {"room_id": room.room_id, "tournament_name": room.tournament_name, **room.to_dict()}


@router.post("/rooms/{room_id}/join")
def join_room(room_id: str, body: JoinRoomRequest):
    try:
        room = draft_manager.join_room(room_id, body.client_id, body.display_name, body.team_name.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _persist_member(room.room_id, body.client_id, body.display_name)
    return room.to_dict()


class UpdateMemberRequest(BaseModel):
    client_id: str
    team_name: str = Field(..., min_length=1, max_length=32)


@router.patch("/rooms/{room_id}/member")
def update_room_member(room_id: str, body: UpdateMemberRequest):
    ok = draft_manager.update_team_name(room_id, body.client_id, body.team_name.strip())
    if not ok:
        raise HTTPException(status_code=404, detail="Room or member not found")
    return {"ok": True}


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
    await ws.accept()
    room = draft_manager.get_room(room_id)
    if not room or client_id not in room.members:
        await ws.close(code=4004, reason="Room not found or not a member")
        return
    draft_manager.connect(room, client_id, ws)
    await draft_manager.send(ws, {"type": "room_state", "data": room.to_dict()})
    await draft_manager.broadcast(room, {"type": "member_connected", "data": {"client_id": client_id}})

    # Auto-start when all members are connected and room is at capacity
    if (room.status == 'waiting'
            and len(room.members) == room.player_count
            and all(m.ws is not None for m in room.members.values())):
        try:
            keeper_ids = _load_keeper_ids()
            draft_manager.start_draft(room, keeper_ids)
            all_pids = _load_all_player_ids()
            await draft_manager.broadcast(room, {"type": "draft_started", "data": room.to_dict()})
            _start_pick_timer(room, all_pids)
        except ValueError:
            pass  # already started by another connection racing here
        except Exception as exc:
            await draft_manager.send(ws, {"type": "error", "data": {"message": f"Auto-start failed: {exc}"}})

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

    elif t == "player_ready":
        if room.status != "reordering":
            return
        room.ready_members.add(client_id)
        await draft_manager.broadcast(room, {
            "type": "ready_update",
            "data": {"ready_members": list(room.ready_members), "total": len(room.members)},
        })
        if len(room.ready_members) >= len(room.members):
            draft_manager.cancel_reorder_timer(room)
            await _start_simulation(room)

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


# ── reorder phase ──────────────────────────────────────────────────────────────

async def _finish_draft(room: RoomState):
    """Called when all picks are done — enters the 60-second reorder phase."""
    room.status = "reordering"
    room.ready_members = set()
    await draft_manager.broadcast(room, {"type": "reorder_phase", "data": room.to_dict()})
    loop = asyncio.get_event_loop()
    room._reorder_task = loop.create_task(_reorder_timeout(room))


async def _reorder_timeout(room: RoomState):
    for remaining in range(60, 0, -1):
        await asyncio.sleep(1)
        if room.status != "reordering":
            return
        await draft_manager.broadcast(room, {
            "type": "reorder_tick",
            "data": {"seconds_remaining": remaining - 1},
        })
    if room.status == "reordering":
        await _start_simulation(room)


async def _start_simulation(room: RoomState):
    if room.status != "reordering":
        return
    room.status = "simulating"
    await draft_manager.broadcast(room, {"type": "sim_started", "data": {}})
    try:
        sim_id, match_id = await asyncio.get_event_loop().run_in_executor(None, _run_simulation, room)
        room.sim_id = sim_id
        room.status = "completed"
        await draft_manager.broadcast(room, {
            "type": "sim_result",
            "data": {"sim_id": sim_id, "mode": room.mode, "match_id": match_id},
        })
    except Exception as e:
        room.status = "reordering"
        await draft_manager.broadcast(room, {"type": "error", "data": {"message": f"Simulation failed: {e}"}})
    finally:
        _cleanup_room_db(room.room_id)
        draft_manager.remove_room(room.room_id)


def _run_simulation(room: RoomState) -> tuple:
    """Build a tournament/match config and kick off the simulation synchronously."""
    from api.worker import run_tournament_job, run_match_job
    from db.simulation_repository import SimulationRepository

    members = sorted(room.members.values(), key=lambda m: m.draft_order)

    def _team_cfg(member) -> dict:
        return {
            "name": member.team_name or member.display_name,
            "players": member.squad,
            "primary_color": "#1a1a2e",
            "secondary_color": "#16213e",
        }

    # client_id → team name for game_session creation after sim
    team_name_by_client: dict = {m.client_id: (m.team_name or m.display_name) for m in members}
    participant_ids = [m.client_id for m in members]

    repo = SimulationRepository()
    try:
        fmt = room.match_format
        if room.mode == "1v1":
            home, away = members[0], members[1]
            config = {
                "simulation_type": "match",
                "match_format": fmt,
                "gender": "male",
                "team_a": _team_cfg(home),
                "team_b": _team_cfg(away),
                "venue": None,
            }
            sim_id = repo.create_simulation("match", config, client_id=None, mode="multiplayer",
                                            participant_ids=participant_ids)
            repo.commit()
            run_match_job(sim_id, config)

            # Create one game_session per participant now that simulation.teams rows exist
            _save_multiplayer_game_sessions(repo, sim_id, team_name_by_client)

            # Fetch the match_id for direct navigation
            repo.cur.execute(
                "SELECT match_id FROM simulation.matches WHERE sim_id = %s LIMIT 1", (sim_id,)
            )
            row = repo.cur.fetchone()
            return sim_id, (row[0] if row else None)
        else:
            teams = [_team_cfg(m) for m in members]
            config = {
                "simulation_type": "tournament",
                "tournament_name": room.tournament_name,
                "season": "2025",
                "format": fmt,
                "gender": "male",
                "teams": teams,
                "outcome_strategy": "enhanced_historical_stats",
                "bowling_strategy": "historical",
            }
            sim_id = repo.create_simulation("tournament", config, client_id=None, mode="multiplayer",
                                            participant_ids=participant_ids)
            repo.commit()
            run_tournament_job(sim_id, config, user_team_name=None)

            # Create one game_session per participant now that simulation.teams rows exist
            _save_multiplayer_game_sessions(repo, sim_id, team_name_by_client)

            return sim_id, None
    finally:
        repo.close()


def _save_multiplayer_game_sessions(
    repo,
    sim_id: str,
    team_name_by_client: dict,
) -> None:
    """After a multiplayer simulation completes, create one game_sessions row per participant.

    Looks up simulation.teams by team name (set during simulation) to resolve user_team_id,
    enabling team-name display and placement badges in list_simulations.
    """
    from db.simulation_repository import SimulationRepository

    # Resolve team names → simulation.teams IDs via the matches table
    # (works for both match and tournament sims without needing sim_id on simulation.teams)
    repo.cur.execute(
        """
        SELECT DISTINCT t.team_id, t.name
        FROM simulation.matches m
        JOIN simulation.teams t ON t.team_id IN (m.home_team_id, m.away_team_id)
        WHERE m.sim_id = %s
        """,
        (sim_id,),
    )
    team_id_by_name = {name: tid for tid, name in repo.cur.fetchall()}

    for client_id, team_name in team_name_by_client.items():
        user_team_id = team_id_by_name.get(team_name)
        repo.save_game_session(
            sim_id=sim_id,
            client_id=client_id,
            mode="multiplayer",
            source_tournament_id=None,
            user_team_id=user_team_id,
            swaps=[],
        )
    repo.commit()


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _persist_room(room: RoomState) -> None:
    conn = get_db_connection(autocommit=True); cur = conn.cursor()
    cur.execute(
        """INSERT INTO simulation.rooms (room_id, host_id, mode, status, tournament_name, player_count, match_format)
           VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        (room.room_id, room.host_id, room.mode, room.status, room.tournament_name, room.player_count, room.match_format),
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
    return f"https://a.espncdn.com/i/headshots/cricket/players/full/{cricinfo_id}.png"


def _random_tournament_name() -> str:
    import random
    adjectives = ["Blitz", "Thunder", "Storm", "Clash", "Rumble", "Duel", "Battle", "Showdown"]
    nouns = ["Cup", "Trophy", "Championship", "Invitational", "Series", "League", "Open"]
    return f"{random.choice(adjectives)} {random.choice(nouns)} 2025"
