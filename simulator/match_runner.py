"""
MatchRunner - orchestrates a single cricket match simulation.

Parallels TournamentEngine for single-match use.

Usage:
    runner = MatchRunner.from_config("match_config.json")
    runner.run()
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from db.stats_repository import StatsRepository
from simulator.admin_settings import get_admin_settings
from simulator.engines.engine_factory import EngineFactory
from simulator.entities.match import SimulationMatch
from simulator.entities.rules import MatchRules
from simulator.entities.team import MatchTeam
from simulator.logger import set_console_level
from simulator.match_logger import MatchLogger
from simulator.predictors.factory import (
    FORMAT_SETTINGS, OutcomeStrategyFactory, BowlingStrategyFactory,
    resolve_player, resolve_player_by_id, resolve_venue,
)
from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy import ERA_NORMALIZE_ALL
from db.entities.tournament import Tournament


class MatchRunner:

    def __init__(
        self,
        config: dict,
        repo: Optional[StatsRepository] = None,
        silent: bool = False,
    ):
        self._config = config
        self._repo   = repo or StatsRepository()
        self._silent = silent

        MatchLogger.SILENT = silent
        set_console_level(logging.CRITICAL if silent else logging.WARNING)

        fmt = MatchRules.get_unified_format(
            config.get("format") or config.get("match_format", "T20")
        )
        if fmt not in FORMAT_SETTINGS:
            raise ValueError(f"Unknown format '{fmt}'. Must be one of: {list(FORMAT_SETTINGS)}")
        self._fmt = fmt

        admin = get_admin_settings()
        self._outcome_strat = OutcomeStrategyFactory.for_name(
            config.get("ball_outcome_strategy") or admin.default_outcome_strategy, fmt
        )
        self._bowling_strat = BowlingStrategyFactory.for_name(
            config.get("bowling_strategy") or admin.default_bowling_strategy, fmt
        )

    @classmethod
    def from_config(cls, path: str, **kwargs) -> "MatchRunner":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f), **kwargs)

    def run(self) -> SimulationMatch:
        match  = self._build_match()
        engine = EngineFactory.create(match, self._outcome_strat, self._bowling_strat)
        engine.simulate()
        return match

    # ── Match construction ─────────────────────────────────────────────────────

    @staticmethod
    def build_match(config: dict, repo: StatsRepository) -> SimulationMatch:
        """
        Construct a SimulationMatch from a config dict.

        Supports two key styles:
          - 'format' / 'team_a' / 'team_b'    (match_config.json native)
          - 'match_format' / 'team1' / 'team2' (validation-script compat)
        """
        fmt = MatchRules.get_unified_format(
            config.get("format") or config.get("match_format", "T20")
        )
        fmt_settings = dict(FORMAT_SETTINGS[fmt])

        team_a_cfg = config.get("team_a") or config.get("team1", {})
        team_b_cfg = config.get("team_b") or config.get("team2", {})

        def _resolve(p):
            return resolve_player_by_id(repo, p) if isinstance(p, int) else resolve_player(repo, p)

        team_a = MatchTeam(
            id=1,
            name=team_a_cfg.get("name", "Team A"),
            players=[_resolve(p) for p in team_a_cfg.get("players", [])],
            primary_color=team_a_cfg.get("primary_color"),
            secondary_color=team_a_cfg.get("secondary_color"),
        )
        team_b = MatchTeam(
            id=2,
            name=team_b_cfg.get("name", "Team B"),
            players=[_resolve(p) for p in team_b_cfg.get("players", [])],
            primary_color=team_b_cfg.get("primary_color"),
            secondary_color=team_b_cfg.get("secondary_color"),
        )
        venue = resolve_venue(repo, config.get("venue"))
        _era = config.get("era_normalize_contexts")
        match = SimulationMatch(
            id=config.get("match_id", 1),
            home_team=team_a,
            away_team=team_b,
            venue=venue,
            match_format=fmt,
            balls_per_over=6,
            era_normalize_contexts=list(ERA_NORMALIZE_ALL) if _era is None else _era,
            **fmt_settings,
        )
        # Default tournament context to IPL for T20 matches without explicit tournament
        if fmt == "T20" and match.tournament is None:
            row = repo.get_tournament_by_name("IPL")
            if row:
                t_id, t_name, t_season = row
                match.tournament = Tournament(name=t_name, season=t_season or "", id=t_id)
        return match

    def _build_match(self) -> SimulationMatch:
        return MatchRunner.build_match(self._config, self._repo)
