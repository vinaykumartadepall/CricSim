"""
Player-of-the-Match and Player-of-the-Tournament scoring.

Points are accumulated delivery-by-delivery during a match and summed
at the end to determine POTM. Across all matches, POTT is the player
with the highest cumulative POTM score.

Scoring system:
  Batting
    Run scored         +0.5 / run
    4 hit              +1.0 bonus
    6 hit              +2.0 bonus
    Milestone 50       +10.0 bonus (once)
    Milestone 100      +20.0 bonus (additional, once)
    Dismissed cheaply  -3.0 (0–9 runs in ≥3 balls)
    Not out at end     +2.0 bonus

  Bowling
    Wicket (credited)  +10.0
    Dot ball           +1.0
    Maiden over        +5.0 bonus
    Wide / No-ball     -1.0 penalty
    Economy bonus:     +2.0 per over under format threshold (min 2 overs)

  Fielding (event-based, post-match)
    Catch              +5.0
    Run out            +5.0
    Stumping           +7.0
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from enums.constants import ExtraType
from simulator.entities.rules import MatchRules


_ECO_THRESHOLD = {'T20': 7.5, 'ODI': 5.5, 'Test': 3.0}


@dataclass
class PlayerMatchPoints:
    player_id: int
    player_name: str
    team: str = ""
    batting_pts: float = 0.0
    bowling_pts: float = 0.0
    fielding_pts: float = 0.0

    # Internal state
    _runs: int = 0
    _balls: int = 0
    _fours: int = 0
    _sixes: int = 0
    _50_awarded: bool = False
    _100_awarded: bool = False
    _not_out: bool = True

    _overs_bowled: int = 0
    _runs_conceded: int = 0
    _wickets: int = 0
    _dots_bowled: int = 0
    _wides: int = 0
    _noballs: int = 0
    _current_over_dots: int = 0
    _current_over_runs: int = 0

    @property
    def total(self) -> float:
        return self.batting_pts + self.bowling_pts + self.fielding_pts

    def on_batting_ball(self, runs: int, is_wicket: bool, extras_type) -> None:
        if extras_type == ExtraType.WIDE:
            return  # wides don't count against batter
        self._balls += 1
        self._runs  += runs
        self.batting_pts += runs * 0.5
        if runs == 4:
            self.batting_pts += 1.0
            self._fours += 1
        if runs == 6:
            self.batting_pts += 2.0
            self._sixes += 1
        if self._runs >= 50 and not self._50_awarded:
            self.batting_pts += 10.0
            self._50_awarded = True
        if self._runs >= 100 and not self._100_awarded:
            self.batting_pts += 20.0
            self._100_awarded = True
        if is_wicket:
            self._not_out = False
            if self._runs < 10 and self._balls >= 3:
                self.batting_pts -= 3.0  # cheap dismissal

    def on_innings_end_batter(self) -> None:
        if self._not_out and self._balls > 0:
            self.batting_pts += 2.0

    def on_bowling_ball(
        self, runs_batter: int, runs_extras: int, extras_type, is_wicket: bool, wicket_kind: str
    ) -> None:
        charged = extras_type in (ExtraType.WIDE, ExtraType.NOBALL)
        runs_charged = runs_batter + (runs_extras if charged else 0)
        self._current_over_runs += runs_charged

        if extras_type == ExtraType.WIDE:
            self._wides += 1
            self.bowling_pts -= 1.0
            return
        if extras_type == ExtraType.NOBALL:
            self._noballs += 1
            self.bowling_pts -= 1.0
            # no-ball still bowled as a delivery but not legal
            return

        # Legal delivery
        if runs_batter == 0 and not is_wicket and extras_type not in (ExtraType.WIDE,):
            self.bowling_pts += 1.0
            self._dots_bowled += 1
            self._current_over_dots += 1

        if is_wicket:
            if MatchRules.is_bowler_credited_wicket(wicket_kind):
                self.bowling_pts += 10.0
                self._wickets += 1

    def on_over_end_bowler(self, match_format: str) -> None:
        self._overs_bowled += 1
        self._runs_conceded += self._current_over_runs
        if self._current_over_runs == 0 and self._current_over_dots >= 6:
            self.bowling_pts += 5.0  # maiden
        self._current_over_runs = 0
        self._current_over_dots = 0

    def finalise_bowling(self, match_format: str) -> None:
        if self._overs_bowled < 2:
            return
        threshold = _ECO_THRESHOLD.get(match_format, 7.5)
        eco = (self._runs_conceded / self._overs_bowled) if self._overs_bowled else 0
        if eco < threshold:
            bonus = (threshold - eco) / threshold * 2.0 * self._overs_bowled
            self.bowling_pts += round(min(bonus, 12.0), 2)

    def on_fielding_event(self, kind: str) -> None:
        """kind: 'catch' | 'run_out' | 'stumping'"""
        if kind == 'catch':
            self.fielding_pts += 5.0
        elif kind == 'run_out':
            self.fielding_pts += 5.0
        elif kind == 'stumping':
            self.fielding_pts += 7.0


class MatchAwards:
    """
    Accumulates player points for a single match.
    Call the on_* methods during match simulation, then call potm() at end.
    """

    def __init__(self):
        self._players: Dict[int, PlayerMatchPoints] = {}

    def _get(self, pid: int, name: str) -> PlayerMatchPoints:
        if pid not in self._players:
            self._players[pid] = PlayerMatchPoints(player_id=pid, player_name=name)
        return self._players[pid]

    def record_from_match(self, match) -> None:
        """
        Populate all player points from a completed SimulationMatch object.
        Called once after engine.simulate().
        """
        for inning in match.innings:
            if not inning.deliveries:
                continue

            # Track batter runs-so-far for over-the-innings context
            batter_runs: Dict[int, int] = defaultdict(int)
            batter_balls: Dict[int, int] = defaultdict(int)
            batter_out: Dict[int, bool] = defaultdict(lambda: False)
            # Track which bowler is bowling each over
            over_bowler: Dict[int, int] = {}

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

                bt.on_batting_ball(rb, wkt, et)
                bw.on_bowling_ball(rb, rx, et, wkt, wkind)

                if wkt:
                    batter_out[batter.id] = True

                batter_runs[batter.id] += rb
                over_bowler[delivery.over_number] = bowler.id

            # Over-end events for bowlers
            if inning.deliveries:
                max_over = max(d.over_number for d in inning.deliveries)
                for over in range(max_over + 1):
                    over_dels = [d for d in inning.deliveries if d.over_number == over]
                    if not over_dels:
                        continue
                    bowler = over_dels[0].bowler
                    if bowler:
                        bw = self._get(bowler.id, bowler.name)
                        # Reconstruct over stats for maiden check
                        legal = [d for d in over_dels
                                 if d.extras_type not in (ExtraType.WIDE, ExtraType.NOBALL)]
                        if len(legal) >= 6:
                            runs_in_over = sum(
                                d.runs_batter + (d.runs_extras
                                                 if d.extras_type in (ExtraType.WIDE, ExtraType.NOBALL)
                                                 else 0)
                                for d in over_dels
                            )
                            if runs_in_over == 0:
                                # Maiden bonus only if 6 legal balls bowled
                                bw.bowling_pts += 5.0

            # Innings-end not-out bonuses
            batting_team = inning.batting_team
            if batting_team:
                for ip in batting_team.inning_players:
                    if not ip.is_out and ip.balls_faced > 0:
                        self._get(ip.id, ip.name).on_innings_end_batter()

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

        # Finalise bowling economy bonuses — once per unique bowler across all innings
        finalised: set = set()
        for inning in match.innings:
            if not inning.deliveries:
                continue
            for delivery in inning.deliveries:
                if delivery.bowler and delivery.bowler.id not in finalised:
                    finalised.add(delivery.bowler.id)
                    self._get(delivery.bowler.id, delivery.bowler.name).finalise_bowling(
                        match.match_format
                    )

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
