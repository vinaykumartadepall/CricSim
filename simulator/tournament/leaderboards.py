"""
Tournament aggregate leaderboards.

Computed from cumulative batter/bowler stats across all match innings.
All stats are computed from SimulationMatch objects collected by TournamentEngine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

# Qualification floors for rate-stat leaderboards. Single source of truth:
# db/leaderboard_repository.py builds its SQL WHERE clauses from these same
# constants, so the CLI boards and the product API can never disagree.
MIN_RUNS_FOR_BATTING_RATE_BOARDS = 50   # best batting average / best strike rate
MIN_BALLS_FOR_BOWLING_RATE_BOARDS = 30  # best bowling average / best economy


@dataclass
class BatterStats:
    player_id: int
    player_name: str
    team: str
    matches: int = 0
    innings: int = 0
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    not_outs: int = 0
    highest_score: int = 0
    highest_score_not_out: bool = False

    @property
    def average(self) -> float:
        denom = self.innings - self.not_outs
        return self.runs / denom if denom > 0 else float('inf')

    @property
    def strike_rate(self) -> float:
        return (self.runs / self.balls * 100) if self.balls else 0.0

    @property
    def average_display(self) -> str:
        a = self.average
        return f"{a:.2f}" if a != float('inf') else "∞"


@dataclass
class BowlerStats:
    player_id: int
    player_name: str
    team: str
    matches: int = 0
    innings: int = 0
    overs: float = 0.0        # e.g. 9.4 = 9 overs 4 balls
    balls: int = 0
    runs: int = 0
    wickets: int = 0
    maidens: int = 0
    best_wickets: int = 0
    best_runs: int = 0

    @property
    def average(self) -> float:
        return self.runs / self.wickets if self.wickets else float('inf')

    @property
    def economy(self) -> float:
        return (self.runs / self.balls * 6) if self.balls else 0.0

    @property
    def strike_rate(self) -> float:
        return (self.balls / self.wickets) if self.wickets else float('inf')

    @property
    def best_figures(self) -> str:
        return f"{self.best_wickets}/{self.best_runs}"


class TournamentLeaderboards:
    """
    Collects per-player batting and bowling stats across the tournament.
    Populated by calling add_match() after each match completes.
    """

    def __init__(self):
        self._batting:  Dict[int, BatterStats] = {}
        self._bowling:  Dict[int, BowlerStats] = {}
        self._player_team: Dict[int, str] = {}

    def add_match(self, match, home_team_name: str, away_team_name: str) -> None:
        """Extract stats from a completed SimulationMatch and accumulate them."""
        # Map player IDs to their team name
        for p in match.home_team.players:
            self._player_team[p.id] = home_team_name
        for p in match.away_team.players:
            self._player_team[p.id] = away_team_name

        for inning in match.innings:
            if not inning.batting_team or not inning.bowling_team:
                continue

            for ip in inning.batting_team.inning_players:
                if ip.balls_faced == 0 and ip.runs_scored == 0:
                    continue
                stats = self._bat(ip.id, ip.name, self._player_team.get(ip.id, ""))
                stats.innings += 1
                stats.runs    += ip.runs_scored
                stats.balls   += ip.balls_faced
                stats.fours   += ip.fours
                stats.sixes   += ip.sixes
                if not ip.is_out:
                    stats.not_outs += 1
                if ip.runs_scored > stats.highest_score:
                    stats.highest_score = ip.runs_scored
                    stats.highest_score_not_out = not ip.is_out

            for ip in inning.bowling_team.inning_players:
                if ip.balls_bowled == 0:
                    continue
                stats = self._bowl(ip.id, ip.name, self._player_team.get(ip.id, ""))
                stats.innings += 1
                stats.balls   += ip.balls_bowled
                stats.runs    += ip.runs_conceded
                stats.wickets += ip.wickets_taken
                stats.maidens += ip.maidens
                stats.overs = stats.balls // 6 + (stats.balls % 6) / 10.0
                # Track best bowling
                if (ip.wickets_taken > stats.best_wickets or
                        (ip.wickets_taken == stats.best_wickets and
                         ip.runs_conceded < stats.best_runs)):
                    stats.best_wickets = ip.wickets_taken
                    stats.best_runs    = ip.runs_conceded

        # Count matches per player
        seen_players = set()
        for p in match.home_team.players:
            if p.id not in seen_players:
                seen_players.add(p.id)
                if p.id in self._batting:  self._batting[p.id].matches += 1
                if p.id in self._bowling:  self._bowling[p.id].matches += 1
        for p in match.away_team.players:
            if p.id not in seen_players:
                seen_players.add(p.id)
                if p.id in self._batting:  self._batting[p.id].matches += 1
                if p.id in self._bowling:  self._bowling[p.id].matches += 1

    # ── Leaderboard queries ───────────────────────────────────────────────────

    def most_runs(self, top_n: int = 10) -> List[BatterStats]:
        return sorted(self._batting.values(), key=lambda s: s.runs, reverse=True)[:top_n]

    def highest_score(self, top_n: int = 10) -> List[BatterStats]:
        return sorted(self._batting.values(),
                       key=lambda s: s.highest_score, reverse=True)[:top_n]

    def best_batting_average(self, min_runs: int = MIN_RUNS_FOR_BATTING_RATE_BOARDS,
                             top_n: int = 10) -> List[BatterStats]:
        eligible = [s for s in self._batting.values() if s.runs >= min_runs]
        return sorted(eligible, key=lambda s: s.average, reverse=True)[:top_n]

    def best_strike_rate(self, min_runs: int = MIN_RUNS_FOR_BATTING_RATE_BOARDS,
                         top_n: int = 10) -> List[BatterStats]:
        eligible = [s for s in self._batting.values() if s.runs >= min_runs]
        return sorted(eligible, key=lambda s: s.strike_rate, reverse=True)[:top_n]

    def most_sixes(self, top_n: int = 10) -> List[BatterStats]:
        return sorted(self._batting.values(), key=lambda s: s.sixes, reverse=True)[:top_n]

    def most_fours(self, top_n: int = 10) -> List[BatterStats]:
        return sorted(self._batting.values(), key=lambda s: s.fours, reverse=True)[:top_n]

    def most_wickets(self, top_n: int = 10) -> List[BowlerStats]:
        return sorted(self._bowling.values(), key=lambda s: s.wickets, reverse=True)[:top_n]

    def best_bowling_average(self, min_balls: int = MIN_BALLS_FOR_BOWLING_RATE_BOARDS,
                             top_n: int = 10) -> List[BowlerStats]:
        eligible = [s for s in self._bowling.values() if s.balls >= min_balls]
        return sorted(eligible, key=lambda s: s.average)[:top_n]

    def best_economy(self, min_balls: int = MIN_BALLS_FOR_BOWLING_RATE_BOARDS,
                     top_n: int = 10) -> List[BowlerStats]:
        eligible = [s for s in self._bowling.values() if s.balls >= min_balls]
        return sorted(eligible, key=lambda s: s.economy)[:top_n]

    def best_bowling_sr(self, min_wickets: int = 5, top_n: int = 10) -> List[BowlerStats]:
        eligible = [s for s in self._bowling.values() if s.wickets >= min_wickets]
        return sorted(eligible, key=lambda s: s.strike_rate)[:top_n]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _bat(self, pid: int, name: str, team: str) -> BatterStats:
        if pid not in self._batting:
            self._batting[pid] = BatterStats(pid, name, team)
        return self._batting[pid]

    def _bowl(self, pid: int, name: str, team: str) -> BowlerStats:
        if pid not in self._bowling:
            self._bowling[pid] = BowlerStats(pid, name, team)
        return self._bowling[pid]
