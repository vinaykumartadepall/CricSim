-- Create Schemas
CREATE SCHEMA IF NOT EXISTS history;
CREATE SCHEMA IF NOT EXISTS simulation;
-- No extension needed for integers
-------------------------------------------------------------------------------
-- SEQUENCES with OFFSETS
-------------------------------------------------------------------------------
-- Tournaments: 1,000+
CREATE SEQUENCE IF NOT EXISTS history.tournaments_id_seq START WITH 1000;
-- Venues: 5,000+
CREATE SEQUENCE IF NOT EXISTS history.venues_id_seq START WITH 5000;
-- Teams: 10,000+
CREATE SEQUENCE IF NOT EXISTS history.teams_id_seq START WITH 10000;
-- Players: 100,000+
CREATE SEQUENCE IF NOT EXISTS history.players_id_seq START WITH 100000;
-- Matches: 1,000,000+
CREATE SEQUENCE IF NOT EXISTS history.matches_id_seq START WITH 1000000;
-- Deliveries: 10,000,000,000+ (BigInt)
CREATE SEQUENCE IF NOT EXISTS history.deliveries_id_seq START WITH 10000000000;
-- Simulation Sequences (venues and players removed - reference history schema)
CREATE SEQUENCE IF NOT EXISTS simulation.tournaments_id_seq START WITH 1000;
CREATE SEQUENCE IF NOT EXISTS simulation.teams_id_seq START WITH 10000;
CREATE SEQUENCE IF NOT EXISTS simulation.matches_id_seq START WITH 1000000;
CREATE SEQUENCE IF NOT EXISTS simulation.deliveries_id_seq START WITH 10000000000;
-------------------------------------------------------------------------------
-- HISTORY SCHEMA
-------------------------------------------------------------------------------
-- Country registry: cricket nations use ESPN team IDs; geographic-only nations have espn_id NULL.
CREATE TABLE IF NOT EXISTS history.countries (
    country_id  SERIAL       PRIMARY KEY,
    name        VARCHAR(128) NOT NULL UNIQUE,
    code        VARCHAR(8),
    espn_id     INT          UNIQUE
);

CREATE TABLE IF NOT EXISTS history.players (
    player_id        INT          PRIMARY KEY DEFAULT nextval('history.players_id_seq'),
    code             VARCHAR(32)  UNIQUE,
    name             VARCHAR(128),
    original_name    VARCHAR(128),
    gender           VARCHAR(16),
    display_name     VARCHAR(256),
    batting_style    VARCHAR(64),
    bowling_style    VARCHAR(64),
    player_role      VARCHAR(32),
    country_id       INT          REFERENCES history.countries(country_id),
    cricinfo_id      INT          UNIQUE,
    espn_country_int INT
);

CREATE TABLE IF NOT EXISTS history.teams (
    team_id INT PRIMARY KEY DEFAULT nextval('history.teams_id_seq'),
    name VARCHAR(256) UNIQUE,
    type VARCHAR(32),
    gender VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS history.venues (
    venue_id   INT PRIMARY KEY DEFAULT nextval('history.venues_id_seq'),
    name       VARCHAR(256) UNIQUE,
    city       VARCHAR(128),
    country_id INT REFERENCES history.countries(country_id)
);

CREATE TABLE IF NOT EXISTS history.tournaments (
    tournament_id   INT  PRIMARY KEY DEFAULT nextval('history.tournaments_id_seq'),
    tournament_name VARCHAR(256),
    season          VARCHAR(32),
    UNIQUE(tournament_name, season)
);

CREATE TABLE IF NOT EXISTS history.tournament_teams (
    tournament_id INT REFERENCES history.tournaments(tournament_id),
    team_id       INT REFERENCES history.teams(team_id),
    PRIMARY KEY (tournament_id, team_id)
);

CREATE TABLE IF NOT EXISTS history.matches (
    match_id          INT          PRIMARY KEY DEFAULT nextval('history.matches_id_seq'),
    original_match_id VARCHAR(64),
    name              VARCHAR(256),
    venue_id          INT          REFERENCES history.venues(venue_id),
    tournament_id     INT          REFERENCES history.tournaments(tournament_id),
    home_team_id      INT          REFERENCES history.teams(team_id),
    away_team_id      INT          REFERENCES history.teams(team_id),
    gender            VARCHAR(16),
    match_format      VARCHAR(32),
    match_type        VARCHAR(32),
    balls_per_over    INT DEFAULT 6,
    overs_per_innings INT,
    innings_per_match INT,
    result            VARCHAR(32),
    result_type       VARCHAR(32),
    winner_id         INT          REFERENCES history.teams(team_id),
    win_type          VARCHAR(16),
    win_by            INT,
    player_of_match_id INT         REFERENCES history.players(player_id),
    toss_winner_id    INT          REFERENCES history.teams(team_id),
    toss_decision     VARCHAR(32),
    season            VARCHAR(32),
    date              DATE
);

CREATE TABLE IF NOT EXISTS history.match_players (
    match_id  INT REFERENCES history.matches(match_id),
    team_id   INT REFERENCES history.teams(team_id),
    player_id INT REFERENCES history.players(player_id),
    PRIMARY KEY (match_id, player_id)
);

CREATE TABLE IF NOT EXISTS history.deliveries (
    delivery_id     BIGINT PRIMARY KEY DEFAULT nextval('history.deliveries_id_seq'),
    match_id        INT    REFERENCES history.matches(match_id),
    inning_number   INT,
    over_number     INT,
    ball_number     INT,
    batter_id       INT    REFERENCES history.players(player_id),
    bowler_id       INT    REFERENCES history.players(player_id),
    non_striker_id  INT    REFERENCES history.players(player_id),
    batting_team_id INT    REFERENCES history.teams(team_id),
    bowling_team_id INT    REFERENCES history.teams(team_id),
    runs_batter     INT,
    runs_extras     INT,
    outcome_type    VARCHAR(32),
    outcome_kind    VARCHAR(32),
    outcome_player_id INT  REFERENCES history.players(player_id)
);
-- Performance indexes for the 11M-row delivery table.
CREATE INDEX IF NOT EXISTS idx_deliveries_bowler_id ON history.deliveries (bowler_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_batter_id ON history.deliveries (batter_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_match_id  ON history.deliveries (match_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_outcome_player_id ON history.deliveries (outcome_player_id);

-------------------------------------------------------------------------------
-- PRECOMPUTED TABLES
-------------------------------------------------------------------------------
-- Global outcome distribution per calendar year, format, and gender.
CREATE TABLE IF NOT EXISTS history.global_yearly_baseline (
    year          SMALLINT         NOT NULL,
    match_format  VARCHAR(16)      NOT NULL,
    gender        VARCHAR(8)       NOT NULL,
    runs_batter   SMALLINT         NOT NULL,
    runs_extras   SMALLINT         NOT NULL,
    outcome_type  VARCHAR(32)      NOT NULL,
    outcome_kind  VARCHAR(32),
    probability   DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_global_yearly_baseline
    ON history.global_yearly_baseline (year, match_format, gender, runs_batter, runs_extras, outcome_type, outcome_kind)
    NULLS NOT DISTINCT;
CREATE INDEX IF NOT EXISTS idx_global_yearly_baseline_fmt
    ON history.global_yearly_baseline (match_format, gender, year);

-- Per-player outcome distributions (batting, bowling, per-phase, per-milestone).
-- stat_type values:
--   'batting', 'bowling',
--   'phase_pp1','phase_pp2','phase_mid1','phase_mid2','phase_mid3','phase_death1','phase_death2' (T20/ODI),
--   'phase_new','phase_early','phase_middle','phase_late' (Test),
--   'milestone_m0','milestone_m10',...,'milestone_m100'
-- probs_raw: decay-weighted distribution (no era normalization).
-- probs_era: era-normalized distribution (NULL for Test or when insufficient data).
-- JSONB key format: "runs_batter|runs_extras|outcome_type|outcome_kind" (empty string when NULL).
CREATE TABLE IF NOT EXISTS history.player_outcome_stats (
    player_id    INT          NOT NULL REFERENCES history.players(player_id),
    match_format VARCHAR(4)   NOT NULL CHECK (match_format IN ('T20','ODI','Test')),
    stat_type    VARCHAR(25)  NOT NULL,
    probs_raw    JSONB        NOT NULL,
    probs_era    JSONB,
    ball_count   INT          NOT NULL DEFAULT 0,
    computed_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, match_format, stat_type)
);
CREATE INDEX IF NOT EXISTS idx_player_outcome_stats_fmt_type
    ON history.player_outcome_stats (match_format, stat_type);

-- Per-player distributions at a specific venue or country.
-- context_type='venue': venue_id NOT NULL, country NULL.
-- context_type='country': country NOT NULL, venue_id NULL.
CREATE TABLE IF NOT EXISTS history.player_context_stats (
    player_id    INT          NOT NULL REFERENCES history.players(player_id),
    match_format VARCHAR(4)   NOT NULL CHECK (match_format IN ('T20','ODI','Test')),
    context_type VARCHAR(8)   NOT NULL CHECK (context_type IN ('venue','country')),
    venue_id     INT          REFERENCES history.venues(venue_id),
    country      VARCHAR(60),
    probs_raw    JSONB        NOT NULL,
    probs_era    JSONB,
    ball_count   INT          NOT NULL DEFAULT 0,
    computed_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_ctx_exclusive CHECK (
        (context_type = 'venue'   AND venue_id IS NOT NULL AND country IS NULL) OR
        (context_type = 'country' AND country  IS NOT NULL AND venue_id IS NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_player_context_stats_pk
    ON history.player_context_stats
    (player_id, match_format, context_type,
     COALESCE(venue_id, -1), COALESCE(country, ''));
CREATE INDEX IF NOT EXISTS idx_player_context_stats_venue
    ON history.player_context_stats (venue_id, match_format)
    WHERE context_type = 'venue';

-- Batter-bowler head-to-head distributions (min 12 balls total per pair).
-- probs_era is NULL for Test cricket.
CREATE TABLE IF NOT EXISTS history.batter_bowler_matchups (
    batter_id    INT          NOT NULL REFERENCES history.players(player_id),
    bowler_id    INT          NOT NULL REFERENCES history.players(player_id),
    match_format VARCHAR(4)   NOT NULL CHECK (match_format IN ('T20','ODI','Test')),
    probs_raw    JSONB        NOT NULL,
    probs_era    JSONB,
    ball_count   INT          NOT NULL DEFAULT 0,
    computed_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (batter_id, bowler_id, match_format)
);
CREATE INDEX IF NOT EXISTS idx_batter_bowler_matchups_bowler
    ON history.batter_bowler_matchups (bowler_id, match_format);

-- Bowler over-frequency and phase distributions.
-- dist_type: 'over_freq' | 'phase_dist'
-- match_type: 'all' | 'international'
-- inning_number: 0=all innings, 1=first, 2=second
-- venue_id / country: NULL means all locations.
CREATE TABLE IF NOT EXISTS history.bowler_order_stats (
    player_id     INT          NOT NULL REFERENCES history.players(player_id),
    match_format  VARCHAR(4)   NOT NULL CHECK (match_format IN ('T20','ODI','Test')),
    dist_type     VARCHAR(10)  NOT NULL CHECK (dist_type IN ('over_freq','phase_dist')),
    match_type    VARCHAR(15)  NOT NULL CHECK (match_type IN ('all','international')),
    inning_number SMALLINT     NOT NULL CHECK (inning_number IN (0,1,2)),
    venue_id      INT          REFERENCES history.venues(venue_id),
    country       VARCHAR(60),
    probs         JSONB        NOT NULL,
    computed_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_bowler_order_ctx CHECK (venue_id IS NULL OR country IS NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bowler_order_stats_pk
    ON history.bowler_order_stats
    (player_id, match_format, dist_type, match_type, inning_number,
     COALESCE(venue_id, -1), COALESCE(country, ''));

-- Per-player scalar statistics (career economy/wicket-rate, workload, death-over batting,
-- phase-level bowling, role flags).
-- stat_type values: 'career', 'workload', 'death_overs',
--   'phase_powerplay', 'phase_middle', 'phase_death', 'roles'
-- match_format may be 'any' for format-independent stats (e.g. 'roles').
CREATE TABLE IF NOT EXISTS history.player_scalar_stats (
    player_id    INT          NOT NULL REFERENCES history.players(player_id),
    match_format VARCHAR(4)   NOT NULL,
    stat_type    VARCHAR(20)  NOT NULL,
    data         JSONB        NOT NULL,
    computed_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, match_format, stat_type)
);
CREATE INDEX IF NOT EXISTS idx_player_scalar_stats_fmt_type
    ON history.player_scalar_stats (match_format, stat_type);

-- Format-level aggregate distributions.
-- stat_key examples: 'baseline', 'phase_pp1', ..., 'batting_position_top_order',
--   'innings_1', 'innings_2', 'over_0', ...
CREATE TABLE IF NOT EXISTS history.aggregate_stats (
    match_format  VARCHAR(4)   NOT NULL CHECK (match_format IN ('T20','ODI','Test')),
    gender        VARCHAR(8)   NOT NULL,
    stat_key      VARCHAR(40)  NOT NULL,
    probs         JSONB        NOT NULL,
    computed_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (match_format, gender, stat_key)
);

-- Venue-level outcome distributions (decay-weighted with half-life 7y).
CREATE TABLE IF NOT EXISTS history.venue_stats (
    venue_id      INT          NOT NULL REFERENCES history.venues(venue_id),
    match_format  VARCHAR(4)   NOT NULL CHECK (match_format IN ('T20','ODI','Test')),
    gender        VARCHAR(8)   NOT NULL,
    probs         JSONB        NOT NULL,
    ball_count    INT          NOT NULL DEFAULT 0,
    computed_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (venue_id, match_format, gender)
);

-- Country-level outcome distributions (decay-weighted with half-life 8y).
CREATE TABLE IF NOT EXISTS history.country_stats (
    country       VARCHAR(60)  NOT NULL,
    match_format  VARCHAR(4)   NOT NULL CHECK (match_format IN ('T20','ODI','Test')),
    gender        VARCHAR(8)   NOT NULL,
    probs         JSONB        NOT NULL,
    ball_count    INT          NOT NULL DEFAULT 0,
    computed_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (country, match_format, gender)
);

-- Tournament-level outcome distributions (decay-weighted with half-life 3y).
CREATE TABLE IF NOT EXISTS history.tournament_outcome_stats (
    tournament_id INT          NOT NULL REFERENCES history.tournaments(tournament_id),
    probs         JSONB        NOT NULL,
    ball_count    INT          NOT NULL DEFAULT 0,
    computed_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tournament_id)
);

-------------------------------------------------------------------------------
-- SIMULATION SCHEMA
-- Players and venues are not duplicated here - they are always looked up from
-- the history schema.  Teams and tournaments are simulation-specific (custom
-- squads, custom tournament configs) so they live here.
-------------------------------------------------------------------------------

-- API job tracking: one row per POST /createsim call.
CREATE TABLE IF NOT EXISTS simulation.simulations (
    sim_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_type VARCHAR(20) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    config          JSONB       NOT NULL,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    client_id       VARCHAR(64),
    mode            VARCHAR(16),
    participant_ids TEXT[]      NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_simulations_status_created
    ON simulation.simulations (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_simulations_client_id
    ON simulation.simulations (client_id)
    WHERE client_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_simulations_participant_ids
    ON simulation.simulations USING GIN (participant_ids);

-- UI game context (fun/challenge mode metadata, squad swaps).
-- swaps is a JSONB array: [{"player_out_id": 123, "player_in_id": 456, "from_team_id": 789}]
-- One row per (simulation, participant). Single-player sims have one row (client_id = simulations.client_id).
-- Multiplayer sims have one row per participant, enabling per-user team name and placement tracking.
CREATE TABLE IF NOT EXISTS simulation.game_sessions (
    sim_id               UUID    NOT NULL REFERENCES simulation.simulations(sim_id),
    client_id            TEXT    NOT NULL,
    mode                 VARCHAR(16),
    source_tournament_id INT,
    user_team_id         INT,
    swaps                JSONB   NOT NULL DEFAULT '[]',
    PRIMARY KEY (sim_id, client_id)
);

-- One row per source tournament-season; complete TournamentConfig-compatible document.
--
-- config (step 1: db/seed_sim_configs.py - metadata + schedule + empty players):
-- {
--   "tournament_name": "Indian Premier League",
--   "format": "T20",
--   "gender": "male",
--   "season": "2025",
--   "venues": [{"name": "Wankhede Stadium", "city": "Mumbai"}, ...],
--   "teams": [
--     {
--       "team_id": 10001,           -- history.teams.team_id (for swap lookup)
--       "name":    "Mumbai Indians",
--       "short_name": "MI",
--       "primary_color": "#004B8D",
--       "secondary_color": "#D4AF37",
--       "home_venue": "Wankhede Stadium",
--       "players": []               -- filled by precompute step below
--     }, ...
--   ],
--   "schedule": {
--     "type": "double_round_robin" | "round_robin" | "two_group_hybrid",
--     "neutral_venues": true,
--     "groups": [["Team A", ...], ["Team B", ...]],  -- two_group_hybrid only
--     "within_matches_per_pair": 1,
--     "cross_matches_per_pair":  2
--   },
--   "playoffs": {
--     "format": "none" | "two_teams" | "semis_final" | "ipl" | "quarters_semis_final",
--     "top_n": 4
--   }
-- }
--
-- config.teams[].players (step 2: db/precompute.py seed_tournament_squads):
--   Ordered array of history.players.player_id integers; index = batting position.
--
-- NULL = not yet seeded.  Raises 422 if config is NULL or any team has empty players.
CREATE TABLE IF NOT EXISTS simulation.tournament_seeded (
    tournament_id INT NOT NULL PRIMARY KEY REFERENCES history.tournaments(tournament_id),
    config        JSONB
);

-- Custom teams (simulation squads - not tied to history.teams).
-- No UNIQUE on name: the same team name can appear across multiple simulation runs.
CREATE TABLE IF NOT EXISTS simulation.teams (
    team_id         INT PRIMARY KEY DEFAULT nextval('simulation.teams_id_seq'),
    name            VARCHAR(256) NOT NULL,
    type            VARCHAR(32),
    gender          VARCHAR(16),
    primary_color   VARCHAR(32),
    secondary_color VARCHAR(32)
);

-- Custom tournaments.
-- No UNIQUE on (tournament_name, season): same tournament can be simulated many times.
CREATE TABLE IF NOT EXISTS simulation.tournaments (
    tournament_id   INT  PRIMARY KEY DEFAULT nextval('simulation.tournaments_id_seq'),
    sim_id          UUID NOT NULL REFERENCES simulation.simulations(sim_id),
    tournament_name VARCHAR(256),
    season          VARCHAR(32),
    format          VARCHAR(32),
    gender          VARCHAR(16),
    -- Group-stage standings (team, played, won, lost, tied, no_result, points, nrr),
    -- as computed once by the live tournament engine (simulator/tournament/points_table.py)
    -- when the group stage completes. Read by the results page instead of
    -- re-deriving standings from simulation.deliveries per request.
    final_standings JSONB
);

CREATE TABLE IF NOT EXISTS simulation.tournament_teams (
    tournament_id INT REFERENCES simulation.tournaments(tournament_id),
    team_id       INT REFERENCES simulation.teams(team_id),
    PRIMARY KEY (tournament_id, team_id)
);

-- One row per simulated match.
-- venue_id references history.venues (venues are real-world, not custom).
-- player_of_match_id references history.players (players are always historical).
CREATE TABLE IF NOT EXISTS simulation.matches (
    match_id           INT  PRIMARY KEY DEFAULT nextval('simulation.matches_id_seq'),
    sim_id             UUID NOT NULL REFERENCES simulation.simulations(sim_id),
    match_label        VARCHAR(64),
    name               VARCHAR(256),
    venue_id           INT  REFERENCES history.venues(venue_id),
    tournament_id      INT  REFERENCES simulation.tournaments(tournament_id),
    home_team_id       INT  REFERENCES simulation.teams(team_id),
    away_team_id       INT  REFERENCES simulation.teams(team_id),
    gender             VARCHAR(16),
    match_format       VARCHAR(32),
    balls_per_over     INT DEFAULT 6,
    overs_per_innings  INT,
    result             VARCHAR(32),
    result_type        VARCHAR(32),
    winner_id          INT  REFERENCES simulation.teams(team_id),
    win_type           VARCHAR(16),
    win_by             INT,
    is_super_over      BOOLEAN NOT NULL DEFAULT FALSE,
    player_of_match_id INT  REFERENCES history.players(player_id),
    potm_player_name   TEXT,
    potm_team_name     TEXT,
    potm_points        NUMERIC(6,2),
    toss_winner_id     INT  REFERENCES simulation.teams(team_id),
    toss_decision      VARCHAR(32),
    season             VARCHAR(32),
    date               DATE
);
CREATE INDEX IF NOT EXISTS idx_sim_matches_sim_id
    ON simulation.matches (sim_id, match_label);

-- Players who participated in a match.
CREATE TABLE IF NOT EXISTS simulation.match_players (
    match_id          INT REFERENCES simulation.matches(match_id),
    team_id           INT REFERENCES simulation.teams(team_id),
    player_id         INT REFERENCES history.players(player_id),
    batting_position  SMALLINT,
    PRIMARY KEY (match_id, player_id)
);

-- Ball-by-ball delivery data.
CREATE TABLE IF NOT EXISTS simulation.deliveries (
    delivery_id     BIGINT  PRIMARY KEY DEFAULT nextval('simulation.deliveries_id_seq'),
    match_id        INT     NOT NULL REFERENCES simulation.matches(match_id),
    inning_number   INT     NOT NULL,
    over_number     INT     NOT NULL,
    ball_number     INT     NOT NULL,
    batter_id       INT     REFERENCES history.players(player_id),
    bowler_id       INT     REFERENCES history.players(player_id),
    non_striker_id  INT     REFERENCES history.players(player_id),
    batting_team_id INT     REFERENCES simulation.teams(team_id),
    bowling_team_id INT     REFERENCES simulation.teams(team_id),
    runs_batter     INT,
    runs_extras     INT,
    outcome_type    VARCHAR(32),
    outcome_kind    VARCHAR(32),
    outcome_player_id INT   REFERENCES history.players(player_id),
    is_free_hit     BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_sim_deliveries_match
    ON simulation.deliveries (match_id, inning_number, over_number, ball_number);

CREATE TABLE IF NOT EXISTS simulation.player_awards (
    award_id     SERIAL PRIMARY KEY,
    sim_id       UUID NOT NULL REFERENCES simulation.simulations(sim_id),
    player_id    INT  REFERENCES history.players(player_id),
    player_name  TEXT NOT NULL,
    team_name    TEXT NOT NULL,
    batting_pts  NUMERIC(8, 2) NOT NULL DEFAULT 0,
    bowling_pts  NUMERIC(8, 2) NOT NULL DEFAULT 0,
    fielding_pts NUMERIC(8, 2) NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_player_awards_sim_id
    ON simulation.player_awards (sim_id);

CREATE TABLE IF NOT EXISTS simulation.leaderboard_cache (
    tournament_id    INT         NOT NULL REFERENCES simulation.tournaments(tournament_id),
    leaderboard_type VARCHAR(64) NOT NULL,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    entries          JSONB       NOT NULL,
    PRIMARY KEY (tournament_id, leaderboard_type)
);

-- Multiplayer draft rooms
CREATE TABLE IF NOT EXISTS simulation.rooms (
    room_id        TEXT        PRIMARY KEY,
    host_id        TEXT        NOT NULL,
    mode           TEXT        NOT NULL DEFAULT '1v1' CHECK (mode IN ('1v1','tournament')),
    status         TEXT        NOT NULL DEFAULT 'waiting'
                               CHECK (status IN ('waiting','drafting','reordering','simulating','completed')),
    tournament_name TEXT       NOT NULL,
    player_count   SMALLINT    NOT NULL DEFAULT 2,
    match_format   TEXT        NOT NULL DEFAULT 'T20' CHECK (match_format IN ('T20','ODI','Test')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rooms_status ON simulation.rooms(status);

CREATE TABLE IF NOT EXISTS simulation.room_members (
    room_id      TEXT        NOT NULL REFERENCES simulation.rooms(room_id) ON DELETE CASCADE,
    client_id    TEXT        NOT NULL,
    display_name TEXT        NOT NULL,
    draft_order  SMALLINT,
    squad        JSONB       NOT NULL DEFAULT '[]',
    joined_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (room_id, client_id)
);
