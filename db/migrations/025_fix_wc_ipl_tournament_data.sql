-- Migration 025: fix wrong team short_names, tournament_name, and season values
-- for the ODI World Cup (1074, 1460) and 4 IPL editions (1106, 1515, 1480, 1460)
-- that were seeded incorrectly.
--
-- Root causes:
-- 1. db/seed_sim_configs.py's _TEAM_META override dict only covers franchise
--    teams; national teams fell through to a naive name[:3].upper() truncation
--    (New Zealand -> NEW, South Africa -> SOU, West Indies -> WES,
--    Netherlands -> NET, Sri Lanka -> SRI).
-- 2. history.tournaments had 1074 named "World Cup" instead of the canonical
--    "ICC Cricket World Cup" used by 1460.
-- 3. Cross-year season strings ("2007/08", "2009/10", "2020/21", "2023/24")
--    weren't normalized to the single real-world edition year.
--
-- simulation.tournament_seeded.config is a JSONB snapshot taken at seed time
-- and is never re-synced when history.tournaments changes later, so every fix
-- below is applied in both places. Scope is intentionally limited to these
-- specific tournament_ids only — no other tournaments' data is touched.

BEGIN;

-- 1. Team short_name + tournament_name fix (World Cup: 1074, 1460)
UPDATE simulation.tournament_seeded
SET config = jsonb_set(
    jsonb_set(
        config,
        '{teams}',
        (
            SELECT jsonb_agg(
                CASE team->>'name'
                    WHEN 'New Zealand'  THEN jsonb_set(team, '{short_name}', '"NZ"')
                    WHEN 'South Africa' THEN jsonb_set(team, '{short_name}', '"SA"')
                    WHEN 'West Indies'  THEN jsonb_set(team, '{short_name}', '"WI"')
                    WHEN 'Netherlands'  THEN jsonb_set(team, '{short_name}', '"NED"')
                    WHEN 'Sri Lanka'    THEN jsonb_set(team, '{short_name}', '"SL"')
                    ELSE team
                END
            )
            FROM jsonb_array_elements(config->'teams') AS team
        )
    ),
    '{tournament_name}',
    '"ICC Cricket World Cup"'
)
WHERE tournament_id IN (1074, 1460);

UPDATE history.tournaments
SET tournament_name = 'ICC Cricket World Cup'
WHERE tournament_id = 1074;

-- 2. Season normalization (IPL: 1106, 1515, 1480; World Cup: 1460)
UPDATE history.tournaments
SET season = CASE tournament_id
    WHEN 1106 THEN '2008'
    WHEN 1515 THEN '2010'
    WHEN 1480 THEN '2020'
    WHEN 1460 THEN '2023'
END
WHERE tournament_id IN (1106, 1515, 1480, 1460);

UPDATE simulation.tournament_seeded
SET config = jsonb_set(
    config,
    '{season}',
    (CASE tournament_id
        WHEN 1106 THEN '"2008"'
        WHEN 1515 THEN '"2010"'
        WHEN 1480 THEN '"2020"'
        WHEN 1460 THEN '"2023"'
    END)::jsonb
)
WHERE tournament_id IN (1106, 1515, 1480, 1460);

COMMIT;
