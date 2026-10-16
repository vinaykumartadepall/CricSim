"""
history.schema_migrations records which db/migrations/*.sql files have run on
a database. Rules (CLAUDE.md, Critical Rule #4):
  - every migration from 034 on ends with an unconditional, re-runnable
    INSERT ... ON CONFLICT (filename) DO NOTHING of its own filename;
  - db/schema.sql creates the table and records every migration it contains,
    so a fresh database doesn't look like it is missing them.
Migrations 018-033 predate the rule and were never recorded anywhere.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MIGRATIONS = REPO / "db" / "migrations"
SCHEMA = (REPO / "db" / "schema.sql").read_text()
FIRST_SELF_RECORDING = 34
NOT_IN_MAIN_DB = {"019_add_profiles.sql"}   # old Supabase-only profiles table

ALL_FILES = sorted(p.name for p in MIGRATIONS.glob("*.sql"))
SELF_RECORDING = [f for f in ALL_FILES if int(f[:3]) >= FIRST_SELF_RECORDING]


def _footer(filename: str) -> str:
    return (re.escape(f"INSERT INTO history.schema_migrations (filename) VALUES ('{filename}')")
            + r"\s+ON CONFLICT \(filename\) DO NOTHING;")


class TestEveryMigrationRecordsItself:
    @pytest.mark.parametrize("filename", SELF_RECORDING)
    def test_records_own_filename_rerunnably(self, filename):
        sql = (MIGRATIONS / filename).read_text()
        assert re.search(_footer(filename), sql), \
            f"{filename} must end with: INSERT INTO history.schema_migrations (filename) " \
            f"VALUES ('{filename}') ON CONFLICT (filename) DO NOTHING;"

    @pytest.mark.parametrize("filename", SELF_RECORDING)
    def test_record_is_inside_the_transaction(self, filename):
        sql = (MIGRATIONS / filename).read_text()
        if "COMMIT;" in sql:
            assert re.search(_footer(filename), sql).start() < sql.rindex("COMMIT;")

    def test_filenames_are_numbered_and_unique(self):
        numbers = [f[:3] for f in ALL_FILES]
        assert all(n.isdigit() for n in numbers)
        assert len(numbers) == len(set(numbers)), "two migrations share a number"


class TestSchemaSqlRecordsWhatItContains:
    def _recorded(self):
        block = SCHEMA[SCHEMA.rindex("INSERT INTO history.schema_migrations (filename) VALUES"):]
        return set(re.findall(r"\('(\d{3}_[\w]+\.sql)'\)", block))

    def test_table_is_created(self):
        assert "CREATE TABLE IF NOT EXISTS history.schema_migrations" in SCHEMA

    def test_every_migration_file_is_listed(self):
        assert self._recorded() == set(ALL_FILES) - NOT_IN_MAIN_DB


class TestRealDatabase:
    """DB tier: throwaway databases built from schema.sql."""

    def test_fresh_db_lists_every_migration(self, make_db):
        db = make_db()
        conn = db.connect("test:migrations")
        cur = conn.cursor()
        cur.execute("SELECT filename FROM history.schema_migrations")
        assert {r[0] for r in cur.fetchall()} == set(ALL_FILES) - NOT_IN_MAIN_DB
        conn.close()

    @pytest.mark.parametrize("filename", ["036_tournament_seeded_overseas_columns.sql",
                                          "037_vocabulary_checks.sql"])
    def test_rerunning_a_migration_succeeds_and_keeps_one_row(self, make_db, filename):
        db = make_db()
        conn = db.connect("test:migrations")
        cur = conn.cursor()
        cur.execute("DELETE FROM history.schema_migrations WHERE filename = %s", (filename,))
        body = (MIGRATIONS / filename).read_text().replace("BEGIN;", "").replace("COMMIT;", "")
        cur.execute(body)
        cur.execute(body)
        cur.execute("SELECT count(*), max(updated_by) FROM history.schema_migrations WHERE filename = %s",
                    (filename,))
        count, actor = cur.fetchone()
        assert count == 1
        assert actor == f"migration:{filename[:3]}"
        conn.close()
