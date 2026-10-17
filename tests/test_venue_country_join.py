"""
history.venues has no `country` column any more - venue countries live in
history.countries, referenced by history.venues.country_id. Every query that
needs a venue's country name must join history.countries and filter/select
vc.name. These tests pin that for every query that used the dropped column.
No live DB connection required - SQL is captured, never executed.
"""
import re
from pathlib import Path

import pytest

import db.precompute as pc
import db.stats_repository as sr_mod
from db.stats_repository import StatsRepository

REPO_ROOT = Path(__file__).resolve().parent.parent
COUNTRIES_JOIN = re.compile(r"JOIN\s+history\.countries\s+vc\s+ON\s+vc\.country_id\s*=\s*v\.country_id")


class TestNoDroppedVenueCountryColumn:
    def test_no_python_sql_references_v_country(self):
        offenders = []
        for folder in ("api", "db", "simulator", "validation", "tools", "parser"):
            for path in (REPO_ROOT / folder).rglob("*.py"):
                for lineno, line in enumerate(path.read_text().splitlines(), 1):
                    if re.search(r"\bv\.country\b", line):
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")
        assert offenders == [], f"history.venues.country no longer exists: {offenders}"


@pytest.fixture
def capturing_repo():
    repo = StatsRepository.__new__(StatsRepository)
    repo.conn = object()
    captured = []
    repo._run_query = lambda q, p=(): captured.append((q, p)) or []
    original_cache = sr_mod._PRECOMPUTED_CACHE
    sr_mod._PRECOMPUTED_CACHE = {}
    yield repo, captured
    sr_mod._PRECOMPUTED_CACHE = original_cache


def _country_queries(captured):
    return [(q, p) for q, p in captured if "history.countries" in q]


class TestStatsRepositoryCountryJoin:
    def test_country_distribution_fallback_filters_by_country_name(self, capturing_repo):
        repo, captured = capturing_repo
        repo.get_country_distribution("India", "T20")
        [(q, p)] = _country_queries(captured)
        assert COUNTRIES_JOIN.search(q)
        assert "vc.name = %s" in q
        assert p[0] == "India"

    def test_bowler_over_frequency_countries_filter(self, capturing_repo):
        repo, captured = capturing_repo
        repo.get_bowler_over_frequency([1], "T20", countries=["India", "Sri Lanka"])
        [(q, p)] = _country_queries(captured)
        assert COUNTRIES_JOIN.search(q)
        assert "vc.name = ANY(%s)" in q
        assert ["India", "Sri Lanka"] in list(p)

    def test_bowler_test_phase_frequency_country_filter(self, capturing_repo):
        repo, captured = capturing_repo
        repo.get_bowler_test_phase_frequency([1], country="India")
        [(q, p)] = _country_queries(captured)
        assert COUNTRIES_JOIN.search(q)
        assert "vc.name = ANY(%s)" in q
        assert ["India"] in list(p)

    def test_player_recent_matches_selects_country_name_keeping_all_venues(self, capturing_repo):
        repo, captured = capturing_repo
        repo.get_player_recent_matches(1, "T20")
        [(q, _)] = _country_queries(captured)
        assert re.search(r"LEFT\s+JOIN\s+history\.countries\s+vc", q)
        assert "v.name, vc.name," in q


class _CapturingCursor:
    def __init__(self, sink):
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        self._sink.append(query)

    def fetchall(self):
        return []


class _CapturingConn:
    def __init__(self):
        self.queries = []

    def cursor(self, *args, **kwargs):
        return _CapturingCursor(self.queries)

    def commit(self):
        pass


class TestPrecomputeCountryJoin:
    def _country_select(self, conn):
        selects = [q for q in conn.queries if "history.deliveries" in q]
        assert selects, "expected the country aggregation query to run"
        return selects[0]

    def test_player_country_stats_groups_by_country_name(self):
        conn = _CapturingConn()
        pc._populate_player_country_stats(conn, "T20", "male", {}, {}, True)
        q = self._country_select(conn)
        assert COUNTRIES_JOIN.search(q)
        assert "vc.name AS country" in q
        assert re.search(r"GROUP BY d\.batter_id, vc\.name, year", q)

    def test_country_stats_groups_by_country_name(self):
        conn = _CapturingConn()
        pc._populate_country_stats(conn, "T20", "male", True)
        q = self._country_select(conn)
        assert COUNTRIES_JOIN.search(q)
        assert "vc.name AS country" in q
        assert re.search(r"GROUP BY vc\.name, year", q)
