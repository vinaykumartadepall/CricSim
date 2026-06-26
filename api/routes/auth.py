from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_current_user_id
from db.simulation_repository import SimulationRepository

router = APIRouter(prefix="/auth", tags=["auth"])


class ProfileUpsertRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=32)


class LinkAnonymousRequest(BaseModel):
    anonymous_id: str


@router.get("/profile")
def get_profile(user_id: str = Depends(get_current_user_id)):
    repo = SimulationRepository()
    try:
        profile = repo.get_profile(user_id)
    finally:
        repo.close()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.post("/profile", status_code=200)
def upsert_profile(
    body: ProfileUpsertRequest,
    user_id: str = Depends(get_current_user_id),
):
    repo = SimulationRepository()
    try:
        profile = repo.upsert_profile(user_id, body.display_name.strip())
        repo.commit()
    except Exception:
        repo.rollback()
        raise
    finally:
        repo.close()
    return profile


@router.post("/link-anonymous", status_code=200)
def link_anonymous(
    body: LinkAnonymousRequest,
    user_id: str = Depends(get_current_user_id),
):
    if not body.anonymous_id or body.anonymous_id == user_id:
        return {"migrated": 0}

    repo = SimulationRepository()
    try:
        migrated = repo.link_anonymous(user_id, body.anonymous_id)
        repo.commit()
    except Exception:
        repo.rollback()
        raise
    finally:
        repo.close()
    return {"migrated": migrated}
