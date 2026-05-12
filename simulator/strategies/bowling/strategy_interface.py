from abc import ABC, abstractmethod
from typing import Optional

from simulator.entities.match import SimulationMatch
from simulator.entities.inning_player import InningPlayer


class BowlingStrategy(ABC):
    def init_model(self, match: SimulationMatch) -> None:
        """Called once before the first ball. Override to pre-load historical data."""

    @abstractmethod
    def select_bowler(self, match: SimulationMatch) -> Optional[InningPlayer]:
        """
        Choose the bowler for the next over.

        Called once per over boundary (and once at innings start with no current bowler).
        The returned player will be set as match.current_bowler before the over begins.
        """
