"""
TournamentEngine — orchestrates a complete cricket tournament simulation.

Flow:
  1. Load config → build fixture list
  2. Pre-load all player and venue caches (single DB round-trip per team batch)
  3. Run group-stage fixtures one by one:
     a. Simulate match
     b. Update points table
     c. Record stats for leaderboards
     d. Compute POTM, display result
     e. Print scorecard
  4. Determine playoff qualifiers from standings
  5. Run playoff fixtures (with bracket propagation)
  6. Print final points table, leaderboards, POTT, and tournament winner

Usage:
  engine = TournamentEngine.from_config("tournament_config.json")
  engine.run()
"""

from __future__ import annotations

import logging
import time
import random
from typing import Dict, List, Optional, Tuple

from db.entities.tournament import Tournament
from db.stats_repository import StatsRepository
from simulator.entities.match import SimulationMatch
from simulator.entities.player import Player
from simulator.entities.rules import MatchRules
from simulator.entities.team import MatchTeam
from simulator.engines.engine_factory import EngineFactory
from simulator.logger import set_console_level, get_logger, log_context

_log = get_logger()
from simulator.match_logger import MatchLogger
from simulator.presentation.formatters import print_match_result, print_match_scorecard
from simulator.strategies.factory import (
    FORMAT_SETTINGS,
    OutcomeStrategyFactory,
    BowlingStrategyFactory,
    resolve_player,
    resolve_player_by_id,
    resolve_venue,
)
from simulator.tournament.awards import MatchAwards, TournamentAwards
from simulator.tournament.config import Fixture, TournamentConfig, load_tournament_config
from simulator.tournament.leaderboards import TournamentLeaderboards
from simulator.tournament.points_table import PointsTable
from simulator.tournament.presenter import Presenter
from simulator.tournament.scheduler import generate_fixtures, generate_playoffs


class TournamentEngine:

    def __init__(
        self,
        config: TournamentConfig,
        repo: Optional[StatsRepository] = None,
        seed: Optional[int] = None,
        silent: bool = False,
    ):
        if len(config.teams) < 4:
            raise ValueError(f"Tournament requires at least 4 teams, got {len(config.teams)}")
        self._config    = config
        self._repo      = repo or StatsRepository()
        self._rng       = random.Random(seed)
        self._silent    = silent
        self._presenter = Presenter(config)

        # Suppress sim engine console output — presenter owns all console rendering.
        MatchLogger.SILENT = True
        set_console_level(logging.CRITICAL if silent else logging.WARNING)

        self._fmt          = MatchRules.get_unified_format(config.format)
        self._fmt_settings = dict(FORMAT_SETTINGS[self._fmt])

        # Strategies are shared across all matches; init_model() extends caches per match.
        self._outcome_strat = OutcomeStrategyFactory.for_name(config.outcome_strategy, self._fmt)
        self._bowling_strat = BowlingStrategyFactory.for_name(config.bowling_strategy, self._fmt)

        self._player_cache: Dict[str, Player] = {}
        self._tournament: Optional[Tournament] = self._resolve_tournament(config.tournament_name)

        self._points_table = PointsTable([t.name for t in config.teams])
        self._leaderboards = TournamentLeaderboards()
        self._tourn_awards = TournamentAwards()

        self._match_counter = 0
        self._results: List[dict] = []

    @classmethod
    def from_config(cls, path: str, **kwargs) -> TournamentEngine:
        config = load_tournament_config(path)
        return cls(config, **kwargs)

    # ── Public entry point ─────────────────────────────────────────────────────

    def run(self) -> None:
        cfg = self._config
        p   = self._presenter

        if not self._silent:
            p.print_tournament_header()

        self._preload_players()
        self._prewarm_strategies()

        fixtures = generate_fixtures(cfg, rng=self._rng)
        if not self._silent:
            print(f"  Group stage: {len(fixtures)} matches\n")

        for fixture in fixtures:
            self._run_fixture(fixture, stage="group")

        if not self._silent:
            p.print_points_table(self._points_table)

        playoff_fmt = cfg.playoffs.format
        if playoff_fmt != "none":
            standings_order  = [r.name for r in self._points_table.standings()]
            playoff_fixtures = generate_playoffs(cfg, standings_order, self._match_counter + 1)
            winner = self._run_playoffs(playoff_fixtures)
            if not self._silent and winner:
                print(f"\n  Tournament winner: {p._bold_name(winner)}\n")
        else:
            winner = self._points_table.standings()[0].name
            if not self._silent:
                print(f"\n  Tournament winner (most points): {p._bold_name(winner)}\n")

        if not self._silent:
            p.print_leaderboards(self._leaderboards)
            p.print_pott(self._tourn_awards)

    # ── Group stage ────────────────────────────────────────────────────────────

    def _run_fixture(self, fixture: Fixture, stage: str = "group") -> Optional[str]:
        """Simulate one fixture and update all state. Returns winner name or None."""
        self._match_counter += 1
        cfg = self._config
        p   = self._presenter

        home_cfg = cfg.team_by_name.get(fixture.home)
        away_cfg = cfg.team_by_name.get(fixture.away)
        if home_cfg is None or away_cfg is None:
            return None   # TBD placeholder — playoff slot not yet filled

        home_players = [
            self._player_cache.get(p) or (
                resolve_player_by_id(self._repo, p) if isinstance(p, int) else resolve_player(self._repo, p)
            )
            for p in home_cfg.players
        ]
        away_players = [
            self._player_cache.get(p) or (
                resolve_player_by_id(self._repo, p) if isinstance(p, int) else resolve_player(self._repo, p)
            )
            for p in away_cfg.players
        ]

        venue_name = fixture.venue
        if not venue_name and self._config.venue_names:
            import random
            venue_name = random.choice(self._config.venue_names)
        venue = resolve_venue(self._repo, venue_name) if venue_name else None

        match = SimulationMatch(
            id=self._match_counter,
            home_team=MatchTeam(
                id=1, name=fixture.home, players=home_players,
                primary_color=home_cfg.primary_color,
                secondary_color=home_cfg.secondary_color,
            ),
            away_team=MatchTeam(
                id=2, name=fixture.away, players=away_players,
                primary_color=away_cfg.primary_color,
                secondary_color=away_cfg.secondary_color,
            ),
            venue=venue,
            tournament=self._tournament,
            match_format=self._fmt,
            balls_per_over=6,
            era_normalize_contexts=self._config.era_normalize_contexts,
            **self._fmt_settings,
        )

        with log_context(match_id=self._match_counter):
            # Extend strategy caches for any players not seen in previous matches.
            t0 = time.perf_counter()
            self._outcome_strat.init_model(match)
            t1 = time.perf_counter()
            self._bowling_strat.init_model(match)
            t2 = time.perf_counter()

            engine = EngineFactory.create(match, self._outcome_strat, self._bowling_strat)
            engine.simulate()
            t3 = time.perf_counter()

            _log.warning("[Tournament] Match %d  outcome_init=%.3fs  bowling_init=%.3fs  simulate=%.3fs  total=%.3fs",
                         self._match_counter, t1 - t0, t2 - t1, t3 - t2, t3 - t0)

            winner, pt_result = self._read_result(match, fixture.home, fixture.away)

            summary = match.result.team_innings_summary if match.result else {}
            home_runs,  home_balls = summary.get(fixture.home, (0, 0))
            away_runs,  away_balls = summary.get(fixture.away, (0, 0))

            if stage == "group":
                self._points_table.record_result(
                    fixture.home, fixture.away, pt_result,
                    home_runs, home_balls, away_runs, away_balls,
                )

            self._leaderboards.add_match(match, fixture.home, fixture.away)

            awards = MatchAwards()
            awards.record_from_match(match)
            potm = awards.potm()
            self._tourn_awards.add_match(awards)

            if not self._silent:
                print_match_scorecard(match)
                print_match_result(
                    match,
                    label=getattr(fixture, "match_label", "") or f"Match {self._match_counter}",
                    venue=fixture.venue or "",
                )
                if potm:
                    p.print_potm(potm, self._match_counter)

            self._results.append({
                "match_number": self._match_counter,
                "home":         fixture.home,
                "away":         fixture.away,
                "winner":       winner,
                "result":       match.result.description if match.result else "No result",
                "stage":        stage,
            })

            self._on_fixture_complete(match, fixture, stage)

        return winner

    def _on_fixture_complete(self, match: SimulationMatch, fixture: Fixture, stage: str) -> None:
        """Hook called after each fixture completes. Override to add persistence or side effects."""
        pass

    def get_mvp_leaderboard(self, top_n: int = 9999):
        """Return the full tournament MVP leaderboard after engine.run() completes."""
        return self._tourn_awards.leaderboard(top_n)

    # ── Playoffs ──────────────────────────────────────────────────────────────

    def _run_playoffs(self, fixtures: List[Fixture]) -> Optional[str]:
        """Run playoff fixtures with bracket propagation. Returns the tournament winner."""
        fmt     = self._config.playoffs.format
        results: Dict[str, Optional[str]] = {}

        for fixture in fixtures:
            fixture = self._resolve_playoff_slot(fixture, results, fmt)
            winner  = self._run_fixture(fixture, stage="playoff")
            if fixture.match_label:
                results[fixture.match_label] = winner

        return results.get("Final")

    def _home_venue(self, team_name: str) -> Optional[str]:
        """Return the configured home venue name for a team, or None."""
        team = self._config.team_by_name.get(team_name)
        return (team.home_venue or None) if team else None

    def _higher_placed_venue(self, team_a: str, team_b: str) -> Optional[str]:
        """Return home venue of whichever team finished higher in the group stage."""
        standings = [r.name for r in self._points_table.standings()]
        rank_a = standings.index(team_a) if team_a in standings else 999
        rank_b = standings.index(team_b) if team_b in standings else 999
        return self._home_venue(team_a if rank_a <= rank_b else team_b)

    def _resolve_playoff_slot(
        self,
        fixture: Fixture,
        results: Dict[str, Optional[str]],
        fmt: str,
    ) -> Fixture:
        """Fill TBD team slots from earlier bracket results and assign home-venue advantage."""
        home = fixture.home
        away = fixture.away
        venue = fixture.venue  # already set for known-team fixtures

        if fmt == "ipl":
            if fixture.match_label == "Qualifier 2":
                q1_winner   = results.get("Qualifier 1")
                elim_winner = results.get("Eliminator")
                standings   = [r.name for r in self._points_table.standings()]
                q1_loser    = standings[1] if q1_winner == standings[0] else standings[0]
                home  = q1_loser
                away  = elim_winner or "TBD"
                venue = self._home_venue(home)   # Q1 loser has home advantage
            elif fixture.match_label == "Final":
                home  = results.get("Qualifier 1") or "TBD"
                away  = results.get("Qualifier 2") or "TBD"
                venue = self._home_venue(home)   # Q1 winner has home advantage

        elif fmt == "semis_final":
            if fixture.match_label == "Final":
                home  = results.get("Semi-final 1") or "TBD"
                away  = results.get("Semi-final 2") or "TBD"
                # Higher group-stage finisher gets home advantage
                if home != "TBD" and away != "TBD":
                    venue = self._higher_placed_venue(home, away)

        elif fmt == "quarters_semis_final":
            if fixture.match_label == "SF 1":
                home  = results.get("QF 1") or "TBD"
                away  = results.get("QF 2") or "TBD"
            elif fixture.match_label == "SF 2":
                home  = results.get("QF 3") or "TBD"
                away  = results.get("QF 4") or "TBD"
            elif fixture.match_label == "Final":
                home  = results.get("SF 1") or "TBD"
                away  = results.get("SF 2") or "TBD"
            if fixture.match_label in ("SF 1", "SF 2", "Final") and home != "TBD" and away != "TBD":
                venue = self._higher_placed_venue(home, away)

        return Fixture(
            home=home or fixture.home,
            away=away or fixture.away,
            venue=venue,
            match_number=fixture.match_number,
            match_label=fixture.match_label,
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _resolve_tournament(self, name: str) -> Optional[Tournament]:
        row = self._repo.get_tournament_by_name(name)
        if not row:
            return None
        t_id, t_name, season = row
        return Tournament(name=t_name, season=season or "", id=t_id)

    def _preload_players(self) -> None:
        all_ids = {p for t in self._config.teams for p in t.players}
        for pid in all_ids:
            if pid not in self._player_cache:
                if isinstance(pid, int):
                    self._player_cache[pid] = resolve_player_by_id(self._repo, pid)
                else:
                    self._player_cache[pid] = resolve_player(self._repo, pid)

    def _prewarm_strategies(self) -> None:
        """Pre-warm both strategy caches for every tournament player before match 1,
        plus every distinct venue this tournament could use.

        The venue priming matters beyond just avoiding a live DB round-trip on
        whichever match first touches a new venue: EnhancedStrategy's venue
        context (venue/player_venue/player_country) is refreshed on every
        init_model call, keyed off whatever venue the match it's given
        carries. Priming here with the synthetic warm_match's venue swapped
        to each real venue in turn populates StatsRepository's per-venue
        cache for all of them before any real match runs, so every real
        match's own init_model call — which sees its own real venue — is a
        cache hit rather than a fresh query.
        """
        all_players = [p for p in self._player_cache.values() if p is not None]
        if not all_players:
            return
        t0 = time.perf_counter()
        # Split all players across two synthetic teams so collect_player_ids sees everyone.
        mid = len(all_players) // 2
        warm_match = SimulationMatch(
            id=0,
            home_team=MatchTeam(id=1, name="__warm_home__", players=all_players[:mid] or all_players),
            away_team=MatchTeam(id=2, name="__warm_away__", players=all_players[mid:] or []),
            match_format=self._fmt,
            balls_per_over=6,
            **{k: v for k, v in self._fmt_settings.items() if k != 'era_normalize_contexts'},
        )
        self._outcome_strat.init_model(warm_match)
        self._bowling_strat.init_model(warm_match)

        cfg = self._config
        venue_names = set(cfg.venue_names) | {t.home_venue for t in cfg.teams if t.home_venue}
        primed = 0
        for name in venue_names:
            venue = resolve_venue(self._repo, name)
            if venue:
                warm_match.venue = venue
                self._outcome_strat.init_model(warm_match)
                primed += 1
        warm_match.venue = None

        _log.warning(
            "[Tournament] Pre-warmed strategy caches for %d players and %d/%d venues in %.3fs",
            len(all_players), primed, len(venue_names), time.perf_counter() - t0,
        )

    def _read_result(
        self,
        match: SimulationMatch,
        home: str,
        away: str,
    ) -> Tuple[Optional[str], str]:
        """
        Interpret the engine-set match result.
        Returns (winner_name, points_table_key) where points_table_key is one of
        "home_win" | "away_win" | "tie" | "no_result".
        """
        r = match.result
        if r is None:
            return None, "no_result"
        if r.is_tie:
            return None, "tie"
        if r.is_no_result:
            return None, "no_result"
        pt = "home_win" if r.winner == home else "away_win"
        return r.winner, pt
