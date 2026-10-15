"""
Audit columns (created_at / updated_at / updated_by) on every table - migration
034 and the "Audit columns" section at the end of db/schema.sql.

TestAuditSchemaText is DB-free. TestAuditColumnsOnFreshDatabase is the first
DB-tier test: it builds a throwaway database from schema.sql on the local
Postgres and checks the real trigger/default behaviour. It is skipped when no
local Postgres (or no CREATEDB permission) is available.
"""
import re
import time
from pathlib import Path

import pytest

DB_DIR = Path(__file__).resolve().parent.parent / "db"
SCHEMA_SQL = (DB_DIR / "schema.sql").read_text()
MIGRATION_SQL = (DB_DIR / "migrations" / "034_audit_columns.sql").read_text()
AUDIT_FUNCTIONS = ("audit_actor", "audit_touch", "audit_enable")


def _function_def(sql_text: str, name: str) -> str:
    m = re.search(rf"CREATE OR REPLACE FUNCTION public\.{name}\(.*?\n\$\$;", sql_text, re.S)
    assert m, f"public.{name} not defined"
    return m.group(0)


class TestAuditSchemaText:
    @pytest.mark.parametrize("name", AUDIT_FUNCTIONS)
    def test_schema_and_migration_define_identical_functions(self, name):
        assert _function_def(SCHEMA_SQL, name) == _function_def(MIGRATION_SQL, name)

    def test_audit_section_is_last_so_it_covers_every_table(self):
        audit_start = SCHEMA_SQL.index("CREATE OR REPLACE FUNCTION public.audit_actor")
        assert "CREATE TABLE" not in SCHEMA_SQL[audit_start:]
        assert "PERFORM public.audit_enable(t)" in SCHEMA_SQL[audit_start:]

    def test_every_table_lives_in_an_audited_schema(self):
        tables = re.findall(r"CREATE TABLE IF NOT EXISTS ([\w.]+)", SCHEMA_SQL)
        assert tables
        assert all(t.split(".")[0] in ("history", "simulation") for t in tables)


@pytest.fixture(scope="module")
def fresh_db(make_db):
    return make_db().connect


def _fetch(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


class TestAuditColumnsOnFreshDatabase:
    def test_every_table_has_columns_and_trigger(self, fresh_db):
        conn = fresh_db()
        tables = [t for (t,) in _fetch(conn, """
            SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname IN ('history', 'simulation') AND c.relkind = 'r'""")]
        assert len(tables) > 30
        for t in tables:
            schema, name = t.split(".")
            cols = {c for (c,) in _fetch(conn, """SELECT column_name FROM information_schema.columns
                                                  WHERE table_schema = %s AND table_name = %s""", (schema, name))}
            assert {"created_at", "updated_at", "updated_by"} <= cols, t
            triggers = _fetch(conn, "SELECT tgname FROM pg_trigger WHERE tgrelid = %s::regclass AND NOT tgisinternal", (t,))
            assert triggers == [("audit_touch",)], t
        conn.close()

    def test_insert_fills_columns_from_defaults_with_actor(self, fresh_db):
        conn = fresh_db("script:ingest_data")
        [(created, updated, by)] = _fetch(conn, """INSERT INTO history.countries (name) VALUES ('Atlantis')
                                                   RETURNING created_at, updated_at, updated_by""")
        conn.close()
        assert created is not None and updated == created
        assert by == "script:ingest_data"

    def test_update_bumps_updated_and_keeps_created(self, fresh_db):
        conn = fresh_db("script:a")
        [(cid, created)] = _fetch(conn, "INSERT INTO history.countries (name) VALUES ('Lemuria') RETURNING country_id, created_at")
        conn.close()
        time.sleep(0.01)
        conn = fresh_db("user:abc")
        [(created2, updated, by)] = _fetch(conn, """UPDATE history.countries SET code = 'LM', created_at = '2000-01-01'
                                                    WHERE country_id = %s RETURNING created_at, updated_at, updated_by""", (cid,))
        conn.close()
        assert created2 == created  # cannot be overwritten
        assert updated > created
        assert by == "user:abc"

    def test_upsert_conflict_runs_the_update_trigger(self, fresh_db):
        conn = fresh_db("script:a")
        _fetch(conn, "INSERT INTO history.countries (name) VALUES ('Mu') RETURNING 1")
        conn.close()
        conn = fresh_db("script:precompute")
        [(by,)] = _fetch(conn, """INSERT INTO history.countries (name) VALUES ('Mu')
                                  ON CONFLICT (name) DO UPDATE SET code = 'MU' RETURNING updated_by""")
        conn.close()
        assert by == "script:precompute"

    def test_restore_style_insert_keeps_supplied_values(self, fresh_db):
        conn = fresh_db("script:pg_restore")
        [(created, updated, by)] = _fetch(conn, """
            INSERT INTO history.countries (name, created_at, updated_at, updated_by)
            VALUES ('Hyperborea', '2020-01-01T00:00:00Z', '2021-01-01T00:00:00Z', 'user:original')
            RETURNING created_at, updated_at, updated_by""")
        conn.close()
        assert (created.year, updated.year, by) == (2020, 2021, "user:original")

    def test_schema_sql_can_be_reapplied(self, fresh_db):
        conn = fresh_db("test:reapply")
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        assert _fetch(conn, "SELECT count(*) FROM pg_trigger WHERE tgname = 'audit_touch' AND tgrelid = 'history.countries'::regclass") == [(1,)]
        conn.close()
