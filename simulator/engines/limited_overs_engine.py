from simulator.engines.base_engine import BaseEngine
from simulator.engines.innings_simulator import InningsSimulator
from simulator.engines.super_over_engine import SuperOverEngine
from simulator.entities.match import MatchStatus, MatchResult
from simulator.entities.rules import MatchRules
from simulator.entities.team import MatchTeam


class LimitedOversEngine(BaseEngine):
    """
    Drives ODI and T20 matches: two innings with a fixed over cap and a run chase.
    All ball-by-ball and over-by-over mechanics are handled by InningsSimulator.
    A tied match triggers a super over automatically.
    """

    def simulate(self):
        self._prepare_match_logs()
        team1, team2 = self._execute_toss()

        self._run_inning(inning_num=1, batting_team=team1, bowling_team=team2)

        self._print_innings_summary(self.match.innings[0])
        self.logger.headline(
            f"\n--- Innings Break ---\n"
            f"{team2.name} need {self.match.target_score} runs"
            f" to win in {self.match.overs_per_innings} overs\n"
        )

        self._run_inning(inning_num=2, batting_team=team2, bowling_team=team1)

        self.logger.headline("\n=== Match Complete ===")
        self._print_innings_summary(self.match.innings[1])

        if self._is_tied():
            self._run_super_over(team1, team2)
        else:
            self._print_match_result()

        self.match.status = MatchStatus.COMPLETED
        self.logger.close()
        return self.match

    def _run_inning(self, inning_num: int, batting_team: MatchTeam, bowling_team: MatchTeam):
        inning = self._create_inning(inning_num, batting_team, bowling_team)
        self._set_initial_players()

        sim = InningsSimulator(self.match, self.ball_outcomes, self.logger, self.bowling_strategy)
        sim.run(
            max_overs=self.match.overs_per_innings,
            should_terminate=self._target_reached if inning_num == 2 else None,
        )

        if inning_num == 1:
            self.match.target_score = inning.batting_team.total_runs + 1

    def _target_reached(self) -> bool:
        return (
            self.match.target_score is not None
            and self.match.current_batting_team.total_runs >= self.match.target_score
        )

    def _is_tied(self) -> bool:
        inn1 = self.match.innings[0]
        inn2 = self.match.innings[1]
        return inn1.batting_team.total_runs == inn2.batting_team.total_runs

    def _nrr_summary(self) -> dict:
        """Per-team (runs, NRR-adjusted balls) for the two main-match innings -
        used for points-table/NRR, not the super over (which never counts toward it)."""
        max_balls = self.match.overs_per_innings * 6 if self.match.overs_per_innings else None
        summary = {}
        for inn in (self.match.innings[0], self.match.innings[1]):
            bt = inn.batting_team
            adj_balls = MatchRules.nrr_adjusted_balls(bt.total_balls, bt.total_wickets, max_balls)
            summary[bt.name] = (bt.total_runs, adj_balls)
        return summary

    def _run_super_over(self, team1: MatchTeam, team2: MatchTeam):
        repo = getattr(self.bowling_strategy, 'repo', None)
        so_engine = SuperOverEngine(
            match=self.match,
            ball_outcomes=self.ball_outcomes,
            bowling_strategy=self.bowling_strategy,
            logger=self.logger,
            repo=repo,
        )
        # In real cricket, the team that batted SECOND in the main match bats FIRST in the super over.
        so_result = so_engine.run(
            team1=team2,
            team2=team1,
            team1_inning=self.match.innings[1],
            team2_inning=self.match.innings[0],
        )
        # Propagate super-over outcome to match.result so the tournament layer can read it.
        summary = self._nrr_summary()
        if so_result.winner:
            # winner name is the team with more super-over runs
            so_winner = (so_result.batting_second_team
                         if so_result.batting_second_runs > so_result.batting_first_runs
                         else so_result.batting_first_team)
            self.match.result = MatchResult(winner=so_winner, description=so_result.winner,
                                            team_innings_summary=summary)
        else:
            self.match.result = MatchResult(winner=None, description="Super Over Tied",
                                            is_tie=True, team_innings_summary=summary)

    def _print_match_result(self):
        inn1 = self.match.innings[0]
        inn2 = self.match.innings[1]
        summary = self._nrr_summary()
        if inn2.batting_team.total_runs >= self.match.target_score:
            winner = inn2.batting_team.name
            wkts   = 10 - inn2.batting_team.total_wickets
            desc   = f"{winner} won by {wkts} wicket{'s' if wkts != 1 else ''}"
            self.match.result = MatchResult(winner=winner, description=desc,
                                            team_innings_summary=summary)
        elif inn1.batting_team.total_runs > inn2.batting_team.total_runs:
            winner = inn1.batting_team.name
            margin = inn1.batting_team.total_runs - inn2.batting_team.total_runs
            desc   = f"{winner} won by {margin} run{'s' if margin != 1 else ''}"
            self.match.result = MatchResult(winner=winner, description=desc,
                                            team_innings_summary=summary)
        else:
            self.match.result = MatchResult(winner=None, description="Match Tied",
                                            is_tie=True, team_innings_summary=summary)
        self.logger.headline(f"*** {self.match.result.description}! ***")
