-- 030: Audit log of admin UI edits (tournament configs, player metadata).
--
-- Every admin PUT appends one row here. edit_id is a UUID so the replay CLI
-- (db/replay_admin_edits.py) can sync edits between databases idempotently:
-- --apply skips rows whose edit_id already exists in the target and copies the
-- rows over, leaving both DBs with identical logs. Also lets manual edits be
-- re-applied after re-running seed_sim_configs.py (which overwrites configs).

CREATE TABLE IF NOT EXISTS simulation.admin_edits (
    edit_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    edited_at   timestamptz NOT NULL DEFAULT now(),
    entity_type text NOT NULL,
    entity_id   text NOT NULL,
    payload     jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS admin_edits_edited_at_idx ON simulation.admin_edits (edited_at);
