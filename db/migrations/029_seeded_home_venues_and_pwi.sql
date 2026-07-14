-- 029: Fix already-seeded tournament configs in place
--
-- 1) Franchise leagues (IPL, BBL, PSL, CPL) are home-and-away competitions:
--    set neutral_venues=false so the scheduler assigns each team's home_venue
--    to their home fixtures instead of cycling venues. home_venue is derived
--    per season, so relocated seasons (IPL 2009 SA, 2020/21 UAE) stay correct.
--    (db/seed_sim_configs.py now writes false for new seeds; this backfills.)
--
-- 2) Pune Warriors: history.teams calls them "Pune Warriors" (no "India"),
--    so the seeder's meta lookup missed and auto-derived short_name "PUN".
--    Backfill to "PWI" (seeder meta map now covers both spellings).

BEGIN;

UPDATE simulation.tournament_seeded ts
SET config = jsonb_set(ts.config, '{schedule,neutral_venues}', 'false'::jsonb)
FROM history.tournaments t
WHERE t.tournament_id = ts.tournament_id
  AND t.tournament_name IN ('Indian Premier League', 'Big Bash League',
                            'Pakistan Super League', 'Caribbean Premier League')
  AND ts.config->'schedule'->>'neutral_venues' = 'true';

UPDATE simulation.tournament_seeded
SET config = jsonb_set(config, '{teams}', (
        SELECT jsonb_agg(
                   CASE WHEN team->>'name' = 'Pune Warriors'
                        THEN jsonb_set(team, '{short_name}', '"PWI"'::jsonb)
                        ELSE team END
                   ORDER BY ord)
        FROM jsonb_array_elements(config->'teams') WITH ORDINALITY AS e(team, ord)
    ))
WHERE EXISTS (
    SELECT 1 FROM jsonb_array_elements(config->'teams') AS t
    WHERE t->>'name' = 'Pune Warriors' AND t->>'short_name' <> 'PWI'
);

COMMIT;
