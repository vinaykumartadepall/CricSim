"""
Tests for TournamentEngine._fallback_venue_pool (simulator/tournament/engine.py)
- the stage-aware venue pool group-stage vs. playoff fixtures fall back to
when they have no venue already assigned. Playoffs prefer the marquee
`playoff_venue_names` subset when the config sets one; group stage and
configs without a marquee subset behave exactly as before this existed.

No live DB connection required - StatsRepository is bypassed via conn=None,
matching tests/test_tournament_engine_prewarm.py's pattern.
"""
from db.stats_repository import StatsRepository
from simulator.tournament.config import (
    PlayoffConfig, ScheduleConfig, TeamConfig, TournamentConfig, VenueConfig,
)
from simulator.tournament.engine import TournamentEngine


def _make_config(venues, playoff_venue_names=()):
    teams = [TeamConfig(name=f"Team {i}", short_name=f"T{i}", players=[]) for i in range(4)]
    return TournamentConfig(
        tournament_name="Test Cup",
        format="T20",
        gender="male",
        season="2025",
        venues=[VenueConfig(name=v) for v in venues],
        teams=teams,
        schedule=ScheduleConfig(type="round_robin"),
        playoffs=PlayoffConfig(format="none"),
        playoff_venue_names=list(playoff_venue_names),
    )


def _make_engine(config) -> TournamentEngine:
    fake_repo = StatsRepository.__new__(StatsRepository)
    fake_repo.conn = None
    return TournamentEngine(config, repo=fake_repo, silent=True)


class TestFallbackVenuePool:
    def test_playoff_stage_uses_marquee_subset_when_set(self):
        engine = _make_engine(_make_config(
            venues=["Wankhede Stadium", "Eden Gardens", "Obscure Ground"],
            playoff_venue_names=["Melbourne Cricket Ground"],
        ))
        assert engine._fallback_venue_pool("playoff") == ["Melbourne Cricket Ground"]

    def test_playoff_stage_falls_back_to_full_pool_when_marquee_subset_empty(self):
        engine = _make_engine(_make_config(
            venues=["Wankhede Stadium", "Eden Gardens"],
        ))
        assert engine._fallback_venue_pool("playoff") == ["Wankhede Stadium", "Eden Gardens"]

    def test_group_stage_always_uses_full_pool_ignoring_marquee_subset(self):
        engine = _make_engine(_make_config(
            venues=["Wankhede Stadium", "Eden Gardens"],
            playoff_venue_names=["Melbourne Cricket Ground"],
        ))
        assert engine._fallback_venue_pool("group") == ["Wankhede Stadium", "Eden Gardens"]
