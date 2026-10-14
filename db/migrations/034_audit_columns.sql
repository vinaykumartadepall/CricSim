-- 034: audit columns on every table in history and simulation.
--
--   created_at  timestamptz  set on insert (column default), never changed afterwards
--   updated_at  timestamptz  set on insert (default), bumped on every UPDATE (trigger)
--   updated_by  text         app.actor of the writing connection (default + trigger)
--
-- app.actor is set per connection by db/database.py (db_actor() / process
-- default). Inserts use column defaults only, so a pg_dump restore or replay
-- that supplies these columns keeps its original values. Adding a column with
-- a non-volatile default is catalog-only on PG >= 11 - no table rewrite, even
-- for history.deliveries.
--
-- Keep in sync with the "Audit columns" section at the end of db/schema.sql.

SET app.actor = 'migration:034';

CREATE OR REPLACE FUNCTION public.audit_actor() RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT coalesce(nullif(current_setting('app.actor', true), ''), current_user)::text
$$;

CREATE OR REPLACE FUNCTION public.audit_touch() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.created_at := OLD.created_at;
    NEW.updated_at := now();
    NEW.updated_by := public.audit_actor();
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION public.audit_enable(tbl regclass) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format(
        'ALTER TABLE %s '
        'ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now(), '
        'ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now(), '
        'ADD COLUMN IF NOT EXISTS updated_by text NOT NULL DEFAULT public.audit_actor()',
        tbl);
    EXECUTE format('DROP TRIGGER IF EXISTS audit_touch ON %s', tbl);
    EXECUTE format(
        'CREATE TRIGGER audit_touch BEFORE UPDATE ON %s '
        'FOR EACH ROW EXECUTE FUNCTION public.audit_touch()',
        tbl);
END
$$;

BEGIN;

DO $$
DECLARE t regclass;
BEGIN
    FOR t IN
        SELECT c.oid::regclass
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('history', 'simulation') AND c.relkind IN ('r', 'p')
        ORDER BY 1
    LOOP
        PERFORM public.audit_enable(t);
    END LOOP;
END
$$;

-- Backfill real dates where a table already recorded one. Small tables only;
-- the trigger is disabled so the backfilled created_at isn't reset to OLD.
ALTER TABLE simulation.simulations DISABLE TRIGGER audit_touch;
UPDATE simulation.simulations SET updated_at = coalesce(completed_at, started_at, created_at);
ALTER TABLE simulation.simulations ENABLE TRIGGER audit_touch;

ALTER TABLE simulation.rooms DISABLE TRIGGER audit_touch;
UPDATE simulation.rooms SET updated_at = created_at;
ALTER TABLE simulation.rooms ENABLE TRIGGER audit_touch;

ALTER TABLE simulation.room_members DISABLE TRIGGER audit_touch;
UPDATE simulation.room_members SET created_at = joined_at, updated_at = joined_at WHERE joined_at IS NOT NULL;
ALTER TABLE simulation.room_members ENABLE TRIGGER audit_touch;

ALTER TABLE simulation.admin_edits DISABLE TRIGGER audit_touch;
UPDATE simulation.admin_edits SET created_at = edited_at, updated_at = edited_at;
ALTER TABLE simulation.admin_edits ENABLE TRIGGER audit_touch;

DO $$
BEGIN
    IF to_regclass('history.schema_migrations') IS NOT NULL THEN
        ALTER TABLE history.schema_migrations DISABLE TRIGGER audit_touch;
        UPDATE history.schema_migrations SET created_at = applied_at, updated_at = applied_at WHERE applied_at IS NOT NULL;
        ALTER TABLE history.schema_migrations ENABLE TRIGGER audit_touch;
        INSERT INTO history.schema_migrations (filename) VALUES ('034_audit_columns.sql');
    END IF;
END
$$;

COMMIT;
