from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.lov_repository import LovRepository

router = APIRouter(prefix="/cricsimapi/lov", tags=["lov"])


# ── Response models ────────────────────────────────────────────────────────────

class TournamentItem(BaseModel):
    tournament_id: int
    name: str
    season: str
    team_count: int
    gender: Optional[str] = None
    format: Optional[str] = None
    overseas_limit: Optional[int] = None
    home_country_name: Optional[str] = None


class PlayerItem(BaseModel):
    player_id: int
    player_name: str
    player_role: Optional[str] = None
    batting_style: Optional[str] = None
    bowling_style: Optional[str] = None
    batting_position: int
    cricinfo_id: Optional[int] = None
    headshot_url: Optional[str] = None
    country_name: Optional[str] = None


class TeamSquad(BaseModel):
    team_id: int
    team_name: str
    short_name: Optional[str] = None
    players: list[PlayerItem]


class TournamentSquadsResponse(BaseModel):
    tournament_id: int
    teams: list[TeamSquad]


class TeamSeasonUnderdogItem(BaseModel):
    team_id: int
    team_name: str
    tournament_id: int
    season: str
    wins: int
    total_matches: int
    win_pct: float


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/tournaments", response_model=list[TournamentItem])
def list_tournaments(q: Optional[str] = Query(None, description="Search by tournament name")):
    repo = LovRepository()
    try:
        return repo.get_tournaments(search=q)
    finally:
        repo.close()


@router.get("/tournaments/{tournament_id}/squads", response_model=TournamentSquadsResponse)
def tournament_squads(tournament_id: int):
    repo = LovRepository()
    try:
        data = repo.get_tournament_squads(tournament_id)
    finally:
        repo.close()
    if not data:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return data


@router.get("/underdogs", response_model=list[TeamSeasonUnderdogItem])
def tournament_underdogs(tournament_name: str = Query(..., description="Exact tournament name")):
    repo = LovRepository()
    try:
        return repo.get_underdog_team_seasons(tournament_name)
    finally:
        repo.close()
