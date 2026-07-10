"""
Player-of-the-Match and Player-of-the-Tournament scoring.

Points are accumulated delivery-by-delivery during a match and summed at the
end to determine POTM. Across all matches, POTT is the player with the
highest cumulative POTM score - TournamentAwards just sums each match's
already-computed points, it never recomputes anything.

The actual point values are format-specific and live in a swappable
PointsStrategy (simulator/tournament/points_strategies.py) - MatchAwards
resolves the rules for a match's format once and hands them to every
PlayerMatchPoints it creates. Neither this module nor its callers hardcode
any point value; to change the scoring rubric, write a new PointsStrategy
subclass and pass it to MatchAwards(points_strategy=...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from enums.constants import DismissalType, ExtraType
from simulator.entities.rules import MatchRules
from simulator.tournament.points_strategies import (
    DEFAULT_POINTS_STRATEGY,
    MvpPointsRules,
    PointsStrategy,
)

_FALLBACK_RULES = DEFAULT_POINTS_STRATEGY.rules_for('T20')


@dataclass
class PlayerMatchPoints:
    player_id: int
    player_name: str
    team: str = ""
    rules: MvpPointsRules = field(default=_FALLBACK_RULES)

    batting_pts: float = 0.0
    bowling_pts: float = 0.0
    fielding_pts: float = 0.0

    # Per-innings batting state - resets whenever this player starts a new
    # innings as a batter, since batting milestones are an innings
    # achievement (a century is scored in an innings, not accumulated
    # across a Test match's two innings).
    _batting_inning: Optional[int] = None
    _innings_runs: int = 0
    _batting_milestones_awarded: Set[int] = field(default_factory=set)

    # Per-innings bowling-haul state - a "5-wicket haul" is likewise scoped
    # to one innings, resetting when this player starts bowling a new one.
    _bowling_inning: Optional[int] = None
    _innings_wickets: int = 0
    _bowling_milestones_awarded: Set[int] = field(default_factory=set)

    # Match-total state - never resets between innings.
    _match_wickets: int = 0
    _ten_wicket_bonus_awarded: bool = False
    _match_catches: int = 0
    _catch_milestone_awarded: bool = False

    # Current-over scratch state for maiden detection.
    _current_over_runs: int = 0
    _current_over_legal_balls: int = 0

    @property
    def total(self) -> float:
        return self.batting_pts + self.bowling_pts + self.fielding_pts

    def on_batting_ball(self, inning_number: int, runs: int, is_wicket: bool, extras_type) -> None:
        if self._batting_inning != inning_number:
            self._batting_inning = inning_number
            self._innings_runs = 0
            self._batting_milestones_awarded = set()

        if extras_type == ExtraType.WIDE:
            return  # wides don't count against the batter

        self._innings_runs += runs
        self.batting_pts += runs * self.rules.run
        if runs == 4:
            self.batting_pts += self.rules.boundary_bonus
        if runs == 6:
            self.batting_pts += self.rules.six_bonus

        for threshold, bonus in self.rules.batting_milestones:
            if self._innings_runs >= threshold and threshold not in self._batting_milestones_awarded:
                self.batting_pts += bonus
                self._batting_milestones_awarded.add(threshold)

    def on_bowling_ball(
        self, inning_number: int, runs_batter: int, runs_extras: int, extras_type,
        is_wicket: bool, wicket_kind: str,
    ) -> None:
        if self._bowling_inning != inning_number:
            self._bowling_inning = inning_number
            self._innings_wickets = 0
            self._bowling_milestones_awarded = set()

        charged = extras_type in (ExtraType.WIDE, ExtraType.NOBALL)
        self._current_over_runs += runs_batter + (runs_extras if charged else 0)

        if extras_type in (ExtraType.WIDE, ExtraType.NOBALL):
            return  # not a legal delivery - no dot-ball credit, doesn't count toward a maiden

        self._current_over_legal_balls += 1
        if runs_batter == 0 and not is_wicket:
            self.bowling_pts += self.rules.dot_ball

        if is_wicket and MatchRules.is_bowler_credited_wicket(wicket_kind):
            self.bowling_pts += self.rules.wicket
            if wicket_kind in (DismissalType.BOWLED, DismissalType.LBW):
                self.bowling_pts += self.rules.dismissal_bonus

            self._innings_wickets += 1
            self._match_wickets += 1

            for threshold, bonus in self.rules.bowling_milestones:
                if self._innings_wickets >= threshold and threshold not in self._bowling_milestones_awarded:
                    self.bowling_pts += bonus
                    self._bowling_milestones_awarded.add(threshold)

            if self._match_wickets >= 10 and not self._ten_wicket_bonus_awarded:
                self.bowling_pts += self.rules.ten_wicket_match_bonus
                self._ten_wicket_bonus_awarded = True

    def on_over_end_bowler(self) -> None:
        if self._current_over_runs == 0 and self._current_over_legal_balls >= 6:
            self.bowling_pts += self.rules.maiden
        self._current_over_runs = 0
        self._current_over_legal_balls = 0

    def on_fielding_event(self, kind: str) -> None:
        """kind: 'catch' | 'run_out' | 'stumping'"""
        if kind == 'catch':
            self.fielding_pts += self.rules.catch
            self._match_catches += 1
            if (self._match_catches >= self.rules.catch_milestone_threshold
                    and not self._catch_milestone_awarded):
                self.fielding_pts += self.rules.catch_milestone_bonus
                self._catch_milestone_awarded = True
        elif kind == 'run_out':
            self.fielding_pts += self.rules.runout
        elif kind == 'stumping':
            self.fielding_pts += self.rules.stumping


class MatchAwards:
    """
    Accumulates player points for a single match, using a PointsStrategy
    (defaults to the standard rubric) resolved once per match's format.
    Call record_from_match() during/after match simulation, then potm() at end.
    """

    def __init__(self, points_strategy: PointsStrategy = DEFAULT_POINTS_STRATEGY):
        self._players: Dict[int, PlayerMatchPoints] = {}
        self._points_strategy = points_strategy
        self._rules: MvpPointsRules = _FALLBACK_RULES

    def _get(self, pid: int, name: str) -> PlayerMatchPoints:
        if pid not in self._players:
            self._players[pid] = PlayerMatchPoints(player_id=pid, player_name=name, rules=self._rules)
        return self._players[pid]

    def record_from_match(self, match) -> None:
        """
        Populate all player points from a completed SimulationMatch object.
        Called once after engine.simulate().
        """
        self._rules = self._points_strategy.rules_for(match.match_format)

        for inning in match.innings:
            if not inning.deliveries:
                continue
            inn_num = inning.inning_number

            for delivery in inning.deliveries:
                batter = delivery.batter
                bowler = delivery.bowler
                if batter is None or bowler is None:
                    continue

                bt = self._get(batter.id, batter.name)
                bw = self._get(bowler.id, bowler.name)

                et = delivery.extras_type
                rb = delivery.runs_batter
                rx = delivery.runs_extras
                wkt = delivery.is_wicket
                wkind = delivery.wicket_kind or ""

                bt.on_batting_ball(inn_num, rb, wkt, et)
                bw.on_bowling_ball(inn_num, rb, rx, et, wkt, wkind)

            # Over-end events for bowlers (maiden bonus) - call once per over
            # so PlayerMatchPoints.on_over_end_bowler checks its own
            # internally-tracked over totals (built up ball-by-ball above),
            # rather than this loop reconstructing a second copy of the same
            # runs/legal-balls-this-over accounting.
            max_over = max(d.over_number for d in inning.deliveries)
            for over in range(max_over + 1):
                over_dels = [d for d in inning.deliveries if d.over_number == over]
                if not over_dels:
                    continue
                bowler = over_dels[0].bowler
                if bowler:
                    self._get(bowler.id, bowler.name).on_over_end_bowler()

            # Fielding events from wickets
            for delivery in inning.deliveries:
                if not delivery.is_wicket:
                    continue
                kind = delivery.wicket_kind or ""
                fp = delivery.outcome_player
                if fp is not None:
                    fld = self._get(fp.id, fp.name)
                    if kind in ('caught', 'caught and bowled', 'c and b'):
                        fld.on_fielding_event('catch')
                    elif kind == 'run out':
                        fld.on_fielding_event('run_out')
                    elif kind == 'stumped':
                        fld.on_fielding_event('stumping')

        # Tag each player with their team name (batting team = their team)
        for inning in match.innings:
            if not inning.batting_team:
                continue
            team_name = inning.batting_team.name
            for ip in inning.batting_team.inning_players:
                pmp = self._players.get(ip.id)
                if pmp and not pmp.team:
                    pmp.team = team_name
            if inning.bowling_team:
                bow_name = inning.bowling_team.name
                for ip in inning.bowling_team.inning_players:
                    pmp = self._players.get(ip.id)
                    if pmp and not pmp.team:
                        pmp.team = bow_name

    def potm(self) -> Optional[PlayerMatchPoints]:
        """Return the player with the highest total points, or None if empty."""
        if not self._players:
            return None
        return max(self._players.values(), key=lambda p: p.total)

    def all_sorted(self) -> List[PlayerMatchPoints]:
        return sorted(self._players.values(), key=lambda p: p.total, reverse=True)


class TournamentAwards:
    """Accumulates POTM points across all matches for POTT calculation."""

    def __init__(self):
        self._totals: Dict[int, PlayerMatchPoints] = {}

    def add_match(self, awards: MatchAwards) -> None:
        for pid, pmp in awards._players.items():
            if pid not in self._totals:
                self._totals[pid] = PlayerMatchPoints(pid, pmp.player_name, team=pmp.team)
            t = self._totals[pid]
            if not t.team and pmp.team:
                t.team = pmp.team
            t.batting_pts  += pmp.batting_pts
            t.bowling_pts  += pmp.bowling_pts
            t.fielding_pts += pmp.fielding_pts

    def pott(self) -> Optional[PlayerMatchPoints]:
        if not self._totals:
            return None
        return max(self._totals.values(), key=lambda p: p.total)

    def leaderboard(self, top_n: int = 10) -> List[PlayerMatchPoints]:
        return sorted(self._totals.values(), key=lambda p: p.total, reverse=True)[:top_n]
