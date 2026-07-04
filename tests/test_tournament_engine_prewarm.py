"""
Tests for TournamentEngine._prewarm_strategies' venue-priming loop
(simulator/tournament/engine.py).

Part of the venue-context fix: EnhancedStrategy's venue_cache/player_venue_cache
/player_country_cache now refresh on every init_model call rather than only
the first, but real matches only ever get a cache HIT if every distinct venue
the tournament could use was already resolved before match 1. This is what
_prewarm_strategies' venue loop is for — these tests verify it actually finds
and primes every distinct venue, not just the first one.

No live DB connection required — StatsRepository is bypassed via conn=None,
resolve_venue is monkeypatched, and the two strategies are replaced with
MagicMocks so we only assert on how _prewarm_strategies drives them.
"""
from unittest.mock import MagicMock, patch

import simulator.tournament.engine as engine_mod
from db.entities.venue import Venue
from db.stats_repository import StatsRepository
from simulator.entities.player import Player
from simulator.tournament.config import (
    PlayoffConfig, ScheduleConfig, TeamConfig, TournamentConfig, VenueConfig,
)
from simulator.tournament.engine import TournamentEngine


def _make_config(venues, teams_with_home_venues=()):
    teams = [
        TeamConfig(name=f"Team {i}", short_name=f"T{i}", players=[], home_venue=hv)
        for i, hv in enumerate(teams_with_home_venues or [None, None, None, None])
    ]
    return TournamentConfig(
        tournament_name="Test Cup",
        format="T20",
        gender="male",
        season="2025",
        venues=[VenueConfig(name=v) for v in venues],
        teams=teams,
        schedule=ScheduleConfig(type="round_robin"),
        playoffs=PlayoffConfig(format="none"),
    )


def _fake_resolve_venue(known_venues):
    def _resolve(repo, name):
        vid = known_venues.get(name)
        if vid is None:
            return None
        return Venue.builder().with_id(vid).with_name(name).with_country("India").build()
    return _resolve


def _make_engine(config) -> TournamentEngine:
    """_prewarm_strategies mutates and reuses a single warm_match object
    across calls (matching production's real behavior — each real init_model
    call reads match.venue synchronously before the next iteration mutates
    it again). A MagicMock just stores a reference to that object, so
    call_args_list would only ever show its FINAL state. Capture venue ids
    at call time via side_effect instead."""
    fake_repo = StatsRepository.__new__(StatsRepository)
    fake_repo.conn = None
    engine = TournamentEngine(config, repo=fake_repo, silent=True)
    engine._player_cache = {"p1": Player(id=1, name="P1"), "p2": Player(id=2, name="P2")}

    engine.outcome_venue_ids_seen = []
    engine._outcome_strat = MagicMock(
        init_model=MagicMock(side_effect=lambda m: engine.outcome_venue_ids_seen.append(
            m.venue.id if m.venue else None
        ))
    )
    engine._bowling_strat = MagicMock()
    return engine


class TestPrewarmVenuePriming:

    def test_primes_every_distinct_configured_venue(self):
        config = _make_config(venues=["Wankhede Stadium", "Eden Gardens"])
        engine = _make_engine(config)

        with patch.object(engine_mod, "resolve_venue",
                           _fake_resolve_venue({"Wankhede Stadium": 42, "Eden Gardens": 99})):
            engine._prewarm_strategies()

        venue_ids_seen = {v for v in engine.outcome_venue_ids_seen if v is not None}
        assert venue_ids_seen == {42, 99}

    def test_includes_team_home_venues_not_just_configured_venues(self):
        config = _make_config(venues=["Wankhede Stadium"], teams_with_home_venues=["Chepauk", None, None, None])
        engine = _make_engine(config)

        with patch.object(engine_mod, "resolve_venue",
                           _fake_resolve_venue({"Wankhede Stadium": 42, "Chepauk": 7})):
            engine._prewarm_strategies()

        venue_ids_seen = {v for v in engine.outcome_venue_ids_seen if v is not None}
        assert venue_ids_seen == {42, 7}

    def test_unresolvable_venue_name_is_skipped_not_fatal(self):
        config = _make_config(venues=["Made Up Ground"])
        engine = _make_engine(config)

        with patch.object(engine_mod, "resolve_venue", _fake_resolve_venue({})):
            engine._prewarm_strategies()  # must not raise

        assert all(v is None for v in engine.outcome_venue_ids_seen)

    def test_bowling_strategy_is_not_primed_per_venue(self):
        """Bowling model has no precomputed venue-specific data at all (see
        base.py's venue_over_freq_cache always being {}) — only the outcome
        strategy needs the per-venue priming loop."""
        config = _make_config(venues=["Wankhede Stadium", "Eden Gardens"])
        engine = _make_engine(config)

        with patch.object(engine_mod, "resolve_venue",
                           _fake_resolve_venue({"Wankhede Stadium": 42, "Eden Gardens": 99})):
            engine._prewarm_strategies()

        assert engine._bowling_strat.init_model.call_count == 1

    def test_deduplicates_venue_appearing_as_both_configured_and_home(self):
        config = _make_config(venues=["Wankhede Stadium"], teams_with_home_venues=["Wankhede Stadium", None, None, None])
        engine = _make_engine(config)

        with patch.object(engine_mod, "resolve_venue",
                           _fake_resolve_venue({"Wankhede Stadium": 42})):
            engine._prewarm_strategies()

        venue_calls = [v for v in engine.outcome_venue_ids_seen if v is not None]
        assert len(venue_calls) == 1
