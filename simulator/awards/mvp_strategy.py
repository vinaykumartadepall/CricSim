"""
MVP scoring contract.

An MvpStrategy takes a completed match and decides how much credit each
player earns — how it gets there is entirely up to the strategy. One
implementation (StatisticalAwardsStrategy, see statistical_awards.py) scores
ball-by-ball against a fixed per-format point table; a future strategy could
do something structurally unrelated (e.g. win-probability-added across the
match state trajectory) without touching this contract, MatchAwards, or
anything downstream that consumes the result (persistence, the API, the
frontend) — they only ever read PlayerAward.total (and, best-effort,
.breakdown for display).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from simulator.entities.match import SimulationMatch


@dataclass
class PlayerAward:
    """
    A strategy's verdict for one player in one match.

    total is the only field every consumer (potm/pott selection, leaderboard
    ranking, persistence) relies on. breakdown is optional and entirely the
    strategy's own choice of categories — StatisticalAwardsStrategy reports
    {'batting_pts', 'bowling_pts', 'fielding_pts'}; a different strategy is
    free to report different keys, or none at all.
    """
    player_id: int
    player_name: str
    team: str = ""
    total: float = 0.0
    breakdown: Dict[str, float] = field(default_factory=dict)


class MvpStrategy(ABC):
    """Resolves a completed match into per-player awards."""

    @abstractmethod
    def compute(self, match: "SimulationMatch") -> List[PlayerAward]:
        ...
