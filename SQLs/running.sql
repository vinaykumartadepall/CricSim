SELECT * from history.venues where name LIKE '%MCG%' or name like '%Melbourne%';
select * from history.players WHERE name LIKE '%Symonds%';

select m.name, m.date, pl.name, d.over_number, d.ball_number, m.match_format from history.players pl, history.deliveries d, history.matches m
WHERE pl.player_id = d.bowler_id
AND d.match_id = m.match_id
AND pl.name LIKE '%Green%'
AND m.match_format = 'Test'
order by m.date desc;

select count(v.city) from history.venues v;
select count(v.country) from history.venues v;
select * from history.venues v where lower(v.name) like '%chinnaswamy%';
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