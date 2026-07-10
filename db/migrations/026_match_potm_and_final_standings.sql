-- Migration 026: persist per-match Player of the Match and final group-stage
-- standings, instead of recomputing them on every results-page load.
--
-- simulation.matches.player_of_match_id already existed (reserved, unused -
-- the only prior write of that column name in the codebase targets
-- history.matches via db/repository.py's offline ingest pipeline, a
-- different table entirely). Reusing it here for the player_id half of the
-- award; adding the denormalized name/team/points alongside it so the
-- results page doesn't need a join on every read (same pattern as
-- simulation.player_awards' player_name/team_name columns).
--
-- simulation.tournaments.final_standings stores the live tournament engine's
-- own (already NRR-all-out-rule-correct) group-stage standings as JSONB,
-- written once when the group stage completes - the results page reads this
-- instead of re-deriving standings from simulation.deliveries per request.

BEGIN;

ALTER TABLE simulation.matches
    ADD COLUMN IF NOT EXISTS potm_player_name TEXT,
    ADD COLUMN IF NOT EXISTS potm_team_name   TEXT,
    ADD COLUMN IF NOT EXISTS potm_points      NUMERIC(6,2);

ALTER TABLE simulation.tournaments
    ADD COLUMN IF NOT EXISTS final_standings JSONB;

COMMIT;
