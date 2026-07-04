"""
In-memory admin-configurable simulation defaults.

Mirrors the runtime-configurable pattern already used by simulator.logger's
log-level switching (see set_log_level/get_current_log_level): a small piece
of process-level state that api/routes/admin.py exposes over HTTP, and that
the simulation engine consults directly — no restart required to change it.

Not persisted across a change made via the admin API — but the *startup*
values can be set via DEFAULT_OUTCOME_STRATEGY / DEFAULT_BOWLING_STRATEGY env
vars (same pattern as STATS_CACHE_STRATEGY in db/stats_repository.py), so a
restart/redeploy comes back up with whatever was configured rather than
always resetting to the hardcoded 'enhanced' / 'historical' fallback.

The frontend never sends per-request strategy overrides today, so these
defaults are what every real simulation actually uses.
"""
import os
from dataclasses import dataclass, field

from simulator.strategies.factory import BowlingStrategyFactory, OutcomeStrategyFactory


def _env_default(env_var: str, valid_names: list, fallback: str) -> str:
    value = os.getenv(env_var)
    if value and value in valid_names:
        return value
    return fallback


@dataclass
class AdminSettings:
    default_outcome_strategy: str = field(default_factory=lambda: _env_default(
        "DEFAULT_OUTCOME_STRATEGY", OutcomeStrategyFactory.available_names(), "enhanced"
    ))
    default_bowling_strategy: str = field(default_factory=lambda: _env_default(
        "DEFAULT_BOWLING_STRATEGY", BowlingStrategyFactory.available_names(), "historical"
    ))


_settings = AdminSettings()


def get_admin_settings() -> AdminSettings:
    return _settings


def set_default_outcome_strategy(name: str) -> None:
    valid = OutcomeStrategyFactory.available_names()
    if name not in valid:
        raise ValueError(f"Unknown outcome strategy {name!r}. Choose from {valid}.")
    _settings.default_outcome_strategy = name


def set_default_bowling_strategy(name: str) -> None:
    valid = BowlingStrategyFactory.available_names()
    if name not in valid:
        raise ValueError(f"Unknown bowling strategy {name!r}. Choose from {valid}.")
    _settings.default_bowling_strategy = name
