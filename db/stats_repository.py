from typing import List, Dict, Any, Tuple, Optional
from collections import defaultdict

# Seconds in a Julian year (365.25 × 24 × 3600). Used to convert epoch differences to years
# in all time-decay expressions so the magic number is never repeated in SQL strings.
_SECONDS_PER_YEAR = 31_557_600


def _decay_sql(half_life_years: float) -> str:
    """Return the SQL weight expression for exponential time decay with the given half-life."""
    return (
        f"EXP(-LN(2) / {half_life_years} "
        f"* GREATEST(0.0, EXTRACT(EPOCH FROM NOW() - m.date) / {_SECONDS_PER_YEAR}))"
    )


# Pre-computed decay expressions for the half-lives used across queries.
_D3Y  = _decay_sql(3.0)   # tournament distribution
_D5Y  = _decay_sql(5.0)   # batter, bowler, matchup, phase, player-country (close)
_D6Y  = _decay_sql(6.0)   # player-country (region-wide)
_D7Y  = _decay_sql(7.0)   # venue aggregate
_D8Y  = _decay_sql(8.0)   # player-venue (sparse — slower decay to preserve signal)


# Maps unified format names to all raw DB format strings that belong to that bucket.
_FORMAT_ALIASES: Dict[str, List[str]] = {
    "Test": ["Test", "MDM"],
    "ODI":  ["ODI",  "ODM", "ONE DAY"],
    "T20":  ["T20",  "IT20"],
}

# ── Precomputed-table helpers ──────────────────────────────────────────────────

# Process-level cache: keyed by ('pos', fmt, stat_type) or ('pcs_venue', fmt, venue_id)
_PRECOMPUTED_CACHE: Dict[Tuple, Any] = {}

_PHASE_STAT_TYPES: Dict[str, List[str]] = {
    'T20':  ['phase_pp1', 'phase_pp2', 'phase_mid1', 'phase_mid2', 'phase_death1', 'phase_death2'],
    'ODI':  ['phase_pp1', 'phase_pp2', 'phase_mid1', 'phase_mid2', 'phase_mid3', 'phase_death1', 'phase_death2'],
    'Test': ['phase_new', 'phase_early', 'phase_middle', 'phase_late'],
}
_MILESTONE_STAT_TYPES = [f'milestone_m{i * 10}' for i in range(11)]  # milestone_m0 .. milestone_m100


def _json_to_prob_dict(d: Optional[dict]) -> Optional[Dict[Tuple, float]]:
    """Decode precomputed JSONB probs: {'rb|re|ot|ok': v} → {(rb, re, ot, ok): v}."""
    if not d:
        return None
    result = {}
    for k, v in d.items():
        parts = k.split('|', 3)
        result[(int(parts[0]), int(parts[1]), parts[2], parts[3] or None)] = float(v)
    return result or None


def _decay_weight_per_year(
    per_year: Dict[int, Dict[Tuple, int]], half_life: float = 5.0
) -> Optional[Dict[Tuple, float]]:
    """Collapse per-year raw count dict into a single decay-weighted probability distribution."""
    import math
    from datetime import date as _date
    current_year = _date.today().year
    weighted: Dict[Tuple, float] = {}
    total_w = 0.0
    for year, counts in per_year.items():
        age = max(0, current_year - int(year))
        decay = math.exp(-math.log(2) / half_life * age)
        yr_total = sum(counts.values())
        if yr_total == 0:
            continue
        for key, cnt in counts.items():
            weighted[key] = weighted.get(key, 0.0) + decay * cnt
        total_w += decay * yr_total
    if total_w < 1e-9:
        return None
    return {k: v / total_w for k, v in weighted.items()}


def _fine_grained_phase(over_1indexed: int, match_format: str) -> str:
    """Map an over (1-indexed) to a fine-grained phase bucket."""
    if match_format == 'T20':
        if over_1indexed <= 3:  return 'pp1'
        if over_1indexed <= 6:  return 'pp2'
        if over_1indexed <= 11: return 'mid1'
        if over_1indexed <= 15: return 'mid2'
        if over_1indexed <= 17: return 'death1'
        return 'death2'
    if match_format == 'ODI':
        if over_1indexed <= 5:  return 'pp1'
        if over_1indexed <= 10: return 'pp2'
        if over_1indexed <= 20: return 'mid1'
        if over_1indexed <= 30: return 'mid2'
        if over_1indexed <= 40: return 'mid3'
        if over_1indexed <= 45: return 'death1'
        return 'death2'
    # Test
    if over_1indexed <= 10: return 'new'
    if over_1indexed <= 30: return 'early'
    if over_1indexed <= 80: return 'middle'
    return 'late'

try:
    from db.database import get_db_connection
    HAS_DB = True
except ImportError:
    HAS_DB = False

import logging as _logging
import threading

_repo_log = _logging.getLogger(__name__)

class StatsRepository:
    """
    Singleton DB connection shared across all instances in the process.

    The first StatsRepository() call opens one psycopg2 connection and stores it
    at the class level. Every subsequent StatsRepository() reuses that connection —
    no new DB handshake, no TCP overhead.

    After the process-level _PRECOMPUTED_CACHE is warm, _run_query is almost never
    called (all reads return from the dict). The _query_lock serialises the rare
    cases where an actual DB round-trip is still needed (venue lookups, etc.) because
    psycopg2 connections are not thread-safe.
    """

    _conn = None
    _conn_lock  = threading.Lock()   # guards singleton initialisation
    _query_lock = threading.Lock()   # serialises actual DB round-trips

    def __init__(self):
        if StatsRepository._conn is None:
            with StatsRepository._conn_lock:
                if StatsRepository._conn is None:   # double-checked
                    if HAS_DB:
                        try:
                            StatsRepository._conn = get_db_connection(autocommit=True)
                        except Exception as e:
                            print(f"Warning: Could not connect to DB for stats: {e}")
        self.conn = StatsRepository._conn
            
    def get_player_by_name(self, name: str) -> Optional[Tuple[int, str]]:
        if not self.conn: return None
        # Use exact identity matching since driver scripts have been mapped to proper nomenclature!
        query = "SELECT player_id, name FROM history.players WHERE name = %s LIMIT 1"
        rows = self._run_query(query, (name,))

        if not rows:
            print(f"[DB] Lookup failed: No history found for exact player name '{name}'")
            return None
        return (rows[0][0], rows[0][1])

    def get_player_by_id(self, player_id: int) -> Optional[Tuple[int, str]]:
        if not self.conn: return None
        rows = self._run_query(
            "SELECT player_id, COALESCE(display_name, name) FROM history.players WHERE player_id = %s LIMIT 1",
            (player_id,),
        )
        return (rows[0][0], rows[0][1]) if rows else None

    def get_venue_by_name(self, name: str) -> Optional[Tuple[int, str, Optional[str]]]:
        """Returns (venue_id, name, country) or None.
        Tries the full name first; if not found, strips any ', City' suffix and retries.
        """
        if not self.conn: return None
        query = "SELECT venue_id, name, country FROM history.venues WHERE name ILIKE %s LIMIT 1"

        def _search(n: str):
            s = '%' + '%'.join(n.split()) + '%'
            return self._run_query(query, (s,))

        rows = _search(name)
        if not rows and ',' in name:
            rows = _search(name.split(',')[0].strip())
        if not rows:
            print(f"[DB] Lookup failed: Venue '{name}' not found.")
            return None
        return (rows[0][0], rows[0][1], rows[0][2])

    def get_tournament_by_name(self, name: str) -> Optional[Tuple[int, str, Optional[str]]]:
        """Returns (tournament_id, tournament_name, season) or None. Matches most recent season."""
        if not self.conn: return None
        query = """
            SELECT tournament_id, tournament_name, season
            FROM history.tournaments
            WHERE tournament_name ILIKE %s
            ORDER BY season DESC NULLS LAST
            LIMIT 1
        """
        rows = self._run_query(query, (f"%{name}%",))
        if not rows:
            return None
        return (rows[0][0], rows[0][1], rows[0][2])
        
    def _run_query(self, query: str, params: tuple = ()) -> List[tuple]:
        if not self.conn:
            return []
        with StatsRepository._query_lock:
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
        query = f"""
        SELECT d.batter_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
               SUM({_D5Y})
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
        query = f"""
        SELECT d.bowler_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
               SUM({_D5Y})
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
        cache_key = ('vs', venue_id, match_format, gender)
        if cache_key not in _PRECOMPUTED_CACHE:
            if self.conn:
                rows = self._run_query(
                    "SELECT probs FROM history.venue_stats WHERE venue_id=%s AND match_format=%s AND gender=%s",
                    (venue_id, match_format, gender),
                )
                _PRECOMPUTED_CACHE[cache_key] = _json_to_prob_dict(rows[0][0]) if rows and rows[0][0] else None
            else:
                _PRECOMPUTED_CACHE[cache_key] = None
        if _PRECOMPUTED_CACHE[cache_key]:
            return _PRECOMPUTED_CACHE[cache_key]
        if not self.conn: return {}
        raw_fmts = self._raw_formats(match_format)
        query = f"""
        SELECT d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
               SUM({_D7Y})
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.venue_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (venue_id, raw_fmts, gender))
        return self._parse_rows_to_probs(rows) or {}

    def get_country_distribution(self, country: str, match_format: str, gender: str = 'male') -> Dict[Tuple, float]:
        """Outcome distribution across all venues in a country. Used as fallback when venue data is sparse."""
        cache_key = ('cs', country, match_format, gender)
        if cache_key not in _PRECOMPUTED_CACHE:
            if self.conn:
                rows = self._run_query(
                    "SELECT probs FROM history.country_stats WHERE country=%s AND match_format=%s AND gender=%s",
                    (country, match_format, gender),
                )
                _PRECOMPUTED_CACHE[cache_key] = _json_to_prob_dict(rows[0][0]) if rows and rows[0][0] else None
            else:
                _PRECOMPUTED_CACHE[cache_key] = None
        if _PRECOMPUTED_CACHE[cache_key]:
            return _PRECOMPUTED_CACHE[cache_key]
        if not self.conn: return {}
        raw_fmts = self._raw_formats(match_format)
        query = f"""
        SELECT d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
               SUM({_D8Y})
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        JOIN history.venues  v ON m.venue_id = v.venue_id
        WHERE v.country = %s AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (country, raw_fmts, gender))
        return self._parse_rows_to_probs(rows) or {}

    def get_player_venue_distribution(
        self, player_ids: List[int], venue_id: int, match_format: str, gender: str = 'male'
    ) -> Dict[int, Tuple[Dict[Tuple, float], int]]:
        """Per-batter outcome distributions at a specific venue. Returns {player_id: (probs, ball_count)}."""
        if not player_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = f"""
        SELECT d.batter_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
               SUM({_D5Y})
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.batter_id = ANY(%s) AND m.venue_id = %s
          AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.batter_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (player_ids, venue_id, raw_fmts, gender))
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[0]].append((row[1], row[2], row[3], row[4], row[5]))
        result = {}
        for pid, metrics in grouped.items():
            probs, count = self._parse_rows_to_probs_with_count(metrics)
            if probs:
                result[pid] = (probs, count)
        return result

    def get_player_country_distribution(
        self, player_ids: List[int], country: str, match_format: str, gender: str = 'male',
        countries: Optional[List[str]] = None,
        exclude_venue_id: Optional[int] = None,
    ) -> Dict[int, Tuple[Dict[Tuple, float], int]]:
        """Per-batter distributions at venues in a country or region.

        countries:        when provided, pools all listed countries (e.g. West Indies islands).
                          Overrides the single `country` argument.
        exclude_venue_id: when provided, excludes deliveries at that venue so country data
                          is strictly additive to (not overlapping with) venue-level data.
        """
        if not player_ids or not self.conn:
            return {}

        c_list = countries if countries else [country]

        if exclude_venue_id is None:
            cached = self._load_player_country_stats_cache(match_format)
            if cached:
                result: Dict[int, Tuple[Dict[Tuple, float], int]] = {}
                for pid in player_ids:
                    combined: Dict[Tuple, float] = {}
                    total_count = 0
                    for c in c_list:
                        entry = cached.get((pid, c))
                        if entry:
                            raw, _, count = entry
                            for key, prob in raw.items():
                                combined[key] = combined.get(key, 0.0) + prob * count
                            total_count += count
                    if total_count > 0 and combined:
                        merged = {k: v / total_count for k, v in combined.items()}
                        result[pid] = (merged, total_count)
                return result

        raw_fmts      = self._raw_formats(match_format)
        venue_exclude = "AND m.venue_id != %s" if exclude_venue_id is not None else ""
        query = f"""
        SELECT d.batter_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
               SUM({_D6Y})
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        JOIN history.venues  v ON m.venue_id = v.venue_id
        WHERE d.batter_id = ANY(%s) AND v.country = ANY(%s)
          AND m.match_format = ANY(%s) AND m.gender = %s
          {venue_exclude}
        GROUP BY d.batter_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        params: tuple = (player_ids, c_list, raw_fmts, gender)
        if exclude_venue_id is not None:
            params = params + (exclude_venue_id,)
        rows = self._run_query(query, params)
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[0]].append((row[1], row[2], row[3], row[4], row[5]))
        result = {}
        for pid, metrics in grouped.items():
            probs, count = self._parse_rows_to_probs_with_count(metrics)
            if probs:
                result[pid] = (probs, count)
        return result

    def get_batting_position_baseline(self, match_format: str, gender: str = 'male') -> Dict[str, Dict[Tuple, float]]:
        """
        Returns outcome probability distributions keyed by batting position group:
          'top_order'    — positions 1-3 (openers + first-drop)
          'middle_order' — positions 4-6
          'lower_order'  — positions 7+

        Position is derived from each batter's first appearance (by over/ball) in each innings.
        Used as a fallback when a batter has no personal career history in the cache.
        """
        agg = self._load_aggregate_cache(match_format, gender)
        if agg:
            prefix = 'batting_position_'
            result = {k[len(prefix):]: v for k, v in agg.items() if k.startswith(prefix)}
            if result:
                return result
        if not self.conn: return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        WITH first_ball AS (
            SELECT d.match_id, d.inning_number, d.batter_id,
                   MIN(d.over_number * 1000 + d.ball_number) AS first_key
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY d.match_id, d.inning_number, d.batter_id
        ),
        batter_positions AS (
            SELECT match_id, inning_number, batter_id,
                   RANK() OVER (
                       PARTITION BY match_id, inning_number
                       ORDER BY first_key
                   ) AS position
            FROM first_ball
        )
        SELECT
            CASE
                WHEN bp.position <= 3 THEN 'top_order'
                WHEN bp.position <= 6 THEN 'middle_order'
                ELSE 'lower_order'
            END AS position_group,
            d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
            COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        JOIN batter_positions bp
            ON bp.match_id = d.match_id
           AND bp.inning_number = d.inning_number
           AND bp.batter_id = d.batter_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY position_group, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (raw_fmts, gender, raw_fmts, gender))
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[0]].append((row[1], row[2], row[3], row[4], row[5]))
        res = {}
        for group, metrics in grouped.items():
            probs = self._parse_rows_to_probs(metrics)
            if probs:
                res[group] = probs
        return res

    def get_innings_distribution(self, match_format: str, gender: str = 'male') -> Dict[int, Dict[Tuple, float]]:
        agg = self._load_aggregate_cache(match_format, gender)
        if agg:
            result = {}
            for k, v in agg.items():
                if k.startswith('innings_'):
                    try:
                        result[int(k[len('innings_'):])] = v
                    except ValueError:
                        pass
            if result:
                return result
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
        cache_key = ('ts', tournament_id)
        if cache_key not in _PRECOMPUTED_CACHE:
            if self.conn:
                rows = self._run_query(
                    "SELECT probs FROM history.tournament_outcome_stats WHERE tournament_id=%s",
                    (tournament_id,),
                )
                _PRECOMPUTED_CACHE[cache_key] = _json_to_prob_dict(rows[0][0]) if rows and rows[0][0] else None
            else:
                _PRECOMPUTED_CACHE[cache_key] = None
        if _PRECOMPUTED_CACHE[cache_key]:
            return _PRECOMPUTED_CACHE[cache_key]
        if not self.conn: return {}
        query = f"""
        SELECT d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
               SUM({_D3Y})
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

    def _load_roles_cache(self) -> Dict[int, dict]:
        """Load player roles (is_keeper, is_spinner) from player_scalar_stats; process-level cache."""
        cache_key = ('roles',)
        if cache_key in _PRECOMPUTED_CACHE:
            return _PRECOMPUTED_CACHE[cache_key]
        if not self.conn:
            _PRECOMPUTED_CACHE[cache_key] = {}
            return {}
        rows = self._run_query(
            "SELECT player_id, data FROM history.player_scalar_stats "
            "WHERE stat_type = 'roles' AND match_format = 'any'",
            (),
        )
        result: Dict[int, dict] = {int(pid): data for pid, data in rows if data}
        _PRECOMPUTED_CACHE[cache_key] = result
        return result

    # ── Bowling-strategy precomputed read methods ──────────────────────────────

    def _load_workload_cache(self, match_format: str) -> Dict[int, dict]:
        """All workload scalars for this format; process-level cache."""
        cache_key = ('workload_pc', match_format)
        if cache_key in _PRECOMPUTED_CACHE:
            return _PRECOMPUTED_CACHE[cache_key]
        if not self.conn:
            _PRECOMPUTED_CACHE[cache_key] = {}
            return {}
        rows = self._run_query(
            "SELECT player_id, data FROM history.player_scalar_stats "
            "WHERE match_format = %s AND stat_type = 'workload'",
            (match_format,),
        )
        result: Dict[int, dict] = {int(pid): data for pid, data in rows if data}
        _PRECOMPUTED_CACHE[cache_key] = result
        return result

    def _load_bowler_order_cache(self, match_format: str, dist_type: str) -> Dict[Tuple, Dict[int, dict]]:
        """
        Loads all non-venue/non-country rows from bowler_order_stats for this
        (format, dist_type) and returns {(match_type, inning_number): {pid: probs_dict}}.
        Process-level cache.
        """
        cache_key = ('bowler_order_pc', match_format, dist_type)
        if cache_key in _PRECOMPUTED_CACHE:
            return _PRECOMPUTED_CACHE[cache_key]
        if not self.conn:
            _PRECOMPUTED_CACHE[cache_key] = {}
            return {}
        rows = self._run_query(
            "SELECT player_id, match_type, inning_number, probs "
            "FROM history.bowler_order_stats "
            "WHERE match_format = %s AND dist_type = %s "
            "AND venue_id IS NULL AND country IS NULL",
            (match_format, dist_type),
        )
        result: Dict[Tuple, Dict[int, dict]] = {}
        for pid, mt, inn, probs in rows:
            if probs:
                result.setdefault((mt, int(inn)), {})[int(pid)] = probs
        _PRECOMPUTED_CACHE[cache_key] = result
        return result

    @staticmethod
    def _matchup_scalars(probs_raw: dict, ball_count: int) -> dict:
        economy = 0.0
        wicket_rate = 0.0
        for k, p in probs_raw.items():
            parts = k.split('|', 3)
            economy += (int(parts[0]) + int(parts[1])) * p * 6.0
            if parts[2] == 'Wicket':
                wicket_rate += p
        return {'economy': economy, 'wicket_rate': wicket_rate, 'balls': int(ball_count)}

    def _load_matchup_aggregate_cache(self, match_format: str) -> Dict[Tuple, dict]:
        """Full load of all matchup scalars for this format. Used by warm_all_caches."""
        full_key = ('matchup_agg', match_format)
        done_key = ('matchup_agg_all_loaded', match_format)
        if _PRECOMPUTED_CACHE.get(done_key):
            return _PRECOMPUTED_CACHE.get(full_key, {})
        if not self.conn:
            _PRECOMPUTED_CACHE[full_key] = {}
            _PRECOMPUTED_CACHE[done_key] = True
            return {}
        rows = self._run_query(
            "SELECT batter_id, bowler_id, ball_count, probs_raw "
            "FROM history.batter_bowler_matchups "
            "WHERE match_format = %s AND ball_count >= 6",
            (match_format,),
        )
        result: Dict[Tuple, dict] = _PRECOMPUTED_CACHE.get(full_key, {})
        for batter_id, bowler_id, ball_count, probs_raw in rows:
            if probs_raw:
                result[(int(batter_id), int(bowler_id))] = self._matchup_scalars(probs_raw, ball_count)
        _PRECOMPUTED_CACHE[full_key] = result
        _PRECOMPUTED_CACHE[done_key] = True
        return result

    def _ensure_in_matchup_agg_cache(self, player_ids: List[int], match_format: str) -> Dict[Tuple, dict]:
        """Lazy-load matchup scalars for specific players only. Merges into existing cache."""
        full_key = ('matchup_agg', match_format)
        done_key = ('matchup_agg_all_loaded', match_format)
        if _PRECOMPUTED_CACHE.get(done_key):
            return _PRECOMPUTED_CACHE.get(full_key, {})
        if not player_ids or not self.conn:
            return _PRECOMPUTED_CACHE.get(full_key, {})
        loaded_key = ('matchup_agg_loaded_pids', match_format)
        loaded_pids: set = _PRECOMPUTED_CACHE.get(loaded_key, set())
        missing = [pid for pid in player_ids if pid not in loaded_pids]
        if not missing:
            return _PRECOMPUTED_CACHE.get(full_key, {})
        rows = self._run_query(
            "SELECT batter_id, bowler_id, ball_count, probs_raw "
            "FROM history.batter_bowler_matchups "
            "WHERE match_format = %s AND ball_count >= 6 "
            "AND (batter_id = ANY(%s) OR bowler_id = ANY(%s))",
            (match_format, missing, missing),
        )
        dest = _PRECOMPUTED_CACHE.setdefault(full_key, {})
        for batter_id, bowler_id, ball_count, probs_raw in rows:
            if probs_raw:
                dest[(int(batter_id), int(bowler_id))] = self._matchup_scalars(probs_raw, ball_count)
        loaded_pids.update(missing)
        _PRECOMPUTED_CACHE[loaded_key] = loaded_pids
        return dest

    def get_bowler_workload_precomputed(
        self, player_ids: List[int], match_format: str
    ) -> Dict[int, dict]:
        """Precomputed workload stats filtered to player_ids. Never queries deliveries."""
        full = self._load_workload_cache(match_format)
        pid_set = set(player_ids)
        return {pid: data for pid, data in full.items() if pid in pid_set}

    def get_bowler_over_frequency_precomputed(
        self, player_ids: List[int], match_format: str,
        match_type: str = 'all', inning_number: int = 0,
    ) -> Dict[int, Dict[int, float]]:
        """Precomputed over-frequency for T20/ODI. Returns {pid: {over_key: frac}}."""
        full = self._load_bowler_order_cache(match_format, 'over_freq')
        pid_set = set(player_ids)
        slot = full.get((match_type, inning_number), {})
        return {pid: {int(k): float(v) for k, v in data.items()}
                for pid, data in slot.items() if pid in pid_set}

    def get_bowler_phase_dist_precomputed(
        self, player_ids: List[int], match_format: str,
        match_type: str = 'all', inning_number: int = 0,
    ) -> Dict[int, Dict[str, float]]:
        """Precomputed phase-overs distribution for T20/ODI. Returns {pid: {pp/mid/death: avg}}."""
        full = self._load_bowler_order_cache(match_format, 'phase_dist')
        pid_set = set(player_ids)
        slot = full.get((match_type, inning_number), {})
        return {pid: {str(k): float(v) for k, v in data.items()}
                for pid, data in slot.items() if pid in pid_set}

    def _load_test_phase_freq_cache(self) -> Dict[int, Dict]:
        """
        Loads Test bowler phase-frequency from bowler_order_stats (dist_type='test_phase_freq').
        Returns {player_id: {'n': int, 'buckets': {innings_bucket: {phase_idx: float}}}}.
        Process-level cache; never queries history.deliveries.
        """
        cache_key = ('test_phase_freq_pc',)
        if cache_key in _PRECOMPUTED_CACHE:
            return _PRECOMPUTED_CACHE[cache_key]
        if not self.conn:
            _PRECOMPUTED_CACHE[cache_key] = {}
            return {}
        rows = self._run_query(
            "SELECT player_id, probs "
            "FROM history.bowler_order_stats "
            "WHERE match_format = 'Test' AND dist_type = 'test_phase_freq' "
            "AND match_type = 'all' AND inning_number = 0 "
            "AND venue_id IS NULL AND country IS NULL",
            (),
        )
        result: Dict[int, Dict] = {}
        for pid, probs in rows:
            if probs:
                # Convert string keys back to ints for buckets and phases
                buckets = {}
                for ib_str, phases in probs.get('buckets', {}).items():
                    buckets[int(ib_str)] = {int(ph): float(frac) for ph, frac in phases.items()}
                result[int(pid)] = {'n': int(probs.get('n', 0)), 'buckets': buckets}
        _PRECOMPUTED_CACHE[cache_key] = result
        return result

    def get_bowler_test_phase_frequency_precomputed(
        self, player_ids: List[int],
    ) -> Dict[int, Dict]:
        """
        Precomputed Test phase-frequency for the given player IDs.
        Returns {pid: {'n': int, 'buckets': {innings_bucket: {phase_idx: float}}}}.
        Never queries history.deliveries.
        """
        full = self._load_test_phase_freq_cache()
        pid_set = set(player_ids)
        return {pid: data for pid, data in full.items() if pid in pid_set}

    def get_batter_bowler_matchups_aggregate(
        self, batter_ids: List[int], bowler_ids: List[int], match_format: str
    ) -> Dict[Tuple, dict]:
        """Aggregate H2H scalars from precomputed matchups. Never queries deliveries."""
        all_ids = list(set(batter_ids) | set(bowler_ids))
        full = self._ensure_in_matchup_agg_cache(all_ids, match_format)
        b_set  = set(batter_ids)
        bw_set = set(bowler_ids)
        return {k: v for k, v in full.items() if k[0] in b_set and k[1] in bw_set}

    @classmethod
    def clear_cache(cls) -> int:
        """Clear the entire precomputed cache. Returns the number of entries removed.
        Safe to call at any time — lazy loading re-populates on next simulation."""
        count = len(_PRECOMPUTED_CACHE)
        _PRECOMPUTED_CACHE.clear()
        return count

    @classmethod
    def warm_all_caches(cls) -> None:
        """
        Pre-populate _PRECOMPUTED_CACHE for all formats and genders at server startup.
        After this runs, every init_model call in EnhancedStrategy and the bowling
        model returns from dict — no DB round-trip on any subsequent request.
        """
        import time
        repo = cls()
        if not repo.conn:
            return
        t0 = time.perf_counter()
        formats = ('T20', 'ODI', 'Test')
        genders = ('male', 'female')
        for fmt in formats:
            for gender in genders:
                repo._load_aggregate_cache(fmt, gender)
                repo.get_batter_milestone_distribution(fmt, gender)
                for st in (['batting', 'bowling']
                           + _PHASE_STAT_TYPES.get(fmt, [])
                           + _MILESTONE_STAT_TYPES):
                    repo._load_player_stat_cache(fmt, st)
            repo._load_workload_cache(fmt)
            repo._load_matchup_aggregate_cache(fmt)
        for fmt in ('T20', 'ODI'):
            for dist_type in ('over_freq', 'phase_dist'):
                repo._load_bowler_order_cache(fmt, dist_type)
        repo._load_test_phase_freq_cache()
        from simulator.logger import get_logger
        get_logger().warning("[StartupWarm] All caches loaded in %.2fs", time.perf_counter() - t0)

    def get_wicket_keepers(self, player_ids: List[int], gender: str = 'male') -> set:
        """Returns player_ids who are wicket-keepers, using precomputed roles."""
        if not player_ids or not self.conn:
            return set()
        roles = self._load_roles_cache()
        if roles:
            return {pid for pid in player_ids if roles.get(pid, {}).get('is_keeper', False)}
        query = """
        SELECT d.outcome_player_id
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.outcome_player_id = ANY(%s)
          AND m.gender = %s
          AND d.outcome_type = 'Wicket'
          AND d.outcome_kind = 'stumped'
        GROUP BY d.outcome_player_id
        HAVING COUNT(*) >= 3
        """
        rows = self._run_query(query, (player_ids, gender))
        return {r[0] for r in rows}

    def get_spinner_ids(self, bowler_ids: List[int], gender: str = 'male',
                        match_format: str = None) -> set:
        """Returns spinners from precomputed roles, falling back to delivery stumping counts."""
        if not bowler_ids or not self.conn:
            return set()
        roles = self._load_roles_cache()
        if roles:
            return {pid for pid in bowler_ids if roles.get(pid, {}).get('is_spinner', False)}
        format_filter = ""
        params: list = [bowler_ids, gender]
        if match_format:
            aliases = _FORMAT_ALIASES.get(match_format, [match_format])
            format_filter = "AND m.match_format = ANY(%s)"
            params.append(aliases)
        query = f"""
        SELECT d.bowler_id
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.bowler_id = ANY(%s)
          AND m.gender = %s
          {format_filter}
          AND d.outcome_type = 'Wicket'
          AND d.outcome_kind = 'stumped'
        GROUP BY d.bowler_id
        HAVING COUNT(*) >= 3
        """
        rows = self._run_query(query, tuple(params))
        return {r[0] for r in rows}

    def get_batter_death_stats(
        self, batter_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[str, float]]:
        """
        Returns {player_id: {'death_sr': float, 'boundary_rate': float, 'balls': int}}.
        Derived from precomputed player_outcome_stats death phases — zero deliveries access.
        Bulk-loaded once per process per (format, gender) and cached.
        """
        cache_key = ('batter_death_stats', match_format, gender)
        if cache_key not in _PRECOMPUTED_CACHE:
            death_phases = [t for t in ('phase_death1', 'phase_death2')
                            if t in _PHASE_STAT_TYPES.get(match_format, [])]
            merged: Dict[int, Dict[str, float]] = {}
            for st in death_phases:
                for pid, (probs, _, balls) in self._load_player_stat_cache(match_format, st).items():
                    if balls < 6 or not probs:
                        continue
                    non_extra_prob = sum(p for (rb, re, ot, _), p in probs.items() if ot != 'Extras')
                    if non_extra_prob <= 0:
                        continue
                    exp_rb = sum(rb * p for (rb, re, ot, _), p in probs.items())
                    death_sr = (exp_rb / non_extra_prob) * 100.0
                    boundary_rate = sum(p for (rb, re, ot, _), p in probs.items() if rb >= 4)
                    existing = merged.get(pid)
                    if existing is None or balls > existing['balls']:
                        merged[pid] = {'death_sr': death_sr, 'boundary_rate': boundary_rate, 'balls': balls}
            _PRECOMPUTED_CACHE[cache_key] = merged
        full = _PRECOMPUTED_CACHE[cache_key]
        return {pid: full[pid] for pid in batter_ids if pid in full}

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

    # Maps fine-grained phase stat_type keys → broad super-over phase names
    _SUPER_OVER_PHASE_MAP: Dict[str, str] = {
        'phase_pp1': 'powerplay', 'phase_pp2': 'powerplay',
        'phase_mid1': 'middle',   'phase_mid2': 'middle',   'phase_mid3': 'middle',
        'phase_new': 'middle',    'phase_early': 'middle',  'phase_late': 'middle',
        'phase_death1': 'death',  'phase_death2': 'death',
    }

    def get_bowler_phase_stats(
        self, bowler_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[str, Dict[str, float]]]:
        """
        Returns {player_id: {phase: {'economy': float, 'wicket_rate': float, 'balls': int}}}.
        Phases: 'powerplay', 'middle', 'death'.
        Derived from precomputed player_outcome_stats bowling-role phases — zero deliveries access.
        Bulk-loaded once per process per (format, gender) and cached.
        """
        cache_key = ('bowler_phase_stats', match_format, gender)
        if cache_key not in _PRECOMPUTED_CACHE:
            # Use the bowling stat type from player_outcome_stats to derive per-phase aggregates.
            # Economy = E[runs_batter + runs_extras] * 6; wicket_rate = P(Wicket).
            stat_types = _PHASE_STAT_TYPES.get(match_format, [])
            merged: Dict[int, Dict[str, Dict[str, float]]] = {}
            for st in stat_types:
                broad_phase = self._SUPER_OVER_PHASE_MAP.get(st)
                if not broad_phase:
                    continue
                for pid, (probs, _, balls) in self._load_player_stat_cache(match_format, st).items():
                    if balls < 6 or not probs:
                        continue
                    economy = sum((rb + re) * p for (rb, re, ot, _), p in probs.items()) * 6.0
                    wicket_rate = sum(p for (rb, re, ot, _), p in probs.items() if ot == 'Wicket')
                    existing = merged.setdefault(pid, {}).get(broad_phase)
                    if existing is None or balls > existing['balls']:
                        merged[pid][broad_phase] = {
                            'economy': economy, 'wicket_rate': wicket_rate, 'balls': balls,
                        }
            _PRECOMPUTED_CACHE[cache_key] = merged
        full = _PRECOMPUTED_CACHE[cache_key]
        return {pid: full[pid] for pid in bowler_ids if pid in full}

    def get_batter_bowler_matchups(
        self,
        batter_ids: List[int],
        bowler_ids: List[int],
        match_format: str,
        gender: str = 'male',
        match_ids: Optional[List[int]] = None,
    ) -> Dict[Tuple[int, int], Dict[str, float]]:
        """Returns {(batter_id, bowler_id): {'economy', 'wicket_rate', 'boundary_rate', 'dot_rate', 'balls'}}
        Only pairs with at least 6 historical balls are included.
        When match_ids is provided, restricts to those specific matches only.
        """
        if not batter_ids or not bowler_ids or not self.conn:
            return {}
        if match_ids:
            query = """
            SELECT
                d.batter_id, d.bowler_id,
                SUM(d.runs_batter + d.runs_extras) * 6.0 / NULLIF(COUNT(*), 0) AS economy,
                SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS wicket_rate,
                SUM(CASE WHEN d.runs_batter >= 4 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS boundary_rate,
                SUM(CASE WHEN d.runs_batter = 0 AND d.runs_extras = 0
                              AND d.outcome_type != 'Wicket' THEN 1 ELSE 0 END)::float
                    / NULLIF(COUNT(*), 0) AS dot_rate,
                COUNT(*) AS balls
            FROM history.deliveries d
            WHERE d.batter_id = ANY(%s) AND d.bowler_id = ANY(%s)
              AND d.match_id = ANY(%s)
            GROUP BY d.batter_id, d.bowler_id
            HAVING COUNT(*) >= 6
            """
            rows = self._run_query(query, (batter_ids, bowler_ids, match_ids))
        else:
            query = """
            SELECT
                d.batter_id, d.bowler_id,
                SUM(d.runs_batter + d.runs_extras) * 6.0 / NULLIF(COUNT(*), 0) AS economy,
                SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS wicket_rate,
                SUM(CASE WHEN d.runs_batter >= 4 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS boundary_rate,
                SUM(CASE WHEN d.runs_batter = 0 AND d.runs_extras = 0
                              AND d.outcome_type != 'Wicket' THEN 1 ELSE 0 END)::float
                    / NULLIF(COUNT(*), 0) AS dot_rate,
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
            (r[0], r[1]): {
                'economy':       float(r[2] or 0),
                'wicket_rate':   float(r[3] or 0),
                'boundary_rate': float(r[4] or 0),
                'dot_rate':      float(r[5] or 0),
                'balls':         int(r[6]),
            }
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

        NOTE: No live callers found — superseded by get_bowler_phase_dist_precomputed.
        Queries history.deliveries; do not call at simulation runtime.

        T20 phases  — 'powerplay_early' (ov 1-4), 'powerplay_late' (ov 5-6),
                       'middle' (ov 7-15), 'death_early' (ov 16-17), 'death_late' (ov 18-20)
        ODI phases  — 'powerplay' (ov 1-10), 'middle' (ov 11-39),
                       'death_early' (ov 40-43), 'death_late' (ov 44+)
        All formats — 'opening' (ov 1-2)

        Phase keys that don't apply to a format will be 0 (e.g. 'powerplay_early' is 0 for ODI).
        """
        _repo_log.warning("get_bowler_phase_frequency: no live callers — superseded by precomputed tables. Querying history.deliveries.")
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
        country: Optional[str] = None,
        countries: Optional[List[str]] = None,
        venue_id: Optional[int] = None,
        match_type: Optional[str] = None,
        inning_number: Optional[int] = None,
    ) -> Dict[int, Dict[int, float]]:
        """
        Per-bowler fraction of matches where they bowled in each over (T20) or
        5-over bin (ODI).

        T20:  key = over_number  (0-indexed, 0–19, one bin per over)
        ODI:  key = over_number // 5  (0-indexed, 0–9, one bin per 5 overs)

        Scope (highest priority wins):
          venue_id  — restrict to a specific venue.
          countries — restrict to venues in any of these countries (list).
          country   — convenience alias for countries=[country].
        match_type: when provided (e.g. 'international'), restricts to that match_type only.
        inning_number: when provided (1 or 2), restricts to that innings only.
        Returns {player_id: {key: fraction}} — sparse (only keys with data present).
        """
        if not bowler_ids or not self.conn:
            return {}
        unified = match_format
        if unified not in ('T20', 'ODI'):
            return {}

        raw_fmts = self._raw_formats(unified)

        if venue_id is not None:
            loc_join   = ""
            loc_filter = "AND m.venue_id = %s"
            loc_param: Optional[object] = venue_id
        elif countries or country:
            c_list     = countries if countries else [country]
            loc_join   = "JOIN history.venues v ON m.venue_id = v.venue_id"
            loc_filter = "AND v.country = ANY(%s)"
            loc_param  = c_list
        else:
            loc_join   = ""
            loc_filter = ""
            loc_param  = None

        match_type_filter = "AND m.match_type = %s"    if match_type        else ""
        inning_filter     = "AND d.inning_number = %s" if inning_number is not None else ""

        if unified == 'T20':
            key_expr    = "d.over_number"
            over_filter = "AND d.over_number BETWEEN 0 AND 19"
        else:
            key_expr    = "d.over_number / 5"
            over_filter = "AND d.over_number BETWEEN 0 AND 49"

        total_matches_sql = f"""
            SELECT mp.player_id, COUNT(DISTINCT mp.match_id) AS n
            FROM history.match_players mp
            JOIN history.matches m ON mp.match_id = m.match_id
            {loc_join}
            WHERE mp.player_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {loc_filter}
              {match_type_filter}
            GROUP BY mp.player_id"""

        total_params = [bowler_ids, raw_fmts, gender]
        if loc_param  is not None: total_params.append(loc_param)
        if match_type:             total_params.append(match_type)

        key_params = [bowler_ids, raw_fmts, gender]
        if loc_param  is not None:     key_params.append(loc_param)
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
            {loc_join}
            WHERE d.bowler_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {loc_filter}
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
        NOTE: No live callers found. Queries history.deliveries; do not call at simulation runtime.
        """
        _repo_log.warning("get_bowler_venue_stats: no live callers — queries history.deliveries.")
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
        NOTE: No live callers found. Queries history.deliveries; do not call at simulation runtime.
        """
        _repo_log.warning("get_bowler_country_stats: no live callers — queries history.deliveries.")
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
        NOTE: No live callers found. Queries history.deliveries; do not call at simulation runtime.
        """
        _repo_log.warning("get_bowler_recent_form: no live callers — queries history.deliveries.")
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
        countries: Optional[List[str]] = None,
        venue_id: Optional[int] = None,
    ) -> Dict[int, Dict]:
        """
        Returns {player_id: {'n': int, 'buckets': {innings_bucket: {phase_idx: float}}}}
        for Test cricket. No minimum-match threshold — callers blend with a global prior.

        innings_bucket 1 = match innings 1 or 2 (first innings of each team).
        innings_bucket 2 = match innings 3 or 4 (second innings of each team).
        Phases 0-7 map to ball-age windows of 10 overs each within an 80-over
        new-ball cycle: 0→overs 0-9, 1→10-19, ..., 7→70-79.

        Scope (highest priority wins):
          venue_id  — restrict to a specific venue (most granular, sparsest).
          countries — restrict to venues in any of these countries (list); use for
                      regional grouping e.g. West Indies islands under one pool.
          country   — convenience alias for countries=[country].
        `n` is total matches the player participated in within the chosen scope.
        """
        if not player_ids or not self.conn:
            return {}

        if venue_id is not None:
            loc_join   = ""
            loc_filter = "AND m.venue_id = %s"
            loc_param: Optional[object] = venue_id
        elif countries or country:
            c_list     = countries if countries else [country]
            loc_join   = "JOIN history.venues v ON m.venue_id = v.venue_id"
            loc_filter = "AND v.country = ANY(%s)"
            loc_param  = c_list
        else:
            loc_join   = ""
            loc_filter = ""
            loc_param  = None

        raw_fmts = self._raw_formats("Test")
        query = f"""
        WITH total_matches AS (
            SELECT mp.player_id, COUNT(DISTINCT mp.match_id) AS n
            FROM history.match_players mp
            JOIN history.matches m ON mp.match_id = m.match_id
            {loc_join}
            WHERE mp.player_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {loc_filter}
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
            {loc_join}
            WHERE d.bowler_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
              {loc_filter}
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
        half = [player_ids, raw_fmts, gender]
        if loc_param is not None:
            half.append(loc_param)
        rows = self._run_query(query, tuple(half + half))

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
        """Like get_batters_distribution but also returns {player_id: (probs, effective_ball_count)}."""
        if not batter_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = f"""
        SELECT d.batter_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
               SUM({_D5Y})
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
        """Like get_bowlers_distribution but also returns {player_id: (probs, effective_ball_count)}."""
        if not bowler_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = f"""
        SELECT d.bowler_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
               SUM({_D5Y})
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
        cache_key = ('milestone_global', match_format, gender)
        if cache_key in _PRECOMPUTED_CACHE:
            return _PRECOMPUTED_CACHE[cache_key]
        agg = self._load_aggregate_cache(match_format, gender)
        if agg:
            prefix = 'milestone_'
            result = {k[len(prefix):]: v for k, v in agg.items() if k.startswith(prefix)}
            if result:
                _PRECOMPUTED_CACHE[cache_key] = result
                return result
        if not self.conn:
            _PRECOMPUTED_CACHE[cache_key] = {}
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
        _PRECOMPUTED_CACHE[cache_key] = result
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
        self,
        match_format: str,
        gender: str = 'male',
        sample_size: int = 5000,
        venue_id: Optional[int] = None,
    ) -> List[tuple]:
        """
        Returns up to sample_size random deliveries with full context for model validation.

        Each row:
          (batter_id, bowler_id, venue_id, inning_number, over_number, tournament_id,
           runs_batter, runs_extras, outcome_type, outcome_kind,
           batter_score_before, team_score_before, team_wickets_before)

        batter_score_before  — batter's runs in this innings before this delivery (window fn).
        team_score_before    — team's total runs before this delivery (window fn).
        team_wickets_before  — team's wickets fallen before this delivery (window fn).
        These last two allow pressure-proxy classification without a target lookup.

        venue_id: when set, restricts sample to that venue (for context-specific testing).
        """
        if not self.conn:
            return []
        raw_fmts = self._raw_formats(match_format)
        venue_filter = "AND m.venue_id = %s" if venue_id is not None else ""
        query = f"""
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
                ) AS batter_score_before,
                COALESCE(
                    SUM(d.runs_batter + d.runs_extras) OVER (
                        PARTITION BY d.match_id, d.inning_number
                        ORDER BY d.over_number, d.ball_number
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
                ) AS team_score_before,
                COALESCE(
                    SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END) OVER (
                        PARTITION BY d.match_id, d.inning_number
                        ORDER BY d.over_number, d.ball_number
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
                ) AS team_wickets_before
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s {venue_filter}
        )
        SELECT batter_id, bowler_id, venue_id, inning_number, over_number, tournament_id,
               runs_batter, runs_extras, outcome_type, outcome_kind,
               batter_score_before, team_score_before, team_wickets_before
        FROM delivery_running
        ORDER BY RANDOM()
        LIMIT %s
        """
        params = [raw_fmts, gender]
        if venue_id is not None:
            params.append(venue_id)
        params.append(sample_size)
        return self._run_query(query, params)

    def get_player_historical_profile(
        self,
        player_id: int,
        match_format: str,
        gender: str = 'male',
    ) -> List[tuple]:
        """
        Returns every delivery faced by a batter, with context for
        phase / milestone / bowler-type bucketing.

        Each row: (over_number, runs_batter, outcome_type,
                   batter_score_before, bowler_career_balls)

        bowler_career_balls is the bowler's total ball count across ALL
        matches in this format — same metric used by _PARTTIME_THRESHOLDS.
        """
        if not self.conn:
            return []
        raw_fmts = self._raw_formats(match_format)
        return self._run_query("""
            WITH bowler_career AS (
                SELECT d2.bowler_id, COUNT(*) AS career_balls
                FROM history.deliveries d2
                JOIN history.matches m2 ON d2.match_id = m2.match_id
                WHERE m2.match_format = ANY(%s) AND m2.gender = %s
                GROUP BY d2.bowler_id
            )
            SELECT
                d.over_number,
                d.runs_batter,
                d.outcome_type,
                COALESCE(SUM(d.runs_batter) OVER (
                    PARTITION BY d.batter_id, d.match_id, d.inning_number
                    ORDER BY d.over_number, d.ball_number
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ), 0) AS batter_score_before,
                COALESCE(bc.career_balls, 0) AS bowler_career_balls
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            LEFT JOIN bowler_career bc ON bc.bowler_id = d.bowler_id
            WHERE d.batter_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
        """, (raw_fmts, gender, player_id, raw_fmts, gender))

    def get_player_recent_matches(
        self,
        player_id: int,
        match_format: str,
        gender: str = 'male',
        limit: int = 20,
    ) -> List[tuple]:
        """
        Returns recent matches a player appeared in, ordered newest first.
        Each row: (match_id, venue_id, venue_name, venue_country,
                   home_team_id, away_team_id, date)
        """
        if not self.conn:
            return []
        raw_fmts = self._raw_formats(match_format)
        return self._run_query("""
            SELECT DISTINCT mp.match_id, m.venue_id, v.name, v.country,
                   m.home_team_id, m.away_team_id, m.date
            FROM history.match_players mp
            JOIN history.matches m  ON mp.match_id = m.match_id
            JOIN history.venues  v  ON m.venue_id  = v.venue_id
            WHERE mp.player_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
            ORDER BY m.date DESC
            LIMIT %s
        """, (player_id, raw_fmts, gender, limit))

    def get_match_lineup(self, match_id: int) -> List[tuple]:
        """
        Returns the full roster for a match ordered by batting position.
        Each row: (team_id, team_name, player_id, player_name)
        Players who never batted appear last (ordered by player_id).
        """
        if not self.conn:
            return []
        return self._run_query("""
            SELECT mp.team_id, t.name, mp.player_id, p.name
            FROM history.match_players mp
            JOIN history.players p ON mp.player_id = p.player_id
            JOIN history.teams   t ON mp.team_id   = t.team_id
            LEFT JOIN (
                SELECT player_id, batting_team_id,
                       MIN((inning_number * 10000 + over_number * 100 + ball_number) * 2 + role)
                           AS sort_key
                FROM (
                    SELECT batter_id     AS player_id, batting_team_id,
                           inning_number, over_number, ball_number, 0 AS role
                    FROM history.deliveries WHERE match_id = %s
                    UNION ALL
                    SELECT non_striker_id AS player_id, batting_team_id,
                           inning_number, over_number, ball_number, 1 AS role
                    FROM history.deliveries WHERE match_id = %s
                ) appearances
                GROUP BY player_id, batting_team_id
            ) fb ON fb.player_id = mp.player_id AND fb.batting_team_id = mp.team_id
            WHERE mp.match_id = %s
            ORDER BY mp.team_id, COALESCE(fb.sort_key, 999999999), mp.player_id
        """, (match_id, match_id, match_id))

    def get_bowler_career_balls(
        self,
        player_ids: List[int],
        match_format: str,
        gender: str = 'male',
    ) -> Dict[int, int]:
        """
        Returns career ball counts (as bowler) for the given player IDs.
        Used to classify genuine vs part-time bowlers in simulation tracking.
        """
        if not self.conn or not player_ids:
            return {}
        raw_fmts = self._raw_formats(match_format)
        rows = self._run_query("""
            SELECT d.bowler_id, COUNT(*) AS career_balls
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE d.bowler_id = ANY(%s)
              AND m.match_format = ANY(%s)
              AND m.gender = %s
            GROUP BY d.bowler_id
        """, (player_ids, raw_fmts, gender))
        return {pid: int(cnt) for pid, cnt in rows}

    def _load_player_country_stats_cache(self, match_format: str) -> Dict[Tuple, Tuple]:
        """Bulk-load player_context_stats for country context; keyed by (player_id, country)."""
        cache_key = ('pcs_country', match_format)
        if cache_key in _PRECOMPUTED_CACHE:
            return _PRECOMPUTED_CACHE[cache_key]
        if not self.conn:
            _PRECOMPUTED_CACHE[cache_key] = {}
            return {}
        rows = self._run_query(
            "SELECT player_id, country, probs_raw, probs_era, ball_count "
            "FROM history.player_context_stats "
            "WHERE match_format = %s AND context_type = 'country'",
            (match_format,),
        )
        result: Dict[Tuple, tuple] = {}
        for pid, country, raw_j, era_j, count in rows:
            raw = _json_to_prob_dict(raw_j)
            if raw:
                result[(int(pid), country)] = (raw, _json_to_prob_dict(era_j), int(count))
        _PRECOMPUTED_CACHE[cache_key] = result
        return result

    def _load_aggregate_cache(self, match_format: str, gender: str) -> Dict[str, Any]:
        """Bulk-load history.aggregate_stats for a format/gender; cached at process level.

        Most keys store outcome-probability dicts decoded by _json_to_prob_dict.
        'fielding_counts' is stored raw as {str(player_id): count} and kept as-is.
        """
        cache_key = ('agg', match_format, gender)
        if cache_key in _PRECOMPUTED_CACHE:
            return _PRECOMPUTED_CACHE[cache_key]
        if not self.conn:
            _PRECOMPUTED_CACHE[cache_key] = {}
            return {}
        rows = self._run_query(
            "SELECT stat_key, probs FROM history.aggregate_stats WHERE match_format = %s AND gender = %s",
            (match_format, gender),
        )
        result: Dict[str, Any] = {}
        for row in rows:
            stat_key, raw_json = row[0], row[1]
            if stat_key == 'fielding_counts':
                result[stat_key] = raw_json  # already a dict {str: int}
            else:
                probs = _json_to_prob_dict(raw_json)
                if probs:
                    result[stat_key] = probs
        _PRECOMPUTED_CACHE[cache_key] = result
        return result

    def get_full_aggregate_distribution(self, match_format: str, gender: str = 'male') -> Dict[Tuple, float]:
        """
        Overall delivery outcome probability distribution across all deliveries for this format.
        Used as the baseline anchor in the enhanced strategy — derived from raw counts rather
        than by averaging per-innings distributions.
        """
        agg = self._load_aggregate_cache(match_format, gender)
        if agg and 'baseline' in agg:
            return agg['baseline']
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
        agg = self._load_aggregate_cache(match_format, gender)
        if agg:
            result = {k[len('phase_'):]: v for k, v in agg.items() if k.startswith('phase_')}
            if result:
                return result
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
               d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
               SUM({_D5Y})
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
        cache_key = ('fielding', match_format, gender)
        if cache_key in _PRECOMPUTED_CACHE:
            return _PRECOMPUTED_CACHE[cache_key]
        agg = self._load_aggregate_cache(match_format, gender)
        if agg and 'fielding_counts' in agg:
            result = {int(pid): int(cnt) for pid, cnt in agg['fielding_counts'].items()}
            _PRECOMPUTED_CACHE[cache_key] = result
            return result
        if not self.conn:
            _PRECOMPUTED_CACHE[cache_key] = {}
            return {}
        query = """
        SELECT d.outcome_player_id, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s AND d.outcome_type = 'Wicket' AND d.outcome_player_id IS NOT NULL
        GROUP BY d.outcome_player_id
        """
        rows = self._run_query(query, (self._raw_formats(match_format), gender))
        result = {r[0]: r[1] for r in rows}
        _PRECOMPUTED_CACHE[cache_key] = result
        return result

    def get_batter_phase_distribution(
        self, batter_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Tuple[Dict[int, Dict[str, Dict[Tuple, float]]], Dict[int, Dict[str, int]]]:
        """
        Per-batter, per-phase outcome distributions using time-decayed ball weights.
        Returns (phase_dists, phase_ball_counts):
          phase_dists       = {batter_id: {phase: {outcome_key: prob}}}
          phase_ball_counts = {batter_id: {phase: approx_ball_count}}
        NOTE: No live callers found — superseded by get_batter_phase_probs_precomputed.
        Queries history.deliveries; do not call at simulation runtime.
        """
        _repo_log.warning("get_batter_phase_distribution: no live callers — superseded by precomputed tables. Querying history.deliveries.")
        if not batter_ids or not self.conn:
            return {}, {}
        raw_fmts = self._raw_formats(match_format)
        query = f"""
        SELECT d.batter_id, d.over_number,
               d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
               SUM({_D5Y})
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.batter_id = ANY(%s) AND m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY d.batter_id, d.over_number,
                 d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (batter_ids, raw_fmts, gender))

        # Accumulate weighted counts per (batter_id, phase, outcome_key)
        acc: Dict[int, Dict[str, Dict[tuple, float]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(float))
        )
        for batter_id, over_num, r_bat, r_ext, out_type, out_kind, weight in rows:
            phase = _fine_grained_phase(over_num, match_format)
            acc[batter_id][phase][(r_bat, r_ext, out_type, out_kind)] += weight

        phase_dists: Dict[int, Dict[str, Dict[Tuple, float]]] = {}
        phase_ball_counts: Dict[int, Dict[str, int]] = {}
        for batter_id, phases in acc.items():
            phase_dists[batter_id] = {}
            phase_ball_counts[batter_id] = {}
            for phase, outcome_counts in phases.items():
                total = sum(outcome_counts.values())
                if total > 0:
                    phase_dists[batter_id][phase] = {k: v / total for k, v in outcome_counts.items()}
                    phase_ball_counts[batter_id][phase] = int(round(total))

        return phase_dists, phase_ball_counts

    # ── Era normalization — per-year raw count queries ────────────────────────

    def get_global_yearly_baseline(
        self, match_format: str, gender: str = 'male',
        use_precomputed: bool = True,
    ) -> Dict[int, Dict[Tuple, float]]:
        """
        Returns {year: {outcome_key: probability}} — the global outcome distribution
        per calendar year. Used as the era denominator in era normalization.

        When use_precomputed=True (default), reads from history.global_yearly_baseline
        (populated by db/precompute.py). Falls back to computing from raw deliveries
        if the table is empty or use_precomputed=False.
        NOTE: No live callers found in simulation or API code.
        """
        _repo_log.warning("get_global_yearly_baseline: no live callers — use precompute.py directly.")
        if not self.conn:
            return {}

        if use_precomputed:
            # Map raw format aliases (e.g. "IT20") to the canonical name used in the table
            unified = next((k for k, vs in _FORMAT_ALIASES.items() if match_format in vs), match_format)
            query = """
            SELECT year, runs_batter, runs_extras, outcome_type, outcome_kind, probability
            FROM history.global_yearly_baseline
            WHERE match_format = %s AND gender = %s
            ORDER BY year
            """
            rows = self._run_query(query, (unified, gender))
            if rows:
                result: Dict[int, Dict[Tuple, float]] = {}
                for row in rows:
                    year = int(row[0])
                    key  = (row[1], row[2], row[3], row[4])
                    if year not in result:
                        result[year] = {}
                    result[year][key] = float(row[5])
                return result

        # Fallback: compute from raw deliveries (slow on large datasets)
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT EXTRACT(YEAR FROM m.date)::INTEGER AS year,
               d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
               COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s AND m.date IS NOT NULL
        GROUP BY year, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        ORDER BY year
        """
        rows = self._run_query(query, (raw_fmts, gender))
        year_counts: Dict[int, Dict[Tuple, int]] = defaultdict(lambda: defaultdict(int))
        for row in rows:
            year_counts[int(row[0])][(row[1], row[2], row[3], row[4])] += int(row[5])
        result = {}
        for year, counts in year_counts.items():
            total = sum(counts.values())
            if total > 0:
                result[year] = {k: v / total for k, v in counts.items()}
        return result

    def get_matchup_distribution_per_year(
        self,
        batter_ids: List[int],
        bowler_ids: List[int],
        match_format: str,
        gender: str = 'male',
        min_balls: int = 12,
    ) -> Dict[Tuple[int, int], Dict[int, Dict[Tuple, int]]]:
        """
        Per-year raw delivery counts for qualified batter-bowler pairs.
        Only pairs with total >= min_balls (across all years) are included.
        Returns {(batter_id, bowler_id): {year: {outcome_key: count}}}.
        NOTE: No live callers found. Used by precompute.py logic only.
        """
        _repo_log.warning("get_matchup_distribution_per_year: no live callers — queries history.deliveries.")
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
               EXTRACT(YEAR FROM m.date)::INTEGER AS year,
               d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        JOIN qualified_pairs qp ON d.batter_id = qp.batter_id AND d.bowler_id = qp.bowler_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s AND m.date IS NOT NULL
        GROUP BY d.batter_id, d.bowler_id, year,
                 d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (batter_ids, bowler_ids, raw_fmts, gender, min_balls, raw_fmts, gender))
        result: Dict[Tuple, Dict[int, Dict[Tuple, int]]] = {}
        for row in rows:
            pair = (row[0], row[1])
            year = int(row[2])
            key  = (row[3], row[4], row[5], row[6])
            cnt  = int(row[7])
            if pair not in result:
                result[pair] = {}
            if year not in result[pair]:
                result[pair][year] = {}
            result[pair][year][key] = result[pair][year].get(key, 0) + cnt
        return result

    def get_batters_distribution_per_year(
        self, batter_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[int, Dict[Tuple, int]]]:
        """
        Per-year raw delivery counts for each batter.
        Returns {batter_id: {year: {outcome_key: count}}}.
        NOTE: No live callers found. Used by precompute.py logic only.
        """
        _repo_log.warning("get_batters_distribution_per_year: no live callers — queries history.deliveries.")
        if not batter_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT d.batter_id, EXTRACT(YEAR FROM m.date)::INTEGER AS year,
               d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.batter_id = ANY(%s) AND m.match_format = ANY(%s) AND m.gender = %s
          AND m.date IS NOT NULL
        GROUP BY d.batter_id, year,
                 d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (batter_ids, raw_fmts, gender))
        result: Dict[int, Dict[int, Dict[Tuple, int]]] = {}
        for row in rows:
            pid  = row[0]
            year = int(row[1])
            key  = (row[2], row[3], row[4], row[5])
            cnt  = int(row[6])
            if pid not in result:
                result[pid] = {}
            if year not in result[pid]:
                result[pid][year] = {}
            result[pid][year][key] = result[pid][year].get(key, 0) + cnt
        return result

    def get_bowlers_distribution_per_year(
        self, bowler_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[int, Dict[Tuple, int]]]:
        """
        Per-year raw delivery counts for each bowler.
        Returns {bowler_id: {year: {outcome_key: count}}}.
        NOTE: No live callers found. Used by precompute.py logic only.
        """
        _repo_log.warning("get_bowlers_distribution_per_year: no live callers — queries history.deliveries.")
        if not bowler_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT d.bowler_id, EXTRACT(YEAR FROM m.date)::INTEGER AS year,
               d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.bowler_id = ANY(%s) AND m.match_format = ANY(%s) AND m.gender = %s
          AND m.date IS NOT NULL
        GROUP BY d.bowler_id, year,
                 d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (bowler_ids, raw_fmts, gender))
        result: Dict[int, Dict[int, Dict[Tuple, int]]] = {}
        for row in rows:
            pid  = row[0]
            year = int(row[1])
            key  = (row[2], row[3], row[4], row[5])
            cnt  = int(row[6])
            if pid not in result:
                result[pid] = {}
            if year not in result[pid]:
                result[pid][year] = {}
            result[pid][year][key] = result[pid][year].get(key, 0) + cnt
        return result

    def get_batter_phase_distribution_per_year(
        self, batter_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[str, Dict[int, Dict[Tuple, int]]]]:
        """
        Per-batter, per-phase, per-year raw delivery counts.
        Returns {batter_id: {phase: {year: {outcome_key: count}}}}.
        NOTE: No live callers found. Used by precompute.py logic only.
        """
        _repo_log.warning("get_batter_phase_distribution_per_year: no live callers — queries history.deliveries.")
        if not batter_ids or not self.conn:
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
        else:
            phase_expr = """
            CASE
                WHEN d.over_number <= 10 THEN 'new'
                WHEN d.over_number <= 30 THEN 'early'
                WHEN d.over_number <= 80 THEN 'middle'
                ELSE 'late'
            END"""
        query = f"""
        SELECT d.batter_id, {phase_expr} AS phase,
               EXTRACT(YEAR FROM m.date)::INTEGER AS year,
               d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.batter_id = ANY(%s) AND m.match_format = ANY(%s) AND m.gender = %s
          AND m.date IS NOT NULL
        GROUP BY d.batter_id, phase, year,
                 d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (batter_ids, raw_fmts, gender))
        result: Dict[int, Dict[str, Dict[int, Dict[Tuple, int]]]] = {}
        for row in rows:
            pid   = row[0]
            phase = row[1]
            year  = int(row[2])
            key   = (row[3], row[4], row[5], row[6])
            cnt   = int(row[7])
            if pid not in result:
                result[pid] = {}
            if phase not in result[pid]:
                result[pid][phase] = {}
            if year not in result[pid][phase]:
                result[pid][phase][year] = {}
            result[pid][phase][year][key] = result[pid][phase][year].get(key, 0) + cnt
        return result

    def get_player_venue_distribution_per_year(
        self, player_ids: List[int], venue_id: int, match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[int, Dict[Tuple, int]]]:
        """
        Per-player, per-year raw delivery counts at a specific venue.
        Returns {player_id: {year: {outcome_key: count}}}.
        NOTE: No live callers found. Used by precompute.py logic only.
        """
        _repo_log.warning("get_player_venue_distribution_per_year: no live callers — queries history.deliveries.")
        if not player_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        SELECT d.batter_id, EXTRACT(YEAR FROM m.date)::INTEGER AS year,
               d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.batter_id = ANY(%s) AND m.venue_id = %s
          AND m.match_format = ANY(%s) AND m.gender = %s AND m.date IS NOT NULL
        GROUP BY d.batter_id, year,
                 d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        """
        rows = self._run_query(query, (player_ids, venue_id, raw_fmts, gender))
        result: Dict[int, Dict[int, Dict[Tuple, int]]] = {}
        for row in rows:
            pid  = row[0]
            year = int(row[1])
            key  = (row[2], row[3], row[4], row[5])
            cnt  = int(row[6])
            if pid not in result:
                result[pid] = {}
            if year not in result[pid]:
                result[pid][year] = {}
            result[pid][year][key] = result[pid][year].get(key, 0) + cnt
        return result

    def get_player_milestone_distributions_per_year(
        self, player_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[str, Dict[int, Dict[Tuple, int]]]]:
        """
        Per-player, per-milestone (10-run bucket), per-year raw delivery counts.
        Returns {player_id: {milestone: {year: {outcome_key: count}}}}.
        NOTE: No live callers found. Used by precompute.py logic only.
        """
        _repo_log.warning("get_player_milestone_distributions_per_year: no live callers — queries history.deliveries.")
        if not player_ids or not self.conn:
            return {}
        raw_fmts = self._raw_formats(match_format)
        query = """
        WITH delivery_running AS (
            SELECT
                d.batter_id,
                d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                m.date,
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
              AND d.batter_id = ANY(%s) AND m.date IS NOT NULL
        )
        SELECT
            batter_id,
            CASE
                WHEN score_before >= 100 THEN 'm100'
                ELSE 'm' || ((score_before / 10) * 10)::text
            END AS milestone,
            EXTRACT(YEAR FROM date)::INTEGER AS year,
            runs_batter, runs_extras, outcome_type, outcome_kind,
            COUNT(*) AS cnt
        FROM delivery_running
        GROUP BY batter_id, milestone, year,
                 runs_batter, runs_extras, outcome_type, outcome_kind
        """
        rows = self._run_query(query, (raw_fmts, gender, player_ids))
        result: Dict[int, Dict[str, Dict[int, Dict[Tuple, int]]]] = {}
        for row in rows:
            pid       = row[0]
            milestone = row[1]
            year      = int(row[2])
            key       = (row[3], row[4], row[5], row[6])
            cnt       = int(row[7])
            if pid not in result:
                result[pid] = {}
            if milestone not in result[pid]:
                result[pid][milestone] = {}
            if year not in result[pid][milestone]:
                result[pid][milestone][year] = {}
            result[pid][milestone][year][key] = result[pid][milestone][year].get(key, 0) + cnt
        return result

    # ── Precomputed read paths ─────────────────────────────────────────────────

    def _load_player_stat_cache(self, match_format: str, stat_type: str) -> Dict[int, tuple]:
        """Full load of all players for a (format, stat_type) pair. Used by warm_all_caches."""
        full_key = ('pos', match_format, stat_type)
        done_key = ('pos_all_loaded', match_format, stat_type)
        if _PRECOMPUTED_CACHE.get(done_key):
            return _PRECOMPUTED_CACHE.get(full_key, {})
        if not self.conn:
            _PRECOMPUTED_CACHE[full_key] = {}
            _PRECOMPUTED_CACHE[done_key] = True
            return {}
        rows = self._run_query(
            "SELECT player_id, probs_raw, probs_era, ball_count "
            "FROM history.player_outcome_stats "
            "WHERE match_format = %s AND stat_type = %s",
            (match_format, stat_type),
        )
        result: Dict[int, tuple] = _PRECOMPUTED_CACHE.get(full_key, {})
        for row in rows:
            pid, raw_json, era_json, count = row[0], row[1], row[2], row[3]
            raw = _json_to_prob_dict(raw_json)
            if raw:
                result[int(pid)] = (raw, _json_to_prob_dict(era_json), int(count))
        _PRECOMPUTED_CACHE[full_key] = result
        _PRECOMPUTED_CACHE[done_key] = True
        return result

    def _ensure_in_stat_cache(self, player_ids: List[int], match_format: str, stat_type: str) -> Dict[int, tuple]:
        """Lazy-load player_outcome_stats for specific players only. Merges into existing cache."""
        full_key = ('pos', match_format, stat_type)
        done_key = ('pos_all_loaded', match_format, stat_type)
        if _PRECOMPUTED_CACHE.get(done_key):
            return _PRECOMPUTED_CACHE.get(full_key, {})
        if not player_ids or not self.conn:
            return _PRECOMPUTED_CACHE.get(full_key, {})
        loaded_key = ('pos_loaded_pids', match_format, stat_type)
        loaded_pids: set = _PRECOMPUTED_CACHE.get(loaded_key, set())
        missing = [pid for pid in player_ids if pid not in loaded_pids]
        if not missing:
            return _PRECOMPUTED_CACHE.get(full_key, {})
        rows = self._run_query(
            "SELECT player_id, probs_raw, probs_era, ball_count "
            "FROM history.player_outcome_stats "
            "WHERE match_format = %s AND stat_type = %s AND player_id = ANY(%s)",
            (match_format, stat_type, missing),
        )
        dest = _PRECOMPUTED_CACHE.setdefault(full_key, {})
        for row in rows:
            pid, raw_json, era_json, count = row[0], row[1], row[2], row[3]
            raw = _json_to_prob_dict(raw_json)
            if raw:
                dest[int(pid)] = (raw, _json_to_prob_dict(era_json), int(count))
        loaded_pids.update(missing)
        _PRECOMPUTED_CACHE[loaded_key] = loaded_pids
        return dest

    def get_batters_probs_precomputed(
        self, batter_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Tuple]:
        """
        Returns {player_id: (probs_raw, probs_era, ball_count)} from precomputed table.
        probs_era is None for Test or when era data wasn't computed.
        Falls back to decay-weighted distribution if the precomputed table is empty.
        """
        cached = self._ensure_in_stat_cache(batter_ids, match_format, 'batting')
        if cached:
            return {pid: cached[pid] for pid in batter_ids if pid in cached}
        data = self.get_batters_distribution_with_counts(batter_ids, match_format, gender)
        return {pid: (probs, None, count) for pid, (probs, count) in data.items()}

    def get_bowlers_probs_precomputed(
        self, bowler_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Tuple]:
        """
        Returns {player_id: (probs_raw, probs_era, ball_count)} from precomputed table.
        Falls back to decay-weighted distribution if the precomputed table is empty.
        """
        cached = self._ensure_in_stat_cache(bowler_ids, match_format, 'bowling')
        if cached:
            return {pid: cached[pid] for pid in bowler_ids if pid in cached}
        data = self.get_bowlers_distribution_with_counts(bowler_ids, match_format, gender)
        return {pid: (probs, None, count) for pid, (probs, count) in data.items()}

    def get_batter_phase_probs_precomputed(
        self, batter_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[str, Tuple]]:
        """
        Returns {player_id: {phase: (probs_raw, probs_era, ball_count)}}.
        Phase keys use the short form without 'phase_' prefix (e.g. 'pp1', 'mid1').
        Falls back to the decay-weighted phase query if precomputed table is empty.
        """
        stat_types = _PHASE_STAT_TYPES.get(match_format, [])
        if not stat_types:
            return {}

        result: Dict[int, Dict[str, tuple]] = {}
        any_data = False
        for st in stat_types:
            cached = self._ensure_in_stat_cache(batter_ids, match_format, st)
            if cached:
                any_data = True
                phase = st[len('phase_'):]
                for pid in batter_ids:
                    if pid in cached:
                        result.setdefault(pid, {})[phase] = cached[pid]

        if any_data:
            return result

        phase_dists, phase_counts = self.get_batter_phase_distribution(batter_ids, match_format, gender)
        fb: Dict[int, Dict[str, tuple]] = {}
        for pid in batter_ids:
            if pid in phase_dists:
                fb[pid] = {
                    phase: (probs, None, phase_counts.get(pid, {}).get(phase, 0))
                    for phase, probs in phase_dists[pid].items()
                }
        return fb

    def get_player_milestone_probs_precomputed(
        self, player_ids: List[int], match_format: str, gender: str = 'male'
    ) -> Dict[int, Dict[str, Tuple]]:
        """
        Returns {player_id: {milestone: (probs_raw, probs_era, ball_count)}}.
        Milestone keys use the short form without 'milestone_' prefix (e.g. 'm0', 'm10').
        Falls back to the raw milestone query if the precomputed table is empty.
        """
        result: Dict[int, Dict[str, tuple]] = {}
        any_data = False
        for st in _MILESTONE_STAT_TYPES:
            cached = self._ensure_in_stat_cache(player_ids, match_format, st)
            if cached:
                any_data = True
                milestone = st[len('milestone_'):]
                for pid in player_ids:
                    if pid in cached:
                        result.setdefault(pid, {})[milestone] = cached[pid]

        if any_data:
            return result

        raw_dists = self.get_player_milestone_distributions(player_ids, match_format, gender)
        return {pid: {m: (probs, None, 0) for m, probs in milestones.items()}
                for pid, milestones in raw_dists.items()}

    def get_matchup_probs_precomputed(
        self,
        batter_ids: List[int],
        bowler_ids: List[int],
        match_format: str,
        gender: str = 'male',
    ) -> Dict[Tuple[int, int], Tuple]:
        """
        Returns {(batter_id, bowler_id): (probs_raw, probs_era, ball_count)}.
        Queries batter_bowler_matchups for the requested pairs directly.
        When the table is populated for this format, pairs not present simply have no
        qualifying head-to-head data — returns empty dict rather than falling back to
        a full deliveries scan.  Only falls back when the table itself is empty
        (i.e. precompute.py hasn't been run yet).
        """
        if not batter_ids or not bowler_ids or not self.conn:
            return {}

        table_key = ('matchup_table_populated', match_format)
        if table_key not in _PRECOMPUTED_CACHE:
            check = self._run_query(
                "SELECT 1 FROM history.batter_bowler_matchups WHERE match_format = %s LIMIT 1",
                (match_format,),
            )
            _PRECOMPUTED_CACHE[table_key] = bool(check)

        rows = self._run_query(
            "SELECT batter_id, bowler_id, probs_raw, probs_era, ball_count "
            "FROM history.batter_bowler_matchups "
            "WHERE match_format = %s AND batter_id = ANY(%s) AND bowler_id = ANY(%s)",
            (match_format, batter_ids, bowler_ids),
        )
        if rows or _PRECOMPUTED_CACHE[table_key]:
            result: Dict[Tuple[int, int], tuple] = {}
            for row in rows:
                bid, bowid, raw_j, era_j, count = row
                raw = _json_to_prob_dict(raw_j)
                if raw:
                    result[(int(bid), int(bowid))] = (raw, _json_to_prob_dict(era_j), int(count))
            return result

        if match_format != 'Test':
            per_year = self.get_matchup_distribution_per_year(
                batter_ids, bowler_ids, match_format, gender
            )
            fb: Dict[Tuple[int, int], tuple] = {}
            for pair, py in per_year.items():
                raw = _decay_weight_per_year(py, 5.0)
                total = sum(sum(y.values()) for y in py.values())
                if raw:
                    fb[pair] = (raw, None, total)
            return fb

        data = self.get_matchup_distribution_with_counts(
            batter_ids, bowler_ids, match_format, gender
        )
        return {pair: (probs, None, count) for pair, (probs, count) in data.items()}

    def get_player_venue_probs_precomputed(
        self, player_ids: List[int], venue_id: int, match_format: str, gender: str = 'male'
    ) -> Dict[int, Tuple]:
        """
        Returns {player_id: (probs_raw, probs_era, ball_count)} from precomputed table.
        Caches per venue so subsequent matches at the same venue are zero-query.
        Falls back to the decay-weighted venue query if precomputed table is empty.
        """
        cache_key = ('pcs_venue', match_format, venue_id)
        if cache_key not in _PRECOMPUTED_CACHE:
            if not self.conn:
                _PRECOMPUTED_CACHE[cache_key] = {}
            else:
                rows = self._run_query(
                    "SELECT player_id, probs_raw, probs_era, ball_count "
                    "FROM history.player_context_stats "
                    "WHERE match_format = %s AND context_type = 'venue' AND venue_id = %s",
                    (match_format, venue_id),
                )
                cached: Dict[int, tuple] = {}
                for row in rows:
                    pid, raw_j, era_j, count = row
                    raw = _json_to_prob_dict(raw_j)
                    if raw:
                        cached[int(pid)] = (raw, _json_to_prob_dict(era_j), int(count))
                _PRECOMPUTED_CACHE[cache_key] = cached

        cached = _PRECOMPUTED_CACHE[cache_key]
        if cached:
            return {pid: cached[pid] for pid in player_ids if pid in cached}

        raw_venue = self.get_player_venue_distribution(player_ids, venue_id, match_format, gender)
        return {pid: (probs, None, count) for pid, (probs, count) in raw_venue.items()}
