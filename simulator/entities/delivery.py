from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from simulator.entities.inning_player import InningPlayer


@dataclass
class SimulationDelivery:
    inning_number: int
    over_number: int
    ball_number: int
    batter: Optional["InningPlayer"]
    bowler: Optional["InningPlayer"]
    runs_batter: int = 0
    runs_extras: int = 0
    is_wicket: bool = False
    wicket_kind: Optional[str] = None
    extras_type: Optional[str] = None
    outcome_player: Optional["InningPlayer"] = None
