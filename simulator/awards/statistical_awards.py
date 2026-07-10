"""
Statistical Awards - the default MVP scoring rubric.

Scores every ball against a fixed, per-format point table. Point values are
looked up once per match (via _rules_for, which routes through
MatchRules.get_unified_format so format aliases like 'MDM'/'IT20' resolve
correctly) and handed to a private per-player accumulator (_PlayerTally) that
does the actual ball-by-ball bookkeeping. Nothing outside this module ever
sees _PlayerTally or MvpPointsRules - the only thing StatisticalAwardsStrategy
exposes is compute(match) -> List[PlayerAward], per the MvpStrategy contract.

  Batting (points differ by format - see _RULES)
    Run                base points, every run scored
    Boundary bonus      extra, on top of run points, for a four
    Six bonus            extra, on top of run points, for a six
    Milestone bonuses    30/50/100/150/200 runs - stack within an innings,
                          reset at the start of each new innings

  Bowling
    Wicket (credited)    base points per dismissal
    Bowled/LBW bonus     extra, only for those two dismissal types
    Maiden over          per maiden (6 legal balls, 0 runs conceded)
    Wicket-haul bonuses  3/4/5 wickets - stack within an innings, reset per innings
    Dot ball              per scoreless legal delivery
    Ten-wicket match     10+ wickets across the whole match (both Test
                          innings combined) - a no-op for T20/ODI (0 pts)

  Fielding (event-based, from wicket deliveries)
    Catch                 per catch, plus a one-time bonus at 3 catches (match-total)
    Stumping
    Run out
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from enums.constants import DismissalType, ExtraType
from simulator.awards.mvp_strategy import MvpStrategy, PlayerAward
from simulator.entities.rules import MatchRules


@dataclass(frozen=True)
class MvpPointsRules:
    """
    Point values for one match format.

    batting_milestones / bowling_milestones are (threshold, bonus) pairs in
    ascending order. Every threshold reached during an innings is awarded
    once and stacks with lower thresholds already crossed.
    """
    run: float
    boundary_bonus: float
    six_bonus: float
    batting_milestones: Tuple[Tuple[int, float], ...]

    wicket: float
    dismissal_bonus: float
    maiden: float
    bowling_milestones: Tuple[Tuple[int, float], ...]
    dot_ball: float
    ten_wicket_match_bonus: float

    catch: float
    catch_milestone_threshold: int
    catch_milestone_bonus: float
    stumping: float
    runout: float


class StatisticalAwardsStrategy(MvpStrategy):
    """The default MVP rubric - a fixed, per-format point table."""

    _RULES: Dict[str, MvpPointsRules] = {
        'T20': MvpPointsRules(
            run=1, boundary_bonus=1, six_bonus=2,
            batting_milestones=((30, 4), (50, 8), (100, 16), (150, 24), (200, 24)),
            wicket=25, dismissal_bonus=8, maiden=12,
            bowling_milestones=((3, 8), (4, 16), (5, 24)),
            dot_ball=1, ten_wicket_match_bonus=0,
            catch=8, catch_milestone_threshold=3, catch_milestone_bonus=4,
            stumping=12, runout=12,
        ),
        'ODI': MvpPointsRules(
            run=1, boundary_bonus=0.5, six_bonus=1,
            batting_milestones=((50, 8), (100, 16), (150, 24), (200, 24)),
            wicket=25, dismissal_bonus=8, maiden=8,
            bowling_milestones=((3, 8), (4, 16), (5, 24)),
            dot_ball=0.5, ten_wicket_match_bonus=0,
            catch=8, catch_milestone_threshold=3, catch_milestone_bonus=4,
            stumping=12, runout=12,
        ),
        'Test': MvpPointsRules(
            run=1, boundary_bonus=0.5, six_bonus=1,
            batting_milestones=((50, 8), (100, 16), (150, 24), (200, 24)),
            wicket=20, dismissal_bonus=8, maiden=6,
            bowling_milestones=((3, 6), (4, 12), (5, 20)),
            dot_ball=0, ten_wicket_match_bonus=40,
            catch=8, catch_milestone_threshold=3, catch_milestone_bonus=4,
            stumping=12, runout=12,
        ),
    }

    def _rules_for(self, match_format: str) -> MvpPointsRules:
        fmt = MatchRules.get_unified_format(match_format)
        return self._RULES.get(fmt, self._RULES['T20'])

    def compute(self, match) -> List[PlayerAward]:
        rules = self._rules_for(match.match_format)
        tallies: Dict[int, "_PlayerTally"] = {}

        def _get(pid: int, name: str) -> "_PlayerTally":
            if pid not in tallies:
                tallies[pid] = _PlayerTally(player_id=pid, player_name=name, rules=rules)
            return tallies[pid]

        for inning in match.innings:
            if not inning.deliveries:
                continue
            inn_num = inning.inning_number

            for delivery in inning.deliveries:
                batter = delivery.batter
                bowler = delivery.bowler
                if batter is None or bowler is None:
                    continue

                bt = _get(batter.id, batter.name)
                bw = _get(bowler.id, bowler.name)

                et = delivery.extras_type
                rb = delivery.runs_batter
                rx = delivery.runs_extras
                wkt = delivery.is_wicket
                wkind = delivery.wicket_kind or ""

                bt.on_batting_ball(inn_num, rb, wkt, et)
                bw.on_bowling_ball(inn_num, rb, rx, et, wkt, wkind)

            # Over-end events for bowlers (maiden bonus) - call once per over
            # so _PlayerTally.on_over_end_bowler checks its own
            # internally-tracked over totals (built up ball-by-ball above),
            # rather than reconstructing a second copy of the same accounting.
            max_over = max(d.over_number for d in inning.deliveries)
            for over in range(max_over + 1):
                over_dels = [d for d in inning.deliveries if d.over_number == over]
                if not over_dels:
                    continue
                bowler = over_dels[0].bowler
                if bowler:
                    _get(bowler.id, bowler.name).on_over_end_bowler()

            # Fielding events from wickets
            for delivery in inning.deliveries:
                if not delivery.is_wicket:
                    continue
                kind = delivery.wicket_kind or ""
                fp = delivery.outcome_player
                if fp is not None:
                    fld = _get(fp.id, fp.name)
                    if kind in ('caught', 'caught and bowled', 'c and b'):
                        fld.on_fielding_event('catch')
                    elif kind == 'run out':
                        fld.on_fielding_event('run_out')
                    elif kind == 'stumped':
                        fld.on_fielding_event('stumping')

        # Tag each tracked player with their team name (batting team = their team)
        for inning in match.innings:
            if not inning.batting_team:
                continue
            team_name = inning.batting_team.name
            for ip in inning.batting_team.inning_players:
                t = tallies.get(ip.id)
                if t and not t.team:
                    t.team = team_name
            if inning.bowling_team:
                bow_name = inning.bowling_team.name
                for ip in inning.bowling_team.inning_players:
                    t = tallies.get(ip.id)
                    if t and not t.team:
                        t.team = bow_name

        return [
            PlayerAward(
                player_id=t.player_id,
                player_name=t.player_name,
                team=t.team,
                total=t.batting_pts + t.bowling_pts + t.fielding_pts,
                breakdown={
                    'batting_pts': t.batting_pts,
                    'bowling_pts': t.bowling_pts,
                    'fielding_pts': t.fielding_pts,
                },
            )
            for t in tallies.values()
        ]


@dataclass
class _PlayerTally:
    """
    Internal per-player, per-match ball-by-ball accumulator. Private to
    StatisticalAwardsStrategy - nothing outside this module constructs or
    reads one directly; compute() converts these into PlayerAward objects
    before returning.
    """
    player_id: int
    player_name: str
    rules: MvpPointsRules
    team: str = ""

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


DEFAULT_MVP_STRATEGY = StatisticalAwardsStrategy()
