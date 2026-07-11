"""
Background simulation worker.

run_match_job and run_tournament_job are called in a ThreadPoolExecutor.
Each job:
  1. Updates status → running
  2. Runs simulation
  3. Persists results via SimulationRepository
  4. Updates status → completed | failed
"""

from __future__ import annotations

from typing import Any, Dict

from db.simulation_repository import SimulationRepository
from db.stats_repository import StatsRepository
from simulator.admin_settings import get_admin_settings
from simulator.logger import get_logger, log_context
from simulator.match_runner import MatchRunner
from simulator.predictors.factory import FORMAT_SETTINGS, resolve_venue
from simulator.awards import MatchAwards
from simulator.tournament.config import TournamentConfig
from simulator.tournament.engine import TournamentEngine
from simulator.tournament.scheduler import generate_fixtures

# logging.getLogger(__name__) ("api.worker") is a different branch of the
# logging hierarchy than get_logger()'s "cricket_sim" - the app's file
# handlers (logs/simulation.log, logs/errors.log) and [sim_id/mN] context
# tagging are only attached to "cricket_sim". Using the stdlib logger here
# meant every logger.exception(...) in this file silently went to Python's
# lastResort stderr handler instead of anywhere durable - including the
# exception that explains why a job actually failed.
logger = get_logger()

# Process-level progress tracker for in-flight tournament jobs, keyed by sim_id.
# In-memory only (see api/main.py's _memory_monitor / _PRECOMPUTED_CACHE for the
# same pattern) - fine because this deploys as a single uvicorn process; a
# multi-worker deployment would need this moved to shared storage instead.
# Populated at job start (everything below is fully known before any match
# runs - see _PLAYOFF_MATCH_COUNTS and _estimate_total_deliveries), updated
# per match, popped on job end.
_TOURNAMENT_PROGRESS: Dict[str, Dict[str, Any]] = {}

# Playoff match count is deterministic from format alone (scheduler.py's
# generate_playoffs) - doesn't depend on standings, so the total is knowable
# before the group stage even starts. Must stay in sync with every branch of
# generate_playoffs; an unrecognized format falls back to 0 there too.
_PLAYOFF_MATCH_COUNTS = {
    "none": 0,
    "two_teams": 1,
    "semis_final": 3,
    "ipl": 4,
    "quarters_semis_final": 7,
}

# Test matches have no fixed overs_per_innings (FORMAT_SETTINGS["Test"] is
# days-based, not over-based) - there's no exact delivery count to compute.
# This is a flavor stat, not a simulation guarantee, so a labeled rough
# estimate (5 days x 90 overs/day, spanning all innings) is good enough.
_TEST_OVERS_ESTIMATE = 5 * 90


def _estimate_total_deliveries(match_format: str, total_matches: int) -> int:
    settings = FORMAT_SETTINGS.get(match_format)
    if match_format == "Test" or not settings or settings.get("overs_per_innings") is None:
        return _TEST_OVERS_ESTIMATE * 6 * total_matches
    return settings["overs_per_innings"] * settings["innings_per_match"] * 6 * total_matches


def get_tournament_progress(sim_id: str) -> Dict[str, Any] | None:
    """Progress snapshot for an in-flight tournament job, or None if sim_id
    isn't a currently-running tournament (single-match job, not yet started,
    or already finished)."""
    return _TOURNAMENT_PROGRESS.get(sim_id)


def run_match_job(sim_id: str, config: dict) -> None:
    with log_context(sim_id=sim_id, match_id=1):
        repo = SimulationRepository()
        try:
            repo.update_status(sim_id, 'running')
            repo.commit()

            stats_repo = StatsRepository()
            runner     = MatchRunner(config, repo=stats_repo, silent=True)
            match      = runner.run()

            # Persist teams
            home_id = repo.save_team(match.home_team)
            away_id = repo.save_team(match.away_team)

            # Venue ID (None if no venue resolved)
            venue_id = match.venue.id if match.venue else None

            match_id = repo.save_match(
                sim_id       = sim_id,
                match_label  = "Match 1",
                sim_match    = match,
                home_team_id = home_id,
                away_team_id = away_id,
                venue_id     = venue_id,
            )

            team_id_map = {
                match.home_team.name: home_id,
                match.away_team.name: away_id,
            }

            for inning in match.innings:
                batting_tid = team_id_map[inning.batting_team.name]
                repo.save_match_players_from_inning(match_id, inning, batting_tid)
                repo.save_deliveries(match_id, inning, team_id_map)

            awards = MatchAwards()
            awards.record_from_match(match)
            repo.save_match_potm(match_id, awards.potm())

            repo.commit()
            repo.update_status(sim_id, 'completed')
            repo.commit()

        except Exception as exc:
            logger.exception("Match simulation %s failed", sim_id)
            try:
                repo.rollback()
            except Exception:
                pass
            repo.update_status(sim_id, 'failed', error=str(exc))
            repo.commit()
        finally:
            repo.close()
            StatsRepository.on_job_end()


def run_tournament_job(
    sim_id: str,
    config: dict,
    user_team_name: str | None = None,
    client_id: str | None = None,
) -> None:
    with log_context(sim_id=sim_id):
        repo = SimulationRepository()
        try:
            repo.update_status(sim_id, 'running')
            repo.commit()

            tc = _build_tournament_config(config)
            stats_repo = StatsRepository()

            total_matches = len(generate_fixtures(tc)) + _PLAYOFF_MATCH_COUNTS.get(tc.playoffs.format, 0)
            _TOURNAMENT_PROGRESS[sim_id] = {
                "completed": 0,
                "total": total_matches,
                "teams": len(tc.teams),
                "total_deliveries": _estimate_total_deliveries(tc.format, total_matches),
                "results": [],
            }

            # Save tournament metadata
            tournament_id = repo.save_tournament(
                sim_id          = sim_id,
                tournament_name = tc.tournament_name,
                season          = tc.season,
                format          = tc.format,
                gender          = tc.gender,
            )

            # Save all teams up-front so we have IDs before matches run
            team_id_map: Dict[str, int] = {}
            for team_cfg in tc.teams:
                from simulator.entities.team import MatchTeam
                dummy = MatchTeam(id=0, name=team_cfg.name,
                                  primary_color=team_cfg.primary_color,
                                  secondary_color=team_cfg.secondary_color)
                team_id_map[team_cfg.name] = repo.save_team(dummy)

            repo.save_tournament_teams(tournament_id, list(team_id_map.values()))

            # Back-fill game_sessions.user_team_id now that simulation.teams rows exist
            if user_team_name and user_team_name in team_id_map and client_id:
                repo.cur.execute(
                    "UPDATE simulation.game_sessions SET user_team_id = %s "
                    "WHERE sim_id = %s AND client_id = %s",
                    (team_id_map[user_team_name], sim_id, client_id),
                )

            repo.commit()

            # Run tournament - intercept each completed match for persistence
            engine = _PersistingTournamentEngine(
                config        = tc,
                repo          = stats_repo,
                sim_repo      = repo,
                sim_id        = sim_id,
                team_id_map   = team_id_map,
                tournament_id = tournament_id,
                silent        = True,
            )
            engine.run()

            mvp_lb = engine.get_mvp_leaderboard()
            if mvp_lb:
                repo.save_player_awards(sim_id, mvp_lb)

            standings = engine.get_final_standings()
            if standings:
                repo.save_final_standings(sim_id, [
                    {
                        "team": r.name, "played": r.played, "won": r.won,
                        "lost": r.lost, "tied": r.tied, "no_result": r.no_result,
                        "points": r.points, "nrr": r.nrr,
                    }
                    for r in standings
                ])

            _cache_leaderboards(repo, sim_id, tournament_id)

            repo.commit()
            repo.update_status(sim_id, 'completed')
            repo.commit()

        except Exception as exc:
            logger.exception("Tournament simulation %s failed", sim_id)
            try:
                repo.rollback()
            except Exception:
                pass
            repo.update_status(sim_id, 'failed', error=str(exc))
            repo.commit()
        finally:
            repo.close()
            StatsRepository.on_job_end()
            _TOURNAMENT_PROGRESS.pop(sim_id, None)


def _build_tournament_config(raw: dict) -> TournamentConfig:
    """Convert the API request dict into a TournamentConfig."""
    from simulator.tournament.config import (
        TournamentConfig, VenueConfig, TeamConfig as TcTeamConfig,
        ScheduleConfig, Fixture, PlayoffConfig, ERA_NORMALIZE_ALL,
    )

    venues = [VenueConfig(name=v['name'], city=v.get('city', ''))
              for v in raw.get('venues', [])]

    teams = []
    for t in raw.get('teams', []):
        teams.append(TcTeamConfig(
            name=t['name'],
            short_name=t.get('short_name', t['name'][:3].upper()),
            players=t.get('players', []),
            home_venue=t.get('home_venue'),
            primary_color=t.get('primary_color', '#1E88E5'),
            secondary_color=t.get('secondary_color', '#FFFFFF'),
        ))

    raw_sched = raw.get('schedule', {'type': 'round_robin'})
    if isinstance(raw_sched, list):
        schedule = [Fixture(home=f['home'], away=f['away'],
                            venue=f.get('venue'), match_number=i + 1)
                    for i, f in enumerate(raw_sched)]
    else:
        schedule = ScheduleConfig(
            type=raw_sched.get('type', 'round_robin'),
            matches_per_pair=raw_sched.get('matches_per_pair', 1),
            neutral_venues=raw_sched.get('neutral_venues', True),
            groups=raw_sched.get('groups'),
            within_matches_per_pair=raw_sched.get('within_matches_per_pair', 1),
            cross_matches_per_pair=raw_sched.get('cross_matches_per_pair', 2),
        )

    raw_po = raw.get('playoffs', {'format': 'none'})
    playoffs = PlayoffConfig(
        format=raw_po.get('format', 'none'),
        top_n=raw_po.get('top_n', 4),
    )

    return TournamentConfig(
        tournament_name=raw.get('tournament_name', 'Cricket Tournament'),
        format=raw.get('format', 'T20'),
        gender=raw.get('gender', 'male'),
        season=raw.get('season', '2025'),
        venues=venues,
        teams=teams,
        schedule=schedule,
        playoffs=playoffs,
        outcome_strategy=raw.get('outcome_strategy') or get_admin_settings().default_outcome_strategy,
        bowling_strategy=raw.get('bowling_strategy') or get_admin_settings().default_bowling_strategy,
        era_normalize_contexts=list(ERA_NORMALIZE_ALL) if raw.get('era_normalize_contexts') is None else raw['era_normalize_contexts'],
    )


def _cache_leaderboards(repo: SimulationRepository, sim_id: str, tournament_id: int) -> None:
    """Compute top-10 snapshot of every leaderboard and store in leaderboard_cache."""
    from db.leaderboard_repository import LeaderboardRepository, _BATTING_SORT, _BOWLING_SORT

    lb = LeaderboardRepository(repo.dict_cursor)

    tasks = (
        [(lb_type, lambda t=lb_type: lb.batting_aggregate(sim_id, t, 10, 0))
         for lb_type in _BATTING_SORT]
        + [('highest-score',       lambda: lb.highest_score(sim_id, 10, 0))]
        + [(lb_type, lambda t=lb_type: lb.bowling_aggregate(sim_id, t, 10, 0))
           for lb_type in _BOWLING_SORT]
        + [('best-bowling-figures', lambda: lb.best_bowling_figures(sim_id, 10, 0))]
        + [('mvp',                  lambda: lb.mvp(sim_id, 10, 0))]
    )

    for lb_type, compute in tasks:
        try:
            entries, _ = compute()
            repo.save_leaderboard_cache(tournament_id, lb_type, entries)
        except Exception:
            logger.exception("Failed to cache leaderboard '%s' for tournament %d", lb_type, tournament_id)


_DB_BATCH_SIZE = 20  # commit to DB after every N matches


class _PersistingTournamentEngine(TournamentEngine):
    """
    Subclass of TournamentEngine that persists each completed match to the
    simulation DB via the _on_fixture_complete hook.
    Writes are batched (every _DB_BATCH_SIZE matches) to reduce commit overhead.
    A final commit in run_tournament_job flushes any remainder.
    """

    def __init__(self, sim_repo: SimulationRepository, sim_id: str,
                 team_id_map: Dict[str, int], tournament_id: int, **kwargs):
        super().__init__(**kwargs)
        self._sim_repo        = sim_repo
        self._sim_id          = sim_id
        self._team_id_map     = team_id_map
        self._tournament_id   = tournament_id
        self._pending_commits = 0

    def _on_fixture_complete(self, match, fixture, stage: str, potm=None) -> None:
        home_name   = fixture.home
        away_name   = fixture.away
        match_label = (getattr(fixture, 'match_label', '') or
                       f"Match {self._match_counter}")

        progress = _TOURNAMENT_PROGRESS.get(self._sim_id)
        if progress is not None:
            progress["completed"] += 1
            if match.result:
                progress["results"].append({
                    "label": match_label,
                    "text": f"{home_name} vs {away_name} - {match.result.description}",
                    "home": home_name,
                    "away": away_name,
                })

        home_sim_id = self._team_id_map.get(home_name)
        away_sim_id = self._team_id_map.get(away_name)

        if home_sim_id is None or away_sim_id is None:
            return  # TBD playoff slot - teams not yet known

        venue_id = match.venue.id if match.venue else None

        try:
            match_id = self._sim_repo.save_match(
                sim_id        = self._sim_id,
                match_label   = match_label,
                sim_match     = match,
                home_team_id  = home_sim_id,
                away_team_id  = away_sim_id,
                venue_id      = venue_id,
                tournament_id = self._tournament_id,
            )
            team_id_map = {home_name: home_sim_id, away_name: away_sim_id}
            for inning in match.innings:
                batting_tid = team_id_map[inning.batting_team.name]
                self._sim_repo.save_match_players_from_inning(match_id, inning, batting_tid)
                self._sim_repo.save_deliveries(match_id, inning, team_id_map)

            self._sim_repo.save_match_potm(match_id, potm)

            self._pending_commits += 1
            if self._pending_commits >= _DB_BATCH_SIZE:
                self._sim_repo.commit()
                self._pending_commits = 0

        except Exception:
            logger.exception("Failed to persist match %s in tournament %s", match_label, self._sim_id)
            self._sim_repo.rollback()
            self._pending_commits = 0
