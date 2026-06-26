from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.simulation_repository import SimulationRepository

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
