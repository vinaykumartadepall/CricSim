-- Migration 028: add batting_position to simulation.match_players.
--
-- Lets the scorecard's "Did not bat" list show a team's remaining batters in
-- their actual lineup order (matching how team.players/inning_players are
-- ordered at simulation time), instead of an arbitrary DB read order.
-- NULL for rows inserted before this migration.

BEGIN;

ALTER TABLE simulation.match_players ADD COLUMN IF NOT EXISTS batting_position SMALLINT;

COMMIT;
