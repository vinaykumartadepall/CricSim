"""
db/precompute.py rebuilds derived tables in place, so every write must
UPDATE an existing row on key conflict - `ON CONFLICT DO NOTHING` silently
keeps stale values forever (bowler_order_stats did exactly that).
No live DB connection required - execute_batch is captured, never run.
"""
import re
from pathlib import Path

import psycopg2.extras
import pytest

import db.precompute as pc

PRECOMPUTE_SRC = (Path(__file__).resolve().parent.parent / "db" / "precompute.py").read_text()


class _Conn:
    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        pass


@pytest.fixture
def captured(monkeypatch):
    calls = []
    monkeypatch.setattr(psycopg2.extras, "execute_batch",
                        lambda cur, sql, rows, page_size=100: calls.append((" ".join(sql.split()), rows)))
    return calls


class TestNoSilentlySkippedRows:
    def test_precompute_never_ignores_key_conflicts(self):
        assert "ON CONFLICT DO NOTHING" not in PRECOMPUTE_SRC

    def test_every_insert_updates_on_conflict(self):
        inserts = re.findall(r"INSERT INTO (history\.\w+)(.*?)\"\"\"", PRECOMPUTE_SRC, re.S)
        assert inserts
        for table, body in inserts:
            if table == "history.global_yearly_baseline":
                continue  # deleted and fully re-inserted per format/gender
            assert "DO UPDATE" in body, f"{table} insert doesn't update existing rows"


class TestBowlerOrderUpsert:
    def test_updates_probs_on_existing_key(self, captured):
        rows = [(1, "T20", "over_freq", "all", 0, None, None, "{}")]
        assert pc._upsert_bowler_order(_Conn(), rows, dry_run=False) == 1
        [(sql, sent)] = captured
        assert sent == rows
        assert ("ON CONFLICT (player_id, match_format, dist_type, match_type, inning_number, "
                "(COALESCE(venue_id, -1)), (COALESCE(country, ''))) DO UPDATE SET probs = EXCLUDED.probs") in sql

    def test_dry_run_writes_nothing(self, captured):
        assert pc._upsert_bowler_order(_Conn(), [(1,)], dry_run=True) == 1
        assert captured == []


class TestPlayerContextUpsert:
    def test_single_write_that_updates_existing_rows(self, captured):
        rows = [(1, "T20", "venue", 5000, None, "{}", "{}", 10)]
        assert pc._upsert_player_context(_Conn(), rows, dry_run=False) == 1
        assert len(captured) == 1, "rows should be written once, not inserted then re-upserted"
        sql, sent = captured[0]
        assert sent == rows
        assert "DO UPDATE SET probs_raw = EXCLUDED.probs_raw" in sql
