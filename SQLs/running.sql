SELECT * from history.venues where name LIKE '%MCG%' or name like '%Melbourne%';
select p.NAME, STRING_AGG(distinct t.NAME,', ') from history.players p, history.match_players mp, history.matches m, history.teams t
WHERE lower(p.name) LIKE '%rana%'
AND p.player_id = mp.player_id
AND mp.match_id = m.match_id
AND mp.team_id = t.team_id
group by p.NAME;

select * from history.players WHERE lower(display_name) like '%nitish rana%';
select count(*) from history.players where player_role is null;
select * FROM history.players where display_name is null;
select * from history.players where country_id is null;
select * from history.players where batting_style is null and bowling_style is not null;
select * from history.players where bowling_style is null and batting_style is not null;


select m.name, m.date, pl.name, d.over_number, d.ball_number, m.match_format from history.players pl, history.deliveries d, history.matches m
WHERE pl.player_id = d.bowler_id
AND d.match_id = m.match_id
AND lower(pl.name) LIKE '%simmons%'
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
and lower(p.name) like '%simmons%'
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


select v.name, v.city, v.country, count(*)
from history.venues v, history.matches m
WHERE lower(v.name) like '%ekana%'
AND v.venue_id = m.venue_id
group by v.venue_id;

select * from history.venues where lower(name) like '%chepauk%';

select distinct match_type from history.matches;

select * from history.teams;
select * from history.match_players;
select DISTINCT country FROM history.venues;

select * from history.players;

select t.tournament_id, t.tournament_name, t.season, config from simulation.tournament_seeded ts, history.tournaments t
WHERE ts.tournament_id = t.tournament_id;

select * from simulation.simulations ORDER BY created_at desc;

select * from simulation.matches where sim_id='3ab0f604-b40a-4034-b264-1ad001346c02';
select * from simulation.teams where team_id=10377;
select * from simulation.match_players where match_id=1002717;
select * from simulation.deliveries where match_id=1002716;

select * from simulation.rooms;
select * from simulation.room_members;
delete from simulation.room_members;
delete from simulation.rooms;
commit;

select * from simulation.game_sessions where source_tournament_id=3039;
select * from simulation.teams where team_id in (10354,10364);
select * from simulation.tournament_seeded;

SELECT 
    column_name, 
    data_type, 
    character_maximum_length AS max_length,
    is_nullable, 
    column_default
FROM 
    information_schema.columns
WHERE 
    table_name = 'simulations'
ORDER BY 
    ordinal_position;

select * from history.players where display_name = 'Finn Allen' or display_name = 'Sunil Narine';
select DISTINCT player_role from history.players;
update history.players set player_role='Keeper' where display_name='Finn Allen';