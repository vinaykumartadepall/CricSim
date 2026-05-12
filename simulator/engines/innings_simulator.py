from dataclasses import replace
from typing import Callable, Optional, Tuple

from simulator.entities.delivery import SimulationDelivery
from simulator.entities.match import SimulationMatch
from simulator.entities.rules import MatchRules
from simulator.events import MatchEvent, EventType
from simulator.match_logger import MatchLogger
from simulator.presentation.formatters import format_ball_commentary, format_over_summary
from simulator.strategies.ball_outcome_prediction.strategy_interface import BallOutcomeStrategy
from simulator.strategies.bowling.strategy_interface import BowlingStrategy


class InningsSimulator:
    """
    Simulates a single innings ball-by-ball and over-by-over.

    Engines own match flow (innings ordering, targets, results). This class owns
    everything within an innings: delivery execution, over housekeeping, and
    configurable termination so engines stay free of repetition.
    """

    def __init__(
        self,
        match: SimulationMatch,
        ball_outcome_strategy: BallOutcomeStrategy,
        logger: MatchLogger,
        bowling_strategy: BowlingStrategy = None,
    ):
        self.match = match
        self.ball_outcomes = ball_outcome_strategy
        self.logger = logger
        self.bowling_strategy = bowling_strategy

    def run(
        self,
        max_overs: Optional[int] = None,
        should_terminate: Optional[Callable[[], bool]] = None,
        on_over_complete: Optional[Callable[[int, int, int], None]] = None,
        max_wickets: int = 10,
    ) -> int:
        """
        Simulates the innings until max_wickets, the over cap, or the engine signals stop.

        Args:
            max_overs:        Innings over limit (None = no cap, e.g. Test).
            should_terminate: Called after each ball and after each over; return True to stop.
            on_over_complete: Called after each over as (overs_bowled, over_runs, over_wickets).
            max_wickets:      Wickets that end the innings (default 10; set 2 for super over).

        Returns:
            Number of complete overs bowled in this innings.
        """
        overs_bowled = 0

        while True:
            if self.match.current_batting_team.total_wickets >= max_wickets:
                break
            if max_overs is not None and self.match.current_over >= max_overs:
                break

            bowler = self.match.current_bowler
            over_runs, over_wickets = self._simulate_over(should_terminate, max_wickets)
            overs_bowled += 1

            self.match.event_bus.publish(MatchEvent(
                type=EventType.OVER_COMPLETED,
                data={"bowler": bowler, "runs": over_runs},
            ))

            self.match.striker, self.match.non_striker = (
                self.match.non_striker, self.match.striker
            )

            # Log summary before incrementing so formatter can filter deliveries
            # by current_over directly (0-indexed, no adjustment needed).
            self.logger.over_summary(
                format_over_summary(self.match, self.match.innings[-1])
            )

            self.match.current_over += 1

            more_overs_left = (
                max_overs is None or self.match.current_over < max_overs
            ) and self.match.current_batting_team.total_wickets < max_wickets
            if more_overs_left and self.match.current_bowling_team and self.bowling_strategy:
                self.match.current_bowler = self.bowling_strategy.select_bowler(self.match)

            if on_over_complete:
                on_over_complete(overs_bowled, over_runs, over_wickets)

            if should_terminate and should_terminate():
                break

        return overs_bowled

    def _simulate_over(
        self,
        should_terminate: Optional[Callable[[], bool]] = None,
        max_wickets: int = 10,
    ) -> Tuple[int, int]:
        """Simulates exactly one over, returning (over_runs, over_wickets)."""
        self.match.current_ball = 0
        over_runs = 0
        over_wickets = 0
        is_free_hit = False
        free_hit_supported = MatchRules.supports_free_hit(self.match.match_format)
        current_inning = self.match.innings[-1]

        while True:
            if (
                self.match.current_ball >= self.match.balls_per_over
                or self.match.current_batting_team.total_wickets >= max_wickets
            ):
                break

            outcome = self.ball_outcomes.predict_next_ball(self.match)

            this_ball_is_free_hit = is_free_hit  # capture before updating state

            if free_hit_supported and is_free_hit and outcome.is_wicket and outcome.wicket_kind != "run out":
                outcome = replace(outcome, is_wicket=False, wicket_kind=None, outcome_player=None)

            is_legal = MatchRules.is_legal_delivery(outcome.extras_type)
            if is_legal:
                self.match.current_ball += 1
                is_free_hit = False

            if free_hit_supported and MatchRules.is_free_hit_awarded(outcome.extras_type):
                is_free_hit = True

            display_ball = self.match.current_ball if is_legal else self.match.current_ball + 1
            outcome_was_free_hit = this_ball_is_free_hit
            over_runs += outcome.runs_batter + outcome.runs_extras

            delivery = SimulationDelivery(
                inning_number=self.match.current_inning,
                over_number=self.match.current_over,
                ball_number=display_ball,
                batter=self.match.striker,
                bowler=self.match.current_bowler,
                runs_batter=outcome.runs_batter,
                runs_extras=outcome.runs_extras,
                is_wicket=outcome.is_wicket,
                wicket_kind=outcome.wicket_kind,
                extras_type=outcome.extras_type,
                outcome_player=outcome.outcome_player,
            )
            current_inning.deliveries.append(delivery)

            self.match.event_bus.publish(MatchEvent(
                type=EventType.BALL_BOWLED,
                data={
                    "match": self.match,
                    "inning": self.match.current_inning,
                    "batting_team": self.match.current_batting_team,
                    "bowling_team": self.match.current_bowling_team,
                    "batter": self.match.striker,
                    "bowler": self.match.current_bowler,
                    "outcome": outcome,
                },
            ))

            prefix = "(Free Hit) " if outcome_was_free_hit else ""
            self.logger.ball(prefix + format_ball_commentary(
                delivery, is_super_over=getattr(self.match, 'is_super_over', False)
            ))

            if outcome.is_wicket:
                over_wickets += 1
                if self.match.current_batting_team.total_wickets < max_wickets:
                    next_batter = self.match.current_batting_team.get_next_batter(
                        self.match.striker, self.match.non_striker
                    )
                    if next_batter:
                        self.match.striker = next_batter
                    else:
                        self.logger.warn(
                            f"[InningsSimulator] No next batter available after wicket "
                            f"in inning {self.match.current_inning} — innings may end prematurely."
                        )
            elif outcome.runs_batter % 2 != 0:
                self.match.striker, self.match.non_striker = (
                    self.match.non_striker, self.match.striker
                )

            if should_terminate and should_terminate():
                break

        return over_runs, over_wickets
