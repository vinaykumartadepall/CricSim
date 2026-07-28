ALTER TABLE simulation.rooms
    ADD COLUMN IF NOT EXISTS schedule_type TEXT
        CHECK (schedule_type IS NULL OR schedule_type IN ('round_robin', 'double_round_robin')),
    ADD COLUMN IF NOT EXISTS playoff_format TEXT
        CHECK (playoff_format IS NULL OR playoff_format IN ('semis_final', 'ipl')),
    ADD COLUMN IF NOT EXISTS venue_config JSONB;
