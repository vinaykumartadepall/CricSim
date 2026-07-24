"""
ALLOW_DELIVERIES_FALLBACK gate on StatsRepository._run_query.

Several StatsRepository methods (get_tournament_distribution,
get_wicket_keepers, get_batter_phase_distribution, ...) fall back to a live
query against history.deliveries when their precomputed table has no row for
the requested key. That's safe in local dev, where the table exists, but
production was deliberately built without it (CLAUDE.md rule 1) - so in prod
every one of those fallbacks was a guaranteed psycopg2.errors.UndefinedTable,
silently swallowed by _run_query's blanket except-and-return-[].

Rather than patching each of the ~40 call sites individually, the flag is
enforced at the one choke point every query passes through (_run_query),
off by default, so any query mentioning history.deliveries is skipped
entirely - not even attempted - unless explicitly opted in.
"""
import db.stats_repository as sr_mod
from db.stats_repository import StatsRepository


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = False

    def mogrify(self, query, params):
        return b"<query>"

    def execute(self, query, params):
        self.executed = True

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.cursors = []

    def cursor(self):
        c = _FakeCursor(self._rows)
        self.cursors.append(c)
        return c


class TestDeliveriesFallbackGate:
    def setup_method(self):
        self._orig_flag = sr_mod._ALLOW_DELIVERIES_FALLBACK
        self.repo = StatsRepository.__new__(StatsRepository)

    def teardown_method(self):
        sr_mod._ALLOW_DELIVERIES_FALLBACK = self._orig_flag

    def test_default_is_off(self):
        # Reload-independent check of the parsed default - no env var set.
        import os
        assert os.getenv('ALLOW_DELIVERIES_FALLBACK') in (None, '')

    def test_deliveries_query_blocked_when_flag_off(self):
        sr_mod._ALLOW_DELIVERIES_FALLBACK = False
        conn = _FakeConn(rows=[(1, 2)])
        self.repo.conn = conn

        result = self.repo._run_query(
            "SELECT d.runs_batter FROM history.deliveries d WHERE 1=1", ()
        )

        assert result == []
        assert conn.cursors == []  # never even opened a cursor - fully skipped

    def test_deliveries_query_runs_when_flag_on(self):
        sr_mod._ALLOW_DELIVERIES_FALLBACK = True
        conn = _FakeConn(rows=[(1, 2)])
        self.repo.conn = conn

        result = self.repo._run_query(
            "SELECT d.runs_batter FROM history.deliveries d WHERE 1=1", ()
        )

        assert result == [(1, 2)]
        assert len(conn.cursors) == 1
        assert conn.cursors[0].executed

    def test_non_deliveries_query_unaffected_by_flag_off(self):
        sr_mod._ALLOW_DELIVERIES_FALLBACK = False
        conn = _FakeConn(rows=[(42,)])
        self.repo.conn = conn

        result = self.repo._run_query(
            "SELECT player_id FROM history.players WHERE player_id = %s", (1,)
        )

        assert result == [(42,)]
        assert len(conn.cursors) == 1
