"""
Who is making this request - verified, never just claimed.

Two ways to prove identity:

- Signed-in users send their Supabase JWT (`Authorization: Bearer ...`). It is
  verified (api/deps.py::get_current_user_id) and resolved to the account's
  canonical identity (simulation.identity_links).
- Everyone else sends their browser credential: `X-Client-Id` (the client_id
  the browser has always used) plus `X-Client-Secret`, a random secret the
  browser generated itself (frontend/src/api/clientId.ts). The first request
  for a client_id records a hash of its secret in simulation.client_credentials;
  every later request for that id must present the same secret. The record is
  write-once - a database trigger refuses to replace it (migration 038).

A client_id on its own (query string, request body) is never trusted any more:
it is shown to other users in places, so knowing it must not be enough to act
as someone. Anonymous credentials are refused for identities linked to an
account - those need the account's JWT.

The room WebSocket can't send headers, so it passes the same values in its
first message and uses identity_from_credentials directly.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from typing import NamedTuple, Optional

from fastapi import Depends, Header, HTTPException

from api.deps import get_current_user_id
from db.database import bind_actor, db_actor, db_cursor
from simulator.logger import get_logger

CLIENT_ID_HEADER = "X-Client-Id"
SECRET_HEADER = "X-Client-Secret"
ERROR_HEADER = "X-Identity-Error"     # machine-readable reason, for the frontend

_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")

REFRESH_MESSAGE = "This page is out of date - please refresh it."


class Identity(NamedTuple):
    id: str      # canonical identity: what every simulation.* row is keyed by
    actor: str   # audit label: user:<supabase id> or client:<client_id>


class IdentityError(HTTPException):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(status_code=status, detail=message, headers={ERROR_HEADER: code})
        self.code = code


def _secret_hash(secret: str) -> str:
    # The secret is 256 random bits, so a plain hash is enough (no password
    # stretching needed); only the hash is stored.
    return hashlib.sha256(secret.encode()).hexdigest()


def verify_browser_credential(client_id: str, secret: str) -> str:
    """client_id if the secret proves it, raising IdentityError otherwise.
    The first call for an unrecorded client_id records its secret."""
    if not (client_id and _CLIENT_ID_RE.match(client_id) and secret and _SECRET_RE.match(secret)):
        raise IdentityError(401, "invalid_credential", REFRESH_MESSAGE)
    secret_hash = _secret_hash(secret)
    with db_actor(f"client:{client_id}"), db_cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (SELECT 1 FROM simulation.identity_links
                           WHERE linked_auth_id IS NOT NULL
                             AND (id = %(cid)s OR linked_auth_id = %(cid)s)),
                   (SELECT secret_hash FROM simulation.client_credentials WHERE client_id = %(cid)s)
            """,
            {"cid": client_id},
        )
        linked, stored = cur.fetchone()
        if linked:
            raise IdentityError(403, "identity_linked",
                                "This identity belongs to a signed-in account - please sign in.")
        if stored is None:
            # First use: record it. ON CONFLICT covers two first requests
            # racing each other - exactly one insert wins, and the loser falls
            # through to the comparison below like any later request.
            cur.execute(
                "INSERT INTO simulation.client_credentials (client_id, secret_hash) VALUES (%s, %s) "
                "ON CONFLICT (client_id) DO NOTHING RETURNING client_id",
                (client_id, secret_hash),
            )
            if cur.fetchone():
                get_logger().info("Recorded browser credential for client %s", client_id)
                return client_id
            cur.execute("SELECT secret_hash FROM simulation.client_credentials WHERE client_id = %s",
                        (client_id,))
            stored = cur.fetchone()[0]
    if not hmac.compare_digest(stored, secret_hash):
        get_logger().warning("Rejected mismatched credential for client %s", client_id)
        raise IdentityError(401, "credential_mismatch",
                            "This browser's identity could not be verified - please refresh the page.")
    return client_id


def account_identity(auth_user_id: str) -> str:
    """The canonical identity a signed-in account resolves to: the identity it
    was linked to at first sign-in, or the account id itself before that."""
    with db_cursor() as cur:
        cur.execute("SELECT id FROM simulation.identity_links WHERE linked_auth_id = %s", (auth_user_id,))
        row = cur.fetchone()
    return row[0] if row else auth_user_id


def identity_from_credentials(
    authorization: Optional[str], client_id: Optional[str], secret: Optional[str],
) -> Optional[Identity]:
    """The verified identity behind a request, None if it carries no
    credentials at all. A JWT, when present, wins over browser credentials."""
    if authorization:
        user_id = get_current_user_id(authorization)
        return Identity(account_identity(user_id), f"user:{user_id}")
    if client_id or secret:
        return Identity(verify_browser_credential(client_id or "", secret or ""), f"client:{client_id}")
    return None


def _request_identity(
    authorization: Optional[str] = Header(None),
    x_client_id: Optional[str] = Header(None, alias=CLIENT_ID_HEADER),
    x_client_secret: Optional[str] = Header(None, alias=SECRET_HEADER),
) -> Optional[Identity]:
    # Sync on purpose: the DB lookup runs in FastAPI's threadpool, off the event loop.
    return identity_from_credentials(authorization, x_client_id, x_client_secret)


# Async wrappers, like api/deps.py::audit_user: an async dependency binds the
# audit actor in the request's own context, so the endpoint's DB writes see it.
async def optional_identity(ident: Optional[Identity] = Depends(_request_identity)) -> Optional[str]:
    """Verified canonical identity, or None for a request with no credentials
    (pages anyone can view, like a shared scorecard). Bad credentials still fail."""
    if ident is None:
        return None
    bind_actor(ident.actor)
    return ident.id


async def require_identity(ident: Optional[Identity] = Depends(_request_identity)) -> str:
    """Verified canonical identity; 401 when the request carries no credentials."""
    if ident is None:
        raise IdentityError(401, "missing_credential", REFRESH_MESSAGE)
    bind_actor(ident.actor)
    return ident.id
