from dataclasses import dataclass
from typing import Optional
from .player import Player
from .team import Team

@dataclass
class Delivery:
    inning_number: int
    over_number: int
    ball_number: int
    batter: Player
    bowler: Player
    non_striker: Player
    batting_team: Team
    bowling_team: Team
    runs_batter: int
    runs_extras: int
    outcome_type: str # 'Wicket', 'Runs', 'Extras', 'Dot'
    outcome_kind: Optional[str] = None # 'Caught', 'Wide', etc.
    outcome_player: Optional[Player] = None # Fielder/player involved (Player object with integer id)
    delivery_id: Optional[int] = None

    @classmethod
    def builder(cls):
        return cls.Builder()

    class Builder:
        def __init__(self):
            self._inning_number: Optional[int] = None
            self._over_number: Optional[int] = None
            self._ball_number: Optional[int] = None
            self._batter: Optional[Player] = None
            self._bowler: Optional[Player] = None
            self._non_striker: Optional[Player] = None
            self._batting_team: Optional[Team] = None
            self._bowling_team: Optional[Team] = None
            self._runs_batter: Optional[int] = None
            self._runs_extras: Optional[int] = None
            self._outcome_type: Optional[str] = None
            self._outcome_kind: Optional[str] = None
            self._outcome_player: Optional[Player] = None
            self._delivery_id: Optional[int] = None

        def with_inning_number(self, inning_number: int):
            self._inning_number = inning_number
            return self

        def with_over_number(self, over_number: int):
            self._over_number = over_number
            return self

        def with_ball_number(self, ball_number: int):
            self._ball_number = ball_number
            return self

        def with_batter(self, batter: Player):
            self._batter = batter
            return self

        def with_bowler(self, bowler: Player):
            self._bowler = bowler
            return self

        def with_non_striker(self, non_striker: Player):
            self._non_striker = non_striker
            return self

        def with_batting_team(self, batting_team: Team):
            self._batting_team = batting_team
            return self

        def with_bowling_team(self, bowling_team: Team):
            self._bowling_team = bowling_team
            return self

        def with_runs_batter(self, runs_batter: int):
            self._runs_batter = runs_batter
            return self

        def with_runs_extras(self, runs_extras: int):
            self._runs_extras = runs_extras
            return self

        def with_outcome_type(self, outcome_type: str):
            self._outcome_type = outcome_type
            return self

        def with_outcome_kind(self, outcome_kind: Optional[str]):
            self._outcome_kind = outcome_kind
            return self

        def with_outcome_player(self, outcome_player: Optional[Player]):
            self._outcome_player = outcome_player
            return self

        def with_delivery_id(self, delivery_id: Optional[int]):
            self._delivery_id = delivery_id
            return self

        def build(self):
            if any(x is None for x in [
                self._inning_number, self._over_number, self._ball_number,
                self._batter, self._bowler, self._non_striker,
                self._batting_team, self._bowling_team,
                self._runs_batter, self._runs_extras, self._outcome_type
            ]):
                raise ValueError("Missing required fields for Delivery")

            return Delivery(
                inning_number=self._inning_number,
                over_number=self._over_number,
                ball_number=self._ball_number,
                batter=self._batter,
                bowler=self._bowler,
                non_striker=self._non_striker,
                batting_team=self._batting_team,
                bowling_team=self._bowling_team,
                runs_batter=self._runs_batter,
                runs_extras=self._runs_extras,
                outcome_type=self._outcome_type,
                outcome_kind=self._outcome_kind,
                outcome_player=self._outcome_player,
                delivery_id=self._delivery_id
            )
