"""
simulation.identity_links is the single source of identity for both
anonymous and authenticated users - see db/identity_repository.py. Replaces
the old /cricsimapi/auth profile + link-anonymous routes and the
Supabase-hosted simulation.profiles table.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_current_user_id
from db.identity_repository import IdentityRepository, UsernameTakenError
from simulator.logger import get_logger

router = APIRouter(prefix="/cricsimapi/identity", tags=["identity"])


class SyncAnonymousRequest(BaseModel):
    client_id: str
    username: str = Field(..., min_length=1, max_length=32)


class LinkRequest(BaseModel):
    client_id: str
    fallback_username: str = Field(..., min_length=1, max_length=32)


class SetUsernameRequest(BaseModel):
    client_id: str
    username: str = Field(..., min_length=1, max_length=32)


@router.post("/sync-anonymous", status_code=204)
def sync_anonymous(body: SyncAnonymousRequest):
    """Passive background sync of an anonymous session's current name -
    called on app load. Collisions (astronomically unlikely for an
    auto-generated name) are swallowed by the repo itself, not surfaced."""
    repo = IdentityRepository()
    try:
        repo.sync_anonymous(body.client_id, body.username.strip())
    finally:
        repo.close()


@router.post("/link")
def link(body: LinkRequest, user_id: str = Depends(get_current_user_id)):
    """
    Called once per sign-in. First-ever sign-in for this Google account
    links whichever identity client_id currently resolves to; every sign-in
    after that is a no-op that returns the existing canonical identity -
    it never merges in anonymous activity that happened since the last
    sign-out.
    """
    repo = IdentityRepository()
    try:
        canonical_id = repo.link_account(
            auth_id=user_id,
            current_client_id=body.client_id,
            fallback_username=body.fallback_username.strip(),
        )
        username = repo.get_username(canonical_id)
    except UsernameTakenError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception:
        get_logger().exception("Failed to link identity for auth user %s", user_id)
        repo.rollback()
        raise
    finally:
        repo.close()
    return {"canonical_id": canonical_id, "username": username}


@router.put("/username", status_code=200)
def set_username(body: SetUsernameRequest):
    """Explicit rename, for anonymous and authenticated identities alike -
    client_id is resolved to its canonical identity first either way."""
    repo = IdentityRepository()
    try:
        canonical_id = repo.resolve_client_id(body.client_id)
        username = body.username.strip()
        repo.set_username(canonical_id, username)
    except UsernameTakenError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception:
        get_logger().exception("Failed to set username for client %s", body.client_id)
        repo.rollback()
        raise
    finally:
        repo.close()
    return {"canonical_id": canonical_id, "username": username}
