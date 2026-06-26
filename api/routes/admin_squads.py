from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from db.squad_repository import SquadRepository

router = APIRouter(prefix="/admin/squads", tags=["admin-squads"])


# ── Request / response models ─────────────────────────────────────────────────

class PlayerEntry(BaseModel):
    player_id:       int
    batting_position: int


class UpsertSquadRequest(BaseModel):
    players: list[PlayerEntry]

    @field_validator("players")
    @classmethod
    def must_be_eleven(cls, v):
        if len(v) != 11:
            raise ValueError(f"Squad must have exactly 11 players, got {len(v)}")
        return v


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/tournaments")
def list_seeded_tournaments(q: Optional[str] = None):
    repo = SquadRepository()
    try:
        return repo.get_seeded_tournaments(search=q)
    finally:
        repo.close()


@router.get("/tournaments/{tournament_id}")
def get_tournament_squads(tournament_id: int):
    repo = SquadRepository()
    try:
        data = repo.get_squads(tournament_id)
    finally:
        repo.close()
    if not data:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return data


@router.put("/tournaments/{tournament_id}/teams/{team_id}")
def upsert_team_squad(tournament_id: int, team_id: int, body: UpsertSquadRequest):
    repo = SquadRepository()
    try:
        count = repo.upsert_team_squad(
            tournament_id, team_id,
            [p.model_dump() for p in body.players],
        )
    finally:
        repo.close()
    return {"updated": count}


@router.delete("/tournaments/{tournament_id}")
def delete_tournament_squads(tournament_id: int):
    repo = SquadRepository()
    try:
        count = repo.delete_tournament_squads_seeded(tournament_id)
    finally:
        repo.close()
    return {"deleted": count}
