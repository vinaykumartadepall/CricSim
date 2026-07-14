"""
Read-only admin data views - cross-user queries with no client_id filter.

Every route here is mounted in api/main.py with the require_admin_user guard
(verified Supabase JWT in ADMIN_USER_IDS), which is what makes the unfiltered
queries acceptable. Keep this router strictly read-only: mutations belong on
the regular admin router, and per-user views belong on the public routes.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.models.responses import AdminSimListResponse
from db.player_repository import PlayerRepository
from db.profile_repository import ProfileRepository
from db.simulation_repository import SimulationRepository
from db.squad_repository import SquadRepository
from simulator.logger import get_logger

router = APIRouter(prefix="/admin/data", tags=["admin-data"])


def _run(repo, fn):
    """Run one repository call, mapping validation errors to 422."""
    try:
        return fn()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        repo.close()


def _display_names_for(client_ids: set) -> dict:
    """Profiles live in the separate Supabase DB, so names can't be joined in
    the main list query - fetch them in one batched lookup instead. Best
    effort: the list must still render (ids only) if Supabase is unreachable."""
    if not client_ids:
        return {}
    try:
        repo = ProfileRepository()
        try:
            return repo.get_display_names(list(client_ids))
        finally:
            repo.close()
    except Exception:
        get_logger().exception("Admin data: profile display-name lookup failed")
        return {}


@router.get("/simulations", response_model=AdminSimListResponse)
def list_all_simulations(limit: int = Query(50, le=200), offset: int = Query(0, ge=0)):
    """Every user's simulations, newest first, failed ones included."""
    repo = SimulationRepository()
    try:
        rows = repo.list_simulations(limit=limit, offset=offset, client_id=None, admin_view=True)
    finally:
        repo.close()

    total = rows[0]["total_count"] if rows else 0
    names = _display_names_for({r["client_id"] for r in rows if r.get("client_id")})
    for r in rows:
        r.pop("total_count", None)
        r["display_name"] = names.get(r.get("client_id"))
    return {"simulations": rows, "total": total}


# ── Tournament config editor ────────────────────────────────────────────────────

class TournamentMetaRequest(BaseModel):
    tournament_name: Optional[str] = None
    format: Optional[str] = None
    gender: Optional[str] = None


class TeamMetaRequest(BaseModel):
    name: Optional[str] = None
    short_name: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    # home_venue is nullable on purpose: null clears the home ground
    home_venue: Optional[str] = None
    clear_home_venue: bool = False


class VenueEntry(BaseModel):
    name: str
    city: str = ""
    previous_name: Optional[str] = None  # set when renaming an existing venue


class VenuesRequest(BaseModel):
    venues: list[VenueEntry]


class ScheduleRequest(BaseModel):
    schedule: Optional[dict] = None
    playoffs: Optional[dict] = None


@router.get("/tournaments")
def list_tournaments(q: Optional[str] = None):
    repo = SquadRepository()
    return _run(repo, lambda: repo.get_seeded_tournaments(search=q))


@router.get("/tournaments/{tournament_id}")
def get_tournament_detail(tournament_id: int):
    repo = SquadRepository()
    data = _run(repo, lambda: repo.get_tournament_detail(tournament_id))
    if not data:
        raise HTTPException(status_code=404, detail="Tournament not found or not seeded")
    return data


@router.put("/tournaments/{tournament_id}/meta")
def put_tournament_meta(tournament_id: int, body: TournamentMetaRequest):
    repo = SquadRepository()
    updated = _run(repo, lambda: repo.update_tournament_meta(
        tournament_id, body.model_dump(exclude_none=True)))
    return {"updated": updated}


@router.put("/tournaments/{tournament_id}/teams/{team_id}/meta")
def put_team_meta(tournament_id: int, team_id: int, body: TeamMetaRequest):
    fields = body.model_dump(exclude_none=True, exclude={"clear_home_venue"})
    if body.clear_home_venue:
        fields["home_venue"] = None
    repo = SquadRepository()
    updated = _run(repo, lambda: repo.update_team_meta(tournament_id, team_id, fields))
    return {"updated": updated}


@router.put("/tournaments/{tournament_id}/venues")
def put_venues(tournament_id: int, body: VenuesRequest):
    repo = SquadRepository()
    count = _run(repo, lambda: repo.update_venues(
        tournament_id, [v.model_dump() for v in body.venues]))
    return {"venues": count}


@router.put("/tournaments/{tournament_id}/schedule")
def put_schedule(tournament_id: int, body: ScheduleRequest):
    repo = SquadRepository()
    _run(repo, lambda: repo.update_schedule(tournament_id, body.schedule, body.playoffs))
    return {"updated": True}


# ── Player editor ───────────────────────────────────────────────────────────────

class PlayerUpdateRequest(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    player_role: Optional[str] = None
    batting_style: Optional[str] = None
    bowling_style: Optional[str] = None
    country_id: Optional[int] = None
    cricinfo_id: Optional[int] = None
    gender: Optional[str] = None


@router.get("/players")
def search_players(q: str = "", limit: int = Query(30, le=100)):
    repo = PlayerRepository()
    return _run(repo, lambda: repo.search_players_full(q=q, limit=limit))


@router.put("/players/{player_id}")
def put_player(player_id: int, body: PlayerUpdateRequest):
    repo = PlayerRepository()
    updated = _run(repo, lambda: repo.update_player(
        player_id, body.model_dump(exclude_none=True)))
    return {"updated": updated}


@router.get("/countries")
def list_countries():
    repo = PlayerRepository()
    return _run(repo, lambda: repo.list_countries())
