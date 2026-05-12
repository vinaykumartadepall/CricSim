from dataclasses import dataclass, field
from typing import List, Optional
from datetime import date
from .tournament import Tournament
from .venue import Venue
from .team import Team
from .player import Player
from .delivery import Delivery

@dataclass
class Match:
    original_match_id: str
    name: str 
    tournament: Tournament
    venue: Venue
    home_team: Team
    away_team: Team
    date: Optional[date]
    gender: str
    match_format: str
    match_type: str 
    balls_per_over: int
    overs_per_innings: Optional[int]
    innings_per_match: int
    result: str
    result_type: Optional[str]
    winner: Optional[Team]
    win_type: Optional[str]
    win_by: Optional[int]
    player_of_match: Optional[Player]
    toss_winner: Optional[Team]
    toss_decision: Optional[str]
    season: str
    
    # Relationships
    deliveries: List[Delivery] = field(default_factory=list)
    players: List[Player] = field(default_factory=list) 
    
    id: Optional[int] = None

    def add_delivery(self, delivery: Delivery):
        self.deliveries.append(delivery)

    def add_player(self, player: Player):
        self.players.append(player)

    @classmethod
    def builder(cls):
        return cls.Builder()

    class Builder:
        def __init__(self):
            self._original_match_id: Optional[str] = None
            self._name: Optional[str] = None
            self._tournament: Optional[Tournament] = None
            self._venue: Optional[Venue] = None
            self._home_team: Optional[Team] = None
            self._away_team: Optional[Team] = None
            self._date: Optional[date] = None
            self._gender: Optional[str] = None
            self._match_format: Optional[str] = None
            self._match_type: Optional[str] = None
            self._balls_per_over: Optional[int] = None
            self._overs_per_innings: Optional[int] = None
            self._innings_per_match: Optional[int] = None
            self._result: Optional[str] = None
            self._result_type: Optional[str] = None
            self._winner: Optional[Team] = None
            self._win_type: Optional[str] = None
            self._win_by: Optional[int] = None
            self._player_of_match: Optional[Player] = None
            self._toss_winner: Optional[Team] = None
            self._toss_decision: Optional[str] = None
            self._season: Optional[str] = None
            self._id: Optional[int] = None

        def with_original_match_id(self, original_match_id: str):
            self._original_match_id = original_match_id
            return self

        def with_name(self, name: str):
            self._name = name
            return self

        def with_tournament(self, tournament: Tournament):
            self._tournament = tournament
            return self

        def with_venue(self, venue: Venue):
            self._venue = venue
            return self

        def with_home_team(self, home_team: Team):
            self._home_team = home_team
            return self

        def with_away_team(self, away_team: Team):
            self._away_team = away_team
            return self

        def with_date(self, match_date: Optional[date]):
            self._date = match_date
            return self

        def with_gender(self, gender: str):
            self._gender = gender
            return self

        def with_match_format(self, match_format: str):
            self._match_format = match_format
            return self

        def with_match_type(self, match_type: str):
            self._match_type = match_type
            return self

        def with_balls_per_over(self, balls_per_over: int):
            self._balls_per_over = balls_per_over
            return self

        def with_overs_per_innings(self, overs_per_innings: Optional[int]):
            self._overs_per_innings = overs_per_innings
            return self

        def with_innings_per_match(self, innings_per_match: int):
            self._innings_per_match = innings_per_match
            return self

        def with_result(self, result: str):
            self._result = result
            return self

        def with_result_type(self, result_type: Optional[str]):
            self._result_type = result_type
            return self

        def with_winner(self, winner: Optional[Team]):
            self._winner = winner
            return self

        def with_win_type(self, win_type: Optional[str]):
            self._win_type = win_type
            return self

        def with_win_by(self, win_by: Optional[int]):
            self._win_by = win_by
            return self

        def with_player_of_match(self, player_of_match: Optional[Player]):
            self._player_of_match = player_of_match
            return self

        def with_toss_winner(self, toss_winner: Optional[Team]):
            self._toss_winner = toss_winner
            return self

        def with_toss_decision(self, toss_decision: Optional[str]):
            self._toss_decision = toss_decision
            return self

        def with_season(self, season: str):
            self._season = season
            return self

        def with_id(self, match_id: Optional[int]):
            self._id = match_id
            return self

        def build(self):
            if any(x is None for x in [
                self._original_match_id, self._name, self._tournament, self._venue,
                self._home_team, self._away_team, self._gender, self._match_format,
                self._match_type, self._balls_per_over, self._innings_per_match,
                self._result, self._season
            ]):
                raise ValueError("Missing required fields for Match")

            return Match(
                original_match_id=self._original_match_id,
                name=self._name,
                tournament=self._tournament,
                venue=self._venue,
                home_team=self._home_team,
                away_team=self._away_team,
                date=self._date,
                gender=self._gender,
                match_format=self._match_format,
                match_type=self._match_type,
                balls_per_over=self._balls_per_over,
                overs_per_innings=self._overs_per_innings,
                innings_per_match=self._innings_per_match,
                result=self._result,
                result_type=self._result_type,
                winner=self._winner,
                win_type=self._win_type,
                win_by=self._win_by,
                player_of_match=self._player_of_match,
                toss_winner=self._toss_winner,
                toss_decision=self._toss_decision,
                season=self._season,
                id=self._id
            )
