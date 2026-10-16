-- 037: database-level CHECKs for the fixed vocabularies in enums/domain.py, and
-- the first-class (MDM) match-shape fix.
--
-- 1. CHECK constraints: rooms and the precomputed history tables already had
--    them; the tables below accepted any string. Each list must equal its enum
--    (tests/test_enums.py compares them against db/schema.sql, which mirrors
--    this file). Constraint names are Postgres's own defaults for an inline
--    column CHECK (<table>_<column>_check), so a database built from schema.sql
--    ends up with identical names. Adding a CHECK scans the table and fails -
--    rolling back this whole migration - if any existing row violates it.
--
-- 2. MDM rows: the Cricsheet parser only treated the exact label 'Test' as a
--    4-innings game, so every multi-day 'MDM' match (first-class) was stored
--    as 2 innings of 20 overs. Fixed in parser/cricsheet_parser.py; this
--    corrects the existing rows to match Tests (4 innings, no over limit).

SET app.actor = 'migration:037';

BEGIN;

ALTER TABLE simulation.simulations
    DROP CONSTRAINT IF EXISTS simulations_simulation_type_check,
    ADD  CONSTRAINT simulations_simulation_type_check
         CHECK (simulation_type IN ('match','tournament')),
    DROP CONSTRAINT IF EXISTS simulations_status_check,
    ADD  CONSTRAINT simulations_status_check
         CHECK (status IN ('pending','running','completed','failed')),
    DROP CONSTRAINT IF EXISTS simulations_mode_check,
    ADD  CONSTRAINT simulations_mode_check
         CHECK (mode IS NULL OR mode IN ('fun','challenge','custom','multiplayer'));

ALTER TABLE simulation.game_sessions
    DROP CONSTRAINT IF EXISTS game_sessions_mode_check,
    ADD  CONSTRAINT game_sessions_mode_check
         CHECK (mode IS NULL OR mode IN ('fun','challenge','custom','multiplayer'));

ALTER TABLE simulation.tournaments
    DROP CONSTRAINT IF EXISTS tournaments_format_check,
    ADD  CONSTRAINT tournaments_format_check
         CHECK (format IS NULL OR format IN ('T20','ODI','Test')),
    DROP CONSTRAINT IF EXISTS tournaments_gender_check,
    ADD  CONSTRAINT tournaments_gender_check
         CHECK (gender IS NULL OR gender IN ('male','female'));

ALTER TABLE simulation.matches
    DROP CONSTRAINT IF EXISTS matches_match_format_check,
    ADD  CONSTRAINT matches_match_format_check
         CHECK (match_format IS NULL OR match_format IN ('T20','ODI','Test')),
    DROP CONSTRAINT IF EXISTS matches_result_check,
    ADD  CONSTRAINT matches_result_check
         CHECK (result IS NULL OR result IN ('win','tie','no result')),
    DROP CONSTRAINT IF EXISTS matches_gender_check,
    ADD  CONSTRAINT matches_gender_check
         CHECK (gender IS NULL OR gender IN ('male','female'));

UPDATE history.matches
SET innings_per_match = 4, overs_per_innings = NULL
WHERE match_format = 'MDM'
  AND (innings_per_match IS DISTINCT FROM 4 OR overs_per_innings IS NOT NULL);

ALTER TABLE history.matches
    DROP CONSTRAINT IF EXISTS matches_match_format_check,
    ADD  CONSTRAINT matches_match_format_check
         CHECK (match_format IS NULL OR match_format IN ('Test','MDM','ODI','ODM','T20','IT20')),
    DROP CONSTRAINT IF EXISTS matches_match_type_check,
    ADD  CONSTRAINT matches_match_type_check
         CHECK (match_type IS NULL OR match_type IN ('international','club')),
    DROP CONSTRAINT IF EXISTS matches_gender_check,
    ADD  CONSTRAINT matches_gender_check
         CHECK (gender IS NULL OR gender IN ('male','female'));

INSERT INTO history.schema_migrations (filename) VALUES ('037_vocabulary_checks.sql') ON CONFLICT (filename) DO NOTHING;

COMMIT;
