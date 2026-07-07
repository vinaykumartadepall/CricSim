"""
Points table for a cricket tournament.

Tracks matches played, wins, losses, ties, no-results, points, and NRR.
Updated after every match.

NRR formula lives in MatchRules.net_run_rate/nrr_adjusted_balls (the ICC
all-out rule — a dismissed side is credited its full overs quota, not just
balls actually faced) — record_result() callers must pass in balls that
have already had that adjustment applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from simulator.entities.rules import MatchRules


@dataclass
class TeamRecord:
    name: str
    played: int = 0
    won: int = 0
    lost: int = 0
    tied: int = 0
    no_result: int = 0
    points: int = 0

    # NRR accumulators
    _runs_scored: int = 0
    _balls_faced: int = 0       # NRR-adjusted legal balls (all-out rule applied)
    _runs_conceded: int = 0
    _balls_bowled: int = 0      # NRR-adjusted legal balls (all-out rule applied)

    @property
    def nrr(self) -> float:
        return MatchRules.net_run_rate(
            self._runs_scored, self._balls_faced,
            self._runs_conceded, self._balls_bowled,
        )


class PointsTable:
    """Live points table, updated match by match."""

    WIN_POINTS = 2
    TIE_POINTS = 1
    NR_POINTS  = 1

    def __init__(self, team_names: List[str]):
        self._records: Dict[str, TeamRecord] = {
            name: TeamRecord(name=name) for name in team_names
        }

    def record_result(
        self,
        home: str,
        away: str,
        result: str,           # "home_win" | "away_win" | "tie" | "no_result"
        home_runs: int,
        home_balls: int,       # NRR-adjusted balls faced by home team (see MatchRules.nrr_adjusted_balls)
        away_runs: int,
        away_balls: int,       # NRR-adjusted balls faced by away team
    ) -> None:
        h = self._records[home]
        a = self._records[away]

        h.played += 1
        a.played += 1

        h._runs_scored    += home_runs
        h._balls_faced    += home_balls
        h._runs_conceded  += away_runs
        h._balls_bowled   += away_balls

        a._runs_scored    += away_runs
        a._balls_faced    += away_balls
        a._runs_conceded  += home_runs
        a._balls_bowled   += home_balls

        if result == "home_win":
            h.won    += 1;  h.points += self.WIN_POINTS
            a.lost   += 1
        elif result == "away_win":
            a.won    += 1;  a.points += self.WIN_POINTS
            h.lost   += 1
        elif result == "tie":
            h.tied   += 1;  h.points += self.TIE_POINTS
            a.tied   += 1;  a.points += self.TIE_POINTS
        elif result == "no_result":
            h.no_result += 1;  h.points += self.NR_POINTS
            a.no_result += 1;  a.points += self.NR_POINTS

    def standings(self) -> List[TeamRecord]:
        """Teams ordered by points (desc) then NRR (desc)."""
        return sorted(
            self._records.values(),
            key=lambda r: (r.points, r.nrr, r.won),
            reverse=True,
        )

    def __getitem__(self, team_name: str) -> TeamRecord:
        return self._records[team_name]
