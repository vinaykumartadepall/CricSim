"""
Precomputed tables for the cricket simulator.

Populates:
  history.global_yearly_baseline     — per-year global outcome distribution (era denominator)
  history.player_outcome_stats       — batting/bowling/phase/milestone distributions per player
  history.player_context_stats       — per-player venue and country distributions
  history.batter_bowler_matchups     — head-to-head pair distributions
  history.bowler_order_stats         — per-bowler over-frequency and phase-overs distributions
  history.player_scalar_stats        — career, workload, death-over, phase, role scalars
  history.aggregate_stats            — format-level baseline, phase, innings, position distributions
  history.venue_stats                — venue-level distributions
  history.country_stats              — country-level distributions
  history.tournament_outcome_stats   — tournament-level distributions

Usage:
    python -m db.precompute                  # Full rebuild of all tables
    python -m db.precompute --current-year-only   # Only refresh current year in global_yearly_baseline
    python -m db.precompute --dry-run        # Print row counts, no writes
    python -m db.precompute --tables player  # Rebuild only player_outcome_stats + related tables
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from db.database import get_db_connection

_FORMATS = ["T20", "ODI", "Test"]
_GENDERS  = ["male", "female"]
_HALF_LIFE_PLAYER  = 5.0   # batter/bowler/phase/milestone/matchup/venue
_HALF_LIFE_VENUE   = 7.0   # venue aggregate
_HALF_LIFE_COUNTRY = 8.0   # country aggregate
_HALF_LIFE_TOURN   = 3.0   # tournament

_FORMAT_ALIASES: Dict[str, List[str]] = {
    "Test": ["Test", "MDM"],
    "ODI":  ["ODI",  "ODM", "ONE DAY"],
    "T20":  ["T20",  "IT20"],
}

_MATCHUP_MIN_BALLS = 12


# ── JSONB encoding helpers ─────────────────────────────────────────────────────

def _key_str(rb: int, re: int, ot: str, ok: Optional[str]) -> str:
    return f"{rb}|{re}|{ot}|{ok or ''}"


def _probs_to_jsonb(probs: Dict[Tuple, float]) -> Dict[str, float]:
    return {_key_str(rb, re, ot, ok): v for (rb, re, ot, ok), v in probs.items()}


# ── Era normalization (mirrors strategy._era_normalize_probs) ─────────────────

def _era_normalize(
    per_year_counts: Dict[int, Dict[Tuple, int]],
    global_yearly_baseline: Dict[int, Dict[Tuple, float]],
    current_baseline: Dict[Tuple, float],
    half_life: float = _HALF_LIFE_PLAYER,
) -> Optional[Dict[Tuple, float]]:
    current_year = date.today().year
    total_weight = 0.0
    weighted_ratio: Dict[Tuple, float] = {}

    for year, year_counts in per_year_counts.items():
        global_year = global_yearly_baseline.get(year)
        if not global_year:
            continue
        year_total = sum(year_counts.values())
        if year_total == 0:
            continue
        age = max(0, current_year - year)
        decay = math.exp(-math.log(2) / half_life * age)
        for key in current_baseline:
            player_prob = year_counts.get(key, 0) / year_total
            global_prob = global_year.get(key, 0.0)
            if global_prob < 1e-9:
                continue
            weighted_ratio[key] = weighted_ratio.get(key, 0.0) + decay * (player_prob / global_prob)
        total_weight += decay

    if total_weight < 1e-9:
        return None
    result: Dict[Tuple, float] = {}
    for key, bp in current_baseline.items():
        ratio = weighted_ratio.get(key, 0.0) / total_weight
        result[key] = bp * ratio
    total = sum(result.values())
    if total < 1e-9:
        return None
    return {k: v / total for k, v in result.items()}


def _decay_weighted_probs(
    per_year_counts: Dict[int, Dict[Tuple, int]],
    half_life: float = _HALF_LIFE_PLAYER,
) -> Optional[Dict[Tuple, float]]:
    """Decay-weighted probability distribution from per-year counts (probs_raw)."""
    current_year = date.today().year
    weighted: Dict[Tuple, float] = defaultdict(float)
    total_w = 0.0
    for year, year_counts in per_year_counts.items():
        age = max(0, current_year - year)
        decay = math.exp(-math.log(2) / half_life * age)
        for key, cnt in year_counts.items():
            weighted[key] += decay * cnt
        total_w += decay * sum(year_counts.values())
    if total_w < 1e-9:
        return None
    return {k: v / total_w for k, v in weighted.items()}


def _total_balls(per_year_counts: Dict[int, Dict[Tuple, int]]) -> int:
    return sum(sum(yc.values()) for yc in per_year_counts.values())


# ── Reference data loaders ─────────────────────────────────────────────────────

def _load_global_baseline(
    conn, fmt: str, gender: str
) -> Dict[int, Dict[Tuple, float]]:
    """Load history.global_yearly_baseline for era normalization."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT year, runs_batter, runs_extras, outcome_type, outcome_kind, probability
            FROM history.global_yearly_baseline
            WHERE match_format = %s AND gender = %s
            """,
            (fmt, gender),
        )
        rows = cur.fetchall()
    result: Dict[int, Dict[Tuple, float]] = {}
    for row in rows:
        year = int(row[0])
        key: Tuple = (row[1], row[2], row[3], row[4])
        result.setdefault(year, {})[key] = float(row[5])
    return result


def _load_aggregate_baseline(conn, fmt: str, gender: str) -> Dict[Tuple, float]:
    """
    Compute the raw aggregate outcome distribution (no decay) used as the era
    normalization baseline. This is the same as get_full_aggregate_distribution.
    """
    raw_fmts = _FORMAT_ALIASES[fmt]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender),
        )
        rows = cur.fetchall()
    total = sum(r[4] for r in rows)
    if total == 0:
        return {}
    return {(r[0], r[1], r[2], r[3]): r[4] / total for r in rows}


# ── Upsert helpers ─────────────────────────────────────────────────────────────

def _upsert_player_outcome_stats(
    conn, rows: list, dry_run: bool
) -> int:
    """rows: list of (player_id, match_format, stat_type, probs_raw_json, probs_era_json, ball_count)"""
    if dry_run:
        print(f"    [dry-run] would write {len(rows)} rows to player_outcome_stats")
        return len(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        import psycopg2.extras
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO history.player_outcome_stats
                (player_id, match_format, stat_type, probs_raw, probs_era, ball_count)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
            ON CONFLICT (player_id, match_format, stat_type) DO UPDATE
                SET probs_raw = EXCLUDED.probs_raw,
                    probs_era = EXCLUDED.probs_era,
                    ball_count = EXCLUDED.ball_count,
                    computed_at = now()
            """,
            rows,
            page_size=500,
        )
    conn.commit()
    return len(rows)


def _upsert_matchups(conn, rows: list, dry_run: bool) -> int:
    if dry_run:
        print(f"    [dry-run] would write {len(rows)} matchup rows")
        return len(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        import psycopg2.extras
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO history.batter_bowler_matchups
                (batter_id, bowler_id, match_format, probs_raw, probs_era, ball_count)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
            ON CONFLICT (batter_id, bowler_id, match_format) DO UPDATE
                SET probs_raw = EXCLUDED.probs_raw,
                    probs_era = EXCLUDED.probs_era,
                    ball_count = EXCLUDED.ball_count,
                    computed_at = now()
            """,
            rows,
            page_size=500,
        )
    conn.commit()
    return len(rows)


def _upsert_player_context(conn, rows: list, dry_run: bool) -> int:
    if dry_run:
        print(f"    [dry-run] would write {len(rows)} player_context_stats rows")
        return len(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        import psycopg2.extras
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO history.player_context_stats
                (player_id, match_format, context_type, venue_id, country,
                 probs_raw, probs_era, ball_count)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            ON CONFLICT DO NOTHING
            """,
            rows,
            page_size=500,
        )
        # Handle conflict by updating
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO history.player_context_stats
                (player_id, match_format, context_type, venue_id, country,
                 probs_raw, probs_era, ball_count)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            ON CONFLICT (player_id, match_format, context_type,
                         (COALESCE(venue_id, -1)), (COALESCE(country, '')))
            DO UPDATE SET
                probs_raw = EXCLUDED.probs_raw,
                probs_era = EXCLUDED.probs_era,
                ball_count = EXCLUDED.ball_count,
                computed_at = now()
            """,
            rows,
            page_size=500,
        )
    conn.commit()
    return len(rows)


def _upsert_scalar(conn, rows: list, dry_run: bool) -> int:
    if dry_run:
        print(f"    [dry-run] would write {len(rows)} player_scalar_stats rows")
        return len(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        import psycopg2.extras
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO history.player_scalar_stats
                (player_id, match_format, stat_type, data)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (player_id, match_format, stat_type) DO UPDATE
                SET data = EXCLUDED.data,
                    computed_at = now()
            """,
            rows,
            page_size=500,
        )
    conn.commit()
    return len(rows)


def _upsert_aggregate(conn, rows: list, dry_run: bool) -> int:
    if dry_run:
        print(f"    [dry-run] would write {len(rows)} aggregate_stats rows")
        return len(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        import psycopg2.extras
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO history.aggregate_stats (match_format, gender, stat_key, probs)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (match_format, gender, stat_key) DO UPDATE
                SET probs = EXCLUDED.probs,
                    computed_at = now()
            """,
            rows,
            page_size=200,
        )
    conn.commit()
    return len(rows)


def _upsert_venue_stats(conn, rows: list, dry_run: bool) -> int:
    if dry_run:
        print(f"    [dry-run] would write {len(rows)} venue_stats rows")
        return len(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        import psycopg2.extras
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO history.venue_stats (venue_id, match_format, gender, probs, ball_count)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (venue_id, match_format, gender) DO UPDATE
                SET probs = EXCLUDED.probs,
                    ball_count = EXCLUDED.ball_count,
                    computed_at = now()
            """,
            rows,
            page_size=200,
        )
    conn.commit()
    return len(rows)


def _upsert_country_stats(conn, rows: list, dry_run: bool) -> int:
    if dry_run:
        print(f"    [dry-run] would write {len(rows)} country_stats rows")
        return len(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        import psycopg2.extras
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO history.country_stats (country, match_format, gender, probs, ball_count)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (country, match_format, gender) DO UPDATE
                SET probs = EXCLUDED.probs,
                    ball_count = EXCLUDED.ball_count,
                    computed_at = now()
            """,
            rows,
            page_size=200,
        )
    conn.commit()
    return len(rows)


def _upsert_tournament_stats(conn, rows: list, dry_run: bool) -> int:
    if dry_run:
        print(f"    [dry-run] would write {len(rows)} tournament_outcome_stats rows")
        return len(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        import psycopg2.extras
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO history.tournament_outcome_stats (tournament_id, probs, ball_count)
            VALUES (%s, %s::jsonb, %s)
            ON CONFLICT (tournament_id) DO UPDATE
                SET probs = EXCLUDED.probs,
                    ball_count = EXCLUDED.ball_count,
                    computed_at = now()
            """,
            rows,
            page_size=200,
        )
    conn.commit()
    return len(rows)


def _upsert_bowler_order(conn, rows: list, dry_run: bool) -> int:
    if dry_run:
        print(f"    [dry-run] would write {len(rows)} bowler_order_stats rows")
        return len(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        import psycopg2.extras
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO history.bowler_order_stats
                (player_id, match_format, dist_type, match_type, inning_number,
                 venue_id, country, probs)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT DO NOTHING
            """,
            rows,
            page_size=500,
        )
    conn.commit()
    return len(rows)


# ── Per-format phase expression helpers ───────────────────────────────────────

def _phase_case(fmt: str) -> str:
    if fmt == 'T20':
        return """
        CASE
            WHEN d.over_number <= 3  THEN 'pp1'
            WHEN d.over_number <= 6  THEN 'pp2'
            WHEN d.over_number <= 11 THEN 'mid1'
            WHEN d.over_number <= 15 THEN 'mid2'
            WHEN d.over_number <= 17 THEN 'death1'
            ELSE 'death2'
        END"""
    if fmt == 'ODI':
        return """
        CASE
            WHEN d.over_number <= 5  THEN 'pp1'
            WHEN d.over_number <= 10 THEN 'pp2'
            WHEN d.over_number <= 20 THEN 'mid1'
            WHEN d.over_number <= 30 THEN 'mid2'
            WHEN d.over_number <= 40 THEN 'mid3'
            WHEN d.over_number <= 45 THEN 'death1'
            ELSE 'death2'
        END"""
    return """
        CASE
            WHEN d.over_number <= 10 THEN 'new'
            WHEN d.over_number <= 30 THEN 'early'
            WHEN d.over_number <= 80 THEN 'middle'
            ELSE 'late'
        END"""


# ═══════════════════════════════════════════════════════════════════════════════
# populate_global_yearly_baseline — existing logic, unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_global_yearly_baseline(
    conn,
    unified_format: str,
    gender: str,
    year_filter: int | None = None,
) -> Dict[int, Dict[Tuple, float]]:
    raw_fmts = _FORMAT_ALIASES[unified_format]
    params: list = [raw_fmts, gender]
    year_clause = ""
    if year_filter is not None:
        year_clause = "AND EXTRACT(YEAR FROM m.date) = %s"
        params.append(year_filter)
    query = f"""
    SELECT EXTRACT(YEAR FROM m.date)::INTEGER AS year,
           d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
           COUNT(*) AS cnt
    FROM history.deliveries d
    JOIN history.matches m ON d.match_id = m.match_id
    WHERE m.match_format = ANY(%s) AND m.gender = %s AND m.date IS NOT NULL
    {year_clause}
    GROUP BY year, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
    ORDER BY year
    """
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    year_counts: Dict[int, Dict[Tuple, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        year_counts[int(row[0])][(row[1], row[2], row[3], row[4])] += int(row[5])
    result: Dict[int, Dict[Tuple, float]] = {}
    for year, counts in year_counts.items():
        total = sum(counts.values())
        if total > 0:
            result[year] = {k: v / total for k, v in counts.items()}
    return result


def _upsert_global_yearly_baseline(
    conn, unified_format: str, gender: str,
    data: Dict[int, Dict[Tuple, float]], year_filter: int | None, dry_run: bool,
) -> int:
    rows_to_insert = []
    for year, dist in data.items():
        for (runs_batter, runs_extras, outcome_type, outcome_kind), prob in dist.items():
            rows_to_insert.append((year, unified_format, gender, runs_batter, runs_extras, outcome_type, outcome_kind, prob))
    if dry_run:
        print(f"  [dry-run] {unified_format}/{gender}: would write {len(rows_to_insert)} rows ({len(data)} years)")
        return len(rows_to_insert)
    with conn.cursor() as cur:
        if year_filter is not None:
            cur.execute("DELETE FROM history.global_yearly_baseline WHERE match_format = %s AND gender = %s AND year = %s", (unified_format, gender, year_filter))
        else:
            cur.execute("DELETE FROM history.global_yearly_baseline WHERE match_format = %s AND gender = %s", (unified_format, gender))
        if rows_to_insert:
            args = ",".join(cur.mogrify("(%s,%s,%s,%s,%s,%s,%s,%s)", r).decode() for r in rows_to_insert)
            cur.execute(f"INSERT INTO history.global_yearly_baseline (year,match_format,gender,runs_batter,runs_extras,outcome_type,outcome_kind,probability) VALUES {args}")
    conn.commit()
    print(f"  {unified_format}/{gender}: wrote {len(rows_to_insert)} rows ({len(data)} years)")
    return len(rows_to_insert)


def populate_global_yearly_baseline(current_year_only: bool = False, dry_run: bool = False) -> None:
    year_filter = date.today().year if current_year_only else None
    label = f"year={year_filter}" if year_filter else "all years"
    print(f"\nPopulating history.global_yearly_baseline ({label}) ...")
    conn = get_db_connection(autocommit=False)
    try:
        total = 0
        for fmt in _FORMATS:
            for gender in _GENDERS:
                t0 = time.perf_counter()
                data = _compute_global_yearly_baseline(conn, fmt, gender, year_filter)
                print(f"  Computed {fmt}/{gender}: {len(data)} years  ({time.perf_counter()-t0:.1f}s)")
                total += _upsert_global_yearly_baseline(conn, fmt, gender, data, year_filter, dry_run)
    finally:
        conn.close()
    print(f"Done. Total rows: {total}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# player_outcome_stats: batting + bowling
# ═══════════════════════════════════════════════════════════════════════════════

def _populate_batting_bowling(
    conn, fmt: str, gender: str,
    global_baseline: Dict[int, Dict[Tuple, float]],
    agg_baseline: Dict[Tuple, float],
    dry_run: bool,
) -> int:
    raw_fmts = _FORMAT_ALIASES[fmt]
    print(f"  batting/bowling {fmt}/{gender} ...", end=" ", flush=True)
    t0 = time.perf_counter()

    # Per-year counts for batting
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.batter_id,
                   EXTRACT(YEAR FROM m.date)::INTEGER AS year,
                   d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                   COUNT(*) AS cnt
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
              AND m.date IS NOT NULL AND d.batter_id IS NOT NULL
            GROUP BY d.batter_id, year,
                     d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender),
        )
        bat_rows = cur.fetchall()

    bat_per_year: Dict[int, Dict[int, Dict[Tuple, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for row in bat_rows:
        pid, year, rb, re, ot, ok, cnt = row[0], int(row[1]), row[2], row[3], row[4], row[5], int(row[6])
        bat_per_year[pid][year][(rb, re, ot, ok)] += cnt

    # Per-year counts for bowling
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.bowler_id,
                   EXTRACT(YEAR FROM m.date)::INTEGER AS year,
                   d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                   COUNT(*) AS cnt
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
              AND m.date IS NOT NULL AND d.bowler_id IS NOT NULL
            GROUP BY d.bowler_id, year,
                     d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender),
        )
        bowl_rows = cur.fetchall()

    bowl_per_year: Dict[int, Dict[int, Dict[Tuple, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for row in bowl_rows:
        pid, year, rb, re, ot, ok, cnt = row[0], int(row[1]), row[2], row[3], row[4], row[5], int(row[6])
        bowl_per_year[pid][year][(rb, re, ot, ok)] += cnt

    era_ok = (fmt != 'Test') and bool(global_baseline) and bool(agg_baseline)

    insert_rows = []
    for pid, py_data in bat_per_year.items():
        raw = _decay_weighted_probs(py_data)
        if not raw:
            continue
        era = _era_normalize(py_data, global_baseline, agg_baseline) if era_ok else None
        balls = _total_balls(py_data)
        insert_rows.append((
            pid, fmt, 'batting',
            json.dumps(_probs_to_jsonb(raw)),
            json.dumps(_probs_to_jsonb(era)) if era else None,
            balls,
        ))

    for pid, py_data in bowl_per_year.items():
        raw = _decay_weighted_probs(py_data)
        if not raw:
            continue
        era = _era_normalize(py_data, global_baseline, agg_baseline) if era_ok else None
        balls = _total_balls(py_data)
        insert_rows.append((
            pid, fmt, 'bowling',
            json.dumps(_probs_to_jsonb(raw)),
            json.dumps(_probs_to_jsonb(era)) if era else None,
            balls,
        ))

    count = _upsert_player_outcome_stats(conn, insert_rows, dry_run)
    print(f"{len(bat_per_year)} batters, {len(bowl_per_year)} bowlers → {count} rows  ({time.perf_counter()-t0:.1f}s)")
    return count


# ═══════════════════════════════════════════════════════════════════════════════
# player_outcome_stats: phase distributions
# ═══════════════════════════════════════════════════════════════════════════════

def _populate_phase_stats(
    conn, fmt: str, gender: str,
    global_baseline: Dict[int, Dict[Tuple, float]],
    agg_baseline: Dict[Tuple, float],
    dry_run: bool,
) -> int:
    raw_fmts = _FORMAT_ALIASES[fmt]
    phase_expr = _phase_case(fmt)
    print(f"  phase {fmt}/{gender} ...", end=" ", flush=True)
    t0 = time.perf_counter()

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT d.batter_id,
                   {phase_expr} AS phase,
                   EXTRACT(YEAR FROM m.date)::INTEGER AS year,
                   d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                   COUNT(*) AS cnt
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
              AND m.date IS NOT NULL AND d.batter_id IS NOT NULL
            GROUP BY d.batter_id, phase, year,
                     d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender),
        )
        rows = cur.fetchall()

    # group: pid → phase → year → outcome_key → count
    acc: Dict[int, Dict[str, Dict[int, Dict[Tuple, int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    )
    for row in rows:
        pid, phase, year, rb, re, ot, ok, cnt = row[0], row[1], int(row[2]), row[3], row[4], row[5], row[6], int(row[7])
        acc[pid][phase][year][(rb, re, ot, ok)] += cnt

    era_ok = (fmt != 'Test') and bool(global_baseline) and bool(agg_baseline)
    insert_rows = []
    for pid, phases in acc.items():
        for phase, py_data in phases.items():
            raw = _decay_weighted_probs(py_data)
            if not raw:
                continue
            era = _era_normalize(py_data, global_baseline, agg_baseline) if era_ok else None
            balls = _total_balls(py_data)
            insert_rows.append((
                pid, fmt, f'phase_{phase}',
                json.dumps(_probs_to_jsonb(raw)),
                json.dumps(_probs_to_jsonb(era)) if era else None,
                balls,
            ))

    count = _upsert_player_outcome_stats(conn, insert_rows, dry_run)
    print(f"{len(acc)} batters → {count} rows  ({time.perf_counter()-t0:.1f}s)")
    return count


# ═══════════════════════════════════════════════════════════════════════════════
# player_outcome_stats: milestone distributions
# ═══════════════════════════════════════════════════════════════════════════════

def _populate_milestone_stats(
    conn, fmt: str, gender: str,
    global_baseline: Dict[int, Dict[Tuple, float]],
    agg_baseline: Dict[Tuple, float],
    dry_run: bool,
) -> int:
    raw_fmts = _FORMAT_ALIASES[fmt]
    print(f"  milestones {fmt}/{gender} ...", end=" ", flush=True)
    t0 = time.perf_counter()

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH running AS (
                SELECT
                    d.batter_id,
                    d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                    m.date,
                    COALESCE(SUM(d.runs_batter) OVER (
                        PARTITION BY d.batter_id, d.match_id, d.inning_number
                        ORDER BY d.over_number, d.ball_number
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0) AS score_before
                FROM history.deliveries d
                JOIN history.matches m ON d.match_id = m.match_id
                WHERE m.match_format = ANY(%s) AND m.gender = %s
                  AND m.date IS NOT NULL AND d.batter_id IS NOT NULL
            )
            SELECT
                batter_id,
                CASE WHEN score_before >= 100 THEN 'm100'
                     ELSE 'm' || ((score_before / 10) * 10)::text
                END AS milestone,
                EXTRACT(YEAR FROM date)::INTEGER AS year,
                runs_batter, runs_extras, outcome_type, outcome_kind,
                COUNT(*) AS cnt
            FROM running
            GROUP BY batter_id, milestone, year,
                     runs_batter, runs_extras, outcome_type, outcome_kind
            """,
            (raw_fmts, gender),
        )
        rows = cur.fetchall()

    acc: Dict[int, Dict[str, Dict[int, Dict[Tuple, int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    )
    for row in rows:
        pid, ms, year, rb, re, ot, ok, cnt = row[0], row[1], int(row[2]), row[3], row[4], row[5], row[6], int(row[7])
        acc[pid][ms][year][(rb, re, ot, ok)] += cnt

    era_ok = (fmt != 'Test') and bool(global_baseline) and bool(agg_baseline)
    insert_rows = []
    for pid, milestones in acc.items():
        for ms, py_data in milestones.items():
            if _total_balls(py_data) < 20:
                continue  # too sparse — strategy will use global milestone fallback
            raw = _decay_weighted_probs(py_data)
            if not raw:
                continue
            era = _era_normalize(py_data, global_baseline, agg_baseline) if era_ok else None
            balls = _total_balls(py_data)
            insert_rows.append((
                pid, fmt, f'milestone_{ms}',
                json.dumps(_probs_to_jsonb(raw)),
                json.dumps(_probs_to_jsonb(era)) if era else None,
                balls,
            ))

    count = _upsert_player_outcome_stats(conn, insert_rows, dry_run)
    print(f"{len(acc)} batters → {count} rows  ({time.perf_counter()-t0:.1f}s)")
    return count


# ═══════════════════════════════════════════════════════════════════════════════
# batter_bowler_matchups
# ═══════════════════════════════════════════════════════════════════════════════

def _populate_matchups(
    conn, fmt: str, gender: str,
    global_baseline: Dict[int, Dict[Tuple, float]],
    agg_baseline: Dict[Tuple, float],
    dry_run: bool,
) -> int:
    raw_fmts = _FORMAT_ALIASES[fmt]
    print(f"  matchups {fmt}/{gender} ...", end=" ", flush=True)
    t0 = time.perf_counter()

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH qualified AS (
                SELECT d.batter_id, d.bowler_id
                FROM history.deliveries d
                JOIN history.matches m ON d.match_id = m.match_id
                WHERE m.match_format = ANY(%s) AND m.gender = %s
                  AND d.batter_id IS NOT NULL AND d.bowler_id IS NOT NULL
                GROUP BY d.batter_id, d.bowler_id
                HAVING COUNT(*) >= %s
            )
            SELECT d.batter_id, d.bowler_id,
                   EXTRACT(YEAR FROM m.date)::INTEGER AS year,
                   d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                   COUNT(*) AS cnt
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            JOIN qualified q ON d.batter_id = q.batter_id AND d.bowler_id = q.bowler_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s AND m.date IS NOT NULL
            GROUP BY d.batter_id, d.bowler_id, year,
                     d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender, _MATCHUP_MIN_BALLS, raw_fmts, gender),
        )
        rows = cur.fetchall()

    # group: (batter_id, bowler_id) → year → outcome_key → count
    acc: Dict[Tuple[int,int], Dict[int, Dict[Tuple, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    for row in rows:
        bid, bowid, year, rb, re, ot, ok, cnt = row[0], row[1], int(row[2]), row[3], row[4], row[5], row[6], int(row[7])
        acc[(bid, bowid)][year][(rb, re, ot, ok)] += cnt

    era_ok = (fmt != 'Test') and bool(global_baseline) and bool(agg_baseline)
    insert_rows = []
    for (bid, bowid), py_data in acc.items():
        raw = _decay_weighted_probs(py_data)
        if not raw:
            continue
        era = _era_normalize(py_data, global_baseline, agg_baseline) if era_ok else None
        balls = _total_balls(py_data)
        insert_rows.append((
            bid, bowid, fmt,
            json.dumps(_probs_to_jsonb(raw)),
            json.dumps(_probs_to_jsonb(era)) if era else None,
            balls,
        ))

    count = _upsert_matchups(conn, insert_rows, dry_run)
    print(f"{len(acc)} pairs → {count} rows  ({time.perf_counter()-t0:.1f}s)")
    return count


# ═══════════════════════════════════════════════════════════════════════════════
# player_context_stats: venue
# ═══════════════════════════════════════════════════════════════════════════════

def _populate_player_venue_stats(
    conn, fmt: str, gender: str,
    global_baseline: Dict[int, Dict[Tuple, float]],
    agg_baseline: Dict[Tuple, float],
    dry_run: bool,
) -> int:
    raw_fmts = _FORMAT_ALIASES[fmt]
    print(f"  player_venue {fmt}/{gender} ...", end=" ", flush=True)
    t0 = time.perf_counter()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.batter_id, m.venue_id,
                   EXTRACT(YEAR FROM m.date)::INTEGER AS year,
                   d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                   COUNT(*) AS cnt
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
              AND m.date IS NOT NULL AND d.batter_id IS NOT NULL AND m.venue_id IS NOT NULL
            GROUP BY d.batter_id, m.venue_id, year,
                     d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender),
        )
        rows = cur.fetchall()

    # group: (player_id, venue_id) → year → outcome_key → count
    acc: Dict[Tuple[int,int], Dict[int, Dict[Tuple, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    for row in rows:
        pid, vid, year, rb, re, ot, ok, cnt = row[0], row[1], int(row[2]), row[3], row[4], row[5], row[6], int(row[7])
        acc[(pid, vid)][year][(rb, re, ot, ok)] += cnt

    era_ok = (fmt != 'Test') and bool(global_baseline) and bool(agg_baseline)
    insert_rows = []
    for (pid, vid), py_data in acc.items():
        if _total_balls(py_data) < 6:
            continue
        raw = _decay_weighted_probs(py_data, _HALF_LIFE_PLAYER)
        if not raw:
            continue
        era = _era_normalize(py_data, global_baseline, agg_baseline) if era_ok else None
        balls = _total_balls(py_data)
        insert_rows.append((
            pid, fmt, 'venue', vid, None,
            json.dumps(_probs_to_jsonb(raw)),
            json.dumps(_probs_to_jsonb(era)) if era else None,
            balls,
        ))

    count = _upsert_player_context(conn, insert_rows, dry_run)
    print(f"{len(acc)} player-venue pairs → {count} rows  ({time.perf_counter()-t0:.1f}s)")
    return count


def _populate_player_country_stats(
    conn, fmt: str, gender: str,
    global_baseline: Dict[int, Dict[Tuple, float]],
    agg_baseline: Dict[Tuple, float],
    dry_run: bool,
) -> int:
    raw_fmts = _FORMAT_ALIASES[fmt]
    print(f"  player_country {fmt}/{gender} ...", end=" ", flush=True)
    t0 = time.perf_counter()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.batter_id, v.country,
                   EXTRACT(YEAR FROM m.date)::INTEGER AS year,
                   d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                   COUNT(*) AS cnt
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            JOIN history.venues  v ON m.venue_id = v.venue_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
              AND m.date IS NOT NULL AND d.batter_id IS NOT NULL AND v.country IS NOT NULL
            GROUP BY d.batter_id, v.country, year,
                     d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender),
        )
        rows = cur.fetchall()

    # group: (player_id, country) → year → outcome_key → count
    acc: Dict[Tuple, Dict[int, Dict[Tuple, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    for row in rows:
        pid, country, year, rb, re, ot, ok, cnt = row[0], row[1], int(row[2]), row[3], row[4], row[5], row[6], int(row[7])
        acc[(pid, country)][year][(rb, re, ot, ok)] += cnt

    era_ok = (fmt != 'Test') and bool(global_baseline) and bool(agg_baseline)
    insert_rows = []
    for (pid, country), py_data in acc.items():
        if _total_balls(py_data) < 12:
            continue
        raw = _decay_weighted_probs(py_data, _HALF_LIFE_PLAYER)
        if not raw:
            continue
        era = _era_normalize(py_data, global_baseline, agg_baseline) if era_ok else None
        balls = _total_balls(py_data)
        insert_rows.append((
            pid, fmt, 'country', None, country,
            json.dumps(_probs_to_jsonb(raw)),
            json.dumps(_probs_to_jsonb(era)) if era else None,
            balls,
        ))

    count = _upsert_player_context(conn, insert_rows, dry_run)
    print(f"{len(acc)} player-country pairs → {count} rows  ({time.perf_counter()-t0:.1f}s)")
    return count


# ═══════════════════════════════════════════════════════════════════════════════
# aggregate_stats: baseline + phase + innings + position
# ═══════════════════════════════════════════════════════════════════════════════

def _populate_aggregate_stats(conn, fmt: str, gender: str, dry_run: bool) -> int:
    raw_fmts = _FORMAT_ALIASES[fmt]
    print(f"  aggregate {fmt}/{gender} ...", end=" ", flush=True)
    t0 = time.perf_counter()

    insert_rows = []

    # Baseline (no decay — raw counts)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender),
        )
        rows = cur.fetchall()
    total = sum(r[4] for r in rows)
    if total > 0:
        probs = {(r[0], r[1], r[2], r[3]): r[4] / total for r in rows}
        insert_rows.append((fmt, gender, 'baseline', json.dumps(_probs_to_jsonb(probs))))

    # Phase distributions (decay _D5Y approximation via per-year)
    # Use a simpler no-decay count for aggregate phase data
    phase_expr = _phase_case(fmt)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {phase_expr} AS phase,
                   d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY phase, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender),
        )
        rows = cur.fetchall()
    phase_acc: Dict[str, Dict[Tuple, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        phase_acc[row[0]][(row[1], row[2], row[3], row[4])] += int(row[5])
    for phase, counts in phase_acc.items():
        total = sum(counts.values())
        if total > 0:
            probs = {k: v / total for k, v in counts.items()}
            insert_rows.append((fmt, gender, f'phase_{phase}', json.dumps(_probs_to_jsonb(probs))))

    # Innings distributions
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.inning_number, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY d.inning_number, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender),
        )
        rows = cur.fetchall()
    inn_acc: Dict[int, Dict[Tuple, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        inn_acc[int(row[0])][(row[1], row[2], row[3], row[4])] += int(row[5])
    for inn_num, counts in inn_acc.items():
        total = sum(counts.values())
        if total > 0:
            probs = {k: v / total for k, v in counts.items()}
            insert_rows.append((fmt, gender, f'innings_{inn_num}', json.dumps(_probs_to_jsonb(probs))))

    # Batting position baseline
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH first_ball AS (
                SELECT d.match_id, d.inning_number, d.batter_id,
                       MIN(d.over_number * 1000 + d.ball_number) AS first_key
                FROM history.deliveries d
                JOIN history.matches m ON d.match_id = m.match_id
                WHERE m.match_format = ANY(%s) AND m.gender = %s
                GROUP BY d.match_id, d.inning_number, d.batter_id
            ),
            batter_pos AS (
                SELECT match_id, inning_number, batter_id,
                       RANK() OVER (PARTITION BY match_id, inning_number ORDER BY first_key) AS pos
                FROM first_ball
            )
            SELECT
                CASE WHEN bp.pos <= 3 THEN 'top_order'
                     WHEN bp.pos <= 6 THEN 'middle_order'
                     ELSE 'lower_order' END AS grp,
                d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            JOIN batter_pos bp ON bp.match_id = d.match_id AND bp.inning_number = d.inning_number AND bp.batter_id = d.batter_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY grp, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender, raw_fmts, gender),
        )
        rows = cur.fetchall()
    pos_acc: Dict[str, Dict[Tuple, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        pos_acc[row[0]][(row[1], row[2], row[3], row[4])] += int(row[5])
    for grp, counts in pos_acc.items():
        total = sum(counts.values())
        if total > 0:
            probs = {k: v / total for k, v in counts.items()}
            insert_rows.append((fmt, gender, f'batting_position_{grp}', json.dumps(_probs_to_jsonb(probs))))

    # Global milestone distributions (10-run score buckets, m0..m100)
    with conn.cursor() as cur:
        cur.execute(
            """
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
                CASE WHEN score_before >= 100 THEN 'm100'
                     ELSE 'm' || ((score_before / 10) * 10)::text
                END AS milestone,
                runs_batter, runs_extras, outcome_type, outcome_kind,
                COUNT(*) AS cnt
            FROM delivery_running
            GROUP BY milestone, runs_batter, runs_extras, outcome_type, outcome_kind
            """,
            (raw_fmts, gender),
        )
        rows = cur.fetchall()
    ms_acc: Dict[str, Dict[Tuple, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        ms_acc[row[0]][(row[1], row[2], row[3], row[4])] += int(row[5])
    for milestone, counts in ms_acc.items():
        total = sum(counts.values())
        if total > 0:
            probs = {k: v / total for k, v in counts.items()}
            insert_rows.append((fmt, gender, f'milestone_{milestone}', json.dumps(_probs_to_jsonb(probs))))

    # Fielding counts: {player_id: wicket_count} stored as JSON with str keys
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.outcome_player_id::TEXT, COUNT(*)
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
              AND d.outcome_type = 'Wicket' AND d.outcome_player_id IS NOT NULL
            GROUP BY d.outcome_player_id
            """,
            (raw_fmts, gender),
        )
        fd_rows = cur.fetchall()
    if fd_rows:
        fd_json = json.dumps({pid: int(cnt) for pid, cnt in fd_rows})
        insert_rows.append((fmt, gender, 'fielding_counts', fd_json))

    count = _upsert_aggregate(conn, insert_rows, dry_run)
    print(f"{count} rows  ({time.perf_counter()-t0:.1f}s)")
    return count


# ═══════════════════════════════════════════════════════════════════════════════
# venue_stats + country_stats
# ═══════════════════════════════════════════════════════════════════════════════

def _populate_venue_stats(conn, fmt: str, gender: str, dry_run: bool) -> int:
    raw_fmts = _FORMAT_ALIASES[fmt]
    print(f"  venue_stats {fmt}/{gender} ...", end=" ", flush=True)
    t0 = time.perf_counter()

    # Use per-year with _HALF_LIFE_VENUE decay
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.venue_id,
                   EXTRACT(YEAR FROM m.date)::INTEGER AS year,
                   d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                   COUNT(*) AS cnt
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
              AND m.date IS NOT NULL AND m.venue_id IS NOT NULL
            GROUP BY m.venue_id, year,
                     d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender),
        )
        rows = cur.fetchall()

    acc: Dict[int, Dict[int, Dict[Tuple, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for row in rows:
        vid, year, rb, re, ot, ok, cnt = row[0], int(row[1]), row[2], row[3], row[4], row[5], int(row[6])
        acc[vid][year][(rb, re, ot, ok)] += cnt

    insert_rows = []
    for vid, py_data in acc.items():
        raw = _decay_weighted_probs(py_data, _HALF_LIFE_VENUE)
        if not raw:
            continue
        balls = _total_balls(py_data)
        insert_rows.append((vid, fmt, gender, json.dumps(_probs_to_jsonb(raw)), balls))

    count = _upsert_venue_stats(conn, insert_rows, dry_run)
    print(f"{len(acc)} venues → {count} rows  ({time.perf_counter()-t0:.1f}s)")
    return count


def _populate_country_stats(conn, fmt: str, gender: str, dry_run: bool) -> int:
    raw_fmts = _FORMAT_ALIASES[fmt]
    print(f"  country_stats {fmt}/{gender} ...", end=" ", flush=True)
    t0 = time.perf_counter()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT v.country,
                   EXTRACT(YEAR FROM m.date)::INTEGER AS year,
                   d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                   COUNT(*) AS cnt
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            JOIN history.venues  v ON m.venue_id  = v.venue_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
              AND m.date IS NOT NULL AND v.country IS NOT NULL
            GROUP BY v.country, year,
                     d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """,
            (raw_fmts, gender),
        )
        rows = cur.fetchall()

    acc: Dict[str, Dict[int, Dict[Tuple, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for row in rows:
        country, year, rb, re, ot, ok, cnt = row[0], int(row[1]), row[2], row[3], row[4], row[5], int(row[6])
        acc[country][year][(rb, re, ot, ok)] += cnt

    insert_rows = []
    for country, py_data in acc.items():
        raw = _decay_weighted_probs(py_data, _HALF_LIFE_COUNTRY)
        if not raw:
            continue
        balls = _total_balls(py_data)
        insert_rows.append((country, fmt, gender, json.dumps(_probs_to_jsonb(raw)), balls))

    count = _upsert_country_stats(conn, insert_rows, dry_run)
    print(f"{len(acc)} countries → {count} rows  ({time.perf_counter()-t0:.1f}s)")
    return count


# ═══════════════════════════════════════════════════════════════════════════════
# tournament_outcome_stats
# ═══════════════════════════════════════════════════════════════════════════════

def _populate_tournament_stats(conn, dry_run: bool) -> int:
    print(f"  tournament_outcome_stats ...", end=" ", flush=True)
    t0 = time.perf_counter()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.tournament_id,
                   EXTRACT(YEAR FROM m.date)::INTEGER AS year,
                   d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind,
                   COUNT(*) AS cnt
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.tournament_id IS NOT NULL AND m.date IS NOT NULL
            GROUP BY m.tournament_id, year,
                     d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
            """
        )
        rows = cur.fetchall()

    acc: Dict[int, Dict[int, Dict[Tuple, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for row in rows:
        tid, year, rb, re, ot, ok, cnt = row[0], int(row[1]), row[2], row[3], row[4], row[5], int(row[6])
        acc[tid][year][(rb, re, ot, ok)] += cnt

    insert_rows = []
    for tid, py_data in acc.items():
        raw = _decay_weighted_probs(py_data, _HALF_LIFE_TOURN)
        if not raw:
            continue
        balls = _total_balls(py_data)
        insert_rows.append((tid, json.dumps(_probs_to_jsonb(raw)), balls))

    count = _upsert_tournament_stats(conn, insert_rows, dry_run)
    print(f"{len(acc)} tournaments → {count} rows  ({time.perf_counter()-t0:.1f}s)")
    return count


# ═══════════════════════════════════════════════════════════════════════════════
# player_scalar_stats: career + workload + death_overs + phase stats + roles
# ═══════════════════════════════════════════════════════════════════════════════

def _populate_scalar_stats(conn, fmt: str, gender: str, dry_run: bool) -> int:
    raw_fmts = _FORMAT_ALIASES[fmt]
    print(f"  scalar_stats {fmt}/{gender} ...", end=" ", flush=True)
    t0 = time.perf_counter()

    insert_rows: list = []

    # Career (economy + wicket_rate)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.bowler_id,
                   SUM(d.runs_batter + d.runs_extras) * 6.0 / NULLIF(COUNT(*), 0) AS economy,
                   SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END)::float
                       / NULLIF(COUNT(*), 0) AS wicket_rate,
                   COUNT(*) AS balls
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE d.bowler_id IS NOT NULL AND m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY d.bowler_id
            HAVING COUNT(*) >= 6
            """,
            (raw_fmts, gender),
        )
        for row in cur.fetchall():
            pid, economy, wr, balls = row
            insert_rows.append((
                pid, fmt, 'career',
                json.dumps({'economy': float(economy or 0), 'wicket_rate': float(wr or 0), 'balls': int(balls)}),
            ))

    # Phase stats (powerplay / middle / death)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.bowler_id,
                   CASE
                       WHEN m.match_format = ANY(%s) AND d.over_number <= 6  THEN 'powerplay'
                       WHEN m.match_format = ANY(%s) AND d.over_number >= 17 THEN 'death'
                       WHEN m.match_format = ANY(%s) AND d.over_number <= 10 THEN 'powerplay'
                       WHEN m.match_format = ANY(%s) AND d.over_number >= 41 THEN 'death'
                       ELSE 'middle'
                   END AS phase,
                   SUM(d.runs_batter + d.runs_extras) * 6.0 / NULLIF(COUNT(*), 0) AS economy,
                   SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END)::float
                       / NULLIF(COUNT(*), 0) AS wicket_rate,
                   COUNT(*) AS balls
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE d.bowler_id IS NOT NULL AND m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY d.bowler_id, phase
            """,
            (
                _FORMAT_ALIASES['T20'], _FORMAT_ALIASES['T20'],
                _FORMAT_ALIASES['ODI'], _FORMAT_ALIASES['ODI'],
                raw_fmts, gender,
            ),
        )
        phase_by_player: Dict[int, Dict[str, dict]] = defaultdict(dict)
        for row in cur.fetchall():
            pid, phase, economy, wr, balls = row
            phase_by_player[pid][phase] = {
                'economy': float(economy or 0),
                'wicket_rate': float(wr or 0),
                'balls': int(balls),
            }
    for pid, phases in phase_by_player.items():
        for phase_name, data in phases.items():
            insert_rows.append((pid, fmt, f'phase_{phase_name}', json.dumps(data)))

    # Workload
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH distinct_overs AS (
                SELECT DISTINCT del.bowler_id, del.match_id, del.inning_number, del.over_number
                FROM history.deliveries del
                JOIN history.matches m ON del.match_id = m.match_id
                WHERE del.bowler_id IS NOT NULL
                  AND m.match_format = ANY(%s) AND m.gender = %s
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
                       AVG(total_overs)                                             AS avg_overs,
                       PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY total_overs)   AS p75_overs,
                       COUNT(*)                                                     AS innings_count,
                       SUM(total_overs)                                             AS career_overs
                FROM innings_totals GROUP BY bowler_id
            ),
            per_bowler_spells AS (
                SELECT bowler_id,
                       PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY spell_overs)   AS p75_spell
                FROM spells GROUP BY bowler_id
            ),
            total_appearances AS (
                SELECT mp.player_id AS bowler_id, COUNT(DISTINCT mp.match_id) AS total_matches
                FROM history.match_players mp
                JOIN history.matches m ON mp.match_id = m.match_id
                WHERE mp.player_id IS NOT NULL
                  AND m.match_format = ANY(%s) AND m.gender = %s
                GROUP BY mp.player_id
            )
            SELECT pbo.bowler_id,
                   pbo.avg_overs, pbo.p75_overs, pbs.p75_spell,
                   pbo.innings_count,
                   pbo.career_overs::float / NULLIF(ta.total_matches, 0) AS avg_overs_per_match
            FROM per_bowler_overs pbo
            JOIN per_bowler_spells pbs   USING (bowler_id)
            LEFT JOIN total_appearances ta ON ta.bowler_id = pbo.bowler_id
            WHERE pbo.innings_count >= 3
            """,
            (raw_fmts, gender, raw_fmts, gender),
        )
        for row in cur.fetchall():
            pid, avg_ov, p75_ov, p75_sp, inn_cnt, avg_per_match = row
            insert_rows.append((
                pid, fmt, 'workload',
                json.dumps({
                    'avg_overs_per_innings': float(avg_ov or 5.0),
                    'p75_overs_per_innings': float(p75_ov or 6.0),
                    'p75_spell':             float(p75_sp or 4.0),
                    'innings_count':         int(inn_cnt),
                    'avg_overs_per_match':   float(avg_per_match or 0.0),
                }),
            ))

    # Death-over batter stats
    t20_fmts = _FORMAT_ALIASES['T20']
    odi_fmts = _FORMAT_ALIASES['ODI']
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.batter_id,
                   SUM(d.runs_batter) * 100.0 /
                       NULLIF(SUM(CASE WHEN d.outcome_type != 'Extras' THEN 1 ELSE 0 END), 0) AS death_sr,
                   SUM(CASE WHEN d.runs_batter >= 4 THEN 1 ELSE 0 END)::float /
                       NULLIF(COUNT(*), 0) AS boundary_rate,
                   COUNT(*) AS balls
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE d.batter_id IS NOT NULL
              AND m.match_format = ANY(%s) AND m.gender = %s
              AND (
                    (m.match_format = ANY(%s) AND d.over_number >= 17)
                 OR (m.match_format = ANY(%s) AND d.over_number >= 41)
              )
            GROUP BY d.batter_id
            HAVING COUNT(*) >= 6
            """,
            (raw_fmts, gender, t20_fmts, odi_fmts),
        )
        for row in cur.fetchall():
            pid, death_sr, boundary_rate, balls = row
            insert_rows.append((
                pid, fmt, 'death_overs',
                json.dumps({
                    'death_sr':      float(death_sr or 0),
                    'boundary_rate': float(boundary_rate or 0),
                    'balls':         int(balls),
                }),
            ))

    count = _upsert_scalar(conn, insert_rows, dry_run)
    print(f"{count} rows  ({time.perf_counter()-t0:.1f}s)")
    return count


def _populate_player_roles(conn, dry_run: bool) -> int:
    """Keeper and spinner flags — format-independent, stored with match_format='any'."""
    print(f"  player_roles ...", end=" ", flush=True)
    t0 = time.perf_counter()

    # Keepers: ≥3 stumping dismissals
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.outcome_player_id
            FROM history.deliveries d
            WHERE d.outcome_player_id IS NOT NULL
              AND d.outcome_type = 'Wicket' AND d.outcome_kind = 'stumped'
            GROUP BY d.outcome_player_id
            HAVING COUNT(*) >= 3
            """
        )
        keeper_ids = {r[0] for r in cur.fetchall()}

    # Spinners: ≥3 stumped dismissals as bowler
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.bowler_id
            FROM history.deliveries d
            WHERE d.bowler_id IS NOT NULL
              AND d.outcome_type = 'Wicket' AND d.outcome_kind = 'stumped'
            GROUP BY d.bowler_id
            HAVING COUNT(*) >= 3
            """
        )
        spinner_ids = {r[0] for r in cur.fetchall()}

    all_player_ids = keeper_ids | spinner_ids
    insert_rows = [
        (pid, 'any', 'roles', json.dumps({
            'is_keeper':  pid in keeper_ids,
            'is_spinner': pid in spinner_ids,
        }))
        for pid in all_player_ids
    ]

    count = _upsert_scalar(conn, insert_rows, dry_run)
    print(f"{count} players  ({time.perf_counter()-t0:.1f}s)")
    return count


# ═══════════════════════════════════════════════════════════════════════════════
# bowler_order_stats: over_freq + phase_dist
# ═══════════════════════════════════════════════════════════════════════════════

def _populate_bowler_order_stats(conn, fmt: str, gender: str, dry_run: bool) -> int:
    if fmt not in ('T20', 'ODI'):
        return 0  # Test cricket doesn't use bowling-order models
    raw_fmts = _FORMAT_ALIASES[fmt]
    t20_fmts = _FORMAT_ALIASES['T20']
    odi_fmts = _FORMAT_ALIASES['ODI']
    print(f"  bowler_order_stats {fmt}/{gender} ...", end=" ", flush=True)
    t0 = time.perf_counter()

    insert_rows: list = []
    over_filter = "AND d.over_number BETWEEN 0 AND 19" if fmt == 'T20' else "AND d.over_number BETWEEN 0 AND 49"
    key_expr    = "d.over_number" if fmt == 'T20' else "d.over_number / 5"

    for match_type_val in ('all', 'international'):
        mt_filter = "AND m.match_type = 'international'" if match_type_val == 'international' else ""
        for inning_num in (0, 1, 2):
            inn_filter = f"AND d.inning_number = {inning_num}" if inning_num > 0 else ""
            inn_filter_tm = f"AND d.inning_number = {inning_num}" if inning_num > 0 else ""

            # over_freq
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    WITH total_matches AS (
                        SELECT mp.player_id, COUNT(DISTINCT mp.match_id) AS n
                        FROM history.match_players mp
                        JOIN history.matches m ON mp.match_id = m.match_id
                        WHERE mp.player_id IS NOT NULL
                          AND m.match_format = ANY(%s) AND m.gender = %s
                          {mt_filter}
                        GROUP BY mp.player_id
                    ),
                    key_counts AS (
                        SELECT d.bowler_id, {key_expr} AS over_key,
                               COUNT(DISTINCT d.match_id) AS cnt
                        FROM history.deliveries d
                        JOIN history.matches m ON d.match_id = m.match_id
                        WHERE d.bowler_id IS NOT NULL
                          AND m.match_format = ANY(%s) AND m.gender = %s
                          {mt_filter} {inn_filter} {over_filter}
                        GROUP BY d.bowler_id, {key_expr}
                    )
                    SELECT kc.bowler_id, kc.over_key, kc.cnt::float / NULLIF(t.n, 0) AS frac
                    FROM key_counts kc
                    JOIN total_matches t ON kc.bowler_id = t.player_id
                    WHERE t.n >= 5
                    """,
                    (raw_fmts, gender, raw_fmts, gender),
                )
                over_acc: Dict[int, Dict[int, float]] = defaultdict(dict)
                for row in cur.fetchall():
                    over_acc[row[0]][int(row[1])] = float(row[2] or 0)
            for pid, over_dist in over_acc.items():
                insert_rows.append((
                    pid, fmt, 'over_freq', match_type_val, inning_num,
                    None, None,
                    json.dumps({str(k): v for k, v in over_dist.items()}),
                ))

            # phase_dist
            if fmt == 'T20':
                pp_end, mid_start, mid_end, death_start = 5, 6, 14, 15
            else:
                pp_end, mid_start, mid_end, death_start = 9, 10, 38, 39
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    WITH total_matches AS (
                        SELECT mp.player_id, COUNT(DISTINCT mp.match_id) AS n
                        FROM history.match_players mp
                        JOIN history.matches m ON mp.match_id = m.match_id
                        WHERE mp.player_id IS NOT NULL
                          AND m.match_format = ANY(%s) AND m.gender = %s
                          {mt_filter}
                        GROUP BY mp.player_id
                    ),
                    phase_overs AS (
                        SELECT d.bowler_id, d.match_id,
                               COUNT(DISTINCT CASE WHEN d.over_number <= %s THEN d.over_number END) AS pp_overs,
                               COUNT(DISTINCT CASE WHEN d.over_number BETWEEN %s AND %s  THEN d.over_number END) AS mid_overs,
                               COUNT(DISTINCT CASE WHEN d.over_number >= %s THEN d.over_number END) AS death_overs
                        FROM history.deliveries d
                        JOIN history.matches m ON d.match_id = m.match_id
                        WHERE d.bowler_id IS NOT NULL
                          AND m.match_format = ANY(%s) AND m.gender = %s
                          {mt_filter} {inn_filter_tm}
                        GROUP BY d.bowler_id, d.match_id
                    )
                    SELECT o.bowler_id,
                           SUM(o.pp_overs)::float    / NULLIF(t.n, 0) AS avg_pp,
                           SUM(o.mid_overs)::float   / NULLIF(t.n, 0) AS avg_mid,
                           SUM(o.death_overs)::float / NULLIF(t.n, 0) AS avg_death
                    FROM phase_overs o
                    JOIN total_matches t ON o.bowler_id = t.player_id
                    GROUP BY o.bowler_id, t.n
                    HAVING t.n >= 5
                    """,
                    (raw_fmts, gender, pp_end, mid_start, mid_end, death_start, raw_fmts, gender),
                )
                for row in cur.fetchall():
                    pid, avg_pp, avg_mid, avg_death = row
                    insert_rows.append((
                        pid, fmt, 'phase_dist', match_type_val, inning_num,
                        None, None,
                        json.dumps({'pp': float(avg_pp or 0), 'mid': float(avg_mid or 0), 'death': float(avg_death or 0)}),
                    ))

    count = _upsert_bowler_order(conn, insert_rows, dry_run)
    print(f"{count} rows  ({time.perf_counter()-t0:.1f}s)")
    return count


def seed_tournament_squads(
    tournament_ids: list[int],
    last_n: int = 6,
    dry_run: bool = False,
) -> int:
    """
    Seed simulation.tournament_seeded.squads for the given tournament IDs.

    Squad selection: players who appeared most often in the last N matches
    for their team, trimmed to 11. Tiebreak: lower median batting position wins.

    Batting position: median position across ALL tournament matches where the
    player batted. Players who never batted get position 99.

    Safe to re-run — uses INSERT ... ON CONFLICT DO UPDATE so admin edits to
    other players in the same (tournament, team) are preserved.
    """
    conn = get_db_connection(autocommit=False)
    cur  = conn.cursor()
    total = 0

    for tid in tournament_ids:
        t0 = time.perf_counter()
        cur.execute("SELECT tournament_name FROM history.tournaments WHERE tournament_id = %s", (tid,))
        row = cur.fetchone()
        if not row:
            print(f"  tournament_id={tid} not found — skipping")
            continue
        print(f"  Seeding {row[0]} (id={tid}, last_n={last_n}) …")

        # ── Step 1: last N match_ids per team ─────────────────────────────
        cur.execute("""
            SELECT team_id, array_agg(match_id ORDER BY match_date DESC) AS match_ids
            FROM (
                SELECT
                    tt.team_id,
                    m.match_id,
                    m.date AS match_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY tt.team_id ORDER BY m.date DESC
                    ) AS rn
                FROM history.tournament_teams tt
                JOIN history.matches m
                    ON  m.tournament_id = tt.tournament_id
                    AND (m.home_team_id = tt.team_id OR m.away_team_id = tt.team_id)
                WHERE tt.tournament_id = %s
            ) ranked
            WHERE rn <= %s
            GROUP BY team_id
        """, (tid, last_n))
        team_recent_matches: dict[int, list[int]] = {
            r[0]: r[1] for r in cur.fetchall()
        }

        # ── Step 2: appearance counts in last N matches ───────────────────
        # {team_id: {player_id: appearance_count}}
        cur.execute("""
            SELECT mp.team_id, mp.player_id, COUNT(*) AS appearances
            FROM history.match_players mp
            WHERE mp.match_id = ANY(%s::int[])
            GROUP BY mp.team_id, mp.player_id
        """, ([mid for mids in team_recent_matches.values() for mid in mids],))
        appearances: dict[int, dict[int, int]] = {}
        for team_id, player_id, cnt in cur.fetchall():
            appearances.setdefault(team_id, {})[player_id] = cnt

        # ── Step 3: median batting position per player across full tournament ──
        cur.execute("""
            SELECT
                d.batting_team_id                           AS team_id,
                d.batter_id                                 AS player_id,
                PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY d.batting_position_in_innings
                )                                           AS median_pos
            FROM (
                SELECT
                    match_id,
                    batting_team_id,
                    batter_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY match_id, batting_team_id
                        ORDER BY MIN(over_number * 100 + ball_number)
                    ) AS batting_position_in_innings
                FROM history.deliveries
                WHERE match_id IN (
                    SELECT match_id FROM history.matches WHERE tournament_id = %s
                )
                GROUP BY match_id, batting_team_id, batter_id
            ) d
            GROUP BY d.batting_team_id, d.batter_id
        """, (tid,))
        median_pos: dict[int, dict[int, float]] = {}
        for team_id, player_id, pos in cur.fetchall():
            median_pos.setdefault(team_id, {})[player_id] = float(pos)

        # ── Step 4: pick top 11 per team, ordered by batting position ────────
        rows_for_tournament = 0
        # team_id → [player_id, ...] ordered by batting position
        new_squads: dict[int, list[int]] = {}

        for team_id, player_counts in appearances.items():
            team_median = median_pos.get(team_id, {})

            ranked = sorted(
                player_counts.items(),
                key=lambda x: (-x[1], team_median.get(x[0], 99)),
            )[:11]

            squad = []
            for pid, _ in ranked:
                pos = team_median.get(pid, 99)
                squad.append((pid, round(pos) if pos != 99 else 99))

            squad.sort(key=lambda x: x[1])
            batted = [pid for pid, pos in squad if pos != 99]
            no_bat = [pid for pid, pos in squad if pos == 99]
            new_squads[team_id] = batted + no_bat
            rows_for_tournament += len(new_squads[team_id])

        if not dry_run and new_squads:
            # Read existing config and update players in-place per team
            cur.execute(
                "SELECT config FROM simulation.tournament_seeded WHERE tournament_id = %s",
                (tid,),
            )
            row = cur.fetchone()
            if not row or not row[0]:
                print(f"    WARNING: no config row for tournament_id={tid} — "
                      "run seed_sim_configs.py first", file=sys.stderr)
                continue

            config: dict = row[0]
            teams_list = config.get("teams", [])
            for i, team_obj in enumerate(teams_list):
                t_id = team_obj.get("team_id")
                if t_id and t_id in new_squads:
                    teams_list[i] = {**team_obj, "players": new_squads[t_id]}
            config["teams"] = teams_list

            cur.execute(
                """
                UPDATE simulation.tournament_seeded
                SET config = %s::jsonb
                WHERE tournament_id = %s
                """,
                (json.dumps(config), tid),
            )
            conn.commit()

        elapsed = time.perf_counter() - t0
        print(f"    {rows_for_tournament} rows  ({elapsed:.1f}s){' [dry-run]' if dry_run else ''}")
        total += rows_for_tournament

    cur.close()
    conn.close()
    return total


# ═══════════════════════════════════════════════════════════════════════════════
# Top-level orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

def populate_all(current_year_only: bool = False, dry_run: bool = False, tables: str = 'all') -> None:
    """
    Rebuild all precomputed tables.

    tables: 'all' | 'global' | 'player' | 'aggregate' | 'scalar' | 'bowling'
    """
    if not dry_run:
        print("WARNING: This will rewrite all precomputed tables and may take 10–30 minutes.")

    conn = get_db_connection(autocommit=False)
    total = 0
    try:
        do_global    = tables in ('all', 'global')
        do_player    = tables in ('all', 'player')
        do_aggregate = tables in ('all', 'aggregate')
        do_scalar    = tables in ('all', 'scalar')
        do_bowling   = tables in ('all', 'bowling')

        if do_global:
            print("\n── global_yearly_baseline ──")
            year_filter = date.today().year if current_year_only else None
            for fmt in _FORMATS:
                for gender in _GENDERS:
                    t0 = time.perf_counter()
                    data = _compute_global_yearly_baseline(conn, fmt, gender, year_filter)
                    print(f"  {fmt}/{gender}: {len(data)} years  ({time.perf_counter()-t0:.1f}s)")
                    total += _upsert_global_yearly_baseline(conn, fmt, gender, data, year_filter, dry_run)

        for fmt in _FORMATS:
            for gender in _GENDERS:
                if do_player:
                    print(f"\n── player_outcome_stats {fmt}/{gender} ──")
                    gbl = _load_global_baseline(conn, fmt, gender)
                    agg = _load_aggregate_baseline(conn, fmt, gender)
                    total += _populate_batting_bowling(conn, fmt, gender, gbl, agg, dry_run)
                    total += _populate_phase_stats(conn, fmt, gender, gbl, agg, dry_run)
                    total += _populate_milestone_stats(conn, fmt, gender, gbl, agg, dry_run)
                    total += _populate_matchups(conn, fmt, gender, gbl, agg, dry_run)
                    total += _populate_player_venue_stats(conn, fmt, gender, gbl, agg, dry_run)
                    total += _populate_player_country_stats(conn, fmt, gender, gbl, agg, dry_run)

                if do_aggregate:
                    print(f"\n── aggregate_stats + venue/country/tournament {fmt}/{gender} ──")
                    total += _populate_aggregate_stats(conn, fmt, gender, dry_run)
                    total += _populate_venue_stats(conn, fmt, gender, dry_run)
                    total += _populate_country_stats(conn, fmt, gender, dry_run)

                if do_scalar:
                    print(f"\n── player_scalar_stats {fmt}/{gender} ──")
                    total += _populate_scalar_stats(conn, fmt, gender, dry_run)

                if do_bowling:
                    print(f"\n── bowler_order_stats {fmt}/{gender} ──")
                    total += _populate_bowler_order_stats(conn, fmt, gender, dry_run)

        if do_aggregate:
            print(f"\n── tournament_outcome_stats ──")
            total += _populate_tournament_stats(conn, dry_run)

        if do_scalar:
            print(f"\n── player_scalar_stats: roles ──")
            total += _populate_player_roles(conn, dry_run)

    finally:
        conn.close()

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Total rows written: {total}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate precomputed tables for the cricket simulator.")
    parser.add_argument("--current-year-only", action="store_true",
                        help="Only refresh the current calendar year in global_yearly_baseline.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print row counts without modifying the DB.")
    parser.add_argument("--tables", default="all",
                        choices=["all", "global", "player", "aggregate", "scalar", "bowling", "positions"],
                        help="Subset of tables to rebuild.")
    parser.add_argument("--seed-squads", action="store_true",
                        help="Seed simulation.tournament_seeded.squads for matching tournaments.")
    parser.add_argument("--tournament-name", type=str, default=None,
                        help="Tournament name pattern for --seed-squads (e.g. 'Indian Premier League').")
    parser.add_argument("--tournament-ids", type=str, default=None,
                        help="Comma-separated tournament IDs for --seed-squads (e.g. '1243,1029').")
    parser.add_argument("--last-n", type=int, default=6,
                        help="Last N matches to consider for squad selection (default 8).")
    args = parser.parse_args()

    if args.seed_squads:
        conn = get_db_connection(autocommit=False)
        cur  = conn.cursor()
        if args.tournament_ids:
            ids = [int(x.strip()) for x in args.tournament_ids.split(",")]
        elif args.tournament_name:
            cur.execute(
                "SELECT tournament_id FROM history.tournaments WHERE tournament_name ILIKE %s",
                (f"%{args.tournament_name}%",),
            )
            ids = [r[0] for r in cur.fetchall()]
            print(f"Found {len(ids)} tournaments matching '{args.tournament_name}'")
        else:
            parser.error("--seed-squads requires --tournament-name or --tournament-ids")
        cur.close()
        conn.close()
        seed_tournament_squads(ids, last_n=args.last_n, dry_run=args.dry_run)
    elif args.tables == "all" and not args.dry_run:
        populate_all(current_year_only=args.current_year_only, dry_run=args.dry_run)
    elif args.tables == "global":
        populate_global_yearly_baseline(current_year_only=args.current_year_only, dry_run=args.dry_run)
    else:
        populate_all(current_year_only=args.current_year_only, dry_run=args.dry_run, tables=args.tables)


if __name__ == "__main__":
    main()
