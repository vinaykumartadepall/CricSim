from simulator.engines.base_engine import BaseEngine
from simulator.engines.innings_simulator import InningsSimulator
from simulator.entities.match import MatchStatus, MatchResult
from simulator.entities.team import MatchTeam

_FOLLOW_ON_THRESHOLD = 200


class TestMatchEngine(BaseEngine):
    """
    Drives Test matches: four innings with a 450-over global cap, session breaks,
    follow-on, and innings-victory logic. All ball-by-ball mechanics are in InningsSimulator.
    """

    def __init__(self, match, ball_outcome_strategy, bowling_strategy=None):
        super().__init__(match, ball_outcome_strategy, bowling_strategy)
        self.match_overs_total = 0

    def simulate(self):
        self._prepare_match_logs()
        team1, team2 = self._execute_toss()

        self._run_inning(1, team1, team2)
        if self._check_match_completed():
            return self._finalize_match()

        self._run_inning(2, team2, team1)
        if self._check_match_completed():
            return self._finalize_match()

        inn1 = self.match.innings[0]
        inn2 = self.match.innings[1]
        lead = inn1.batting_team.total_runs - inn2.batting_team.total_runs

        if lead >= _FOLLOW_ON_THRESHOLD:
            self.match.follow_on_enforced = True
            self.logger.headline(
                f"\n--- Follow-on enforced. {team2.name} require {lead} more runs "
                f"to avoid the follow-on. {team2.name} batting again. ---\n"
            )

            self._run_inning(3, team2, team1)
            if self._check_match_completed():
                return self._finalize_match()

            inn3 = self.match.innings[2]
            team1_total = inn1.batting_team.total_runs
            team2_total = inn2.batting_team.total_runs + inn3.batting_team.total_runs

            if team1_total > team2_total:
                # team1 wins by an innings
                return self._finalize_match()

            self.match.target_score = team2_total - team1_total + 1
            self.logger.headline(
                f"\n--- {team1.name} need {self.match.target_score} runs to win ---\n"
            )
            self._run_inning(4, team1, team2)
        else:
            self._run_inning(3, team1, team2)
            if self._check_match_completed():
                return self._finalize_match()

            inn3 = self.match.innings[2]
            # Team2 wins by innings if their single innings exceeds team1's combined total
            if inn2.batting_team.total_runs > inn1.batting_team.total_runs + inn3.batting_team.total_runs:
                return self._finalize_match()

            self.match.target_score = (
                inn1.batting_team.total_runs + inn3.batting_team.total_runs
                - inn2.batting_team.total_runs + 1
            )
            self.logger.headline(
                f"\n--- {team2.name} need {self.match.target_score} runs to win ---\n"
            )
            self._run_inning(4, team2, team1)

        return self._finalize_match()

    def _run_inning(self, inning_num: int, batting_team: MatchTeam, bowling_team: MatchTeam):
        inning = self._create_inning(inning_num, batting_team, bowling_team)
        self._set_initial_players()

        remaining_global_overs = 450 - self.match_overs_total
        sim = InningsSimulator(self.match, self.ball_outcomes, self.logger, self.bowling_strategy)
        overs_played = sim.run(
            max_overs=remaining_global_overs,
            should_terminate=self._target_reached if inning_num == 4 else None,
            on_over_complete=self._on_over_complete,
        )
        self.match_overs_total += overs_played

        self._print_innings_summary(inning)
        # Show lead/trail after innings 1 and 2; target announcement handles innings 3.
        if inning_num <= 2:
            self.logger.headline(self._lead_trail_message())
        self.logger.headline(f"\n--- End of Inning {inning_num} ---\n")

    def _target_reached(self) -> bool:
        return (
            self.match.target_score is not None
            and self.match.current_batting_team.total_runs >= self.match.target_score
        )

    def _on_over_complete(self, innings_overs: int, over_runs: int, over_wickets: int):
        """Triggers session breaks (Lunch/Tea/Stumps) every 30 overs of global match time."""
        global_overs = self.match_overs_total + innings_overs
        if global_overs % 30 != 0:
            return

        session_id = (global_overs // 30) % 3
        day = ((global_overs - 1) // 90) + 1
        label = {1: "Lunch", 2: "Tea"}.get(session_id, "Stumps")

        self.logger.headline(f"\n=== Day {day}: {label} ===\n")
        self._print_innings_summary(self.match.innings[-1])

        situation = self._match_situation_message()
        if situation:
            self.logger.headline(situation)

    def _lead_trail_message(self) -> str:
        """Returns a 'X lead/trail by N runs' string based on all innings scored so far."""
        innings = self.match.innings
        if not innings:
            return ""

        first_team = innings[0].batting_team.name
        second_team = innings[0].bowling_team.name

        first_runs  = sum(inn.batting_team.total_runs for inn in innings if inn.batting_team.name == first_team)
        second_runs = sum(inn.batting_team.total_runs for inn in innings if inn.batting_team.name == second_team)

        diff = first_runs - second_runs
        if diff > 0:
            return f"{first_team} lead by {diff} run{'s' if diff != 1 else ''}"
        if diff < 0:
            return f"{second_team} lead by {abs(diff)} run{'s' if abs(diff) != 1 else ''}"
        return "Scores are level"

    def _match_situation_message(self) -> str:
        """
        Returns the context line shown at session breaks:
        lead/trail for innings 1-3, runs needed for innings 4.
        """
        if self.match.current_inning == 4 and self.match.target_score:
            runs_needed = self.match.target_score - self.match.current_batting_team.total_runs
            return f"{self.match.current_batting_team.name} need {runs_needed} more runs to win"
        return self._lead_trail_message()

    def _check_match_completed(self) -> bool:
        return self.match_overs_total >= 450

    def _finalize_match(self):
        self.logger.headline("\n=== Match Complete ===")

        innings = self.match.innings
        # Keyed by team id, not name - InningTeam.id is the in-memory MatchTeam
        # id (always distinct: match_runner assigns 1/2), whereas names can
        # collide (multiplayer display names double as team names). Deduping by
        # name collapsed both teams into one entry here, crashing team_ids[1]
        # below. Room joins now dedupe names, so this is defense in depth:
        # a duplicate from any unforeseen path degrades to ambiguous display
        # text instead of a failed simulation.
        team_ids  = list(dict.fromkeys(inn.batting_team.id for inn in innings))
        id_to_name = {inn.batting_team.id: inn.batting_team.name for inn in innings}
        team_totals = {tid: 0 for tid in team_ids}
        team_balls  = {tid: 0 for tid in team_ids}
        for inn in innings:
            team_totals[inn.batting_team.id] += inn.batting_team.total_runs
            team_balls[inn.batting_team.id]  += inn.batting_team.total_balls

        summary = {id_to_name[tid]: (team_totals[tid], team_balls[tid]) for tid in team_ids}

        if len(innings) == 4:
            # Equal totals / a reached target / an all-out dismissal all decide the match
            # outright - even if the global 450-over cap is hit on the same ball. Only
            # fall back to a draw once none of those decisive conditions hold.
            batting_4th = innings[3].batting_team
            target_reached = bool(self.match.target_score) and batting_4th.total_runs >= self.match.target_score
            all_out = batting_4th.total_wickets >= 10
            totals_equal = team_totals[team_ids[0]] == team_totals[team_ids[1]]

            if totals_equal:
                result = MatchResult(winner=None, description="Match Tied", is_tie=True,
                                     team_innings_summary=summary)
            elif target_reached:
                wkts = 10 - batting_4th.total_wickets
                desc = f"{batting_4th.name} won by {wkts} wicket{'s' if wkts != 1 else ''}"
                result = MatchResult(winner=batting_4th.name, description=desc,
                                     team_innings_summary=summary)
            elif all_out:
                winner_id = max(team_totals, key=team_totals.get)
                margin = abs(team_totals[team_ids[0]] - team_totals[team_ids[1]])
                desc = f"{id_to_name[winner_id]} won by {margin} run{'s' if margin != 1 else ''}"
                result = MatchResult(winner=id_to_name[winner_id], description=desc,
                                     team_innings_summary=summary)
            else:
                result = MatchResult(winner=None, description="Match Drawn", is_no_result=True,
                                     team_innings_summary=summary)
        elif len(innings) <= 3:
            if self.match_overs_total >= 450:
                result = MatchResult(winner=None, description="Match Drawn", is_no_result=True,
                                     team_innings_summary=summary)
            else:
                innings_count = {tid: 0 for tid in team_ids}
                for inn in innings:
                    innings_count[inn.batting_team.id] += 1
                winner_id = next(tid for tid, c in innings_count.items() if c == 1)
                loser_id  = next(tid for tid, c in innings_count.items() if c == 2)
                margin = team_totals[winner_id] - team_totals[loser_id]
                desc = f"{id_to_name[winner_id]} won by an innings and {margin} run{'s' if margin != 1 else ''}"
                result = MatchResult(winner=id_to_name[winner_id], description=desc,
                                     team_innings_summary=summary)
        else:
            result = MatchResult(winner=None, description="Match Drawn", is_no_result=True,
                                 team_innings_summary=summary)

        self.match.result = result
        self.logger.headline(f"*** {result.description}! ***")
        self.match.status = MatchStatus.COMPLETED
        self.logger.close()
        return self.match
