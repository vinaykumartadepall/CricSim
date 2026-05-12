from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from simulator.entities.team import MatchTeam
from simulator.entities.inning_player import InningPlayer
from simulator.events import MatchObserver, MatchEvent, EventType
from simulator.entities.rules import MatchRules
from enums.constants import ExtraType


@dataclass
class InningTeam(MatchObserver):
    team: MatchTeam
    inning_players: List[InningPlayer] = field(default_factory=list)

    total_runs: int = 0
    total_wickets: int = 0
    total_balls: int = 0
    extras_wides: int = 0
    extras_noballs: int = 0
    extras_byes: int = 0
    extras_legbyes: int = 0
    extras_penalty: int = 0

    @staticmethod
    def from_match_team(team: MatchTeam) -> "InningTeam":
        return InningTeam(
            team=team,
            inning_players=[InningPlayer(player=p) for p in team.players],
        )

    @property
    def id(self) -> int:
        return self.team.id

    @property
    def name(self) -> str:
        return self.team.name

    @property
    def extras(self) -> int:
        return self.extras_wides + self.extras_noballs + self.extras_byes + self.extras_legbyes + self.extras_penalty

    def on_event(self, event: MatchEvent):
        if event.type != EventType.BALL_BOWLED:
            return
        data = event.data
        batting_team = data.get("batting_team")
        if not (batting_team and batting_team.id == self.id):
            return

        outcome = data.get("outcome")
        self.total_runs += outcome.runs_batter + outcome.runs_extras

        if outcome.runs_extras > 0:
            r = outcome.runs_extras
            if outcome.extras_type == ExtraType.WIDE:
                self.extras_wides += r
            elif outcome.extras_type == ExtraType.NOBALL:
                self.extras_noballs += r
            elif outcome.extras_type == ExtraType.BYES:
                self.extras_byes += r
            elif outcome.extras_type == ExtraType.LEGBYES:
                self.extras_legbyes += r
            else:
                self.extras_penalty += r

        if outcome.is_wicket:
            self.total_wickets += 1

        if MatchRules.is_legal_delivery(outcome.extras_type):
            self.total_balls += 1

    @property
    def wicket_keeper(self) -> Optional[InningPlayer]:
        return next((ip for ip in self.inning_players if ip.is_keeper), None)

    def get_openers(self) -> Tuple[Optional[InningPlayer], Optional[InningPlayer]]:
        if len(self.inning_players) >= 2:
            return self.inning_players[0], self.inning_players[1]
        if len(self.inning_players) == 1:
            return self.inning_players[0], None
        return None, None

    def get_next_batter(
        self,
        striker: Optional[InningPlayer],
        non_striker: Optional[InningPlayer],
    ) -> Optional[InningPlayer]:
        for ip in self.inning_players:
            if ip != striker and ip != non_striker and not ip.is_out:
                return ip
        return None

    def get_next_bowler(
        self,
        current_bowler: Optional[InningPlayer],
        current_over: int,
    ) -> Optional[InningPlayer]:
        if not self.inning_players:
            return None
        idx = current_over % min(5, len(self.inning_players))
        return self.inning_players[-(idx + 1)]
