import random
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple

from simulator.entities.match import SimulationMatch, MatchStatus
from simulator.entities.team import MatchTeam
from simulator.entities.inning import Inning
from simulator.entities.inning_team import InningTeam
from simulator.match_logger import MatchLogger
from simulator.presentation.formatters import format_innings_scorecard
from simulator.strategies.ball_outcome_prediction.strategy_interface import BallOutcomeStrategy
from simulator.strategies.bowling.strategy_interface import BowlingStrategy
from simulator.strategies.bowling.smart import SmartBowlingStrategy
from simulator.logger import get_logger

_log = get_logger()


class BaseEngine(ABC):
    """
    Abstract base for all match simulation engines.

    Owns match-level concerns: inning creation, event bus wiring, toss, and scorecard output.
    Format-specific flow (innings count, session breaks, result logic) belongs in subclasses.
    Ball-by-ball and over-by-over mechanics live in InningsSimulator.
    """

    def __init__(
        self,
        match: SimulationMatch,
        ball_outcome_strategy: BallOutcomeStrategy,
        bowling_strategy: Optional[BowlingStrategy] = None,
    ):
        self.match = match
        self.ball_outcomes = ball_outcome_strategy
        self.bowling_strategy: BowlingStrategy = bowling_strategy or SmartBowlingStrategy()
        self.logger: Optional[MatchLogger] = None

    @abstractmethod
    def simulate(self):
        """Entry point for match simulation. Subclasses drive the innings sequence."""

    def _prepare_match_logs(self):
        self.match.status = MatchStatus.IN_PROGRESS
        self.logger = MatchLogger(match_id=self.match.id)
        header = (
            f"=== {self.match.home_team.name} vs {self.match.away_team.name} "
            f"| {self.match.match_format} ==="
        )
        self.logger.headline(header)

        t0 = time.perf_counter()
        _log.info("[Engine] ── Model Init: %s %s (%s vs %s) ──",
                  self.match.match_format,
                  getattr(self.match, 'gender', 'male'),
                  self.match.home_team.name,
                  self.match.away_team.name)

        _log.info("[Engine] Initialising ball-outcome model …")
        t = time.perf_counter()
        self.ball_outcomes.init_model(self.match)
        _log.info("[Engine] Ball-outcome model ready              %.2fs", time.perf_counter() - t)

        _log.info("[Engine] Initialising bowling-selection model …")
        t = time.perf_counter()
        self.bowling_strategy.init_model(self.match)
        _log.info("[Engine] Bowling-selection model ready         %.2fs", time.perf_counter() - t)

        _log.info("[Engine] Total model initialisation            %.2fs", time.perf_counter() - t0)

    def _execute_toss(self) -> Tuple[MatchTeam, MatchTeam]:
        """Returns (batting_team, bowling_team) after a randomised toss."""
        toss_winner = random.choice([self.match.home_team, self.match.away_team])
        toss_decision = random.choice(["bat", "bowl"])
        other = self.match.away_team if toss_winner == self.match.home_team else self.match.home_team
        batting, bowling = (toss_winner, other) if toss_decision == "bat" else (other, toss_winner)
        self.logger.headline(
            f"Toss: {toss_winner.name} won the toss and elected to {toss_decision} first.\n"
        )
        return batting, bowling

    def _create_inning(
        self, inning_num: int, batting_team: MatchTeam, bowling_team: MatchTeam
    ) -> Inning:
        """
        Builds a fresh Inning with new InningTeam/InningPlayer objects,
        wires them to the event bus, and sets the match's current team pointers.
        """
        batting_inning_team = InningTeam.from_match_team(batting_team)
        bowling_inning_team = InningTeam.from_match_team(bowling_team)
        inning = Inning(inning_num, batting_inning_team, bowling_inning_team)
        self.match.innings.append(inning)

        self.match.current_inning = inning_num
        self.match.current_batting_team = batting_inning_team
        self.match.current_bowling_team = bowling_inning_team

        # Re-wire event bus with fresh inning-scoped observers only.
        self.match.event_bus.clear()
        self.match.event_bus.subscribe(batting_inning_team)
        self.match.event_bus.subscribe(bowling_inning_team)
        for ip in batting_inning_team.inning_players:
            self.match.event_bus.subscribe(ip)
        for ip in bowling_inning_team.inning_players:
            self.match.event_bus.subscribe(ip)

        return inning

    def _set_initial_players(self):
        """Resets over/ball counters and sets openers and opening bowler for the current inning."""
        self.match.current_over = 0
        self.match.current_ball = 0

        if self.match.current_batting_team:
            self.match.striker, self.match.non_striker = (
                self.match.current_batting_team.get_openers()
            )
            if self.match.striker:
                self.match.striker.came_to_crease = True
            if self.match.non_striker:
                self.match.non_striker.came_to_crease = True

        if self.match.current_bowling_team:
            self.match.current_bowler = self.bowling_strategy.select_bowler(self.match)

    def _print_innings_summary(self, inning: Inning):
        self.logger.scorecard(format_innings_scorecard(inning))
