"""
Read-only leaderboard queries over simulation.deliveries / simulation.player_awards.

All methods return (entries: list[dict], total: int) where total is the unsliced count
suitable for pagination, and entries are already ranked offset+1 … offset+limit.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Tuple

# ── Sort-column whitelists (prevent SQL injection via column-name interpolation) ──

_BATTING_SORT = {
    'most-runs':              ('runs',         'DESC'),
    'best-batting-average':   ('average',      'DESC'),
    'best-strike-rate':       ('strike_rate',  'DESC'),
    'most-sixes':             ('sixes',        'DESC'),
    'most-fours':             ('fours',        'DESC'),
}

_BOWLING_SORT = {
    'most-wickets':           ('wickets',      'DESC'),
    'best-bowling-average':   ('average',      'ASC'),
    'best-economy':           ('economy',      'ASC'),
    'most-dots':              ('dots',         'DESC'),
}

# ── Base CTEs ─────────────────────────────────────────────────────────────────

_INNING_BATTING_CTE = """
inning_batting AS (
    SELECT
        d.batter_id,
        d.match_id,
        d.inning_number,
        d.batting_team_id,
        SUM(d.runs_batter)                                                          AS inning_runs,
        COUNT(*) FILTER (WHERE outcome_kind IS DISTINCT FROM 'Wide')                AS balls,
        SUM(CASE WHEN d.runs_batter = 4 THEN 1 ELSE 0 END)                         AS fours,
        SUM(CASE WHEN d.runs_batter = 6 THEN 1 ELSE 0 END)                         AS sixes,
        BOOL_OR(d.outcome_type = 'Wicket')                                          AS is_out
    FROM simulation.deliveries d
    JOIN simulation.matches m ON m.match_id = d.match_id
    WHERE m.sim_id = %(sim_id)s
      AND d.batter_id IS NOT NULL
      AND m.is_super_over = FALSE
    GROUP BY d.batter_id, d.match_id, d.inning_number, d.batting_team_id
)
"""

_BATTING_AGG_CTE = """
batting_agg AS (
    SELECT
        ib.batter_id,
        COALESCE(hp.display_name, hp.name)                                          AS player,
        st.name                                                                     AS team,
        COUNT(DISTINCT ib.match_id)                                                 AS matches,
        COUNT(*)                                                                    AS innings,
        SUM(ib.inning_runs)                                                         AS runs,
        SUM(ib.fours)                                                               AS fours,
        SUM(ib.sixes)                                                               AS sixes,
        COUNT(*) FILTER (WHERE NOT ib.is_out)                                       AS not_outs,
        MAX(ib.inning_runs)                                                         AS highest_score,
        COUNT(*) FILTER (WHERE ib.inning_runs >= 50 AND ib.inning_runs < 100)      AS fifties,
        COUNT(*) FILTER (WHERE ib.inning_runs >= 100)                               AS hundreds,
        ROUND(
            SUM(ib.inning_runs)::numeric
            / NULLIF(COUNT(*) - COUNT(*) FILTER (WHERE NOT ib.is_out), 0), 2
        )                                                                           AS average,
        ROUND(
            SUM(ib.inning_runs)::numeric / NULLIF(SUM(ib.balls), 0) * 100, 2
        )                                                                           AS strike_rate
    FROM inning_batting ib
    JOIN history.players hp ON hp.player_id = ib.batter_id
    JOIN simulation.teams  st ON st.team_id  = ib.batting_team_id
    GROUP BY ib.batter_id, hp.display_name, hp.name, st.name
)
"""

_INNING_BOWLING_CTE = """
inning_bowling AS (
    SELECT
        d.bowler_id,
        d.match_id,
        d.inning_number,
        d.bowling_team_id,
        COUNT(*) FILTER (
            WHERE outcome_kind IS DISTINCT FROM 'Wide'
              AND outcome_kind IS DISTINCT FROM 'Noball'
        )                                                                           AS balls,
        SUM(d.runs_batter + d.runs_extras)                                          AS runs,
        SUM(CASE
            WHEN d.outcome_type = 'Wicket'
             AND (d.outcome_kind IS NULL OR d.outcome_kind != 'run out')
            THEN 1 ELSE 0 END)                                                      AS wickets,
        SUM(CASE WHEN d.outcome_type = 'Dot' THEN 1 ELSE 0 END)                    AS dots
    FROM simulation.deliveries d
    JOIN simulation.matches m ON m.match_id = d.match_id
    WHERE m.sim_id = %(sim_id)s
      AND d.bowler_id IS NOT NULL
      AND m.is_super_over = FALSE
    GROUP BY d.bowler_id, d.match_id, d.inning_number, d.bowling_team_id
),
best_bowling AS (
    SELECT DISTINCT ON (bowler_id)
        bowler_id,
        wickets AS bb_wickets,
        runs    AS bb_runs
    FROM inning_bowling
    ORDER BY bowler_id, wickets DESC, runs ASC
),
bowling_agg AS (
    SELECT
        ib.bowler_id,
        COALESCE(hp.display_name, hp.name)                                          AS player,
        st.name                                                                     AS team,
        COUNT(DISTINCT ib.match_id)                                                 AS matches,
        COUNT(*)                                                                    AS innings,
        SUM(ib.balls)                                                               AS total_balls,
        SUM(ib.runs)                                                                AS runs,
        SUM(ib.wickets)                                                             AS wickets,
        SUM(ib.dots)                                                                AS dots,
        ROUND(SUM(ib.runs)::numeric / NULLIF(SUM(ib.balls), 0) * 6, 2)            AS economy,
        ROUND(SUM(ib.runs)::numeric / NULLIF(SUM(ib.wickets), 0), 2)              AS average,
        ROUND(SUM(ib.balls)::numeric / NULLIF(SUM(ib.wickets), 0), 2)             AS strike_rate,
        bb.bb_wickets,
        bb.bb_runs,
        COUNT(*) FILTER (WHERE ib.wickets = 4)                                     AS four_wicket_hauls,
        COUNT(*) FILTER (WHERE ib.wickets >= 5)                                    AS five_wicket_hauls
    FROM inning_bowling ib
    JOIN history.players hp ON hp.player_id = ib.bowler_id
    JOIN simulation.teams  st ON st.team_id  = ib.bowling_team_id
    JOIN best_bowling bb ON bb.bowler_id = ib.bowler_id
    GROUP BY ib.bowler_id, hp.display_name, hp.name, st.name, bb.bb_wickets, bb.bb_runs
)
"""


class LeaderboardRepository:
    """
    Wraps a psycopg2 RealDictCursor. Intended to be constructed with
    SimulationRepository.dict_cursor.
    """

    def __init__(self, cur):
        self.cur = cur

    # ── Batting aggregates ────────────────────────────────────────────────────

    def batting_aggregate(
        self, sim_id: str, leaderboard: str, limit: int, offset: int
    ) -> Tuple[List[dict], int]:
        sort_col, sort_dir = _BATTING_SORT[leaderboard]
        # Rate stats (average, strike rate) are meaningless off a handful of
        # runs - a single big hit can otherwise top the board. Qualification
        # thresholds only apply to these two; counting stats (most runs/sixes/
        # fours) have no such distortion and are left unfiltered.
        qualify = "WHERE runs >= 50" if leaderboard in ('best-batting-average', 'best-strike-rate') else ""
        sql = f"""
        WITH {_INNING_BATTING_CTE}, {_BATTING_AGG_CTE}
        SELECT *, COUNT(*) OVER () AS total_count
        FROM batting_agg
        {qualify}
        ORDER BY {sort_col} {sort_dir} NULLS LAST
        LIMIT %(limit)s OFFSET %(offset)s
        """
        self.cur.execute(sql, {'sim_id': sim_id, 'limit': limit, 'offset': offset})
        rows = self.cur.fetchall()
        total = rows[0]['total_count'] if rows else 0
        return _rank_rows(rows, offset), total

    # ── Highest individual score ───────────────────────────────────────────────

    def highest_score(
        self, sim_id: str, limit: int, offset: int
    ) -> Tuple[List[dict], int]:
        sql = f"""
        WITH {_INNING_BATTING_CTE}
        SELECT
            COALESCE(hp.display_name, hp.name)                                      AS player,
            st.name                                                                 AS team,
            ib.inning_runs                                                          AS runs,
            ib.balls,
            ROUND(ib.inning_runs::numeric / NULLIF(ib.balls, 0) * 100, 2)         AS strike_rate,
            ib.fours,
            ib.sixes,
            NOT ib.is_out                                                           AS not_out,
            CASE WHEN m.home_team_id = ib.batting_team_id
                 THEN at.name ELSE ht.name END                                      AS opponent,
            v.name                                                                  AS venue,
            COUNT(*) OVER ()                                                        AS total_count
        FROM inning_batting ib
        JOIN history.players  hp ON hp.player_id = ib.batter_id
        JOIN simulation.teams  st ON st.team_id   = ib.batting_team_id
        JOIN simulation.matches m  ON m.match_id   = ib.match_id
        JOIN simulation.teams  ht ON ht.team_id    = m.home_team_id
        JOIN simulation.teams  at ON at.team_id    = m.away_team_id
        LEFT JOIN history.venues v ON v.venue_id   = m.venue_id
        ORDER BY ib.inning_runs DESC, ib.balls ASC
        LIMIT %(limit)s OFFSET %(offset)s
        """
        self.cur.execute(sql, {'sim_id': sim_id, 'limit': limit, 'offset': offset})
        rows = self.cur.fetchall()
        total = rows[0]['total_count'] if rows else 0
        return _rank_rows(rows, offset), total

    # ── Bowling aggregates ────────────────────────────────────────────────────

    def bowling_aggregate(
        self, sim_id: str, leaderboard: str, limit: int, offset: int
    ) -> Tuple[List[dict], int]:
        sort_col, sort_dir = _BOWLING_SORT[leaderboard]
        # Same reasoning as batting_aggregate's qualify: economy/average off a
        # handful of balls is noise, so only these two rate stats get a floor.
        qualify = "WHERE total_balls >= 30" if leaderboard in ('best-bowling-average', 'best-economy') else ""
        sql = f"""
        WITH {_INNING_BOWLING_CTE}
        SELECT
            player, team, matches, innings, total_balls, runs, wickets, dots,
            economy, average, strike_rate, bb_wickets, bb_runs,
            four_wicket_hauls, five_wicket_hauls,
            COUNT(*) OVER () AS total_count
        FROM bowling_agg
        {qualify}
        ORDER BY {sort_col} {sort_dir} NULLS LAST
        LIMIT %(limit)s OFFSET %(offset)s
        """
        self.cur.execute(sql, {'sim_id': sim_id, 'limit': limit, 'offset': offset})
        rows = self.cur.fetchall()
        total = rows[0]['total_count'] if rows else 0
        return _rank_rows(_format_bowling_rows(rows), offset), total

    # ── Best bowling figures ───────────────────────────────────────────────────

    def best_bowling_figures(
        self, sim_id: str, limit: int, offset: int
    ) -> Tuple[List[dict], int]:
        sql = """
        WITH inning_bowling AS (
            SELECT
                d.bowler_id,
                d.match_id,
                d.bowling_team_id,
                COUNT(*) FILTER (
                    WHERE outcome_kind IS DISTINCT FROM 'Wide'
                      AND outcome_kind IS DISTINCT FROM 'Noball'
                )                                                                   AS balls,
                SUM(d.runs_batter + d.runs_extras)                                  AS runs,
                SUM(CASE
                    WHEN d.outcome_type = 'Wicket'
                     AND (d.outcome_kind IS NULL OR d.outcome_kind != 'run out')
                    THEN 1 ELSE 0 END)                                              AS wickets
            FROM simulation.deliveries d
            JOIN simulation.matches m ON m.match_id = d.match_id
            WHERE m.sim_id = %(sim_id)s
              AND d.bowler_id IS NOT NULL
              AND m.is_super_over = FALSE
            GROUP BY d.bowler_id, d.match_id, d.inning_number, d.bowling_team_id
        )
        SELECT
            COALESCE(hp.display_name, hp.name)                                      AS player,
            st.name                                                                 AS team,
            ib.wickets,
            ib.runs,
            ROUND(ib.runs::numeric / NULLIF(ib.balls, 0) * 6, 2)                  AS economy,
            CASE WHEN m.home_team_id = ib.bowling_team_id
                 THEN at.name ELSE ht.name END                                      AS opponent,
            v.name                                                                  AS venue,
            COUNT(*) OVER ()                                                        AS total_count
        FROM inning_bowling ib
        JOIN history.players  hp ON hp.player_id = ib.bowler_id
        JOIN simulation.teams  st ON st.team_id   = ib.bowling_team_id
        JOIN simulation.matches m  ON m.match_id   = ib.match_id
        JOIN simulation.teams  ht ON ht.team_id    = m.home_team_id
        JOIN simulation.teams  at ON at.team_id    = m.away_team_id
        LEFT JOIN history.venues v ON v.venue_id   = m.venue_id
        ORDER BY ib.wickets DESC, ib.runs ASC
        LIMIT %(limit)s OFFSET %(offset)s
        """
        self.cur.execute(sql, {'sim_id': sim_id, 'limit': limit, 'offset': offset})
        rows = self.cur.fetchall()
        total = rows[0]['total_count'] if rows else 0
        entries = _rank_rows(rows, offset)
        for row in entries:
            row['best_figures'] = f"{row['wickets']}/{row['runs']}"
        return entries, total

    # ── MVP ───────────────────────────────────────────────────────────────────

    def mvp(
        self, sim_id: str, limit: int, offset: int
    ) -> Tuple[List[dict], int]:
        self.cur.execute(
            """
            SELECT
                COALESCE(hp.display_name, hp.name, pa.player_name) AS player,
                pa.team_name                                        AS team,
                pa.batting_pts,
                pa.bowling_pts,
                pa.fielding_pts,
                (pa.batting_pts + pa.bowling_pts + pa.fielding_pts) AS total,
                COUNT(*) OVER ()                                    AS total_count
            FROM simulation.player_awards pa
            LEFT JOIN history.players hp ON hp.player_id = pa.player_id
            WHERE pa.sim_id = %(sim_id)s
            ORDER BY (pa.batting_pts + pa.bowling_pts + pa.fielding_pts) DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {'sim_id': sim_id, 'limit': limit, 'offset': offset},
        )
        rows = self.cur.fetchall()
        total = rows[0]['total_count'] if rows else 0
        return _rank_rows(rows, offset), total


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rank_rows(rows: list, offset: int) -> list:
    result = []
    for i, row in enumerate(rows):
        d = {k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()}
        d['rank'] = offset + i + 1
        d.pop('total_count', None)
        result.append(d)
    return result


def _format_bowling_rows(rows: list) -> list:
    result = []
    for row in rows:
        d = dict(row)
        total_balls = d.pop('total_balls', 0) or 0
        d['overs'] = f"{total_balls // 6}.{total_balls % 6}"
        d['best_bowling'] = f"{d.pop('bb_wickets', 0)}/{d.pop('bb_runs', 0)}"
        result.append(d)
    return result
