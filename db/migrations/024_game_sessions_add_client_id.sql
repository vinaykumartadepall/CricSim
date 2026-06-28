-- Migration 024: add client_id to game_sessions and change primary key to (sim_id, client_id).
-- This allows multiplayer sims to have one row per participant instead of one row per sim.
--
-- All existing rows are single-player sims whose simulations.client_id is not null;
-- they are backfilled safely. Any orphaned rows (client_id unresolvable) are deleted.

BEGIN;

-- 1. Add client_id column (nullable during migration)
ALTER TABLE simulation.game_sessions ADD COLUMN IF NOT EXISTS client_id TEXT;

-- 2. Backfill from the parent simulations row
UPDATE simulation.game_sessions gs
SET client_id = s.client_id
FROM simulation.simulations s
WHERE gs.sim_id = s.sim_id
  AND gs.client_id IS NULL;

-- 3. Drop rows that could not be backfilled (should be none for well-formed data)
DELETE FROM simulation.game_sessions WHERE client_id IS NULL;

-- 4. Enforce NOT NULL now that backfill is done
ALTER TABLE simulation.game_sessions ALTER COLUMN client_id SET NOT NULL;

-- 5. Drop the old single-column primary key
ALTER TABLE simulation.game_sessions DROP CONSTRAINT game_sessions_pkey;

-- 6. New composite primary key: one row per (simulation, participant)
ALTER TABLE simulation.game_sessions ADD PRIMARY KEY (sim_id, client_id);

COMMIT;
