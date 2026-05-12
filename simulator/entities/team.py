from dataclasses import dataclass, field
from typing import List

from simulator.entities.player import Player, TournamentPlayer


@dataclass
class Team:
    id: int
    name: str


@dataclass
class TournamentTeam(Team):
    players: List[TournamentPlayer] = field(default_factory=list)
    matches_won: int = 0
    matches_lost: int = 0


@dataclass
class MatchTeam(Team):
    players: List[Player] = field(default_factory=list)
