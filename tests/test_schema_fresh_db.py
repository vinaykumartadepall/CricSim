"""
db/schema.sql is the full current schema (CLAUDE.md Critical Rule #4): a
database built from it alone must serve the app. These DB-tier tests build a
throwaway database from schema.sql and run real app queries against it, so a
column that exists only in hand-edited live databases fails here.
"""
from pathlib import Path

from db.squad_repository import SquadRepository

MIGRATION_036 = (Path(__file__).resolve().parent.parent / "db" / "migrations"
                 / "036_tournament_seeded_overseas_columns.sql").read_text()


def _seed_one_tournament(db):
    conn = db.connect("test:seed")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO history.tournaments (tournament_name, season) VALUES ('Test League', '2026') RETURNING tournament_id")
        tid = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO simulation.tournament_seeded (tournament_id, config, overseas_limit, home_country_name)
               VALUES (%s, %s::jsonb, 4, 'India')""",
            (tid, '{"format": "T20", "teams": [{"team_id": 1, "name": "A", "players": [1]}]}'),
        )
    conn.close()


class TestFreshSchemaServesApp:
    def test_lov_tournaments_query_runs_on_schema_sql_alone(self, make_db, app_db):
        db = make_db()
        _seed_one_tournament(db)
        app_db(db)
        repo = SquadRepository()
        try:
            rows = repo.get_seeded_tournaments()
        finally:
            repo.close()
        assert [(r["name"], r["overseas_limit"], r["home_country_name"]) for r in rows] == \
            [("Test League", 4, "India")]

    def test_migration_036_is_a_no_op_where_columns_exist(self, make_db):
        db = make_db()
        conn = db.connect("test:migration")
        with conn.cursor() as cur:
            cur.execute(MIGRATION_036)
            cur.execute("""SELECT count(*) FROM information_schema.columns WHERE table_schema = 'simulation'
                           AND table_name = 'tournament_seeded' AND column_name IN ('overseas_limit', 'home_country_name')""")
            assert cur.fetchone()[0] == 2
        conn.close()
