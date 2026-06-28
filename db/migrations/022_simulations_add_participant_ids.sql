ALTER TABLE simulation.simulations
    ADD COLUMN IF NOT EXISTS participant_ids TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_simulations_participant_ids
    ON simulation.simulations USING GIN (participant_ids);
