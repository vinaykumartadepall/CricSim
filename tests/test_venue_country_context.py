"""
A1: Venue.country must be the venue's real country (history.countries name,
via country_id) - the key history.player_context_stats / country_stats use.
It used to be venues.city, so the per-batter country context was empty for
every batter at every venue simulations had used, with nothing in the logs.

Also covers the context-coverage logging added alongside the fix: one INFO
line per match, and a once-per-process WARNING when the country key itself
is unknown (vs. a player who simply has no data there, which isn't logged).
"""
from unittest.mock import patch

import pytest

import db.stats_repository as sr_mod
import simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy as strat_mod
from db.entities.venue import Venue
from db.stats_repository import StatsRepository
from simulator.entities.match import SimulationMatch
from simulator.entities.player import Player
from simulator.entities.team import MatchTeam
from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy import (
    T20EnhancedHistoricalStatsStrategy,
)
from simulator.predictors.factory import resolve_venue


def _offline_repo(rows_by_call=None):
    repo = StatsRepository.__new__(StatsRepository)
    repo.conn = object()      # truthy: get_venue_by_name/get_stat_countries go to _run_query
    calls = []

    def fake_run_query(query, params=()):
        calls.append((" ".join(query.split()), params))
        return rows_by_call.pop(0) if rows_by_call else []

    repo._run_query = fake_run_query
    return repo, calls


@pytest.fixture(autouse=True)
def _clean_caches():
    sr_mod._PRECOMPUTED_CACHE.pop(('cs_countries',), None)
    strat_mod._WARNED_CONTEXT_KEYS.clear()
    yield
    sr_mod._PRECOMPUTED_CACHE.pop(('cs_countries',), None)
    strat_mod._WARNED_CONTEXT_KEYS.clear()


class TestGetVenueByName:
    def test_returns_country_name_not_city(self):
        repo, calls = _offline_repo([[(5203, "Wankhede Stadium", "India")]])
        assert repo.get_venue_by_name("Wankhede Stadium") == (5203, "Wankhede Stadium", "India")
        sql = calls[0][0]
        assert "LEFT JOIN history.countries c ON c.country_id = v.country_id" in sql
        assert "city" not in sql

    def test_resolve_venue_puts_country_on_venue(self):
        repo, _ = _offline_repo([[(5203, "Wankhede Stadium", "India")]])
        assert resolve_venue(repo, "Wankhede Stadium").country == "India"

    def test_venue_without_country_id_gives_none(self):
        repo, _ = _offline_repo([[(9, "Some Ground", None)]])
        assert resolve_venue(repo, "Some Ground").country is None


class TestGetStatCountries:
    def test_loads_once_and_caches(self):
        repo, calls = _offline_repo([[("India",), ("Australia",)]])
        assert repo.get_stat_countries() == frozenset({"India", "Australia"})
        assert repo.get_stat_countries() == frozenset({"India", "Australia"})
        assert len(calls) == 1
        assert calls[0][0] == "SELECT DISTINCT country FROM history.country_stats"

    def test_no_connection_is_empty_and_not_cached(self):
        repo = StatsRepository.__new__(StatsRepository)
        repo.conn = None
        assert repo.get_stat_countries() == frozenset()
        assert ('cs_countries',) not in sr_mod._PRECOMPUTED_CACHE


def _match(venue):
    home = MatchTeam(id=1, name="Home", players=[Player(id=1, name="P1")])
    away = MatchTeam(id=2, name="Away", players=[Player(id=2, name="P2")])
    return SimulationMatch(
        id=0, home_team=home, away_team=away, venue=venue,
        match_format="T20", balls_per_over=6, overs_per_innings=20, innings_per_match=2,
    )


def _venue(country, vid=42, name="Wankhede Stadium"):
    return Venue.builder().with_id(vid).with_name(name).with_country(country).build()


class TestVenueContextCoverageLogging:
    def _run(self, venue, known_countries, player_country=None, matches=1):
        fake_repo = StatsRepository.__new__(StatsRepository)
        fake_repo.conn = None
        seen_country_args = []

        def fake_player_country(_self, player_ids, country, match_format, gender='male', countries=None):
            seen_country_args.append(country)
            return player_country or {}

        with patch.object(StatsRepository, "get_stat_countries", lambda _self: frozenset(known_countries)), \
             patch.object(StatsRepository, "get_player_country_distribution", fake_player_country), \
             patch.object(strat_mod, "StatsRepository", return_value=fake_repo), \
             patch.object(strat_mod, "log") as log:
            strategy = T20EnhancedHistoricalStatsStrategy()
            for _ in range(matches):
                strategy.init_model(_match(venue))
        return strategy, log, seen_country_args

    @staticmethod
    def _warnings(log):
        return [c.args[0] % c.args[1:] for c in log.warning.call_args_list]

    def test_country_name_reaches_the_player_country_lookup(self):
        strategy, _, seen = self._run(_venue("India"), {"India"}, player_country={1: ({}, 120)})
        assert seen == ["India"]
        assert strategy.player_country_cache == {1: ({}, 120)}

    def test_coverage_line_logged_per_match(self):
        _, log, _ = self._run(_venue("India"), {"India"}, player_country={1: ({}, 120)})
        lines = [c.args[0] % c.args[1:] for c in log.info.call_args_list
                 if "Venue context" in c.args[0]]
        assert lines == ["[EnhancedStrategy] Venue context → Wankhede Stadium (#42) country=India "
                         "venue_dist=False player_venue=0/2 player_country=1/2"]

    def test_known_country_with_no_player_data_does_not_warn(self):
        _, log, _ = self._run(_venue("India"), {"India"})
        assert not [w for w in self._warnings(log) if "country" in w.lower()]

    def test_unknown_country_key_warns_once_across_matches(self):
        _, log, _ = self._run(_venue("Mumbai"), {"India"}, matches=3)
        unknown = [w for w in self._warnings(log) if "has no precomputed country stats" in w]
        assert len(unknown) == 1
        assert "'Mumbai'" in unknown[0]

    def test_venue_without_country_warns_once(self):
        _, log, _ = self._run(_venue(None), {"India"}, matches=2)
        missing = [w for w in self._warnings(log) if "has no country" in w]
        assert len(missing) == 1

    def test_no_known_countries_available_does_not_warn(self):
        _, log, _ = self._run(_venue("Mumbai"), set())
        assert not [w for w in self._warnings(log) if "precomputed country stats" in w]


class TestRealSql:
    """DB tier: the real query against a throwaway database built from schema.sql."""

    def test_venue_resolves_to_its_country_name(self, make_db):
        db = make_db()
        conn = db.connect("test:seed")
        with conn.cursor() as cur:
            cur.execute("INSERT INTO history.countries (name) VALUES ('India') RETURNING country_id")
            (cid,) = cur.fetchone()
            cur.execute("INSERT INTO history.venues (name, city, country_id) VALUES ('Wankhede Stadium', 'Mumbai', %s)", (cid,))
            cur.execute("INSERT INTO history.venues (name, city) VALUES ('Nowhere Ground', 'Nowhere')")
        repo = StatsRepository.__new__(StatsRepository)
        repo.conn = conn
        assert resolve_venue(repo, "Wankhede Stadium").country == "India"
        assert resolve_venue(repo, "Nowhere Ground").country is None
        conn.close()
