ALTER TABLE simulation.rooms
    ADD COLUMN IF NOT EXISTS match_format TEXT NOT NULL DEFAULT 'T20'
        CHECK (match_format IN ('T20', 'ODI', 'Test'));
