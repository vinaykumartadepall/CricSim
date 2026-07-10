from __future__ import annotations

import os
from typing import Optional

import jwt as pyjwt
from jwt import PyJWKClient
from fastapi import Header, HTTPException

# Module-level singleton - fetches JWKS once, then caches signing keys.
# PyJWKClient automatically re-fetches when it encounters an unknown kid.
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        supabase_url = os.getenv("SUPABASE_URL")
        if not supabase_url:
            raise HTTPException(status_code=503, detail="Authentication service not configured")
        _jwks_client = PyJWKClient(f"{supabase_url}/auth/v1/.well-known/jwks.json")
    return _jwks_client


def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    """
    FastAPI dependency - extracts the Supabase user ID from the JWT.
    Verifies using Supabase's public JWKS endpoint (supports ES256 and RS256).
    Raises 401 if missing/invalid, 503 if SUPABASE_URL not set.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = authorization[7:]
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            options={"verify_aud": False},
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing sub claim")
    return user_id
