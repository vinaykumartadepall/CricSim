"""
Match/tournament awards orchestration — strategy-agnostic.

MatchAwards delegates all actual scoring to an injected MvpStrategy (see
mvp_strategy.py); it just runs the strategy once per match and exposes the
result (who's POTM, everyone ranked). TournamentAwards accumulates those
results across a tournament's matches for POTT, by summing .total and
merging .breakdown dicts generically — it never assumes any particular set
of category names, so it works unchanged for any MvpStrategy.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from simulator.awards.mvp_strategy import MvpStrategy, PlayerAward
from simulator.awards.statistical_awards import DEFAULT_MVP_STRATEGY


class MatchAwards:
    """
    Resolves a single match's awards via an MvpStrategy (defaults to
    StatisticalAwardsStrategy). Call record_from_match() once after the
    match completes, then potm()/all_sorted() for the result.
    """

    def __init__(self, strategy: MvpStrategy = DEFAULT_MVP_STRATEGY):
        self._strategy = strategy
        self._results: Dict[int, PlayerAward] = {}

    def record_from_match(self, match) -> None:
        self._results = {a.player_id: a for a in self._strategy.compute(match)}

    def potm(self) -> Optional[PlayerAward]:
        """Return the player with the highest total, or None if empty."""
        if not self._results:
            return None
        return max(self._results.values(), key=lambda a: a.total)

    def all_sorted(self) -> List[PlayerAward]:
        return sorted(self._results.values(), key=lambda a: a.total, reverse=True)


class TournamentAwards:
    """Accumulates a tournament's per-match awards for POTT calculation."""

    def __init__(self):
        self._totals: Dict[int, PlayerAward] = {}

    def add_match(self, awards: MatchAwards) -> None:
        for pid, award in awards._results.items():
            if pid not in self._totals:
                self._totals[pid] = PlayerAward(pid, award.player_name, team=award.team)
            t = self._totals[pid]
            if not t.team and award.team:
                t.team = award.team
            t.total += award.total
            for key, value in award.breakdown.items():
                t.breakdown[key] = t.breakdown.get(key, 0.0) + value

    def pott(self) -> Optional[PlayerAward]:
        if not self._totals:
            return None
        return max(self._totals.values(), key=lambda a: a.total)

    def leaderboard(self, top_n: int = 10) -> List[PlayerAward]:
        return sorted(self._totals.values(), key=lambda a: a.total, reverse=True)[:top_n]
