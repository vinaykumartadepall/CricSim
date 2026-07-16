from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.routes._identity_lookup import display_names_for as _display_names_for
from db.simulation_repository import SimulationRepository
from simulator.admin_settings import get_admin_settings

router = APIRouter(prefix="/cricsimapi/sim-history", tags=["sim-history"])


class NameCountItem(BaseModel):
    name: str
    tournament_ids: List[int]
    total: int
    completed: int


class SeasonCountItem(BaseModel):
    tournament_id: int
    total: int
    completed: int


class TeamBestItem(BaseModel):
    team_name: str
    best_placement: str
    swap_count: int
    sim_id: str


class ChallengeLeaderboardEntry(BaseModel):
    rank: int
    client_id: str
    username: str
    is_you: bool
    best_placement: str
    swap_count: int
    win_pct: float
    sim_id: str


class ChallengeLeaderboardResponse(BaseModel):
    entries: List[ChallengeLeaderboardEntry]
    total_entrants: int


class MyTeamRankItem(BaseModel):
    team_name: str
    rank: int
    total_entrants: int
    best_placement: str
    swap_count: int
    win_pct: float


class LeaderboardsEnabledResponse(BaseModel):
    enabled: bool


@router.get("/counts", response_model=List[NameCountItem] | List[SeasonCountItem])
def sim_history_counts(
    client_id: str = Query(...),
    tournament_ids: Optional[str] = Query(None, description="Comma-separated tournament IDs for season-level counts"),
    mode: Optional[str] = Query(None, description="Filter completed counts by mode (e.g. 'challenge', 'fun')"),
):
    """
    Without tournament_ids → per tournament-name counts (Step 1).
    With    tournament_ids → per tournament-id counts   (Step 2).
    """
    ids: list[int] | None = None
    if tournament_ids:
        try:
            ids = [int(x) for x in tournament_ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=422, detail="tournament_ids must be comma-separated integers")

    repo = SimulationRepository()
    try:
        rows = repo.get_sim_history_counts(client_id, ids, mode)
    finally:
        repo.close()

    if ids is None:
        return [NameCountItem(**r) for r in rows]
    return [SeasonCountItem(**r) for r in rows]


@router.get("/leaderboards-enabled", response_model=LeaderboardsEnabledResponse)
def leaderboards_enabled():
    """
    Public read of the admin kill switch (api/routes/admin.py's
    /admin/leaderboards-enabled) - regular users aren't admins and can't call
    that guarded endpoint, but the frontend still needs to know whether to
    show the Leaderboard button/rank hints at all, not just have the data
    calls fail gracefully after the fact.
    """
    return LeaderboardsEnabledResponse(enabled=get_admin_settings().leaderboards_enabled)


@router.get("/best", response_model=List[TeamBestItem])
def sim_history_best(
    client_id: str = Query(...),
    tournament_id: int = Query(...),
    mode: Optional[str] = Query(None, description="Filter by mode (e.g. 'challenge', 'fun')"),
):
    """Best placement per team for a specific tournament+season."""
    repo = SimulationRepository()
    try:
        rows = repo.get_sim_history_best(client_id, tournament_id, mode)
    finally:
        repo.close()
    return [TeamBestItem(**r) for r in rows]


@router.get("/leaderboard", response_model=ChallengeLeaderboardResponse)
def challenge_leaderboard(
    client_id: str = Query(...),
    tournament_id: int = Query(...),
    team_name: str = Query(...),
    mode: str = Query(..., description="Must match the mode of the viewed result: 'challenge' or 'fun'"),
):
    """Every user's best attempt at this tournament+team combo, same mode only."""
    if not get_admin_settings().leaderboards_enabled:
        raise HTTPException(status_code=503, detail="Leaderboards are temporarily disabled")
    if mode not in ("challenge", "fun"):
        raise HTTPException(status_code=422, detail="mode must be 'challenge' or 'fun'")

    repo = SimulationRepository()
    try:
        rows = repo.get_challenge_leaderboard(client_id, tournament_id, team_name, mode)
    finally:
        repo.close()

    names = _display_names_for({r["client_id"] for r in rows if r.get("client_id")})
    entries = [
        ChallengeLeaderboardEntry(
            rank=r["rank"], client_id=r["client_id"],
            username=names.get(r["client_id"]) or "Anonymous Player",
            is_you=r["is_you"], best_placement=r["best_placement"],
            swap_count=r["swap_count"], win_pct=r["win_pct"], sim_id=str(r["sim_id"]),
        )
        for r in rows
    ]
    return ChallengeLeaderboardResponse(entries=entries, total_entrants=len(entries))


@router.get("/my-ranks", response_model=List[MyTeamRankItem])
def my_challenge_ranks(
    client_id: str = Query(...),
    tournament_id: int = Query(...),
    mode: str = Query(..., description="'challenge' or 'fun'"),
):
    """For every team the caller has attempted in this tournament+mode, their rank in that team's own leaderboard."""
    if not get_admin_settings().leaderboards_enabled:
        raise HTTPException(status_code=503, detail="Leaderboards are temporarily disabled")
    if mode not in ("challenge", "fun"):
        raise HTTPException(status_code=422, detail="mode must be 'challenge' or 'fun'")
    repo = SimulationRepository()
    try:
        rows = repo.get_my_challenge_ranks(client_id, tournament_id, mode)
    finally:
        repo.close()
    return [MyTeamRankItem(**r) for r in rows]
