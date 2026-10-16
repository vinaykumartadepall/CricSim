-- 035: correct one player's Cricinfo id after a Cricsheet register fix.
--
-- Cricsheet's people register (people.csv) mapped code f6ba97c6
-- ("Dilum Fernando", Romania) to Cricinfo id 1535795 until it was corrected
-- (register of 2026-10-07): f6ba97c6 -> 1174261, while 1535795 now belongs to
-- 70c36d4d ("Disna Jayasooriya", Bahrain). Our row kept the old id, so ESPN
-- enrichment filled it with Disna Jayasooriya's details, and the unique index
-- on cricinfo_id blocked enrichment pass 1 from mapping her own new row.
--
-- Keyed by the Cricsheet code (stable across databases) and guarded on the old
-- value, so it is a no-op if already applied. The ESPN-derived fields are
-- cleared so `python -m db.enrich_players --commit --pass2-only` re-fetches
-- the correct details. Match history is left exactly as Cricsheet records it.

SET app.actor = 'migration:035';

BEGIN;

UPDATE history.players
SET cricinfo_id      = 1174261,
    display_name     = NULL,
    player_role      = NULL,
    batting_style    = NULL,
    bowling_style    = NULL,
    country_id       = NULL,
    espn_country_int = NULL
WHERE code = 'f6ba97c6' AND cricinfo_id = 1535795;

INSERT INTO history.schema_migrations (filename) VALUES ('035_fix_cricinfo_f6ba97c6.sql') ON CONFLICT (filename) DO NOTHING;

COMMIT;
