-- 036: record two simulation.tournament_seeded columns that were added to the
-- live databases by hand (with the overseas-limit feature, commit 943c9ce) but
-- never written into any DDL. db/squad_repository.py's /lov/tournaments query
-- selects them, so a database built from schema.sql alone could not list
-- tournaments. IF NOT EXISTS makes this a no-op wherever they already exist.
-- Mirrored in db/schema.sql.

SET app.actor = 'migration:036';

BEGIN;

ALTER TABLE simulation.tournament_seeded
    ADD COLUMN IF NOT EXISTS overseas_limit    INT,
    ADD COLUMN IF NOT EXISTS home_country_name VARCHAR(128);

DO $$
BEGIN
    IF to_regclass('history.schema_migrations') IS NOT NULL THEN
        INSERT INTO history.schema_migrations (filename) VALUES ('036_tournament_seeded_overseas_columns.sql');
    END IF;
END
$$;

COMMIT;
