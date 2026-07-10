from __future__ import annotations

import asyncio
import os
import time
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

import json as _json

from api.job_queue import job_queue
from api.multiplayer.manager import HOST_RECONNECT_GRACE_S, SQUAD_SIZE, RoomState, draft_manager, _snake_sequence
from db.database import get_db_connection
from simulator.logger import get_logger

router = APIRouter(prefix="/cricsimapi/multiplayer", tags=["multiplayer"])

_KEEPER_ROLE = "Keeper"
# How long a 'waiting' room can sit with no activity (creation, join,
# reconnect, or a reset-to-waiting after a simulation) before the idle
# reaper cleans it up - see _reap_idle_rooms_forever.
ROOM_IDLE_TIMEOUT_S = int(os.getenv("ROOM_IDLE_TIMEOUT_S", str(30 * 60)))


# ── player search ──────────────────────────────────────────────────────────────

@router.get("/players")
def search_players(
    q: str = Query("", description="Search by name"),
    role: Optional[List[str]] = Query(None),
    country_id: Optional[List[int]] = Query(None),
    batting_style: Optional[List[str]] = Query(None),
    bowling_style: Optional[List[str]] = Query(None),
    limit: int = Query(30, le=50),
):
    conn = get_db_connection(); cur = conn.cursor()
    try:
        # Each filter is multi-select (repeated query params) - ANY(%s) against
        # a list matches "role IN (...)" without building a dynamic IN clause.
        filters: list[str] = []
        params: list = []
        if role:
            filters.append("p.player_role = ANY(%s)")
            params.append(role)
        if country_id:
            filters.append("p.country_id = ANY(%s)")
            params.append(country_id)
        if batting_style:
            filters.append("p.batting_style = ANY(%s)")
            params.append(batting_style)
        if bowling_style:
            filters.append("p.bowling_style = ANY(%s)")
            params.append(bowling_style)
        extra_filters = (" AND " + " AND ".join(filters)) if filters else ""

        cur.execute(
            f"""
            SELECT p.player_id, COALESCE(p.display_name, p.name) AS display_name, p.player_role, p.batting_style, p.bowling_style,
                   p.cricinfo_id, p.player_role = 'Keeper' AS is_keeper, c.name AS country
            FROM history.players p
            LEFT JOIN history.countries c ON c.country_id = p.country_id
            LEFT JOIN (
                SELECT player_id, COUNT(*) AS matches_played
                FROM history.match_players
                GROUP BY player_id
            ) mp ON mp.player_id = p.player_id
            WHERE p.gender = 'male' {extra_filters}
              AND (p.display_name ILIKE %s OR p.name ILIKE %s)
            ORDER BY COALESCE(mp.matches_played, 0) DESC LIMIT %s
            """,
            (*params, f"%{q}%", f"%{q}%", limit),
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
            "country": r[7],
        }
        for r in rows
    ]


# ── player search filter options ────────────────────────────────────────────────

@router.get("/player-filters")
def player_filter_options():
    """Distinct values to populate the search filter dropdowns - kept as a
    live query (not hardcoded) so it always matches the actual player data."""
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute(
            "SELECT DISTINCT player_role FROM history.players "
            "WHERE gender = 'male' AND player_role IS NOT NULL ORDER BY 1"
        )
        roles = [r[0] for r in cur.fetchall()]

        cur.execute(
            """
            SELECT DISTINCT c.country_id, c.name
            FROM history.countries c
            JOIN history.players p ON p.country_id = c.country_id
            WHERE p.gender = 'male'
            ORDER BY c.name
            """
        )
        countries = [{"country_id": r[0], "name": r[1]} for r in cur.fetchall()]

        cur.execute(
            "SELECT DISTINCT batting_style FROM history.players "
            "WHERE gender = 'male' AND batting_style IS NOT NULL ORDER BY 1"
        )
        batting_styles = [r[0] for r in cur.fetchall()]

        cur.execute(
            "SELECT DISTINCT bowling_style FROM history.players "
            "WHERE gender = 'male' AND bowling_style IS NOT NULL ORDER BY 1"
        )
        bowling_styles = [r[0] for r in cur.fetchall()]
    finally:
        cur.close(); conn.close()

    return {
        "roles": roles,
        "countries": countries,
        "batting_styles": batting_styles,
        "bowling_styles": bowling_styles,
    }


# ── room create/join ───────────────────────────────────────────────────────────

class CreateRoomRequest(BaseModel):
    client_id: str
    display_name: str = Field(..., min_length=1, max_length=32)
    mode: str = Field("1v1", pattern="^(1v1|tournament)$")
    tournament_name: str = Field("", max_length=64)
    player_count: int = Field(2, ge=2, le=10)
    match_format: str = Field("T20", pattern="^(T20|ODI|Test)$")


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
        match_format=body.match_format,
    )
    _persist_room(room)
    return {"room_id": room.room_id, "tournament_name": room.tournament_name, **room.to_dict()}


@router.post("/rooms/{room_id}/join")
def join_room(room_id: str, body: JoinRoomRequest):
    if not _room_exists_in_db(room_id):
        draft_manager.remove_room(room_id)
        raise HTTPException(status_code=404, detail="Room no longer exists")
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
    await ws.accept()
    room = draft_manager.get_room(room_id)
    if not room:
        room = _restore_room_from_db(room_id)
    if not room:
        await ws.close(code=4004, reason="Room not found")
        return
    if client_id not in room.members:
        await ws.close(code=4003, reason="Not a member of this room")
        return
    draft_manager.connect(room, client_id, ws)
    room_dict = room.to_dict()
    if room.drafted_ids:
        room_dict["player_details"] = _fetch_player_details(list(room.drafted_ids))
    await draft_manager.send(ws, {"type": "room_state", "data": room_dict})
    await draft_manager.broadcast(room, {"type": "member_connected", "data": {"client_id": client_id}})
    # During waiting, push full room_state so all clients refresh the member list
    if room.status == "waiting":
        await draft_manager.broadcast(room, {"type": "room_state", "data": room.to_dict()})

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
        # During waiting, push full room_state so the member list's
        # connected/disconnected dot refreshes immediately.
        if room.status == "waiting":
            await draft_manager.broadcast(room, {"type": "room_state", "data": room.to_dict()})
        # Host leaving is very often just a page reload (same client_id
        # reconnects within a couple seconds) - wait out a grace period
        # before actually handing host to someone else, instead of
        # transferring instantly on every disconnect.
        if room.status == "waiting" and client_id == room.host_id:
            asyncio.create_task(_transfer_host_after_grace_period(room, client_id))


async def _transfer_host_after_grace_period(room: RoomState, client_id: str) -> None:
    await asyncio.sleep(HOST_RECONNECT_GRACE_S)
    if room.status != "waiting" or room.host_id != client_id:
        return  # already resolved (transferred some other way, draft started, etc.)
    member = room.members.get(client_id)
    if member is not None and member.ws is not None:
        return  # reconnected within the grace period - nothing to do
    if draft_manager.transfer_host(room, client_id):
        await draft_manager.broadcast(room, {"type": "room_state", "data": room.to_dict()})


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
        _persist_draft_start(room)
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
        room.members[client_id].disconnected_auto_picks = 0
        _persist_squad(room.room_id, client_id, room.members[client_id].squad)

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
            "data": {"client_id": client_id, "batting_order": order},
        })

    elif t == "player_ready":
        if room.status not in ("reordering", "waiting"):
            return
        room.ready_members.add(client_id)
        await draft_manager.broadcast(room, {
            "type": "ready_update",
            "data": {"ready_members": list(room.ready_members), "total": len(room.members)},
        })
        # Waiting-room ready is informational only - lets players signal they've
        # read the rules, but the host always has to click Start Draft manually,
        # even once everyone's ready. Only the post-draft reorder phase auto-proceeds.
        if room.status == "reordering" and len(room.ready_members) >= len(room.members):
            draft_manager.cancel_reorder_timer(room)
            await _start_simulation(room)

    elif t == "kick_player":
        target_id = msg.get("client_id")
        if not isinstance(target_id, str):
            return
        try:
            kicked = draft_manager.kick_member(room, client_id, target_id)
        except ValueError as e:
            await draft_manager.send(ws, {"type": "error", "data": {"message": str(e)}})
            return
        if kicked.ws is not None:
            try:
                await kicked.ws.close(code=4001, reason="Removed from room by host")
            except Exception:
                pass
        await draft_manager.broadcast(room, {"type": "room_state", "data": room.to_dict()})

    elif t == "leave_room":
        try:
            result = draft_manager.leave_room(room, client_id)
        except ValueError as e:
            await draft_manager.send(ws, {"type": "error", "data": {"message": str(e)}})
            return
        try:
            _persist_leave_room(room.room_id, client_id)
        except Exception:
            get_logger().exception("Failed to persist leave for room %s, client %s", room.room_id, client_id)
        await draft_manager.send(ws, {"type": "left_room", "data": {}})
        if result["ended"]:
            try:
                _cleanup_room_db(room.room_id)
            except Exception:
                pass
            draft_manager.remove_room(room.room_id)
        else:
            await draft_manager.broadcast(room, {"type": "room_state", "data": room.to_dict()})

    elif t == "ping":
        await draft_manager.send(ws, {"type": "pong"})


# ── auto-pick on timeout ───────────────────────────────────────────────────────

# A disconnected picker's first 2 turns still wait out the full timer (real
# chances to reconnect); from the 3rd consecutive disconnected turn,
# _start_pick_timer skips the wait entirely - see DraftManager.auto_pick,
# which is what actually increments Member.disconnected_auto_picks.
_INSTANT_PICK_THRESHOLD = 2

async def _on_timeout(room: RoomState, all_player_ids: list):
    """Auto-picks the current turn - called either after the normal 60s
    timer lapses, or immediately (via _start_pick_timer) for a picker who's
    already missed _INSTANT_PICK_THRESHOLD turns in a row while disconnected."""
    result = draft_manager.auto_pick(room, all_player_ids)
    if not result:
        return
    picker = room.members.get(result["picker"])
    if picker is not None and picker.ws is None and picker.disconnected_auto_picks == _INSTANT_PICK_THRESHOLD + 1:
        # Threshold just crossed for the first time - one-time notification,
        # not a repeated one on every subsequent instant pick.
        await draft_manager.broadcast(room, {
            "type": "player_auto_drafting",
            "data": {"client_id": picker.client_id, "display_name": picker.display_name},
        })
    _persist_squad(room.room_id, result["picker"], room.members[result["picker"]].squad)
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
    picker = room.members.get(room.current_picker_id) if room.current_picker_id else None
    if picker is not None and picker.ws is None and picker.disconnected_auto_picks >= _INSTANT_PICK_THRESHOLD:
        # Already missed 2 turns in a row while disconnected - stop waiting
        # out the timer for them and auto-pick instantly until they
        # reconnect. Scheduled as a task (not awaited inline) since this
        # function is sync, matching how the timer path itself is scheduled.
        loop.create_task(_on_timeout(room, all_pids))
        return
    draft_manager.start_timer(room, loop, _on_timeout, all_pids)


# ── reorder phase ──────────────────────────────────────────────────────────────

async def _finish_draft(room: RoomState):
    """Called when all picks are done - enters the 60-second reorder phase."""
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

    loop = asyncio.get_event_loop()

    def on_sim_created(sim_id: str) -> None:
        # _run_simulation runs in a worker thread - hop back onto the event
        # loop to broadcast, so clients can hand off to the shared
        # "simulating" page immediately instead of waiting the full 10-30s
        # for the simulation itself to finish.
        future = asyncio.run_coroutine_threadsafe(
            draft_manager.broadcast(room, {"type": "sim_created", "data": {"sim_id": sim_id}}),
            loop,
        )
        # run_coroutine_threadsafe's Future silently drops exceptions unless
        # something retrieves them - log any broadcast failure instead of
        # losing it, consistent with every other except-block in this file.
        def _log_if_failed(f) -> None:
            exc = f.exception()
            if exc:
                get_logger().error("sim_created broadcast failed for room %s: %s", room.room_id, exc)
        future.add_done_callback(_log_if_failed)

    try:
        # Goes through the shared single-worker job_queue (not a bare
        # executor call) so this never runs concurrently with another
        # simulation - see api/job_queue.py. room_id is the tracking key
        # here since the real sim_id doesn't exist yet (on_sim_created is
        # what creates it, once the job actually starts).
        future = job_queue.submit(f"room:{room.room_id}", _run_simulation, room, on_sim_created)
        sim_id, match_id = await asyncio.wrap_future(future)
        room.sim_id = sim_id
        await draft_manager.broadcast(room, {
            "type": "sim_result",
            "data": {"sim_id": sim_id, "mode": room.mode, "match_id": match_id},
        })
        # Reset to a fresh lobby instead of destroying the room - lets the
        # same group draft and play another round without recreating the
        # room and re-sharing the invite code/link. Nobody is actually
        # watching the room page at this point (everyone already navigated
        # to /simulating/:simId off the earlier sim_created broadcast), so
        # there's no "completed" status anyone would ever observe - going
        # straight from simulating to waiting is enough.
        draft_manager.reset_to_waiting(room)
        try:
            _persist_reset_to_waiting(room.room_id)
        except Exception:
            get_logger().exception("Failed to persist waiting-reset for room %s", room.room_id)
        await draft_manager.broadcast(room, {"type": "room_state", "data": room.to_dict()})
    except Exception as e:
        # Deliberately not deleting the room here (previously this whole
        # function unconditionally deleted it in a finally block, including
        # on this exact failure path - despite resetting status to
        # "reordering" a line above, clearly intending to let the room
        # recover so players could retry starting the simulation). The room
        # now only ever gets removed via an explicit leave-until-empty or the
        # idle-timeout reaper, not as a side effect of a failed sim start.
        get_logger().exception("Simulation failed to start for room %s", room.room_id)
        room.status = "reordering"
        await draft_manager.broadcast(room, {"type": "error", "data": {"message": f"Simulation failed: {e}"}})


_INTERNATIONAL_VENUES: dict[str, list[str]] = {
    "T20": [
        "Melbourne Cricket Ground",
        "Sydney Cricket Ground",
        "Sher-e-Bangla National Cricket Stadium",
        "Sylhet International Cricket Stadium",
        "Wankhede Stadium",
        "Eden Gardens",
        "Eden Park",
        "Sky Stadium",
        "Gaddafi Stadium",
        "National Stadium, Karachi",
        "The Wanderers Stadium",
        "Newlands",
        "R Premadasa Stadium",
        "Pallekele International Cricket Stadium",
        "Daren Sammy National Cricket Stadium",
        "Kensington Oval",
    ],
    "ODI": [
        "Sydney Cricket Ground",
        "Melbourne Cricket Ground",
        "Sher-e-Bangla National Cricket Stadium",
        "Zahur Ahmed Chowdhury Stadium, Chattogram",
        "Narendra Modi Stadium",
        "M Chinnaswamy Stadium",
        "Seddon Park",
        "Eden Park",
        "Gaddafi Stadium",
        "National Stadium, Karachi",
        "SuperSport Park",
        "The Wanderers Stadium",
        "R Premadasa Stadium",
        "Rangiri Dambulla International Stadium",
        "Kensington Oval",
        "Queen's Park Oval",
    ],
    "Test": [
        "Adelaide Oval",
        "Western Australia Cricket Association Ground",
        "Sher-e-Bangla National Cricket Stadium",
        "Zahur Ahmed Chowdhury Stadium, Chattogram",
        "Eden Gardens",
        "MA Chidambaram Stadium, Chepauk",
        "Basin Reserve",
        "Seddon Park",
        "Rawalpindi Cricket Stadium",
        "National Stadium, Karachi",
        "Newlands",
        "SuperSport Park",
        "Galle International Stadium",
        "Sinhalese Sports Club Ground",
        "Kensington Oval",
        "Sabina Park, Kingston",
    ],
}


def _venues_for_format(fmt: str) -> list[dict]:
    names = _INTERNATIONAL_VENUES.get(fmt, _INTERNATIONAL_VENUES["T20"])
    return [{"name": n} for n in names]


def _run_simulation(room: RoomState, on_sim_created: Callable[[str], None]) -> tuple:
    """Build a tournament/match config and kick off the simulation synchronously."""
    from api.worker import run_tournament_job, run_match_job
    from db.simulation_repository import SimulationRepository

    members = sorted(room.members.values(), key=lambda m: m.draft_order)

    def _team_cfg(member) -> dict:
        # batting_order reflects any reordering the player did (including
        # moving a pick past an already-filled gap) - squad is pick order
        # only and never touched by reorder_squad. Defensive fallback to
        # squad if batting_order is somehow short/still has gaps (shouldn't
        # happen once the draft is actually complete).
        lineup = [pid for pid in member.batting_order if pid is not None]
        players = lineup if set(lineup) == set(member.squad) else member.squad
        return {
            "name": member.display_name,
            "players": players,
            "primary_color": "#1a1a2e",
            "secondary_color": "#16213e",
        }

    # client_id → team name for game_session creation after sim
    team_name_by_client: dict = {m.client_id: m.display_name for m in members}
    participant_ids = [m.client_id for m in members]

    repo = SimulationRepository()
    try:
        fmt = room.match_format
        venues = _venues_for_format(fmt)
        if room.mode == "1v1":
            import random
            home, away = members[0], members[1]
            venue_name = random.choice(venues)["name"] if venues else None
            config = {
                "simulation_type": "match",
                "match_format": fmt,
                "gender": "male",
                "team_a": _team_cfg(home),
                "team_b": _team_cfg(away),
                "venue": venue_name,
            }
            sim_id = repo.create_simulation("match", config, client_id=None, mode="multiplayer",
                                            participant_ids=participant_ids)
            repo.commit()
            on_sim_created(sim_id)
            run_match_job(sim_id, config)

            # Create one game_session per participant now that simulation.teams rows exist
            _save_multiplayer_game_sessions(repo, sim_id, team_name_by_client, room.room_id)

            # Fetch the match_id for direct navigation
            repo.cur.execute(
                "SELECT match_id FROM simulation.matches WHERE sim_id = %s LIMIT 1", (sim_id,)
            )
            row = repo.cur.fetchone()
            return sim_id, (row[0] if row else None)
        else:
            teams = [_team_cfg(m) for m in members]
            n_teams = len(teams)
            playoffs_fmt = "ipl" if n_teams >= 4 else "none"
            config = {
                "simulation_type": "tournament",
                "tournament_name": room.tournament_name,
                # No real historical season backs a multiplayer tournament
                # (teams are freely drafted, not seeded from one) - leaving
                # this out would default to '2025' (TournamentConfig.from_dict),
                # which then got displayed appended to a name that already
                # has the creation year baked in via MultiplayerLobbyPage's
                # randomName(), e.g. "Mighty Championship 2026 2025".
                "season": "",
                "format": fmt,
                "gender": "male",
                "teams": teams,
                "venues": venues,
                "schedule": {"type": "double_round_robin", "matches_per_pair": 2},
                "playoffs": {"format": playoffs_fmt, "top_n": 4},
                # outcome_strategy/bowling_strategy intentionally omitted - worker.py's
                # _build_tournament_config falls back to the current admin-configured
                # default (simulator.admin_settings) when these are absent.
            }
            sim_id = repo.create_simulation("tournament", config, client_id=None, mode="multiplayer",
                                            participant_ids=participant_ids)
            repo.commit()
            on_sim_created(sim_id)
            run_tournament_job(sim_id, config, user_team_name=None)

            # Create one game_session per participant now that simulation.teams rows exist
            _save_multiplayer_game_sessions(repo, sim_id, team_name_by_client, room.room_id)

            return sim_id, None
    finally:
        repo.close()


def _save_multiplayer_game_sessions(
    repo,
    sim_id: str,
    team_name_by_client: dict,
    room_id: str,
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
            room_id=room_id,
        )
    repo.commit()


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _persist_draft_start(room: RoomState) -> None:
    """Persist room status=drafting and each member's draft_order to DB.

    Also clears room_id off any past sim's game_sessions row that pointed at
    this room: once a new draft starts, the room has moved on from the round
    those old results belonged to, so a "Return to Lobby" button on an old
    result would no longer land somewhere meaningful for that result - it'd
    either barge into a new round already in progress or, later, a fresh one
    entirely. Nulling it here removes the button from those old results
    rather than leaving it to dead-end.
    """
    conn = get_db_connection(autocommit=True); cur = conn.cursor()
    cur.execute("UPDATE simulation.rooms SET status='drafting' WHERE room_id=%s", (room.room_id,))
    cur.execute("UPDATE simulation.game_sessions SET room_id=NULL WHERE room_id=%s", (room.room_id,))
    for m in room.members.values():
        cur.execute(
            "UPDATE simulation.room_members SET draft_order=%s WHERE room_id=%s AND client_id=%s",
            (m.draft_order, room.room_id, m.client_id),
        )
    cur.close(); conn.close()


def _persist_reset_to_waiting(room_id: str) -> None:
    """Mirror DraftManager.reset_to_waiting in the DB - status back to
    'waiting' and every member's squad cleared, ready for a fresh draft."""
    conn = get_db_connection(autocommit=True); cur = conn.cursor()
    cur.execute("UPDATE simulation.rooms SET status='waiting' WHERE room_id=%s", (room_id,))
    cur.execute(
        "UPDATE simulation.room_members SET squad='[]'::jsonb, draft_order=NULL WHERE room_id=%s",
        (room_id,),
    )
    cur.close(); conn.close()


def _persist_leave_room(room_id: str, client_id: str) -> None:
    conn = get_db_connection(autocommit=True); cur = conn.cursor()
    cur.execute("DELETE FROM simulation.room_members WHERE room_id=%s AND client_id=%s", (room_id, client_id))
    cur.close(); conn.close()


def _persist_squad(room_id: str, client_id: str, squad: list) -> None:
    """Update a member's squad in DB after each pick."""
    conn = get_db_connection(autocommit=True); cur = conn.cursor()
    cur.execute(
        "UPDATE simulation.room_members SET squad=%s::jsonb WHERE room_id=%s AND client_id=%s",
        (_json.dumps(squad), room_id, client_id),
    )
    cur.close(); conn.close()


def _fetch_player_details(player_ids: list) -> list:
    """Return player info dicts for a list of player_ids (used to rebuild frontend playerMap)."""
    if not player_ids:
        return []
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute(
        "SELECT player_id, COALESCE(display_name, name) AS display_name, player_role, cricinfo_id "
        "FROM history.players WHERE player_id = ANY(%s)",
        (player_ids,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [
        {"player_id": r[0], "name": r[1], "role": r[2],
         "headshot_url": _headshot(r[3]), "is_keeper": r[2] == "Keeper"}
        for r in rows
    ]


def _room_exists_in_db(room_id: str) -> bool:
    conn = get_db_connection(autocommit=True); cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM simulation.rooms WHERE room_id = %s", (room_id.upper(),))
        return cur.fetchone() is not None
    finally:
        cur.close(); conn.close()


def _restore_room_from_db(room_id: str) -> "RoomState | None":
    """Reconstruct an in-memory RoomState from DB records (e.g. after server restart)."""
    from api.multiplayer.manager import Member, RoomState as RS
    conn = get_db_connection(autocommit=True); cur = conn.cursor()
    try:
        cur.execute(
            "SELECT host_id, mode, status, tournament_name, player_count, match_format "
            "FROM simulation.rooms WHERE room_id = %s",
            (room_id.upper(),),
        )
        row = cur.fetchone()
        if not row:
            return None
        host_id, mode, status, tournament_name, player_count, match_format = row
        if status not in ("waiting", "drafting", "reordering"):
            return None

        cur.execute(
            "SELECT client_id, display_name, draft_order, squad "
            "FROM simulation.room_members WHERE room_id = %s ORDER BY joined_at",
            (room_id.upper(),),
        )
        members_rows = cur.fetchall()

        room = RS(
            room_id=room_id.upper(),
            host_id=host_id,
            mode=mode,
            tournament_name=tournament_name,
            player_count=player_count,
            match_format=match_format or "T20",
            status=status,
        )
        for cid, dname, draft_order, squad_raw in members_rows:
            squad = squad_raw if isinstance(squad_raw, list) else (_json.loads(squad_raw) if squad_raw else [])
            # batting_order isn't persisted (only squad is) - any manual
            # reorder is lost across a server restart mid-draft, but the
            # already-drafted picks themselves must still show up, so seed
            # it from squad rather than leaving it all-None.
            batting_order = list(squad) + [None] * (SQUAD_SIZE - len(squad))
            room.members[cid] = Member(client_id=cid, display_name=dname, draft_order=draft_order or 0,
                                        squad=squad, batting_order=batting_order)

        if status in ("drafting", "reordering"):
            ordered = sorted(room.members.keys(), key=lambda c: room.members[c].draft_order)
            room.pick_sequence = _snake_sequence(ordered, SQUAD_SIZE)
            room.current_pick_idx = sum(len(m.squad) for m in room.members.values())
            room.drafted_ids = {pid for m in room.members.values() for pid in m.squad}
            cur.execute("SELECT player_id FROM history.players WHERE gender='male' AND player_role='Keeper'")
            room.keeper_ids = {r[0] for r in cur.fetchall()}

        draft_manager._rooms[room_id.upper()] = room
        return room
    finally:
        cur.close(); conn.close()


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


# ── idle-room reaper ───────────────────────────────────────────────────────────

async def _reap_idle_rooms_forever() -> None:
    """Background task (started once from api/main.py's lifespan): cleans up
    'waiting' rooms nobody's touched in ROOM_IDLE_TIMEOUT_S - both rooms that
    were created and never played, and rooms reset to waiting after a
    simulation that nobody returned to. Only 'waiting' rooms are ever
    considered; a room mid-draft/reordering/simulating is never reaped
    regardless of how long that takes."""
    log = get_logger()
    while True:
        await asyncio.sleep(60)
        now = time.time()
        stale_room_ids = [
            room_id for room_id, room in list(draft_manager._rooms.items())
            if room.status == "waiting" and now - room.last_activity > ROOM_IDLE_TIMEOUT_S
        ]
        for room_id in stale_room_ids:
            try:
                _cleanup_room_db(room_id)
            except Exception:
                log.exception("Failed to delete idle room %s from DB", room_id)
            draft_manager.remove_room(room_id)
            log.info("Reaped idle waiting room %s (no activity for over %ds)", room_id, ROOM_IDLE_TIMEOUT_S)


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
        "SELECT COALESCE(display_name, name) AS display_name, player_role, cricinfo_id FROM history.players WHERE player_id=%s",
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
