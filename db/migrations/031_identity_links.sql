-- 031: simulation.identity_links - unifies anonymous and authenticated user
-- identity in one table, replacing simulation.profiles (Supabase-hosted) and
-- the (never-built-out) idea of a separate anon_profiles table.
--
-- Design: every person has exactly one canonical `id` - their original
-- anonymous client_id if they ever played anonymously, or their Supabase
-- auth user id if they signed in with no prior anonymous history. Resolving
-- any incoming client_id (anon or auth) to this canonical id is a single
-- lookup (db/identity_repository.py::resolve_client_id), so no
-- simulation.* table (existing or future) ever needs its own migration
-- logic when someone signs in - only this one row changes.
--
-- linked_auth_id is set exactly once, the first time this identity's owner
-- ever signs in with a Google account. It is deliberately never reassigned
-- on subsequent sign-ins: logging into an already-linked account always
-- resolves to that account's existing history and never merges in whatever
-- anonymous activity happened in between sign-outs and sign-ins - a
-- deliberate product decision, not an oversight.

CREATE TABLE IF NOT EXISTS simulation.identity_links (
    id             TEXT        PRIMARY KEY,
    username       TEXT        NOT NULL,
    is_anonymous   BOOLEAN     NOT NULL DEFAULT TRUE,
    linked_auth_id TEXT        UNIQUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Case-insensitive uniqueness: "Rahul" and "rahul" collide.
CREATE UNIQUE INDEX IF NOT EXISTS idx_identity_links_username_lower
    ON simulation.identity_links (lower(username));
