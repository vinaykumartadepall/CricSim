from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from simulator.entities.team import MatchTeam
from simulator.events import MatchEventBus
from db.entities.venue import Venue
from db.entities.tournament import Tournament

if TYPE_CHECKING:
    from simulator.entities.inning import Inning
    from simulator.entities.inning_team import InningTeam
    from simulator.entities.inning_player import InningPlayer
    from simulator.entities.delivery import SimulationDelivery


class MatchStatus(Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


@dataclass
class SimulationMatch:
    id: Optional[int]
    home_team: MatchTeam
    away_team: MatchTeam
    venue: Optional[Venue] = None
    overs_per_innings: Optional[int] = 20
    innings_per_match: int = 2
    balls_per_over: int = 6

    innings: List["Inning"] = field(default_factory=list)

    current_inning: int = 1
    current_over: int = 0
    current_ball: int = 0

    current_batting_team: Optional["InningTeam"] = None
    current_bowling_team: Optional["InningTeam"] = None

    striker: Optional["InningPlayer"] = None
    non_striker: Optional["InningPlayer"] = None
    current_bowler: Optional["InningPlayer"] = None

    target_score: Optional[int] = None
    follow_on_enforced: bool = False
    is_super_over: bool = False
    status: MatchStatus = MatchStatus.SCHEDULED

    match_format: str = "T20"
    gender: str = "male"
    tournament: Optional[Tournament] = None

    event_bus: MatchEventBus = field(default_factory=MatchEventBus)

    @property
    def deliveries(self) -> List["SimulationDelivery"]:
        return [d for inning in self.innings for d in inning.deliveries]
