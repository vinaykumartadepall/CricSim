from __future__ import annotations

import os
from typing import Optional

import jwt as pyjwt
from fastapi import Header, HTTPException


def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    """
    FastAPI dependency — extracts the Supabase user ID from the JWT.
    Raises 401 if missing/invalid, 503 if SUPABASE_JWT_SECRET not set.
    """
    secret = os.getenv("SUPABASE_JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Authentication service not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = authorization[7:]
    try:
        payload = pyjwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing sub claim")
    return user_id
