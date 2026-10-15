"""
Domain vocabularies - the one definition of every fixed set of string values
the simulator, API, database and frontend share.

StrEnum, so members ARE their string values: MatchFormat.T20 == "T20",
str()/f-strings/json.dumps/psycopg2 all give the bare value, and existing
code that compares or keys on plain strings keeps working unchanged.

Consumers that must agree with these lists:
  - db/schema.sql CHECK constraints (tests/test_enums.py checks they match)
  - frontend/src/types/enums.ts (generated: `python -m enums.ts_export`)
"""
from __future__ import annotations

from enum import StrEnum


class _Vocab(StrEnum):
    @classmethod
    def values(cls) -> list[str]:
        """Plain-string values in definition order (for SQL params, messages)."""
        return [m.value for m in cls]


class RawMatchFormat(_Vocab):
    """Cricsheet's match_type labels, as stored in history.matches.match_format.
    Only ingestion and history queries see these; everything else uses MatchFormat."""
    TEST = "Test"
    MDM = "MDM"      # multi-day: first-class domestic, ICC Intercontinental Cup/Shield
    ODI = "ODI"
    ODM = "ODM"      # one-day without ODI status: List A domestic, other internationals
    T20 = "T20"      # T20Is and franchise/domestic T20s
    IT20 = "IT20"    # internationals without T20I status (Asian Games, qualifiers, ...)


class MatchFormat(_Vocab):
    """The three formats the simulator plays."""
    T20 = "T20"
    ODI = "ODI"
    TEST = "Test"

    @classmethod
    def from_raw(cls, raw: str) -> "MatchFormat":
        """The single raw → simulated format mapping. Accepts any RawMatchFormat
        value (which includes the three simulated ones). Raises ValueError on
        anything else."""
        return _RAW_TO_FORMAT[RawMatchFormat((raw or "").strip())]

    def raw_values(self) -> list[str]:
        """Every raw history.matches.match_format value that plays as this
        format - for `m.match_format = ANY(%s)` filters."""
        return [r.value for r, f in _RAW_TO_FORMAT.items() if f is self]


_RAW_TO_FORMAT: dict[RawMatchFormat, MatchFormat] = {
    RawMatchFormat.TEST: MatchFormat.TEST,
    RawMatchFormat.MDM:  MatchFormat.TEST,
    RawMatchFormat.ODI:  MatchFormat.ODI,
    RawMatchFormat.ODM:  MatchFormat.ODI,
    RawMatchFormat.T20:  MatchFormat.T20,
    RawMatchFormat.IT20: MatchFormat.T20,
}


# {"T20": ["T20", "IT20"], ...} - the SQL-filter direction of _RAW_TO_FORMAT.
RAW_VALUES_BY_FORMAT: dict[str, list[str]] = {f.value: f.raw_values() for f in MatchFormat}


class MatchLevel(_Vocab):
    """history.matches.match_type: the level of cricket, independent of format
    (an IPL game and a T20I are both T20)."""
    INTERNATIONAL = "international"
    CLUB = "club"


class Gender(_Vocab):
    MALE = "male"
    FEMALE = "female"


class SimulationType(_Vocab):
    MATCH = "match"
    TOURNAMENT = "tournament"


class SimStatus(_Vocab):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class GameMode(_Vocab):
    """How a simulation was started (simulations.mode / game_sessions.mode)."""
    FUN = "fun"
    CHALLENGE = "challenge"
    CUSTOM = "custom"
    MULTIPLAYER = "multiplayer"


class MatchResult(_Vocab):
    """simulation.matches.result."""
    WIN = "win"
    TIE = "tie"
    NO_RESULT = "no result"


# Exported to the frontend by enums/ts_export.py, in this order.
TS_EXPORTED = (
    MatchFormat, RawMatchFormat, MatchLevel, Gender,
    SimulationType, SimStatus, GameMode, MatchResult,
)
