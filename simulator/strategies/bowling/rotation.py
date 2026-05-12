from typing import Optional

from simulator.entities.match import SimulationMatch
from simulator.entities.inning_player import InningPlayer
from simulator.strategies.bowling.strategy_interface import BowlingStrategy


class RotationBowlingStrategy(BowlingStrategy):
    """
    Baseline bowling strategy: rotates through the bowling unit in fixed order,
    skipping only the bowler who just finished the previous over.

    No quota enforcement, no phase awareness — pure round-robin.
    Useful as a reference baseline or for unit tests.
    """

    def select_bowler(self, match: SimulationMatch) -> Optional[InningPlayer]:
        team = match.current_bowling_team
        if not team or not team.inning_players:
            return match.current_bowler

        eligible = [ip for ip in team.inning_players if ip != match.current_bowler]
        if not eligible:
            return match.current_bowler

        idx = match.current_over % len(eligible)
        return eligible[idx]
