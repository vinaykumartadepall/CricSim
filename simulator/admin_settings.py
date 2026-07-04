"""
In-memory admin-configurable simulation defaults.

Mirrors the runtime-configurable pattern already used by simulator.logger's
log-level switching (see set_log_level/get_current_log_level): a small piece
of process-level state that api/routes/admin.py exposes over HTTP, and that
the simulation engine consults directly — no restart required to change it.

Not persisted — resets to these hardcoded defaults on every process restart.
The frontend never sends per-request strategy overrides today, so these
defaults are what every real simulation actually uses.
"""
from dataclasses import dataclass

from simulator.strategies.factory import BowlingStrategyFactory, OutcomeStrategyFactory


@dataclass
class AdminSettings:
    default_outcome_strategy: str = "enhanced"
    default_bowling_strategy: str = "historical"


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
