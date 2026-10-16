-- 038: per-browser credentials, so a client_id alone no longer proves who you are.
--
-- Until now the API trusted whatever client_id a request carried, and that id
-- was also shown to other users (leaderboards, multiplayer rooms) - knowing it
-- was enough to act as that person. Each browser now also holds a random
-- secret it generated itself. The first request that arrives for a client_id
-- records a SHA-256 hash of its secret here; every later request for that id
-- must present the same secret (api/identity_auth.py).
--
-- Write-once by design: a recorded secret is never replaced or "re-issued" -
-- the trigger below refuses any UPDATE that would change it, whatever code
-- runs. Deleting a row (manual admin recovery) is allowed; the next request
-- for that id then records a fresh secret.
--
-- Signed-in users authenticate with their Supabase JWT instead; anonymous
-- credentials are refused for identities linked to an account.
-- Mirrored in db/schema.sql.

SET app.actor = 'migration:038';

BEGIN;

CREATE TABLE IF NOT EXISTS simulation.client_credentials (
    client_id   VARCHAR(64) PRIMARY KEY,
    secret_hash CHAR(64)    NOT NULL
);

CREATE OR REPLACE FUNCTION simulation.client_credentials_write_once() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.client_id IS DISTINCT FROM OLD.client_id
       OR NEW.secret_hash IS DISTINCT FROM OLD.secret_hash THEN
        RAISE EXCEPTION 'client_credentials is write-once: the secret for % cannot be replaced', OLD.client_id;
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS client_credentials_write_once ON simulation.client_credentials;
CREATE TRIGGER client_credentials_write_once
    BEFORE UPDATE ON simulation.client_credentials
    FOR EACH ROW EXECUTE FUNCTION simulation.client_credentials_write_once();

SELECT public.audit_enable('simulation.client_credentials');

INSERT INTO history.schema_migrations (filename) VALUES ('038_client_credentials.sql') ON CONFLICT (filename) DO NOTHING;

COMMIT;
