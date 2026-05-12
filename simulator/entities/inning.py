from dataclasses import dataclass, field
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from simulator.entities.inning_team import InningTeam
    from simulator.entities.delivery import SimulationDelivery


@dataclass
class Inning:
    inning_number: int
    batting_team: "InningTeam"
    bowling_team: "InningTeam"
    deliveries: List["SimulationDelivery"] = field(default_factory=list)
