from typing import List, Dict, Any, Tuple, Optional
from collections import defaultdict

# Maps unified format names to all raw DB format strings that belong to that bucket.
_FORMAT_ALIASES: Dict[str, List[str]] = {
    "Test": ["Test", "MDM"],
    "ODI":  ["ODI",  "ODM", "ONE DAY"],
    "T20":  ["T20",  "IT20"],
}

try:
    from db.database import get_db_connection
    HAS_DB = True
except ImportError:
    HAS_DB = False

class StatsRepository:
    def __init__(self):
        self.conn = None
        if HAS_DB:
            try:
                self.conn = get_db_connection(autocommit=True)
            except Exception as e:
                print(f"Warning: Could not connect to DB for stats: {e}")
            
    def get_player_by_name(self, name: str) -> Optional[Tuple[int, str]]:
        if not self.conn: return None
        # Use exact identity matching since driver scripts have been mapped to proper nomenclature!
        query = "SELECT player_id, name FROM history.players WHERE name = %s LIMIT 1"
        rows = self._run_query(query, (name,))
        
        if not rows:
            print(f"[DB] Lookup failed: No history found for exact player name '{name}'")
            return None
        return (rows[0][0], rows[0][1])

    def get_venue_by_name(self, name: str) -> Optional[Tuple[int, str, Optional[str]]]:
        """Returns (venue_id, name, country) or None."""
        if not self.conn: return None
        search_str = '%' + '%'.join(name.split()) + '%'
        query = "SELECT venue_id, name, country FROM history.venues WHERE name ILIKE %s LIMIT 1"
        rows = self._run_query(query, (search_str,))
        if not rows:
            print(f"[DB] Lookup failed: Venue '{name}' not found.")
            return None
        return (rows[0][0], rows[0][1], rows[0][2])
        
    def _run_query(self, query: str, params: tuple = ()) -> List[tuple]:
        if not self.conn:
            return []
        try:
            cur = self.conn.cursor()
            cur.execute(query, params)
            res = cur.fetchall()
            cur.close()
            return res
        except Exception as e:
            print(f"DB Query failed: {e}")
            return []
            
    def _parse_rows_to_probs(self, rows) -> Dict[Tuple[int, int, str, Optional[str]], float]:
        # Rows format expected: (runs_batter, runs_extras, outcome_type, outcome_kind, count)
        baseline = defaultdict(int)
        total = 0
        for r_bat, r_ext, out_type, out_kind, count in rows:
            total += count
            baseline[(r_bat, r_ext, out_type, out_kind)] += count
                
        if total > 0:
            return {k: v / total for k, v in baseline.items()}
        return None

    def get_batters_distribution(self, batter_ids: List[int], match_format: str, gender: str = 'male') -> Dict[int, Dict[Tuple, float]]:
        if not batter_ids or not self.conn: return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT d.batter_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.batter_id = ANY(%s) AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.batter_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (batter_ids, raw_fmts, gender))
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[0]].append((row[1], row[2], row[3], row[4], row[5]))
        res = {}
        for item_id, metrics in grouped.items():
            probs = self._parse_rows_to_probs(metrics)
            if probs: res[item_id] = probs
        return res

    def get_bowlers_distribution(self, bowler_ids: List[int], match_format: str, gender: str = 'male') -> Dict[int, Dict[Tuple, float]]:
        if not bowler_ids or not self.conn: return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT d.bowler_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.bowler_id = ANY(%s) AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.bowler_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (bowler_ids, raw_fmts, gender))
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[0]].append((row[1], row[2], row[3], row[4], row[5]))
        res = {}
        for item_id, metrics in grouped.items():
            probs = self._parse_rows_to_probs(metrics)
            if probs: res[item_id] = probs
        return res

    def get_venue_distribution(self, venue_id: int, match_format: str, gender: str = 'male') -> Dict[Tuple, float]:
        if not self.conn: return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.venue_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (venue_id, raw_fmts, gender))
        return self._parse_rows_to_probs(rows) or {}

    def get_country_distribution(self, country: str, match_format: str, gender: str = 'male') -> Dict[Tuple, float]:
        """Outcome distribution across all venues in a country. Used as fallback when venue data is sparse."""
        if not self.conn: return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        JOIN history.venues  v ON m.venue_id = v.venue_id
        WHERE v.country = %s AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (country, raw_fmts, gender))
        return self._parse_rows_to_probs(rows) or {}

    def get_innings_distribution(self, match_format: str, gender: str = 'male') -> Dict[int, Dict[Tuple, float]]:
        if not self.conn: return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT d.inning_number, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.inning_number, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (raw_fmts, gender))
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[0]].append((row[1], row[2], row[3], row[4], row[5]))
        res = {}
        for item_id, metrics in grouped.items():
            probs = self._parse_rows_to_probs(metrics)
            if probs: res[item_id] = probs
        return res

    def get_overs_distribution(self, match_format: str, gender: str = 'male') -> Dict[int, Dict[Tuple, float]]:
        if not self.conn: return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT d.over_number, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.over_number, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (raw_fmts, gender))
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[0]].append((row[1], row[2], row[3], row[4], row[5]))
        res = {}
        for item_id, metrics in grouped.items():
            probs = self._parse_rows_to_probs(metrics)
            if probs: res[item_id] = probs
        return res
        
    def get_tournament_distribution(self, tournament_id: int) -> Dict[Tuple, float]:
        if not self.conn: return {}
        query = """
        SELECT d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*) 
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.tournament_id = %s
        GROUP BY d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (tournament_id,))
        return self._parse_rows_to_probs(rows) or {}

    def _raw_formats(self, unified_format: str) -> List[str]:
        """Returns all raw DB format strings that map to unified_format."""
        return _FORMAT_ALIASES.get(unified_format, [unified_format])

    def get_bowler_workload_stats(
        self, bowler_ids: List[int], unified_format: str, gender: str = 'male',
        match_type: Optional[str] = None,
    ) -> Dict[int, Dict[str, float]]:
        """
        Per-bowler workload profile derived from historical data.

        Returns {player_id: {'avg_overs_per_innings': float, 'p75_spell': float, 'innings_count': int}}
        Only bowlers with at least 3 bowling innings are included.

        Spell detection uses over_number/2 - ROW_NUMBER() so that alternating-end
        overs (1,3,5,… or 2,4,6,…) are correctly grouped into one spell.
        Includes all raw format aliases (e.g. MDM counts as Test).
        match_type: when provided (e.g. 'international'), restricts to that match_type only.
        """
        if not bowler_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(unified_format)
        match_type_filter = "AND m.match_type = %s" if match_type else ""
        query = f"""
        WITH distinct_overs AS (
            SELECT DISTINCT del.bowler_id, del.match_id, del.inning_number, del.over_number
            FROM history.deliveries del
            JOIN history.matches m ON del.match_id = m.match_id
            WHERE del.bowler_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {match_type_filter}
        ),
        ranked AS (
            SELECT bowler_id, match_id, inning_number, over_number,
                   (over_number / 2) - ROW_NUMBER() OVER (
                       PARTITION BY bowler_id, match_id, inning_number
                       ORDER BY over_number
                   ) AS spell_group
            FROM distinct_overs
        ),
        spells AS (
            SELECT bowler_id, match_id, inning_number, spell_group,
                   COUNT(*) AS spell_overs
            FROM ranked
            GROUP BY bowler_id, match_id, inning_number, spell_group
        ),
        innings_totals AS (
            SELECT bowler_id, match_id, inning_number, SUM(spell_overs) AS total_overs
            FROM spells
            GROUP BY bowler_id, match_id, inning_number
        ),
        per_bowler_overs AS (
            SELECT bowler_id,
                   AVG(total_overs)    AS avg_overs,
                   PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY total_overs) AS p75_overs,
                   COUNT(*)            AS innings_count,
                   SUM(total_overs)    AS career_overs
            FROM innings_totals
            GROUP BY bowler_id
        ),
        per_bowler_spells AS (
            SELECT bowler_id,
                   PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY spell_overs) AS p75_spell
            FROM spells
            GROUP BY bowler_id
        ),
        -- Total match appearances: denominator for avg_overs_per_match.
        -- Dividing career overs by appearances (not bowling occasions) correctly
        -- deflates part-timers who bowl rarely (e.g. Kohli 2ov in 3 of 100 T20Is → 0.06).
        total_appearances AS (
            SELECT mp.player_id AS bowler_id, COUNT(DISTINCT mp.match_id) AS total_matches
            FROM history.match_players mp
            JOIN history.matches m ON mp.match_id = m.match_id
            WHERE mp.player_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {match_type_filter}
            GROUP BY mp.player_id
        )
        SELECT pbo.bowler_id,
               pbo.avg_overs,
               pbo.p75_overs,
               pbs.p75_spell,
               pbo.innings_count,
               pbo.career_overs::float / NULLIF(ta.total_matches, 0) AS avg_overs_per_match
        FROM per_bowler_overs pbo
        JOIN per_bowler_spells pbs   USING (bowler_id)
        LEFT JOIN total_appearances ta ON ta.bowler_id = pbo.bowler_id
        WHERE pbo.innings_count >= 3
        """
        params: list = [bowler_ids, raw_fmts, gender]
        if match_type:
            params.append(match_type)
        # total_appearances block repeats the same three positional params
        params += [bowler_ids, raw_fmts, gender]
        if match_type:
            params.append(match_type)
        rows = self._run_query(query, params)
        return {
            r[0]: {
                'avg_overs_per_innings': float(r[1] or 5.0),   # per bowling occasion (hard cap, spell mgmt)
                'p75_overs_per_innings': float(r[2] or 6.0),
                'p75_spell':             float(r[3] or 4.0),
                'innings_count':         int(r[4]),
                'avg_overs_per_match':   float(r[5] or 0.0),   # per appearance (eligibility, F5)
            }
            for r in rows
        }

    def get_wicket_keepers(self, player_ids: List[int], gender: str = 'male') -> set:
        """Returns player_ids who have taken stumping dismissals — i.e., are wicket-keepers."""
        if not player_ids or not self.conn:
            return set()
        # outcome_player_id stores player names (varchar), not integer IDs.
        # Resolve IDs → names, filter by name, then return integer IDs.
        query = """
        SELECT p.player_id
        FROM history.players p
        JOIN history.deliveries d ON d.outcome_player_id = p.name
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE p.player_id = ANY(%s)
          AND m.gender = %s
          AND d.outcome_type = 'Wicket'
          AND d.outcome_kind = 'stumped'
        GROUP BY p.player_id
        HAVING COUNT(*) >= 3
        """
        rows = self._run_query(query, (player_ids, gender))
        return {r[0] for r in rows}

    def get_spinner_ids(self, bowler_ids: List[int], gender: str = 'male') -> set:
        """
        Returns the set of player_ids who are spinners, inferred from having
        at least one stumped dismissal in any format (stumped wickets only occur off spin bowling).
        """
        if not bowler_ids or not self.conn:
            return set()
        query = """
        SELECT DISTINCT d.bowler_id
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.bowler_id = ANY(%s)
          AND m.gender = %s
          AND d.outcome_type = 'Wicket'
          AND d.outcome_kind = 'stumped'
        """
        rows = self._run_query(query, (bowler_ids, gender))
        return {r[0] for r in rows}

    def get_batter_death_stats(
        self, batter_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[str, float]]:
        """
        Returns {player_id: {'death_sr': float, 'boundary_rate': float, 'balls': int}}
        for deliveries bowled in death overs (T20 ov ≥ 17, ODI ov ≥ 41; 1-indexed).
        Only players with at least 6 death-over balls are included.
        """
        if not batter_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT
            d.batter_id,
            SUM(d.runs_batter) * 100.0 /
                NULLIF(SUM(CASE WHEN d.outcome_type != 'Extras' THEN 1 ELSE 0 END), 0)
                AS death_sr,
            SUM(CASE WHEN d.runs_batter >= 4 THEN 1 ELSE 0 END)::float /
                NULLIF(COUNT(*), 0) AS boundary_rate,
            COUNT(*) AS balls
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.batter_id = ANY(%s)
          AND m.match_format = ANY(%s)
          AND m.gender = %s
          AND (
                (m.match_format = ANY(ARRAY['T20','IT20'])          AND d.over_number >= 17)
             OR (m.match_format = ANY(ARRAY['ODI','ODM','ONE DAY']) AND d.over_number >= 41)
          )
        GROUP BY d.batter_id
        HAVING COUNT(*) >= 6
        """
        rows = self._run_query(query, (batter_ids, raw_fmts, gender))
        return {
            r[0]: {
                'death_sr':      float(r[1] or 0),
                'boundary_rate': float(r[2] or 0),
                'balls':         int(r[3]),
            }
            for r in rows
        }

    def get_bowler_career_stats(
        self, bowler_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[str, float]]:
        """Returns {player_id: {'economy': float, 'wicket_rate': float, 'balls': int}}"""
        if not bowler_ids or not self.conn:
            return {}
        query = """
        SELECT
            d.bowler_id,
            SUM(d.runs_batter + d.runs_extras) * 6.0 / NULLIF(COUNT(*), 0) AS economy,
            SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS wicket_rate,
            COUNT(*) AS balls
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.bowler_id = ANY(%s) AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.bowler_id
        HAVING COUNT(*) >= 6
        """
        rows = self._run_query(query, (bowler_ids, self._raw_formats(match_format), gender))
        return {
            r[0]: {'economy': float(r[1] or 0), 'wicket_rate': float(r[2] or 0), 'balls': int(r[3])}
            for r in rows
        }

    def get_bowler_phase_stats(
        self, bowler_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[str, Dict[str, float]]]:
        """Returns {player_id: {phase: {'economy': float, 'wicket_rate': float, 'balls': int}}}
        Phases: 'powerplay', 'middle', 'death' (Test returns only 'middle').
        """
        if not bowler_ids or not self.conn:
            return {}
        query = """
        SELECT
            d.bowler_id,
            CASE
                WHEN m.match_format = 'T20' AND d.over_number <= 6  THEN 'powerplay'
                WHEN m.match_format = 'T20' AND d.over_number >= 17 THEN 'death'
                WHEN m.match_format = 'ODI' AND d.over_number <= 10 THEN 'powerplay'
                WHEN m.match_format = 'ODI' AND d.over_number >= 41 THEN 'death'
                ELSE 'middle'
            END AS phase,
            SUM(d.runs_batter + d.runs_extras) * 6.0 / NULLIF(COUNT(*), 0) AS economy,
            SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS wicket_rate,
            COUNT(*) AS balls
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.bowler_id = ANY(%s) AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.bowler_id, phase
        """
        rows = self._run_query(query, (bowler_ids, self._raw_formats(match_format), gender))
        result: Dict[int, Dict[str, Dict[str, float]]] = defaultdict(dict)
        for bowler_id, phase, economy, wicket_rate, balls in rows:
            result[bowler_id][phase] = {
                'economy': float(economy or 0),
                'wicket_rate': float(wicket_rate or 0),
                'balls': int(balls),
            }
        return dict(result)

    def get_batter_bowler_matchups(
        self,
        batter_ids: List[int],
        bowler_ids: List[int],
        match_format: str,
        gender: str = 'male',
    ) -> Dict[Tuple[int, int], Dict[str, float]]:
        """Returns {(batter_id, bowler_id): {'economy': float, 'wicket_rate': float, 'balls': int}}
        Only pairs with at least 6 historical balls are included.
        """
        if not batter_ids or not bowler_ids or not self.conn:
            return {}
        query = """
        SELECT
            d.batter_id, d.bowler_id,
            SUM(d.runs_batter + d.runs_extras) * 6.0 / NULLIF(COUNT(*), 0) AS economy,
            SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS wicket_rate,
            COUNT(*) AS balls
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.batter_id = ANY(%s) AND d.bowler_id = ANY(%s)
          AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.batter_id, d.bowler_id
        HAVING COUNT(*) >= 6
        """
        rows = self._run_query(query, (batter_ids, bowler_ids, self._raw_formats(match_format), gender))
        return {
            (r[0], r[1]): {'economy': float(r[2] or 0), 'wicket_rate': float(r[3] or 0), 'balls': int(r[4])}
            for r in rows
        }

    def get_bowler_phase_frequency(
        self, bowler_ids: List[int], match_format: str, gender: str = 'male',
        country: Optional[str] = None,
    ) -> Dict[int, Dict[str, float]]:
        """
        For each bowler, returns the fraction of matches where they bowled in each phase.
        Denominator is total matches played (from match_players), not just matches bowled.
        When `country` is provided, only matches at venues in that country are counted.

        T20 phases  — 'powerplay_early' (ov 1-4), 'powerplay_late' (ov 5-6),
                       'middle' (ov 7-15), 'death_early' (ov 16-17), 'death_late' (ov 18-20)
        ODI phases  — 'powerplay' (ov 1-10), 'middle' (ov 11-39),
                       'death_early' (ov 40-43), 'death_late' (ov 44+)
        All formats — 'opening' (ov 1-2)

        Phase keys that don't apply to a format will be 0 (e.g. 'powerplay_early' is 0 for ODI).
        """
        if not bowler_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        t20_fmts = self._raw_formats("T20")
        odi_fmts = self._raw_formats("ODI")

        country_join   = "JOIN history.venues v ON m.venue_id = v.venue_id" if country else ""
        country_filter = "AND v.country = %s"                                if country else ""

        query = f"""
        WITH total_matches AS (
            SELECT mp.player_id, COUNT(DISTINCT mp.match_id) AS n
            FROM history.match_players mp
            JOIN history.matches m ON mp.match_id = m.match_id
            {country_join}
            WHERE mp.player_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {country_filter}
            GROUP BY mp.player_id
        ),
        phase_counts AS (
            SELECT
                d.bowler_id,
                -- opening overs (any format)
                COUNT(DISTINCT CASE WHEN d.over_number <= 2
                    THEN d.match_id END)                                              AS opening_matches,
                -- T20 sub-phases (over_number is 1-indexed)
                COUNT(DISTINCT CASE WHEN m.match_format = ANY(%s) AND d.over_number <= 4
                    THEN d.match_id END)                                              AS t20_pp1_matches,
                COUNT(DISTINCT CASE WHEN m.match_format = ANY(%s) AND d.over_number BETWEEN 5  AND 6
                    THEN d.match_id END)                                              AS t20_pp2_matches,
                COUNT(DISTINCT CASE WHEN m.match_format = ANY(%s) AND d.over_number BETWEEN 7  AND 15
                    THEN d.match_id END)                                              AS t20_mid_matches,
                COUNT(DISTINCT CASE WHEN m.match_format = ANY(%s) AND d.over_number BETWEEN 16 AND 17
                    THEN d.match_id END)                                              AS t20_d1_matches,
                COUNT(DISTINCT CASE WHEN m.match_format = ANY(%s) AND d.over_number >= 18
                    THEN d.match_id END)                                              AS t20_d2_matches,
                -- ODI sub-phases
                COUNT(DISTINCT CASE WHEN m.match_format = ANY(%s) AND d.over_number <= 10
                    THEN d.match_id END)                                              AS odi_pp_matches,
                COUNT(DISTINCT CASE WHEN m.match_format = ANY(%s) AND d.over_number BETWEEN 11 AND 39
                    THEN d.match_id END)                                              AS odi_mid_matches,
                COUNT(DISTINCT CASE WHEN m.match_format = ANY(%s) AND d.over_number BETWEEN 40 AND 43
                    THEN d.match_id END)                                              AS odi_d1_matches,
                COUNT(DISTINCT CASE WHEN m.match_format = ANY(%s) AND d.over_number >= 44
                    THEN d.match_id END)                                              AS odi_d2_matches
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            {country_join}
            WHERE d.bowler_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {country_filter}
            GROUP BY d.bowler_id
        )
        SELECT
            p.bowler_id,
            p.opening_matches::float  / NULLIF(t.n, 0)                           AS opening_frac,
            p.t20_pp1_matches::float  / NULLIF(t.n, 0)                           AS t20_pp1_frac,
            p.t20_pp2_matches::float  / NULLIF(t.n, 0)                           AS t20_pp2_frac,
            p.t20_mid_matches::float  / NULLIF(t.n, 0)                           AS t20_mid_frac,
            p.t20_d1_matches::float   / NULLIF(t.n, 0)                           AS t20_d1_frac,
            p.t20_d2_matches::float   / NULLIF(t.n, 0)                           AS t20_d2_frac,
            p.odi_pp_matches::float   / NULLIF(t.n, 0)                           AS odi_pp_frac,
            p.odi_mid_matches::float  / NULLIF(t.n, 0)                           AS odi_mid_frac,
            -- death_early / death_late: combine T20 and ODI columns so the key is
            -- format-neutral; only one side is non-zero for any given format query.
            (p.t20_d1_matches + p.odi_d1_matches)::float / NULLIF(t.n, 0)        AS death_early_frac,
            (p.t20_d2_matches + p.odi_d2_matches)::float / NULLIF(t.n, 0)        AS death_late_frac,
            t.n AS total_matches
        FROM phase_counts p
        JOIN total_matches t ON p.bowler_id = t.player_id
        WHERE t.n >= 5
        """
        params = [bowler_ids, raw_fmts, gender]
        if country:
            params.append(country)
        # 5 T20 CASE branches, then 4 ODI CASE branches in phase_counts
        params += [t20_fmts] * 5 + [odi_fmts] * 4
        params += [bowler_ids, raw_fmts, gender]
        if country:
            params.append(country)
        rows = self._run_query(query, tuple(params))

        result = {}
        for (bowler_id, opening_frac, t20_pp1, t20_pp2, t20_mid,
             t20_d1, t20_d2, odi_pp, odi_mid, death_early, death_late,
             total_matches) in rows:
            result[bowler_id] = {
                'opening':         float(opening_frac or 0),
                'powerplay_early': float(t20_pp1      or 0),
                'powerplay_late':  float(t20_pp2      or 0),
                'middle':          float((t20_mid or 0) + (odi_mid or 0)),
                'powerplay':       float(odi_pp        or 0),
                'death_early':     float(death_early   or 0),
                'death_late':      float(death_late    or 0),
                'total_matches':   int(total_matches),
            }
        return result

    def get_bowler_over_frequency(
        self, bowler_ids: List[int], match_format: str, gender: str = 'male',
        country: Optional[str] = None, match_type: Optional[str] = None,
        inning_number: Optional[int] = None,
    ) -> Dict[int, Dict[int, float]]:
        """
        Per-bowler fraction of matches where they bowled in each over (T20) or
        5-over bin (ODI).

        T20:  key = over_number  (0-indexed, 0–19, one bin per over)
        ODI:  key = over_number // 5  (0-indexed, 0–9, one bin per 5 overs)

        match_type: when provided (e.g. 'international'), restricts to that match_type only.
        inning_number: when provided (1 or 2), restricts to that innings only; denominator
                       becomes matches where the bowler had deliveries in that inning.
        Returns {player_id: {key: fraction}} — sparse (only keys with data present).
        """
        if not bowler_ids or not self.conn:
            return {}
        unified = match_format
        if unified not in ('T20', 'ODI'):
            return {}

        raw_fmts = self._raw_formats(unified)

        country_join      = "JOIN history.venues v ON m.venue_id = v.venue_id" if country else ""
        country_filter    = "AND v.country = %s"                                if country else ""
        match_type_filter = "AND m.match_type = %s"                             if match_type else ""
        inning_filter     = "AND d.inning_number = %s"                          if inning_number is not None else ""

        if unified == 'T20':
            key_expr    = "d.over_number"
            over_filter = "AND d.over_number BETWEEN 0 AND 19"
        else:
            key_expr    = "d.over_number / 5"
            over_filter = "AND d.over_number BETWEEN 0 AND 49"

        if inning_number is not None:
            # Denominator: total matches played (same as non-inning path),
            # so frequency = "bowled in this over/inning in X% of all appearances".
            total_matches_sql = f"""
            SELECT mp.player_id, COUNT(DISTINCT mp.match_id) AS n
            FROM history.match_players mp
            JOIN history.matches m ON mp.match_id = m.match_id
            {country_join}
            WHERE mp.player_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {country_filter}
              {match_type_filter}
            GROUP BY mp.player_id"""
            total_params = [bowler_ids, raw_fmts, gender]
            if country:    total_params.append(country)
            if match_type: total_params.append(match_type)
        else:
            total_matches_sql = f"""
            SELECT mp.player_id, COUNT(DISTINCT mp.match_id) AS n
            FROM history.match_players mp
            JOIN history.matches m ON mp.match_id = m.match_id
            {country_join}
            WHERE mp.player_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {country_filter}
              {match_type_filter}
            GROUP BY mp.player_id"""
            total_params = [bowler_ids, raw_fmts, gender]
            if country:    total_params.append(country)
            if match_type: total_params.append(match_type)

        key_params = [bowler_ids, raw_fmts, gender]
        if country:                    key_params.append(country)
        if match_type:                 key_params.append(match_type)
        if inning_number is not None:  key_params.append(inning_number)

        query = f"""
        WITH total_matches AS ({total_matches_sql}
        ),
        key_counts AS (
            SELECT d.bowler_id, {key_expr} AS over_key,
                   COUNT(DISTINCT d.match_id) AS cnt
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            {country_join}
            WHERE d.bowler_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {country_filter}
              {match_type_filter}
              {inning_filter}
              {over_filter}
            GROUP BY d.bowler_id, {key_expr}
        )
        SELECT kc.bowler_id, kc.over_key, kc.cnt::float / NULLIF(t.n, 0) AS frac
        FROM key_counts kc
        JOIN total_matches t ON kc.bowler_id = t.player_id
        WHERE t.n >= 5
        """
        rows = self._run_query(query, tuple(total_params + key_params))
        result: Dict[int, Dict[int, float]] = {}
        for bowler_id, over_key, frac in rows:
            result.setdefault(int(bowler_id), {})[int(over_key)] = float(frac or 0)
        return result

    def get_bowler_phase_overs_distribution(
        self, bowler_ids: List[int], match_format: str, gender: str = 'male',
        match_type: Optional[str] = None, inning_number: Optional[int] = None,
    ) -> Dict[int, Dict[str, float]]:
        """
        Average overs bowled per phase per inning appearance, for T20 or ODI.
        Returns {player_id: {'pp': float, 'mid': float, 'death': float}}
        T20 phases: pp=ov0-5, mid=ov6-14, death=ov15+  (0-indexed)
        ODI phases: pp=ov0-9, mid=ov10-38, death=ov39+  (0-indexed)
        match_type:    when provided, restricts to that match_type only.
        inning_number: when provided (1 or 2), restricts to that innings only; denominator
                       becomes innings-specific appearances rather than total matches played.
        """
        if not bowler_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        unified  = match_format

        if unified == 'T20':
            pp_end, mid_start, mid_end, death_start = 5, 6, 14, 15
        else:  # ODI
            pp_end, mid_start, mid_end, death_start = 9, 10, 38, 39

        match_type_filter = "AND m.match_type = %s"    if match_type else ""
        inning_filter     = "AND d.inning_number = %s" if inning_number is not None else ""

        if inning_number is not None:
            # Denominator: matches where bowler delivered in this specific inning
            total_matches_sql = f"""
            SELECT d.bowler_id AS player_id, COUNT(DISTINCT d.match_id) AS n
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE d.bowler_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {match_type_filter}
              {inning_filter}
            GROUP BY d.bowler_id"""
            total_params = [bowler_ids, raw_fmts, gender]
            if match_type: total_params.append(match_type)
            total_params.append(inning_number)
        else:
            total_matches_sql = f"""
            SELECT mp.player_id, COUNT(DISTINCT mp.match_id) AS n
            FROM history.match_players mp
            JOIN history.matches m ON mp.match_id = m.match_id
            WHERE mp.player_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {match_type_filter}
            GROUP BY mp.player_id"""
            total_params = [bowler_ids, raw_fmts, gender]
            if match_type: total_params.append(match_type)

        phase_params = [pp_end, mid_start, mid_end, death_start, bowler_ids, raw_fmts, gender]
        if match_type:                phase_params.append(match_type)
        if inning_number is not None: phase_params.append(inning_number)

        query = f"""
        WITH total_matches AS ({total_matches_sql}
        ),
        phase_overs AS (
            SELECT
                d.bowler_id, d.match_id,
                COUNT(DISTINCT CASE WHEN d.over_number <= %s              THEN d.over_number END) AS pp_overs,
                COUNT(DISTINCT CASE WHEN d.over_number BETWEEN %s AND %s  THEN d.over_number END) AS mid_overs,
                COUNT(DISTINCT CASE WHEN d.over_number >= %s              THEN d.over_number END) AS death_overs
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE d.bowler_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {match_type_filter}
              {inning_filter}
            GROUP BY d.bowler_id, d.match_id
        )
        SELECT
            o.bowler_id,
            SUM(o.pp_overs)::float    / NULLIF(t.n, 0) AS avg_pp,
            SUM(o.mid_overs)::float   / NULLIF(t.n, 0) AS avg_mid,
            SUM(o.death_overs)::float / NULLIF(t.n, 0) AS avg_death
        FROM phase_overs o
        JOIN total_matches t ON o.bowler_id = t.player_id
        GROUP BY o.bowler_id, t.n
        HAVING t.n >= 5
        """
        rows = self._run_query(query, tuple(total_params + phase_params))
        return {
            r[0]: {'pp': float(r[1] or 0), 'mid': float(r[2] or 0), 'death': float(r[3] or 0)}
            for r in rows
        }

    def get_bowler_venue_stats(
        self, bowler_ids: List[int], venue_id: int, match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[str, float]]:
        """
        Economy and wicket rate for each bowler at this specific venue.
        Returns {player_id: {'economy': float, 'wicket_rate': float, 'balls': int}}
        Only bowlers with at least 18 balls at the venue are included.
        """
        if not bowler_ids or not self.conn:
            return {}
        query = """
        SELECT
            d.bowler_id,
            SUM(d.runs_batter + d.runs_extras) * 6.0 / NULLIF(COUNT(*), 0) AS economy,
            SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END)::float
                / NULLIF(COUNT(*), 0)                                          AS wicket_rate,
            COUNT(*) AS balls
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.bowler_id = ANY(%s)
          AND m.venue_id  = %s
          AND m.match_format = ANY(%s)
          AND m.gender = %s
        GROUP BY d.bowler_id
        HAVING COUNT(*) >= 18
        """
        rows = self._run_query(query, (bowler_ids, venue_id, self._raw_formats(match_format), gender))
        return {
            r[0]: {'economy': float(r[1] or 0), 'wicket_rate': float(r[2] or 0), 'balls': int(r[3])}
            for r in rows
        }

    def get_bowler_country_stats(
        self, bowler_ids: List[int], country: str, match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[str, float]]:
        """
        Economy and wicket rate for each bowler across all venues in a country.
        Used as a fallback when venue-specific sample is too small.
        Returns {player_id: {'economy': float, 'wicket_rate': float, 'balls': int}}
        """
        if not bowler_ids or not self.conn:
            return {}
        query = """
        SELECT
            d.bowler_id,
            SUM(d.runs_batter + d.runs_extras) * 6.0 / NULLIF(COUNT(*), 0) AS economy,
            SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END)::float
                / NULLIF(COUNT(*), 0)                                          AS wicket_rate,
            COUNT(*) AS balls
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        JOIN history.venues  v ON m.venue_id = v.venue_id
        WHERE d.bowler_id = ANY(%s)
          AND v.country = %s
          AND m.match_format = ANY(%s)
          AND m.gender = %s
        GROUP BY d.bowler_id
        HAVING COUNT(*) >= 18
        """
        rows = self._run_query(query, (bowler_ids, country, self._raw_formats(match_format), gender))
        return {
            r[0]: {'economy': float(r[1] or 0), 'wicket_rate': float(r[2] or 0), 'balls': int(r[3])}
            for r in rows
        }

    def get_bowler_recent_form(
        self, bowler_ids: List[int], match_format: str, gender: str = 'male', last_n: int = 5
    ) -> Dict[int, Dict[str, float]]:
        """
        Economy and wicket rate across a bowler's last N matches in this format.
        Returns {player_id: {'economy': float, 'wicket_rate': float, 'balls': int}}
        """
        if not bowler_ids or not self.conn:
            return {}
        query = """
        WITH ranked AS (
            SELECT d.bowler_id, d.match_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY d.bowler_id
                       ORDER BY m.date DESC
                   ) AS rn
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE d.bowler_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
            GROUP BY d.bowler_id, d.match_id, m.date
        ),
        recent AS (
            SELECT bowler_id, match_id FROM ranked WHERE rn <= %s
        )
        SELECT
            d.bowler_id,
            SUM(d.runs_batter + d.runs_extras) * 6.0 / NULLIF(COUNT(*), 0) AS economy,
            SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END)::float
                / NULLIF(COUNT(*), 0)                                          AS wicket_rate,
            COUNT(*) AS balls
        FROM history.deliveries d
        JOIN recent r ON d.bowler_id = r.bowler_id AND d.match_id = r.match_id
        GROUP BY d.bowler_id
        HAVING COUNT(*) >= 6
        """
        rows = self._run_query(query, (bowler_ids, self._raw_formats(match_format), gender, last_n))
        return {
            r[0]: {'economy': float(r[1] or 0), 'wicket_rate': float(r[2] or 0), 'balls': int(r[3])}
            for r in rows
        }

    def get_bowler_test_phase_frequency(
        self, player_ids: List[int], gender: str = 'male',
        country: Optional[str] = None,
    ) -> Dict[int, Dict]:
        """
        Returns {player_id: {'n': int, 'buckets': {innings_bucket: {phase_idx: float}}}}
        for Test cricket. No minimum-match threshold — callers blend with a global prior.

        innings_bucket 1 = match innings 1 or 2 (first innings of each team).
        innings_bucket 2 = match innings 3 or 4 (second innings of each team).
        Phases 0-7 map to ball-age windows of 10 overs each within an 80-over
        new-ball cycle: 0→overs 0-9, 1→10-19, ..., 7→70-79.
        When `country` is provided, only matches at venues in that country are used.
        `n` is total matches the player participated in (from match_players) — the same
        for both innings buckets since a player either plays a match in full or not at all.
        """
        if not player_ids or not self.conn:
            return {}

        country_join   = "JOIN history.venues v ON m.venue_id = v.venue_id" if country else ""
        country_filter = "AND v.country = %s"                                if country else ""

        raw_fmts = self._raw_formats("Test")
        query = f"""
        WITH total_matches AS (
            -- Denominator: all matches the player participated in (not just bowled).
            -- Shared across both innings buckets since match_players has one row per match.
            SELECT mp.player_id, COUNT(DISTINCT mp.match_id) AS n
            FROM history.match_players mp
            JOIN history.matches m ON mp.match_id = m.match_id
            {country_join}
            WHERE mp.player_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {country_filter}
            GROUP BY mp.player_id
        ),
        bucketed AS (
            SELECT
                d.bowler_id,
                d.match_id,
                CASE WHEN d.inning_number <= 2 THEN 1 ELSE 2 END AS innings_bucket,
                ((d.over_number %% 80) / 10)::int                AS phase
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            {country_join}
            WHERE d.bowler_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {country_filter}
        ),
        phase_counts AS (
            SELECT bowler_id, innings_bucket, phase, COUNT(DISTINCT match_id) AS phase_matches
            FROM bucketed
            GROUP BY bowler_id, innings_bucket, phase
        )
        SELECT
            p.bowler_id,
            p.innings_bucket,
            t.n,
            p.phase,
            p.phase_matches::float / NULLIF(t.n, 0) AS phase_frac
        FROM phase_counts p
        JOIN total_matches t ON p.bowler_id = t.player_id
        """
        params = [player_ids, raw_fmts, gender]
        if country:
            params.append(country)
        params += [player_ids, raw_fmts, gender]
        if country:
            params.append(country)
        rows = self._run_query(query, tuple(params))

        result: Dict[int, Dict] = {}
        for bowler_id, innings_bucket, n, phase, frac in rows:
            entry = result.setdefault(bowler_id, {'n': int(n), 'buckets': {}})
            entry['buckets'].setdefault(int(innings_bucket), {})[int(phase)] = float(frac)
        return result

    def get_historical_match_ids(
        self, match_format: str, gender: str = 'male', n: int = 30
    ) -> List[int]:
        """Returns n random match IDs for the given format, ordered randomly."""
        if not self.conn:
            return []
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT match_id FROM history.matches
        WHERE match_format = ANY(%s) AND gender = %s
        ORDER BY RANDOM()
        LIMIT %s
        """
        rows = self._run_query(query, (raw_fmts, gender, n))
        return [r[0] for r in rows]

    def get_match_ball_log(self, match_id: int) -> List[tuple]:
        """
        Returns all deliveries for a match in chronological order.
        Each row: (inning_number, over_number, ball_number,
                   bowler_id, batter_id, bowling_team_id,
                   runs_batter, runs_extras, is_wicket)
        """
        if not self.conn:
            return []
        query = """
        SELECT
            d.inning_number,
            d.over_number,
            d.ball_number,
            d.bowler_id,
            d.batter_id,
            d.bowling_team_id,
            d.runs_batter,
            d.runs_extras,
            CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END AS is_wicket
        FROM history.deliveries d
        WHERE d.match_id = %s
        ORDER BY d.inning_number, d.over_number, d.ball_number
        """
        return self._run_query(query, (match_id,))

    def get_player_names(self, player_ids: List[int]) -> Dict[int, str]:
        """Returns {player_id: name} for the given IDs."""
        if not player_ids or not self.conn:
            return {}
        query = "SELECT player_id, name FROM history.players WHERE player_id = ANY(%s)"
        rows = self._run_query(query, (player_ids,))
        return {r[0]: r[1] for r in rows}

    def _parse_rows_to_probs_with_count(self, rows) -> Tuple[Optional[Dict[Tuple, float]], int]:
        """Like _parse_rows_to_probs but also returns the total ball count."""
        baseline = defaultdict(int)
        total = 0
        for r_bat, r_ext, out_type, out_kind, count in rows:
            total += count
            baseline[(r_bat, r_ext, out_type, out_kind)] += count
        if total > 0:
            return ({k: v / total for k, v in baseline.items()}, total)
        return (None, 0)

    def get_batters_distribution_with_counts(
        self, batter_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Tuple[Dict[Tuple, float], int]]:
        """Like get_batters_distribution but also returns {player_id: (probs, ball_count)}."""
        if not batter_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT d.batter_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.batter_id = ANY(%s) AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.batter_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (batter_ids, raw_fmts, gender))
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[0]].append((row[1], row[2], row[3], row[4], row[5]))
        result = {}
        for pid, metrics in grouped.items():
            probs, count = self._parse_rows_to_probs_with_count(metrics)
            if probs:
                result[pid] = (probs, count)
        return result

    def get_bowlers_distribution_with_counts(
        self, bowler_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Tuple[Dict[Tuple, float], int]]:
        """Like get_bowlers_distribution but also returns {player_id: (probs, ball_count)}."""
        if not bowler_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT d.bowler_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.bowler_id = ANY(%s) AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.bowler_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (bowler_ids, raw_fmts, gender))
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[0]].append((row[1], row[2], row[3], row[4], row[5]))
        result = {}
        for pid, metrics in grouped.items():
            probs, count = self._parse_rows_to_probs_with_count(metrics)
            if probs:
                result[pid] = (probs, count)
        return result

    def get_matchup_distribution_with_counts(
        self,
        batter_ids: List[int],
        bowler_ids: List[int],
        match_format: str,
        gender: str = 'male',
        min_balls: int = 12,
    ) -> Dict[Tuple[int, int], Tuple[Dict[Tuple, float], int]]:
        """Like get_matchup_distribution but returns (probs, ball_count) per pair."""
        if not batter_ids or not bowler_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        WITH qualified_pairs AS (
            SELECT d.batter_id, d.bowler_id
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE d.batter_id = ANY(%s) AND d.bowler_id = ANY(%s)
              AND m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY d.batter_id, d.bowler_id
            HAVING COUNT(*) >= %s
        )
        SELECT d.batter_id, d.bowler_id,
               d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        JOIN qualified_pairs qp ON d.batter_id = qp.batter_id AND d.bowler_id = qp.bowler_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.batter_id, d.bowler_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (batter_ids, bowler_ids, raw_fmts, gender, min_balls, raw_fmts, gender))
        grouped = defaultdict(list)
        for row in rows:
            grouped[(row[0], row[1])].append((row[2], row[3], row[4], row[5], row[6]))
        result = {}
        for pair, metrics in grouped.items():
            probs, count = self._parse_rows_to_probs_with_count(metrics)
            if probs:
                result[pair] = (probs, count)
        return result

    def get_batter_milestone_distribution(
        self, match_format: str, gender: str = 'male'
    ) -> Dict[str, Dict[Tuple, float]]:
        """
        Outcome distribution conditioned on the batter's running score at the time of delivery.
        Uses a window function to compute score_before for every delivery.

        Milestones: 10-run buckets — 'm0' (0-9), 'm10' (10-19), ..., 'm90' (90-99), 'm100' (100+).
        These are global (all-batter) distributions used as fallback when a specific
        batter lacks sufficient per-bucket data.

        Returns {milestone: {outcome_key: prob}}.
        """
        if not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        WITH delivery_running AS (
            SELECT
                d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                COALESCE(
                    SUM(d.runs_batter) OVER (
                        PARTITION BY d.batter_id, d.match_id, d.inning_number
                        ORDER BY d.over_number, d.ball_number
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
                ) AS score_before
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
        )
        SELECT
            CASE
                WHEN score_before >= 100 THEN 'm100'
                ELSE 'm' || ((score_before / 10) * 10)::text
            END AS milestone,
            runs_batter, runs_extras, outcome_type, outcome_kind,
            COUNT(*) AS cnt
        FROM delivery_running
        GROUP BY milestone, runs_batter, runs_extras, outcome_type, outcome_kind
        """
        rows = self._run_query(query, (raw_fmts, gender))
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[0]].append((row[1], row[2], row[3], row[4], row[5]))
        result = {}
        for milestone, metrics in grouped.items():
            probs = self._parse_rows_to_probs(metrics)
            if probs:
                result[milestone] = probs
        return result

    def get_player_milestone_distributions(
        self, player_ids: List[int], match_format: str, gender: str = 'male',
        min_balls: int = 20,
    ) -> Dict[int, Dict[str, Dict[Tuple, float]]]:
        """
        Per-batter milestone distributions using 10-run buckets.
        Only includes (player, bucket) pairs with >= min_balls deliveries.
        Returns {batter_id: {milestone_label: {outcome_key: prob}}}.
        """
        if not self.conn or not player_ids:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        WITH delivery_running AS (
            SELECT
                d.batter_id,
                d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                COALESCE(
                    SUM(d.runs_batter) OVER (
                        PARTITION BY d.batter_id, d.match_id, d.inning_number
                        ORDER BY d.over_number, d.ball_number
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
                ) AS score_before
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
              AND d.batter_id = ANY(%s)
        )
        SELECT
            batter_id,
            CASE
                WHEN score_before >= 100 THEN 'm100'
                ELSE 'm' || ((score_before / 10) * 10)::text
            END AS milestone,
            runs_batter, runs_extras, outcome_type, outcome_kind,
            COUNT(*) AS cnt
        FROM delivery_running
        GROUP BY batter_id, milestone, runs_batter, runs_extras, outcome_type, outcome_kind
        HAVING COUNT(*) >= 1
        """
        rows = self._run_query(query, (raw_fmts, gender, player_ids))

        # Group: player_id -> milestone -> [(r_bat, r_ext, out_type, out_kind, cnt)]
        grouped: Dict[int, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
        bucket_totals: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for batter_id, milestone, r_bat, r_ext, out_type, out_kind, cnt in rows:
            grouped[batter_id][milestone].append((r_bat, r_ext, out_type, out_kind, cnt))
            bucket_totals[batter_id][milestone] += cnt

        result: Dict[int, Dict[str, Dict[Tuple, float]]] = {}
        for batter_id, ms_data in grouped.items():
            player_ms: Dict[str, Dict[Tuple, float]] = {}
            for milestone, metric_rows in ms_data.items():
                if bucket_totals[batter_id][milestone] < min_balls:
                    continue  # too few samples — caller will fall back to global
                probs = self._parse_rows_to_probs(metric_rows)
                if probs:
                    player_ms[milestone] = probs
            if player_ms:
                result[batter_id] = player_ms
        return result

    def get_validation_deliveries(
        self, match_format: str, gender: str = 'male', sample_size: int = 5000
    ) -> List[tuple]:
        """
        Returns up to sample_size random deliveries with full context for model validation.
        Each row: (batter_id, bowler_id, venue_id, inning_number, over_number, tournament_id,
                   runs_batter, runs_extras, outcome_type, outcome_kind, batter_score_before)

        batter_score_before is the batter's accumulated runs in this innings BEFORE this delivery,
        computed via a window function — used to derive the confidence milestone at prediction time.
        """
        if not self.conn:
            return []
        raw_fmts = self._raw_formats(match_format)
        query = """
        WITH delivery_running AS (
            SELECT
                d.batter_id, d.bowler_id, m.venue_id, d.inning_number, d.over_number,
                m.tournament_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                COALESCE(
                    SUM(d.runs_batter) OVER (
                        PARTITION BY d.batter_id, d.match_id, d.inning_number
                        ORDER BY d.over_number, d.ball_number
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
                ) AS batter_score_before
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
        )
        SELECT batter_id, bowler_id, venue_id, inning_number, over_number, tournament_id,
               runs_batter, runs_extras, outcome_type, outcome_kind, batter_score_before
        FROM delivery_running
        ORDER BY RANDOM()
        LIMIT %s
        """
        return self._run_query(query, (raw_fmts, gender, sample_size))

    def get_full_aggregate_distribution(self, match_format: str, gender: str = 'male') -> Dict[Tuple, float]:
        """
        Overall delivery outcome probability distribution across all deliveries for this format.
        Used as the baseline anchor in the enhanced strategy — derived from raw counts rather
        than by averaging per-innings distributions.
        """
        if not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (raw_fmts, gender))
        return self._parse_rows_to_probs(rows) or {}

    def get_phase_distribution(self, match_format: str, gender: str = 'male') -> Dict[str, Dict[Tuple, float]]:
        """
        Outcome probability distribution per fine-grained phase bucket.

        T20  (6 buckets): pp1 (ov 1-3), pp2 (4-6), mid1 (7-11),
                           mid2 (12-15), death1 (16-17), death2 (18-20).
        ODI  (7 buckets): pp1 (ov 1-5), pp2 (6-10), mid1 (11-20),
                           mid2 (21-30), mid3 (31-40), death1 (41-45), death2 (46-50).
        Test (4 buckets): new (ov 1-10), early (11-30), middle (31-80), late (81+).

        Returns {phase_name: {outcome_key: prob}}.
        """
        if not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        if match_format == 'T20':
            phase_expr = """
            CASE
                WHEN d.over_number <= 3  THEN 'pp1'
                WHEN d.over_number <= 6  THEN 'pp2'
                WHEN d.over_number <= 11 THEN 'mid1'
                WHEN d.over_number <= 15 THEN 'mid2'
                WHEN d.over_number <= 17 THEN 'death1'
                ELSE 'death2'
            END"""
        elif match_format == 'ODI':
            phase_expr = """
            CASE
                WHEN d.over_number <= 5  THEN 'pp1'
                WHEN d.over_number <= 10 THEN 'pp2'
                WHEN d.over_number <= 20 THEN 'mid1'
                WHEN d.over_number <= 30 THEN 'mid2'
                WHEN d.over_number <= 40 THEN 'mid3'
                WHEN d.over_number <= 45 THEN 'death1'
                ELSE 'death2'
            END"""
        else:  # Test
            phase_expr = """
            CASE
                WHEN d.over_number <= 10 THEN 'new'
                WHEN d.over_number <= 30 THEN 'early'
                WHEN d.over_number <= 80 THEN 'middle'
                ELSE 'late'
            END"""
        query = f"""
        SELECT {phase_expr} AS phase,
               d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY phase, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (raw_fmts, gender))
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[0]].append((row[1], row[2], row[3], row[4], row[5]))
        result = {}
        for phase, metrics in grouped.items():
            probs = self._parse_rows_to_probs(metrics)
            if probs:
                result[phase] = probs
        return result

    def get_matchup_distribution(
        self,
        batter_ids: List[int],
        bowler_ids: List[int],
        match_format: str,
        gender: str = 'male',
        min_balls: int = 12,
    ) -> Dict[Tuple[int, int], Dict[Tuple, float]]:
        """
        Head-to-head ball outcome distribution per (batter_id, bowler_id) pair.
        Only pairs with at least min_balls deliveries are included.
        Returns {(batter_id, bowler_id): {outcome_key: prob}}.
        """
        if not batter_ids or not bowler_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        WITH qualified_pairs AS (
            SELECT d.batter_id, d.bowler_id
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE d.batter_id = ANY(%s) AND d.bowler_id = ANY(%s)
              AND m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY d.batter_id, d.bowler_id
            HAVING COUNT(*) >= %s
        )
        SELECT d.batter_id, d.bowler_id,
               d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        JOIN qualified_pairs qp ON d.batter_id = qp.batter_id AND d.bowler_id = qp.bowler_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.batter_id, d.bowler_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (batter_ids, bowler_ids, raw_fmts, gender, min_balls, raw_fmts, gender))
        grouped = defaultdict(list)
        for row in rows:
            grouped[(row[0], row[1])].append((row[2], row[3], row[4], row[5], row[6]))
        result = {}
        for pair, metrics in grouped.items():
            probs = self._parse_rows_to_probs(metrics)
            if probs:
                result[pair] = probs
        return result

    def get_fielding_distribution(self, match_format: str, gender: str = 'male') -> Dict[int, int]:
        if not self.conn: return {}
        query = """
        SELECT d.outcome_player_id, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s AND d.outcome_type = 'Wicket' AND d.outcome_player_id IS NOT NULL
        GROUP BY d.outcome_player_id
        """
        rows = self._run_query(query, (self._raw_formats(match_format), gender))
        return {r[0]: r[1] for r in rows}
