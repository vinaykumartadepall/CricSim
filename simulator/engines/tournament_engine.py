from typing import List
from simulator.entities.match import SimulationMatch
from simulator.engines.engine_factory import EngineFactory
from simulator.strategies.ball_outcome_prediction.strategy_interface import BallOutcomeStrategy


class TournamentEngine:
    def __init__(self, matches: List[SimulationMatch], ball_outcome_strategy: BallOutcomeStrategy):
        self.matches = matches
        self.ball_outcomes = ball_outcome_strategy

    def simulate_all(self):
        for match in self.matches:
            engine = EngineFactory.create(match, self.ball_outcomes)
            engine.simulate()
