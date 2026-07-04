"""Admin endpoints for server-side operational controls."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.stats_repository import StatsRepository
from simulator.admin_settings import (
    get_admin_settings,
    set_default_bowling_strategy,
    set_default_outcome_strategy,
)
from simulator.logger import get_current_log_level, set_log_level
from simulator.strategies.factory import BowlingStrategyFactory, OutcomeStrategyFactory

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


class CacheStrategyRequest(BaseModel):
    strategy: str


class CacheStrategyResponse(BaseModel):
    strategy: str
    available: List[str]


@router.get("/cache-strategy", response_model=CacheStrategyResponse)
def get_cache_strategy():
    """Return the active _PRECOMPUTED_CACHE retention strategy."""
    return CacheStrategyResponse(
        strategy=StatsRepository.get_cache_strategy_name(),
        available=StatsRepository.available_cache_strategies(),
    )


@router.put("/cache-strategy", response_model=CacheStrategyResponse)
def put_cache_strategy(body: CacheStrategyRequest):
    """
    Hot-swap the cache retention strategy at runtime — no restart required.
    Switching always starts the new strategy empty (existing entries are dropped).

    - persistent: entries live for the process lifetime (default).
    - per_job:    entries are cleared at the end of every simulation job.
    """
    try:
        StatsRepository.set_cache_strategy(body.strategy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return CacheStrategyResponse(
        strategy=StatsRepository.get_cache_strategy_name(),
        available=StatsRepository.available_cache_strategies(),
    )


class SimulationDefaultsRequest(BaseModel):
    outcome_strategy: Optional[str] = None
    bowling_strategy: Optional[str] = None


class SimulationDefaultsResponse(BaseModel):
    outcome_strategy: str
    bowling_strategy: str
    available_outcome_strategies: List[str]
    available_bowling_strategies: List[str]


def _simulation_defaults_response() -> SimulationDefaultsResponse:
    s = get_admin_settings()
    return SimulationDefaultsResponse(
        outcome_strategy=s.default_outcome_strategy,
        bowling_strategy=s.default_bowling_strategy,
        available_outcome_strategies=OutcomeStrategyFactory.available_names(),
        available_bowling_strategies=BowlingStrategyFactory.available_names(),
    )


@router.get("/simulation-defaults", response_model=SimulationDefaultsResponse)
def get_simulation_defaults():
    """
    Return the current default outcome/bowling strategy used whenever a
    simulation request doesn't explicitly override them (the frontend never
    does today, so these are effectively what every real simulation uses).
    """
    return _simulation_defaults_response()


@router.put("/simulation-defaults", response_model=SimulationDefaultsResponse)
def put_simulation_defaults(body: SimulationDefaultsRequest):
    """Change the default outcome and/or bowling strategy. Only fields provided are updated."""
    try:
        if body.outcome_strategy is not None:
            set_default_outcome_strategy(body.outcome_strategy)
        if body.bowling_strategy is not None:
            set_default_bowling_strategy(body.bowling_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _simulation_defaults_response()


class AdminSettingsResponse(BaseModel):
    log_level: str
    cache_strategy: str
    available_cache_strategies: List[str]
    outcome_strategy: str
    bowling_strategy: str
    available_outcome_strategies: List[str]
    available_bowling_strategies: List[str]


@router.get("/settings", response_model=AdminSettingsResponse)
def get_all_settings():
    """Consolidated snapshot of every admin-configurable setting, for a single page load."""
    s = get_admin_settings()
    return AdminSettingsResponse(
        log_level=get_current_log_level(),
        cache_strategy=StatsRepository.get_cache_strategy_name(),
        available_cache_strategies=StatsRepository.available_cache_strategies(),
        outcome_strategy=s.default_outcome_strategy,
        bowling_strategy=s.default_bowling_strategy,
        available_outcome_strategies=OutcomeStrategyFactory.available_names(),
        available_bowling_strategies=BowlingStrategyFactory.available_names(),
    )
