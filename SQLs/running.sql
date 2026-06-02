SELECT * from history.venues where name LIKE '%MCG%' or name like '%Melbourne%';
select p.NAME, group_concat(t.NAME seperator ', ') from history.players p, history.match_players mp, history.matches m, history.teams t
WHERE p.name LIKE '%Patel%'
AND p.player_id = mp.player_id
AND mp.match_id = m.match_id
AND mp.team_id = t.team_id
group by p.NAME;

select m.name, m.date, pl.name, d.over_number, d.ball_number, m.match_format from history.players pl, history.deliveries d, history.matches m
WHERE pl.player_id = d.bowler_id
AND d.match_id = m.match_id
AND pl.name LIKE '%Green%'
AND m.match_format = 'Test'
order by m.date desc;

select count(v.city) from history.venues v;
select count(v.country) from history.venues v;
select * from history.venues v where lower(v.name) like '%london%';
select count(*), v.name, v.city
from history.venues v, history.matches m
where v.venue_id = m.venue_id
and (v.city = 'Bangalore' or v.city = 'Bengaluru') 
GROUP BY v.name, v.city;

select m.name, m.date, v.name, v.city
from history.matches m, history.venues v
where m.venue_id = v.venue_id
and (v.city = 'Bangalore' or v.city = 'Bengaluru')
order by m.date desc;
update history.venues set country = 'Pakistan' where city = 'Mirpur';
select * from history.matches m where m.venue_id = '5605';
commit;

select * from history.matches m where m.name like '%Ranji%' order by m.date desc;

--write a query to find list of all matches (not deliveries) played by A Zampa, also show the date, opponent team bowled by A Zampa in those matches. Order the results by date in descending order.
select m.match_id, m.name, m.date, m.match_format, m.original_match_id, m.match_type, p.name
from history.matches m, history.match_players mp, history.players p
where m.match_id = mp.match_id
and mp.player_id = p.player_id
and p.name like '%AJ Finch%'
order by m.date desc;

select distinct d.over_number
from history.deliveries d, history.matches m
where m.match_format = 'T20'
and m.match_id = d.match_id;



  BEGIN;

  -- 1. Add a new integer column alongside the existing varchar one
  ALTER TABLE history.deliveries
    ADD COLUMN outcome_player_id_new INTEGER;

  -- 2. Populate it by resolving stored names to integer player IDs.
  --    Rows where the name doesn't match any player (e.g. sub fielders not
  --    in the squad registry) are left NULL — same semantics as before.
  UPDATE history.deliveries d
  SET outcome_player_id_new = p.player_id
  FROM history.players p
  WHERE d.outcome_player_id = p.name;

  -- 3. Optional: inspect how many rows resolved vs stayed NULL before committing.
  --    Run this SELECT, then decide whether to COMMIT or ROLLBACK.
  --
  SELECT
    COUNT(*)                                                    AS total_with_outcome_player,
    COUNT(*) FILTER (WHERE outcome_player_id_new IS NOT NULL)  AS resolved,
    COUNT(*) FILTER (WHERE outcome_player_id_new IS NULL)      AS unresolved
  FROM history.deliveries
  WHERE outcome_player_id IS NOT NULL;

  SELECT DISTINCT d.outcome_player_id
  FROM history.deliveries d
  WHERE d.outcome_player_id IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM history.players p WHERE p.name = d.outcome_player_id
    )
  LIMIT 20;

  SELECT player_id, name
  FROM history.players
  WHERE name ILIKE '%ashok%sharma%'
     OR name ILIKE '%sharma%ashok%';

  -- 4. Drop the old varchar column and promote the new integer one
  ALTER TABLE history.deliveries DROP COLUMN outcome_player_id;
  ALTER TABLE history.deliveries RENAME COLUMN outcome_player_id_new TO outcome_player_id;
  
  -- 5. Add FK constraint and a partial index (outcome_player_id is sparse —
  --    only wicket deliveries with a fielder have it set)
  ALTER TABLE history.deliveries
    ADD CONSTRAINT fk_delivery_outcome_player
    FOREIGN KEY (outcome_player_id) REFERENCES history.players(player_id);

  CREATE INDEX idx_deliveries_outcome_player_id
    ON history.deliveries (outcome_player_id)
    WHERE outcome_player_id IS NOT NULL;

  COMMIT;
