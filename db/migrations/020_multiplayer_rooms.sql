CREATE TABLE IF NOT EXISTS simulation.rooms (
    room_id       TEXT        PRIMARY KEY,          -- 6-char uppercase code
    host_id       TEXT        NOT NULL,             -- client_id of creator
    mode          TEXT        NOT NULL DEFAULT '1v1' CHECK (mode IN ('1v1','tournament')),
    status        TEXT        NOT NULL DEFAULT 'waiting'
                              CHECK (status IN ('waiting','drafting','simulating','completed')),
    tournament_name TEXT      NOT NULL,
    player_count  SMALLINT    NOT NULL DEFAULT 2,   -- expected number of players
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS simulation.room_members (
    room_id       TEXT        NOT NULL REFERENCES simulation.rooms(room_id) ON DELETE CASCADE,
    client_id     TEXT        NOT NULL,
    display_name  TEXT        NOT NULL,
    draft_order   SMALLINT,                         -- assigned when draft starts
    squad         JSONB       NOT NULL DEFAULT '[]', -- ordered list of player_ids
    joined_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (room_id, client_id)
);

CREATE INDEX IF NOT EXISTS idx_rooms_status ON simulation.rooms(status);
