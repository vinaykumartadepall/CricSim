"""
db/ingest_data.py: each match is saved in its own savepoint, so one match
that fails to save is skipped and reported instead of aborting the whole run
(and losing the uncommitted batch). DB tier: ingests two real Cricsheet files
(tests/fixtures/cricsheet, both at Sabina Park) into a throwaway database
built from schema.sql; skipped when no local Postgres is available.
"""
from pathlib import Path

import pytest

import db.ingest_data as ingest_mod
from db.repository import CricketRepository

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cricsheet"
FIRST, SECOND = "1534186.json", "1534188.json"   # same venue; FIRST is processed first


@pytest.fixture
def ingest_db(make_db, app_db, monkeypatch):
    db = make_db()
    app_db(db)
    monkeypatch.setattr(ingest_mod, "DATA_DIR", str(FIXTURES))
    monkeypatch.setattr(ingest_mod.glob, "glob", lambda pattern: [str(FIXTURES / FIRST), str(FIXTURES / SECOND)])
    return db


def _rows(db, sql):
    conn = db.connect("test:read")
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    conn.close()
    return rows


def _fail_save_for(monkeypatch, original_id):
    real = CricketRepository.save_match

    def save_match(self, match):
        if getattr(match, "original_match_id", None) == original_id:
            raise RuntimeError("simulated save failure")
        return real(self, match)

    monkeypatch.setattr(CricketRepository, "save_match", save_match)


class TestIngestSavepoints:
    def test_both_matches_ingest(self, ingest_db):
        result = ingest_mod.ingest_data()
        assert result == {"ingested": 2, "already_present": 0, "failed": []}
        assert sorted(r[0] for r in _rows(ingest_db, "SELECT original_match_id FROM history.matches")) == [FIRST, SECOND]

    def test_failing_match_is_skipped_and_reported(self, ingest_db, monkeypatch):
        _fail_save_for(monkeypatch, FIRST)
        result = ingest_mod.ingest_data()
        assert result["ingested"] == 1
        assert [(f, stage) for f, stage, _ in result["failed"]] == [(FIRST, "save")]
        assert _rows(ingest_db, "SELECT original_match_id FROM history.matches") == [(SECOND,)]

    def test_failed_match_leaves_no_partial_rows(self, ingest_db, monkeypatch):
        # FIRST created the venue, its teams and players before failing. All of
        # that must be rolled back - and the id caches reset, or SECOND would
        # reuse the rolled-back venue/team ids and fail on foreign keys.
        _fail_save_for(monkeypatch, FIRST)
        ingest_mod.ingest_data()
        assert _rows(ingest_db, "SELECT count(*) FROM history.venues WHERE name ILIKE 'Sabina Park%'") == [(1,)]
        assert _rows(ingest_db, "SELECT count(*) FROM history.teams WHERE name = 'Trinbago Knight Riders'") == [(0,)]
        assert _rows(ingest_db, """SELECT count(*) FROM history.matches m
                                   JOIN history.venues v USING (venue_id)""") == [(1,)]

    def test_rerun_after_fix_picks_up_the_skipped_match(self, ingest_db, monkeypatch):
        with monkeypatch.context() as m:
            _fail_save_for(m, FIRST)
            ingest_mod.ingest_data()
        result = ingest_mod.ingest_data()
        assert result == {"ingested": 1, "already_present": 1, "failed": []}
        assert sorted(r[0] for r in _rows(ingest_db, "SELECT original_match_id FROM history.matches")) == [FIRST, SECOND]


class TestForgetCachedIds:
    def test_clears_every_id_cache(self):
        repo = CricketRepository.__new__(CricketRepository)
        repo._players_cache, repo._teams_cache = {"c": 1}, {"t": 2}
        repo._venues_cache, repo._tournaments_cache, repo._country_ids = {"v": 3}, {("x", "y"): 4}, {"India": 5}
        repo.forget_cached_ids()
        assert not (repo._players_cache or repo._teams_cache or repo._venues_cache
                    or repo._tournaments_cache or repo._country_ids)
