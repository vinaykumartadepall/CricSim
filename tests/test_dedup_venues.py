"""
db/dedup_venues.py merges duplicate venue rows. Every table with an FK to
history.venues must be re-pointed or cleared before the losing rows are
deleted, or the DELETE fails and the whole merge rolls back.
No live DB connection required - a fake connection records the SQL.
"""
import re
from pathlib import Path

import db.dedup_venues as dedup

REPO_ROOT = Path(__file__).resolve().parent.parent
REPOINTED_TABLES = {"history.matches", "simulation.matches"}


class _Cursor:
    def __init__(self, venue_rows):
        self.executed = []
        self._venue_rows = venue_rows
        self.rowcount = 0

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))
        self.rowcount = 3 if query.startswith("DELETE FROM history.player_context_stats") else 0

    def fetchall(self):
        return self._venue_rows

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur = cur
        self.committed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def close(self):
        pass


def _run(monkeypatch, commit, venue_rows):
    cur = _Cursor(venue_rows)
    conn = _Conn(cur)
    group = {"canonical": "Kennington Oval", "city": "London", "aliases": ["The Oval"]}
    monkeypatch.setattr(dedup, "get_db_connection", lambda autocommit=False: conn)
    monkeypatch.setattr(dedup, "load_overrides", lambda: {})
    monkeypatch.setattr(dedup, "all_canonical_groups", lambda overrides: [group])
    monkeypatch.setattr(dedup, "invalidate_cache", lambda: None)
    dedup.run(commit=commit)
    return cur, conn


ROWS = [(5314, "Kennington Oval", "London", 392), (5899, "The Oval", "London", 2)]


class TestDedupMerge:
    def test_repoints_both_match_tables_to_winner(self, monkeypatch):
        cur, conn = _run(monkeypatch, True, ROWS)
        sql = [q for q, _ in cur.executed]
        assert ("UPDATE history.matches SET venue_id = %s WHERE venue_id = %s", (5314, 5899)) in cur.executed
        assert ("UPDATE simulation.matches SET venue_id = %s WHERE venue_id = %s", (5314, 5899)) in cur.executed
        assert conn.committed
        assert sql[-1] == "DELETE FROM history.venues WHERE venue_id = ANY(%s)"

    def test_clears_derived_stats_before_deleting_losers(self, monkeypatch):
        cur, _ = _run(monkeypatch, True, ROWS)
        sql = [q for q, _ in cur.executed]
        delete_venue_at = sql.index("DELETE FROM history.venues WHERE venue_id = ANY(%s)")
        for table in dedup._DERIVED_VENUE_TABLES:
            stmt = f"DELETE FROM {table} WHERE venue_id = ANY(%s)"
            assert stmt in sql
            assert sql.index(stmt) < delete_venue_at
            assert (stmt, ([5899],)) in cur.executed

    def test_winner_is_never_touched_by_deletes(self, monkeypatch):
        cur, _ = _run(monkeypatch, True, ROWS)
        for q, p in cur.executed:
            if q.startswith("DELETE"):
                assert 5314 not in p[0]

    def test_dry_run_writes_nothing(self, monkeypatch):
        cur, _ = _run(monkeypatch, False, ROWS)
        assert all(q.startswith("SELECT") for q, _ in cur.executed)

    def test_single_row_group_is_left_alone(self, monkeypatch):
        cur, _ = _run(monkeypatch, True, ROWS[:1])
        assert all(q.startswith("SELECT") for q, _ in cur.executed)


class TestEveryVenueForeignKeyIsHandled:
    def test_schema_fks_to_venues_are_repointed_or_cleared(self):
        schema = (REPO_ROOT / "db" / "schema.sql").read_text()
        referencing = set()
        for m in re.finditer(r"CREATE TABLE IF NOT EXISTS ([\w.]+)\s*\((.*?)\n\);", schema, re.S):
            if re.search(r"REFERENCES\s+history\.venues\b", m.group(2)):
                referencing.add(m.group(1))
        assert referencing, "expected tables referencing history.venues in schema.sql"
        handled = REPOINTED_TABLES | set(dedup._DERIVED_VENUE_TABLES)
        assert referencing <= handled, f"dedup_venues doesn't handle: {sorted(referencing - handled)}"
