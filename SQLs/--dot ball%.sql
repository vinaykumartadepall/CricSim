--dot ball%
SELECT
  p.name AS player_name,
  SUM(CASE WHEN d.runs_batter = 0 AND d.runs_extras = 0 THEN 1 ELSE 0 END) AS dot_balls,
  ROUND(
    100.0 * SUM(CASE WHEN d.runs_batter = 0 AND d.runs_extras = 0 THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN d.outcome_kind ILIKE 'Wide' THEN 0 ELSE 1 END), 0)
  , 2) AS dot_ball_percentage
FROM history.deliveries d
JOIN history.matches m ON d.match_id = m.match_id
JOIN history.tournaments t ON m.tournament_id = t.tournament_id
JOIN history.players p ON d.batter_id = p.player_id
WHERE t.tournament_name ILIKE '%Indian Premier League%'
GROUP BY p.name
HAVING SUM(CASE WHEN d.outcome_kind ILIKE 'Wide' THEN 0 ELSE 1 END) >= 100
ORDER BY dot_balls desc LIMIT 100;

select pl.name,
       count(*) balls_faced,
       sum(del.runs_batter) runs,
       100*((1.0*sum(del.runs_batter))/count(*)) strike_rate
FROM history.deliveries del,
     history.matches mat,
     history.players pl,
     history.tournaments tour
where del.match_id = mat.match_id
  and mat.tournament_id = tour.tournament_id
  and pl.player_id = del.batter_id
  and tour.tournament_name = 'Indian Premier League'
  and (del.outcome_type != 'Extras' or outcome_kind!='Wide')
--   and del.over_number>=15 and del.over_number<=19
GROUP by pl.name
HAVING count(*)>400
order by strike_rate desc;

GROUP BY del.over_number, pl.name;

select DISTINCT outcome_kind from history.deliveries;
select DISTINCT outcome_type from history.deliveries;

SELECT distinct match_format from history.matches;

select * from history.matches where match_format = 'ODM';