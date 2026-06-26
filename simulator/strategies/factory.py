"""
Strategy factories — separate abstract factory for each model dimension.

Architecture:
  OutcomeStrategyFactory (ABC)
    ├─ HistoricalOutcomeFactory   — historical RMS ball-outcome model
    └─ EnhancedOutcomeFactory     — enhanced RMS ball-outcome model (v2)

  BowlingStrategyFactory (ABC)
    ├─ HistoricalBowlingFactory   — history-based bowling order
    └─ SmartBowlingFactory        — heuristic bowling selection

To add a new strategy:
  1. Subclass the relevant ABC and implement create(fmt).
  2. Call OutcomeStrategyFactory.register("my_name", MyOutcomeFactory)
     or BowlingStrategyFactory.register("my_name", MyBowlingFactory).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import ClassVar, Optional

from db.entities.venue import Venue
from db.stats_repository import StatsRepository
from simulator.entities.player import Player
from simulator.strategies.ball_outcome_prediction.strategy_interface import BallOutcomeStrategy
from simulator.strategies.ball_outcome_prediction.historical_stats.strategy import (
    ODIHistoricalStatsStrategy,
    T20HistoricalStatsStrategy,
    TestHistoricalStatsStrategy,
)
from simulator.strategies.ball_outcome_prediction.enhanced_historical_stats import (
    ODIEnhancedHistoricalStatsStrategy,
    T20EnhancedHistoricalStatsStrategy,
    TestEnhancedHistoricalStatsStrategy,
)
from simulator.strategies.bowling.strategy_interface import BowlingStrategy
from simulator.strategies.bowling.historical import create_historical_bowling_strategy
from simulator.strategies.bowling.smart import SmartBowlingStrategy

log = logging.getLogger(__name__)

# Maps format name → SimulationMatch constructor kwargs.
FORMAT_SETTINGS: dict[str, dict] = {
    "T20":  {"overs_per_innings": 20,   "innings_per_match": 2},
    "ODI":  {"overs_per_innings": 50,   "innings_per_match": 2},
    "Test": {"overs_per_innings": None, "innings_per_match": 4},
}

# ── Per-format outcome class tables ───────────────────────────────────────────

_HISTORICAL_OUTCOME: dict[str, type[BallOutcomeStrategy]] = {
    "T20":  T20HistoricalStatsStrategy,
    "ODI":  ODIHistoricalStatsStrategy,
    "Test": TestHistoricalStatsStrategy,
}

_ENHANCED_OUTCOME: dict[str, type[BallOutcomeStrategy]] = {
    "T20":  T20EnhancedHistoricalStatsStrategy,
    "ODI":  ODIEnhancedHistoricalStatsStrategy,
    "Test": TestEnhancedHistoricalStatsStrategy,
}


# ── Outcome strategy factory ───────────────────────────────────────────────────

class OutcomeStrategyFactory(ABC):
    """
    Abstract factory for ball-outcome strategies.

    Each subclass represents one outcome model family. The class-level registry
    maps config-file names to factory classes so callers need not import any
    concrete strategy class.
    """

    _registry: ClassVar[dict[str, type[OutcomeStrategyFactory]]] = {}

    @abstractmethod
    def create(self, fmt: str) -> BallOutcomeStrategy:
        """Return a freshly constructed BallOutcomeStrategy for the given format."""

    @classmethod
    def for_name(cls, name: str, fmt: str) -> BallOutcomeStrategy:
        """Instantiate the named outcome strategy for the given format."""
        factory_cls = cls._registry.get(name)
        if factory_cls is None:
            raise ValueError(
                f"Unknown outcome strategy {name!r}. "
                f"Registered: {sorted(cls._registry)}"
            )
        return factory_cls().create(fmt)

    @classmethod
    def register(cls, name: str, factory_cls: type[OutcomeStrategyFactory]) -> None:
        cls._registry[name] = factory_cls


class HistoricalOutcomeFactory(OutcomeStrategyFactory):
    """Historical RMS ball-outcome model."""

    def create(self, fmt: str) -> BallOutcomeStrategy:
        return _HISTORICAL_OUTCOME[fmt]()


class EnhancedOutcomeFactory(OutcomeStrategyFactory):
    """Enhanced RMS ball-outcome model (v2)."""

    def create(self, fmt: str) -> BallOutcomeStrategy:
        return _ENHANCED_OUTCOME[fmt]()


OutcomeStrategyFactory.register("historical", HistoricalOutcomeFactory)
OutcomeStrategyFactory.register("enhanced",   EnhancedOutcomeFactory)


# ── Bowling strategy factory ───────────────────────────────────────────────────

class BowlingStrategyFactory(ABC):
    """
    Abstract factory for bowling-selection strategies.

    Each subclass represents one bowling model. Format is passed through so
    format-sensitive models (e.g. historical) can tune themselves.
    """

    _registry: ClassVar[dict[str, type[BowlingStrategyFactory]]] = {}

    @abstractmethod
    def create(self, fmt: str) -> BowlingStrategy:
        """Return a freshly constructed BowlingStrategy for the given format."""

    @classmethod
    def for_name(cls, name: str, fmt: str) -> BowlingStrategy:
        """Instantiate the named bowling strategy for the given format."""
        factory_cls = cls._registry.get(name)
        if factory_cls is None:
            raise ValueError(
                f"Unknown bowling strategy {name!r}. "
                f"Registered: {sorted(cls._registry)}"
            )
        return factory_cls().create(fmt)

    @classmethod
    def register(cls, name: str, factory_cls: type[BowlingStrategyFactory]) -> None:
        cls._registry[name] = factory_cls


class HistoricalBowlingFactory(BowlingStrategyFactory):
    """History-based bowling order."""

    def create(self, fmt: str) -> BowlingStrategy:
        return create_historical_bowling_strategy(fmt)


class SmartBowlingFactory(BowlingStrategyFactory):
    """Heuristic bowling selection."""

    def create(self, fmt: str) -> BowlingStrategy:
        return SmartBowlingStrategy()


BowlingStrategyFactory.register("historical", HistoricalBowlingFactory)
BowlingStrategyFactory.register("smart",      SmartBowlingFactory)


# ── Repository helpers ─────────────────────────────────────────────────────────

def resolve_player(repo: StatsRepository, name: str) -> Player:
    """Look up a player by name; fall back to a hash-based ID if not found."""
    result = repo.get_player_by_name(name)
    if result:
        return Player(id=result[0], name=result[1])
    log.warning("Player '%s' not found in DB — using hash-based fallback ID", name)
    return Player(id=abs(hash(name)) % 10_000, name=name)


def resolve_player_by_id(repo: StatsRepository, player_id: int) -> Player:
    """Look up a player by their history.players ID. ID is authoritative — no fallback."""
    result = repo.get_player_by_id(player_id)
    if result:
        return Player(id=result[0], name=result[1])
    log.warning("Player id=%d not found in DB — creating nameless placeholder", player_id)
    return Player(id=player_id, name=f"Player#{player_id}")


def resolve_venue(repo: StatsRepository, name: str | None) -> Optional[Venue]:
    """Look up a venue by name; return None if missing or not provided."""
    if not name:
        return None
    result = repo.get_venue_by_name(name)
    if result:
        venue_id, venue_name, country = result
        return Venue.builder().with_id(venue_id).with_name(venue_name).with_country(country).build()
    log.warning("Venue '%s' not found in DB — proceeding without venue context", name)
    return None
