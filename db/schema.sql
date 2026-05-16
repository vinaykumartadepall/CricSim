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
-- Simulation Sequences (Mirror)
CREATE SEQUENCE IF NOT EXISTS simulation.tournaments_id_seq START WITH 1000;
CREATE SEQUENCE IF NOT EXISTS simulation.venues_id_seq START WITH 5000;
CREATE SEQUENCE IF NOT EXISTS simulation.teams_id_seq START WITH 10000;
CREATE SEQUENCE IF NOT EXISTS simulation.players_id_seq START WITH 100000;
CREATE SEQUENCE IF NOT EXISTS simulation.matches_id_seq START WITH 1000000;
CREATE SEQUENCE IF NOT EXISTS simulation.deliveries_id_seq START WITH 10000000000;
-------------------------------------------------------------------------------
-- HISTORY SCHEMA
-------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS history.players (
    player_id INT PRIMARY KEY DEFAULT nextval('history.players_id_seq'),
    code VARCHAR(32) UNIQUE,
    -- JSON hash (e.g. "864c199e")
    name VARCHAR(128),
    original_name VARCHAR(128),
    gender VARCHAR(16)
);
CREATE TABLE IF NOT EXISTS history.teams (
    team_id INT PRIMARY KEY DEFAULT nextval('history.teams_id_seq'),
    name VARCHAR(256) UNIQUE,
    type VARCHAR(32),
    gender VARCHAR(16)
);
CREATE TABLE IF NOT EXISTS history.venues (
    venue_id INT PRIMARY KEY DEFAULT nextval('history.venues_id_seq'),
    name VARCHAR(256) UNIQUE,
    city VARCHAR(128),
    country TEXT
);
CREATE TABLE IF NOT EXISTS history.tournaments (
    tournament_id INT PRIMARY KEY DEFAULT nextval('history.tournaments_id_seq'),
    tournament_name VARCHAR(256),
    season VARCHAR(32),
    UNIQUE(tournament_name, season)
);
CREATE TABLE IF NOT EXISTS history.tournament_teams (
    tournament_id INT REFERENCES history.tournaments(tournament_id),
    team_id INT REFERENCES history.teams(team_id),
    PRIMARY KEY (tournament_id, team_id)
);
CREATE TABLE IF NOT EXISTS history.matches (
    match_id INT PRIMARY KEY DEFAULT nextval('history.matches_id_seq'),
    original_match_id VARCHAR(64),
    -- JSON filename or internal ID
    name VARCHAR(256),
    venue_id INT REFERENCES history.venues(venue_id),
    tournament_id INT REFERENCES history.tournaments(tournament_id),
    home_team_id INT REFERENCES history.teams(team_id),
    away_team_id INT REFERENCES history.teams(team_id),
    gender VARCHAR(16),
    match_format VARCHAR(32),
    -- Test, ODI, T20
    match_type VARCHAR(32),
    -- Men's, Women's
    balls_per_over INT DEFAULT 6,
    overs_per_innings INT,
    innings_per_match INT,
    result VARCHAR(32),
    -- Win, tie, no result
    result_type VARCHAR(32),
    -- Normal, DLS
    winner_id INT REFERENCES history.teams(team_id),
    win_type VARCHAR(16),
    -- Runs, wickets
    win_by INT,
    -- Number of runs/wickets
    player_of_match_id INT REFERENCES history.players(player_id),
    toss_winner_id INT REFERENCES history.teams(team_id),
    toss_decision VARCHAR(32),
    -- Extra meta fields useful for us not in strict schema.txt but good to have
    season VARCHAR(32),
    date DATE
);
CREATE TABLE IF NOT EXISTS history.match_players (
    match_id INT REFERENCES history.matches(match_id),
    team_id INT REFERENCES history.teams(team_id),
    player_id INT REFERENCES history.players(player_id),
    PRIMARY KEY (match_id, player_id)
);
CREATE TABLE IF NOT EXISTS history.deliveries (
    delivery_id BIGINT PRIMARY KEY DEFAULT nextval('history.deliveries_id_seq'),
    match_id INT REFERENCES history.matches(match_id),
    inning_number INT,
    over_number INT,
    ball_number INT,
    -- The legal ball number
    batter_id INT REFERENCES history.players(player_id),
    bowler_id INT REFERENCES history.players(player_id),
    non_striker_id INT REFERENCES history.players(player_id),
    batting_team_id INT REFERENCES history.teams(team_id),
    bowling_team_id INT REFERENCES history.teams(team_id),
    runs_batter INT,
    runs_extras INT,
    outcome_type VARCHAR(32),
    -- Wicket, dot, runs, extras
    outcome_kind VARCHAR(32),
    -- Caught, runout, Wide, Noball
    outcome_player_id INT REFERENCES history.players(player_id) -- Player ID of fielder involved
);
-------------------------------------------------------------------------------
-- SIMULATION SCHEMA (Identical Structure)
-------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS simulation.players (
    player_id INT PRIMARY KEY DEFAULT nextval('simulation.players_id_seq'),
    code VARCHAR(32) UNIQUE,
    name VARCHAR(128),
    original_name VARCHAR(128),
    gender VARCHAR(16)
);
CREATE TABLE IF NOT EXISTS simulation.teams (
    team_id INT PRIMARY KEY DEFAULT nextval('simulation.teams_id_seq'),
    name VARCHAR(256) UNIQUE,
    type VARCHAR(32),
    gender VARCHAR(16)
);
CREATE TABLE IF NOT EXISTS simulation.venues (
    venue_id INT PRIMARY KEY DEFAULT nextval('simulation.venues_id_seq'),
    name VARCHAR(256) UNIQUE,
    city VARCHAR(128)
);
CREATE TABLE IF NOT EXISTS simulation.tournaments (
    tournament_id INT PRIMARY KEY DEFAULT nextval('simulation.tournaments_id_seq'),
    tournament_name VARCHAR(256),
    season VARCHAR(32),
    UNIQUE(tournament_name, season)
);
CREATE TABLE IF NOT EXISTS simulation.tournament_teams (
    tournament_id INT REFERENCES simulation.tournaments(tournament_id),
    team_id INT REFERENCES simulation.teams(team_id),
    PRIMARY KEY (tournament_id, team_id)
);
CREATE TABLE IF NOT EXISTS simulation.matches (
    match_id INT PRIMARY KEY DEFAULT nextval('simulation.matches_id_seq'),
    original_match_id VARCHAR(64),
    name VARCHAR(256),
    venue_id INT REFERENCES simulation.venues(venue_id),
    tournament_id INT REFERENCES simulation.tournaments(tournament_id),
    home_team_id INT REFERENCES simulation.teams(team_id),
    away_team_id INT REFERENCES simulation.teams(team_id),
    gender VARCHAR(16),
    match_format VARCHAR(32),
    match_type VARCHAR(32),
    balls_per_over INT DEFAULT 6,
    overs_per_innings INT,
    innings_per_match INT,
    result VARCHAR(32),
    result_type VARCHAR(32),
    winner_id INT REFERENCES simulation.teams(team_id),
    win_type VARCHAR(16),
    win_by INT,
    player_of_match_id INT REFERENCES simulation.players(player_id),
    toss_winner_id INT REFERENCES simulation.teams(team_id),
    toss_decision VARCHAR(32),
    season VARCHAR(32),
    date DATE
);
CREATE TABLE IF NOT EXISTS simulation.match_players (
    match_id INT REFERENCES simulation.matches(match_id),
    team_id INT REFERENCES simulation.teams(team_id),
    player_id INT REFERENCES simulation.players(player_id),
    PRIMARY KEY (match_id, player_id)
);
CREATE TABLE IF NOT EXISTS simulation.deliveries (
    delivery_id BIGINT PRIMARY KEY DEFAULT nextval('simulation.deliveries_id_seq'),
    match_id INT REFERENCES simulation.matches(match_id),
    inning_number INT,
    over_number INT,
    ball_number INT,
    batter_id INT REFERENCES simulation.players(player_id),
    bowler_id INT REFERENCES simulation.players(player_id),
    non_striker_id INT REFERENCES simulation.players(player_id),
    batting_team_id INT REFERENCES simulation.teams(team_id),
    bowling_team_id INT REFERENCES simulation.teams(team_id),
    runs_batter INT,
    runs_extras INT,
    outcome_type VARCHAR(32),
    outcome_kind VARCHAR(32),
    outcome_player_id INT REFERENCES simulation.players(player_id)
);