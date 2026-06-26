-- User profiles table for authenticated users.
-- anonymous_id stores the original localStorage UUID so we can trace lineage.
CREATE TABLE IF NOT EXISTS simulation.profiles (
    user_id      TEXT        PRIMARY KEY,
    display_name TEXT        NOT NULL,
    anonymous_id TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
