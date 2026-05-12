from dataclasses import dataclass, field
from simulator.entities.player import Player
from simulator.events import MatchObserver, MatchEvent, EventType
from simulator.entities.rules import MatchRules
from enums.constants import ExtraType


# First 0-indexed over that is considered "death" per format.
_DEATH_OVER_START = {'T20': 16, 'ODI': 40, 'Test': 999}


def _is_death_over(over_0indexed: int, match_format: str) -> bool:
    return over_0indexed >= _DEATH_OVER_START.get(match_format, 999)


@dataclass
class InningPlayer(MatchObserver):
    player: Player

    runs_scored: int = 0
    balls_faced: int = 0
    fours: int = 0
    sixes: int = 0
    dot_balls_faced: int = 0
    is_out: bool = False

    # Death-phase subset (used by SuperOverSelector)
    death_runs_scored:  int = 0
    death_balls_faced:  int = 0
    death_fours:        int = 0
    death_sixes:        int = 0

    runs_conceded: int = 0
    balls_bowled: int = 0
    wickets_taken: int = 0
    maidens: int = 0
    dot_balls_bowled: int = 0

    # Death-phase subset (used by SuperOverSelector)
    death_runs_conceded: int = 0
    death_balls_bowled:  int = 0

    @property
    def id(self) -> int:
        return self.player.id

    @property
    def name(self) -> str:
        return self.player.name

    @property
    def is_keeper(self) -> bool:
        return self.player.is_keeper

    def on_event(self, event: MatchEvent):
        if event.type == EventType.BALL_BOWLED:
            data = event.data
            outcome = data.get("outcome")
            batter = data.get("batter")
            bowler = data.get("bowler")
            match  = data.get("match")

            is_death = False
            if match is not None:
                is_death = _is_death_over(match.current_over, match.match_format)

            if batter and batter.id == self.id:
                self.runs_scored += outcome.runs_batter
                if outcome.extras_type != ExtraType.WIDE:
                    self.balls_faced += 1
                if outcome.runs_batter == 4:
                    self.fours += 1
                if outcome.runs_batter == 6:
                    self.sixes += 1
                if outcome.runs_batter == 0 and not outcome.is_wicket and MatchRules.is_legal_delivery(outcome.extras_type):
                    self.dot_balls_faced += 1
                if outcome.is_wicket:
                    self.is_out = True
                if is_death:
                    self.death_runs_scored += outcome.runs_batter
                    if outcome.extras_type != ExtraType.WIDE:
                        self.death_balls_faced += 1
                    if outcome.runs_batter == 4:
                        self.death_fours += 1
                    if outcome.runs_batter == 6:
                        self.death_sixes += 1

            if bowler and bowler.id == self.id:
                self.runs_conceded += outcome.runs_batter + outcome.runs_extras
                if outcome.runs_batter == 0 and outcome.runs_extras == 0 and not outcome.is_wicket:
                    self.dot_balls_bowled += 1
                if MatchRules.is_legal_delivery(outcome.extras_type):
                    self.balls_bowled += 1
                if outcome.is_wicket and MatchRules.is_bowler_credited_wicket(outcome.wicket_kind):
                    self.wickets_taken += 1
                    self.dot_balls_bowled += 1
                if is_death:
                    self.death_runs_conceded += outcome.runs_batter + outcome.runs_extras
                    if MatchRules.is_legal_delivery(outcome.extras_type):
                        self.death_balls_bowled += 1

        elif event.type == EventType.OVER_COMPLETED:
            data = event.data
            bowler = data.get("bowler")
            if bowler and bowler.id == self.id and data.get("runs") == 0:
                self.maidens += 1
