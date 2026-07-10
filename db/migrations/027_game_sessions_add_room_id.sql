-- Migration 027: add room_id to game_sessions.
--
-- Lets a "Return to Lobby" feature recover the originating multiplayer room
-- from a sim_id alone (via game_sessions), regardless of navigation state,
-- page reloads, or viewing the result long after the fact from history.
-- NULL for single-player sessions, which have no room.

BEGIN;

ALTER TABLE simulation.game_sessions ADD COLUMN IF NOT EXISTS room_id TEXT;

COMMIT;
