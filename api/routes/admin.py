"""Admin endpoints for server-side operational controls."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from simulator.logger import get_current_log_level, set_log_level

router = APIRouter(prefix="/admin", tags=["admin"])

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


class LogLevelRequest(BaseModel):
    level: str


class LogLevelResponse(BaseModel):
    level: str


@router.get("/log-level", response_model=LogLevelResponse)
def get_log_level():
    """Return the current simulation.log level."""
    return LogLevelResponse(level=get_current_log_level())


@router.put("/log-level", response_model=LogLevelResponse)
def put_log_level(body: LogLevelRequest):
    """
    Change the minimum level written to simulation.log at runtime.
    errors.log is always fixed at WARNING and is unaffected.

    Valid levels: DEBUG | INFO | WARNING | ERROR
    """
    level = body.level.upper()
    if level not in _VALID_LEVELS:
        raise HTTPException(status_code=422, detail=f"Invalid level {level!r}. Choose from {sorted(_VALID_LEVELS)}.")
    set_log_level(level)
    return LogLevelResponse(level=level)
