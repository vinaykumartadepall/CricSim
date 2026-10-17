-- 039: the seed each simulation ran with, so it can be replayed exactly.
--
-- Every chance event in a simulation (toss, each ball, fielders, fixture
-- order, venue picks) is drawn from generators derived from this one number
-- (simulator/seeding.py). The same seed + the same stored config replays the
-- same result ball by ball, provided the code and precomputed stats haven't
-- changed (tools/replay_sim.py checks it against the stored deliveries).
--
-- Assigned when the job first runs (SimulationRepository.ensure_seed) and
-- never changed afterwards; a restarted job reuses it. NULL for simulations
-- that ran before this existed - they can't be replayed.
-- Mirrored in db/schema.sql.

SET app.actor = 'migration:039';

BEGIN;

ALTER TABLE simulation.simulations ADD COLUMN IF NOT EXISTS seed BIGINT;

INSERT INTO history.schema_migrations (filename) VALUES ('039_simulation_seed.sql') ON CONFLICT (filename) DO NOTHING;

COMMIT;
