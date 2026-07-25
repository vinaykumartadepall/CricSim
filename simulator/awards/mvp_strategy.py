"""
MVP scoring contract.

An MvpStrategy takes a completed match and decides how much credit each
player earns - how it gets there is entirely up to the strategy. One
implementation (StatisticalAwardsStrategy, see statistical_awards.py) scores
ball-by-ball against a fixed per-format point table; a future strategy could
do something structurally unrelated (e.g. win-probability-added across the
match state trajectory) without touching this contract, MatchAwards, or
anything downstream that consumes the result (persistence, the API, the
frontend) - they only ever read PlayerAward.total (and, best-effort,
.breakdown for display).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from simulator.entities.match import SimulationMatch


@dataclass
class PlayerAward:
    """
    A strategy's verdict for one player in one match.

    total is the score that matters everywhere a player's performance is
    accumulated or compared across matches - TournamentAwards sums it for the
    Player of the Tournament / MVP leaderboard, so it must stay strategy's
    "true" number, with no match-local bonuses baked in.

    match_score is what actually decides Player of the Match for *this one*
    match - it defaults to total (see __post_init__) but a strategy may set
    it independently (e.g. StatisticalAwardsStrategy applies a winning-team
    multiplier here, and only here - see its WINNER_MULTIPLIER). MatchAwards
    ranks/selects POTM by match_score; TournamentAwards never reads it, so a
    match-only bonus can never leak into the tournament-wide total by
    construction, not just by convention.

    breakdown is optional and entirely the strategy's own choice of
    categories - StatisticalAwardsStrategy reports {'batting_pts',
    'bowling_pts', 'fielding_pts'}; a different strategy is free to report
    different keys, or none at all.
    """
    player_id: int
    player_name: str
    team: str = ""
    total: float = 0.0
    breakdown: Dict[str, float] = field(default_factory=dict)
    match_score: Optional[float] = None

    def __post_init__(self) -> None:
        if self.match_score is None:
            self.match_score = self.total


class MvpStrategy(ABC):
    """Resolves a completed match into per-player awards."""

    @abstractmethod
    def compute(self, match: "SimulationMatch") -> List[PlayerAward]:
        ...
