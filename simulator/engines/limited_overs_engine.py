from simulator.engines.base_engine import BaseEngine
from simulator.engines.innings_simulator import InningsSimulator
from simulator.entities.match import MatchStatus
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

    def _run_super_over(self, team1: MatchTeam, team2: MatchTeam):
        from db.stats_repository import StatsRepository
        from simulator.engines.super_over_engine import SuperOverEngine

        repo = StatsRepository()
        so_engine = SuperOverEngine(
            match=self.match,
            ball_outcomes=self.ball_outcomes,
            bowling_strategy=self.bowling_strategy,
            logger=self.logger,
            repo=repo,
        )
        # In real cricket, the team that batted SECOND in the main match bats FIRST in the super over.
        so_engine.run(
            team1=team2,
            team2=team1,
            team1_inning=self.match.innings[1],
            team2_inning=self.match.innings[0],
        )

    def _print_match_result(self):
        inn1 = self.match.innings[0]
        inn2 = self.match.innings[1]
        if inn2.batting_team.total_runs >= self.match.target_score:
            res = f"*** {inn2.batting_team.name} won by {10 - inn2.batting_team.total_wickets} wickets! ***"
        elif inn1.batting_team.total_runs > inn2.batting_team.total_runs:
            res = f"*** {inn1.batting_team.name} won by {inn1.batting_team.total_runs - inn2.batting_team.total_runs} runs! ***"
        else:
            res = "*** Match Tied! ***"
        self.logger.headline(res)
