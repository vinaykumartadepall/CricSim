from dataclasses import replace
from typing import Callable, Optional, Tuple

from simulator.entities.delivery import SimulationDelivery
from simulator.entities.match import SimulationMatch
from simulator.entities.rules import MatchRules
from simulator.events import MatchEvent, EventType
from simulator.match_logger import MatchLogger
from simulator.presentation.formatters import format_ball_commentary, format_over_summary
from simulator.predictors.ball_outcome_prediction.strategy_interface import BallOutcomeStrategy
from simulator.predictors.bowling.strategy_interface import BowlingStrategy


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
        is_super_over: bool = False,
    ):
        self.match          = match
        self.ball_outcomes  = ball_outcome_strategy
        self.logger         = logger
        self.bowling_strategy = bowling_strategy
        self._is_super_over = is_super_over

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
                format_over_summary(self.match, self.match.innings[-1], self._is_super_over)
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

            self.match.is_free_hit = is_free_hit
            outcome = self.ball_outcomes.predict_next_ball(self.match)
            this_ball_is_free_hit = is_free_hit

            outcome, is_free_hit = self._apply_free_hit_rules(
                outcome, is_free_hit, free_hit_supported
            )

            is_legal = MatchRules.is_legal_delivery(outcome.extras_type)
            if is_legal:
                self.match.current_ball += 1

            display_ball = self.match.current_ball if is_legal else self.match.current_ball + 1
            over_runs += outcome.runs_batter + outcome.runs_extras

            delivery = self._build_delivery(outcome, display_ball)
            current_inning.deliveries.append(delivery)

            self._publish_ball_event(outcome)

            prefix = "(Free Hit) " if this_ball_is_free_hit else ""
            self.logger.ball(prefix + format_ball_commentary(
                delivery, is_super_over=self._is_super_over
            ))

            if outcome.is_wicket:
                over_wickets += 1
                self._advance_batter_after_wicket(max_wickets)
            elif outcome.runs_batter % 2 != 0:
                self.match.striker, self.match.non_striker = (
                    self.match.non_striker, self.match.striker
                )

            if should_terminate and should_terminate():
                break

        return over_runs, over_wickets

    # ── Delivery helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _apply_free_hit_rules(outcome, is_free_hit: bool, free_hit_supported: bool):
        """
        Cancels wickets on a free-hit (except run-outs) and returns the updated free-hit state.

        State transitions:
          no-ball              → next ball is a free hit
          legal delivery       → free-hit state ends
          wide (illegal, no NB)→ free-hit state carries over (wide doesn't consume it)
        """
        if free_hit_supported and is_free_hit and outcome.is_wicket and outcome.wicket_kind != "run out":
            outcome = replace(outcome, is_wicket=False, wicket_kind=None, outcome_player=None)

        if free_hit_supported and MatchRules.is_free_hit_awarded(outcome.extras_type):
            next_free_hit = True
        elif MatchRules.is_legal_delivery(outcome.extras_type):
            next_free_hit = False
        else:
            # Wide during a free hit carries the state; but if free hits aren't supported
            # there is never a legitimate free-hit state, so always reset to False.
            next_free_hit = is_free_hit if free_hit_supported else False

        return outcome, next_free_hit

    def _build_delivery(self, outcome, display_ball: int) -> SimulationDelivery:
        return SimulationDelivery(
            inning_number  = self.match.current_inning,
            over_number    = self.match.current_over,
            ball_number    = display_ball,
            batter         = self.match.striker,
            bowler         = self.match.current_bowler,
            non_striker    = self.match.non_striker,
            runs_batter    = outcome.runs_batter,
            runs_extras    = outcome.runs_extras,
            is_wicket      = outcome.is_wicket,
            wicket_kind    = outcome.wicket_kind,
            extras_type    = outcome.extras_type,
            outcome_player = outcome.outcome_player,
        )

    def _publish_ball_event(self, outcome) -> None:
        self.match.event_bus.publish(MatchEvent(
            type=EventType.BALL_BOWLED,
            data={
                "match":        self.match,
                "inning":       self.match.current_inning,
                "batting_team": self.match.current_batting_team,
                "bowling_team": self.match.current_bowling_team,
                "batter":       self.match.striker,
                "bowler":       self.match.current_bowler,
                "outcome":      outcome,
            },
        ))

    def _advance_batter_after_wicket(self, max_wickets: int) -> None:
        if self.match.current_batting_team.total_wickets < max_wickets:
            next_batter = self.match.current_batting_team.get_next_batter(
                self.match.striker, self.match.non_striker
            )
            if next_batter:
                self.match.striker = next_batter
                next_batter.came_to_crease = True
            else:
                self.logger.warn(
                    f"[InningsSimulator] No next batter available after wicket "
                    f"in inning {self.match.current_inning} - innings may end prematurely."
                )
