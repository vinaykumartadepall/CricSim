from dataclasses import dataclass


@dataclass
class Player:
    id: int
    name: str
    is_keeper: bool = False


@dataclass
class TournamentPlayer(Player):
    tournament_runs: int = 0
    tournament_wickets: int = 0
