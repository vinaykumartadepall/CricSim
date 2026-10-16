"""
simulation.identity_links is the single source of identity for both
anonymous and authenticated users - see db/identity_repository.py. Replaces
the old /cricsimapi/auth profile + link-anonymous routes and the
Supabase-hosted simulation.profiles table.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from api.deps import audit_user
from api.identity_auth import CLIENT_ID_HEADER, SECRET_HEADER, IdentityError, require_identity, verify_browser_credential
from db.identity_repository import IdentityRepository, UsernameTakenError
from simulator.logger import get_logger

router = APIRouter(prefix="/cricsimapi/identity", tags=["identity"])


class SyncAnonymousRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)


class LinkRequest(BaseModel):
    fallback_username: str = Field(..., min_length=1, max_length=32)


class SetUsernameRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)


@router.post("/sync-anonymous", status_code=204)
def sync_anonymous(body: SyncAnonymousRequest, client_id: str = Depends(require_identity)):
    """Passive background sync of an anonymous session's current name -
    called on app load. Collisions (astronomically unlikely for an
    auto-generated name) are swallowed by the repo itself, not surfaced."""
    repo = IdentityRepository()
    try:
        repo.sync_anonymous(client_id, body.username.strip())
    finally:
        repo.close()


@router.post("/link")
def link(
    body: LinkRequest,
    user_id: str = Depends(audit_user),
    x_client_id: Optional[str] = Header(None, alias=CLIENT_ID_HEADER),
    x_client_secret: Optional[str] = Header(None, alias=SECRET_HEADER),
):
    """
    Called once per sign-in. First-ever sign-in for this Google account
    links the browser's current anonymous identity; every sign-in after that
    is a no-op that returns the existing canonical identity - it never merges
    in anonymous activity that happened since the last sign-out.

    Linking hands that anonymous identity's whole history to the account, so
    on a first sign-in the browser must prove it owns it (its credential
    headers) - a client_id alone could be someone else's. Returning sign-ins
    skip the check: link_account ignores the browser identity for them.
    """
    repo = IdentityRepository()
    try:
        current_client_id = user_id
        if not repo.is_auth_linked(user_id) and (x_client_id or x_client_secret):
            try:
                current_client_id = verify_browser_credential(x_client_id or "", x_client_secret or "")
            except IdentityError as e:
                if e.code != "identity_linked":
                    raise
                # This browser's anonymous identity already belongs to another
                # account (e.g. that account's session expired here). Never
                # hand it to this one - start this account on its own identity.
        canonical_id = repo.link_account(
            auth_id=user_id,
            current_client_id=current_client_id,
            fallback_username=body.fallback_username.strip(),
        )
        username = repo.get_username(canonical_id)
    except UsernameTakenError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise   # a rejected browser credential - already logged by the check
    except Exception:
        get_logger().exception("Failed to link identity for auth user %s", user_id)
        repo.rollback()
        raise
    finally:
        repo.close()
    return {"canonical_id": canonical_id, "username": username}


@router.put("/username", status_code=200)
def set_username(body: SetUsernameRequest, canonical_id: str = Depends(require_identity)):
    """Explicit rename, for anonymous and authenticated identities alike - of
    the caller's own verified identity only."""
    repo = IdentityRepository()
    try:
        username = body.username.strip()
        repo.set_username(canonical_id, username)
    except UsernameTakenError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception:
        get_logger().exception("Failed to set username for %s", canonical_id)
        repo.rollback()
        raise
    finally:
        repo.close()
    return {"canonical_id": canonical_id, "username": username}
