"""
Super Over smoke test
=====================
Simulates a full match between two squads.  The match target is rigged to the
exact same total as team1 so that innings 2 always ends in a tie, triggering
the super over automatically.

Run from the project root:
    python tests/test_super_over.py [--format T20|ODI] [--gender male|female] [--config match_config.json]
"""

import argparse
import json
import logging
import os
import sys
import time

# Allow running from project root without installing the package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from simulator.logger import configure_logger
from simulator.entities.team import MatchTeam
from simulator.entities.match import SimulationMatch
from simulator.strategies.factory import (
    FORMAT_SETTINGS,
    OutcomeStrategyFactory,
    BowlingStrategyFactory,
    resolve_player,
    resolve_venue,
)
from db.stats_repository import StatsRepository

log = configure_logger(log_dir=os.path.join(os.path.dirname(__file__), "logs"), sim_log_level=logging.DEBUG)

_DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "match_config.json")


def _run_tied_super_over(config_path: str, fmt: str, gender: str):
    """
    Runs a normal match from config but after the main match, directly invokes
    a SuperOverEngine with simulated match innings so we can test player selection
    without having to get lucky with a natural tie.
    """
    from simulator.match_logger import MatchLogger
    from simulator.entities.inning import Inning
    from simulator.entities.inning_team import InningTeam
    from simulator.entities.inning_player import InningPlayer
    from simulator.engines.super_over_engine import SuperOverEngine
    from simulator.engines.innings_simulator import InningsSimulator
    from simulator.entities.match import MatchStatus
    from simulator.events import MatchEventBus

    repo = StatsRepository()

    with open(config_path) as f:
        config = json.load(f)

    team_a_cfg = config["team_a"]
    team_b_cfg = config["team_b"]

    team_a = MatchTeam(
        id=1,
        name=team_a_cfg["name"],
        players=[resolve_player(repo, n) for n in team_a_cfg["players"]],
    )
    team_b = MatchTeam(
        id=2,
        name=team_b_cfg["name"],
        players=[resolve_player(repo, n) for n in team_b_cfg["players"]],
    )
    venue = resolve_venue(repo, config.get("venue"))

    match = SimulationMatch(
        id=config.get("match_id", 99),
        home_team=team_a,
        away_team=team_b,
        venue=venue,
        match_format=fmt,
        balls_per_over=6,
        **FORMAT_SETTINGS[fmt],
    )

    outcome_strategy = OutcomeStrategyFactory.for_name("enhanced", fmt)
    bowling_strategy = BowlingStrategyFactory.for_name("historical", fmt)

    # Init models (required before running any innings)
    log.console("[Test] Initialising models …")
    t = time.perf_counter()
    outcome_strategy.init_model(match)
    bowling_strategy.init_model(match)
    log.console("[Test] Models ready  %.2fs", time.perf_counter() - t)

    match.status = MatchStatus.IN_PROGRESS
    logger = MatchLogger(match_id=match.id)
    logger.headline(f"=== SUPER OVER TEST: {team_a.name} vs {team_b.name} ({fmt}) ===\n")

    # ── Run two real innings ────────────────────────────────────────────────
    from simulator.engines.base_engine import BaseEngine

    class _MinimalEngine(BaseEngine):
        """Helper to get access to _create_inning/_set_initial_players."""
        def simulate(self): pass

    eng = _MinimalEngine(match, outcome_strategy, bowling_strategy)
    eng.logger = logger

    # Innings 1 — team_a bats
    eng._create_inning(1, team_a, team_b)
    eng._set_initial_players()
    sim1 = InningsSimulator(match, outcome_strategy, logger, bowling_strategy)
    sim1.run(max_overs=match.overs_per_innings)
    inn1 = match.innings[0]
    match.target_score = inn1.batting_team.total_runs + 1
    logger.headline(
        f"\n--- Innings break ---\n"
        f"{team_b.name} need {match.target_score} in {match.overs_per_innings} overs\n"
    )

    # Innings 2 — team_b bats, we stop exactly at team_a's total to manufacture a tie
    team_a_total = inn1.batting_team.total_runs
    eng._create_inning(2, team_b, team_a)
    eng._set_initial_players()
    sim2 = InningsSimulator(match, outcome_strategy, logger, bowling_strategy)

    def _tied_or_won():
        return match.current_batting_team.total_runs >= team_a_total

    sim2.run(max_overs=match.overs_per_innings, should_terminate=_tied_or_won)

    # Force the score to be exactly equal so we definitely get a tie
    inn2 = match.innings[1]
    deficit = team_a_total - inn2.batting_team.total_runs
    if deficit > 0:
        # Artificially top up team_b's runs to create an exact tie
        inn2.batting_team.total_runs = team_a_total
        logger.headline(
            f"  [Test] Adjusted {team_b.name} total to {team_a_total} to force a tie.\n"
        )

    logger.headline(
        f"\n=== TIED after 2 innings: "
        f"{team_a.name} {team_a_total} vs {team_b.name} {inn2.batting_team.total_runs} ===\n"
    )

    # ── Super over ─────────────────────────────────────────────────────────
    so_engine = SuperOverEngine(
        match=match,
        ball_outcomes=outcome_strategy,
        bowling_strategy=bowling_strategy,
        logger=logger,
        repo=repo,
    )
    # team_b batted second in the main match → bats first in the super over.
    result = so_engine.run(
        team1=team_b,
        team2=team_a,
        team1_inning=inn2,
        team2_inning=inn1,
    )

    print(f"\nMatch log written to: {logger.file_path}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Super over smoke test")
    parser.add_argument("--config", default=_DEFAULT_CONFIG)
    parser.add_argument("--format", default="T20", choices=["T20", "ODI"])
    parser.add_argument("--gender", default="male", choices=["male", "female"])
    args = parser.parse_args()

    result = _run_tied_super_over(args.config, args.format, args.gender)
    print(f"\nResult: {result.winner or 'Tied!'}")
