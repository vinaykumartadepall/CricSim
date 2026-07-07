from abc import ABC, abstractmethod
from simulator.entities.match import SimulationMatch
from simulator.entities.ball_outcome import BallOutcome


class BallOutcomeStrategy(ABC):
    def init_model(self, match: SimulationMatch):
        """Optional hook to initialize probability arrays and caches before a match simulation starts."""
        pass

    @abstractmethod
    def predict_next_ball(self, match: SimulationMatch) -> BallOutcome:
        """Predicts the next ball's outcome for the match."""
