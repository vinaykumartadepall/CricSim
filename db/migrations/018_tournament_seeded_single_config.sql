-- Migration 018: Replace simulation.tournament_seeded (sim_config + squads columns)
-- with a single `config` JSONB column (TournamentConfig-compatible document).
--
-- Also cleans up any old per-player history.tournament_squads_seeded table and
-- the old sim_config column on history.tournaments (if they still exist).

-- 1. Drop old per-player table if it survived from before the schema consolidation
DROP TABLE IF EXISTS history.tournament_squads_seeded;

-- 2. Remove old sim_config column from history.tournaments (if it still exists)
ALTER TABLE history.tournaments DROP COLUMN IF EXISTS sim_config;

-- 3. Recreate simulation.tournament_seeded with the single config column.
--    If the table already exists with sim_config+squads columns, we rename/drop them.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'simulation' AND table_name = 'tournament_seeded'
    ) THEN
        -- Add config column if not present
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'simulation' AND table_name = 'tournament_seeded'
              AND column_name = 'config'
        ) THEN
            ALTER TABLE simulation.tournament_seeded ADD COLUMN config JSONB;
        END IF;
        -- Drop old columns
        ALTER TABLE simulation.tournament_seeded DROP COLUMN IF EXISTS sim_config;
        ALTER TABLE simulation.tournament_seeded DROP COLUMN IF EXISTS squads;
    ELSE
        CREATE TABLE simulation.tournament_seeded (
            tournament_id INT NOT NULL PRIMARY KEY REFERENCES history.tournaments(tournament_id),
            config        JSONB
        );
    END IF;
END $$;
