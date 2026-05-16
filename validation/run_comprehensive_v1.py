#!/usr/bin/env python3
"""
Comprehensive model validation — T20 / ODI / Test.

Architecture
------------
For each format:
  1. Select targets: N venues (region-diverse) + M batters (position-stratified)
                     + K bowlers (type/phase-stratified).
  2. For each venue, find the P most-recent historical matches AT that venue.
     For each player, find the Q most-recent historical matches FEATURING that player.
  3. Pool all unique match_ids → deduplicated simulation set.
  4. Build configs from actual historical lineups (batting order from delivery data).
  5. Init ball-outcome strategy ONCE (player caches shared across all matches).
     Pre-load venue-specific caches for every unique venue in the pool.
  6. Simulate each unique match R times.
     - Before each match: swap in that match's venue caches (no DB query needed).
     - Bowling order: replay the actual historical bowling order from deliveries
       (HistoricalBowlingOrder strategy).
     - Every delivery attributes simultaneously to all applicable targets.
  7. Compare simulated per-target stats against historical ground truth.
  8. Write per-format files + summary to validation_results/<timestamp>/.

Output: validation_results/<timestamp>/{T20,ODI,Test}.txt + summary.txt
"""

import json
import math
import os
import random
import sys
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.stats_repository import StatsRepository
from simulator.entities.rules import MatchRules
from simulator.strategies.ball_outcome_prediction.historical_stats.validate_simulation import (
    ProfileStats,
    load_historical_phase_stats,
)

# ── Format settings ───────────────────────────────────────────────────────────
FORMAT_SETTINGS = {
    'T20':  dict(R=10, venue_matches=25, player_matches=25, n_venues=10, n_batters=15, n_bowlers=5),
    'ODI':  dict(R=10, venue_matches=25, player_matches=25, n_venues=8,  n_batters=12, n_bowlers=5),
    'Test': dict(R=10, venue_matches=20, player_matches=20, n_venues=5,  n_batters=8,  n_bowlers=3),
}

BOWLER_FULLTIME_THRESHOLDS = {'T20': 120, 'ODI': 180, 'Test': 300}

REGION_MAP = {
    'India': 'South Asia',       'Bangladesh': 'South Asia',
    'Sri Lanka': 'South Asia',   'Pakistan': 'South Asia',
    'Afghanistan': 'South Asia', 'Nepal': 'South Asia',
    'United Arab Emirates': 'Middle East', 'Oman': 'Middle East',
    'Kuwait': 'Middle East',
    'Australia': 'Oceania',      'New Zealand': 'Oceania',
    'Papua New Guinea': 'Oceania',
    'United Kingdom': 'Europe',  'Ireland': 'Europe',
    'Netherlands': 'Europe',     'Scotland': 'Europe',
    'West Indies': 'Americas',   'USA': 'Americas',
    'Barbados': 'Americas',      'Trinidad and Tobago': 'Americas',
    'Jamaica': 'Americas',       'Guyana': 'Americas',
    'South Africa': 'Africa',    'Zimbabwe': 'Africa',
    'Kenya': 'Africa',           'Namibia': 'Africa',
}

TOL_BOUNDARY = 0.020
TOL_WICKET   = 0.010
TOL_ECONOMY  = 0.50
TOL_DOT      = 0.025


# ─────────────────────────────────────────────────────────────────────────────
# Historical bowling order strategy
# ─────────────────────────────────────────────────────────────────────────────

class HistoricalBowlingOrder:
    """
    Replays the actual bowling order from a historical match.
    plan[inning_number][over_0indexed] = player_id
    Falls back to any eligible bowler when the historical bowler isn't found.
    """
    _initialized = True  # signals engine to skip init_model guard

    def __init__(self, plan: Dict[int, Dict[int, int]]):
        self._plan = plan

    def init_model(self, match) -> None:
        pass  # no-op; player caches already live on out_strat

    def select_bowler(self, match):
        inning_num = match.current_inning if match.current_inning else 1
        over_0 = match.current_over  # 0-indexed
        pid = self._plan.get(inning_num, {}).get(over_0)

        bowling_team = match.current_bowling_team
        if not bowling_team or not bowling_team.inning_players:
            return match.current_bowler

        # Find the historical bowler in the inning team
        if pid is not None:
            for ip in bowling_team.inning_players:
                if ip.id == pid:
                    return ip

        # Fallback: any eligible bowler that isn't the previous one
        eligible = [ip for ip in bowling_team.inning_players
                    if ip != match.current_bowler]
        return eligible[0] if eligible else match.current_bowler


# ─────────────────────────────────────────────────────────────────────────────
# Weighted sampling
# ─────────────────────────────────────────────────────────────────────────────

def _wsample(items, weights, k, rng):
    if k >= len(items):
        return list(items)
    items, weights = list(items), list(weights)
    result = []
    for _ in range(k):
        total = sum(weights)
        r = rng.random() * total
        cum = 0.0
        for i, w in enumerate(weights):
            cum += w
            if r <= cum:
                result.append(items.pop(i))
                weights.pop(i)
                break
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Target selection
# ─────────────────────────────────────────────────────────────────────────────

def select_venues(repo, match_format, gender, n, rng, min_deliveries=2000):
    raw_fmts = repo._raw_formats(match_format)
    rows = repo._run_query("""
        SELECT v.venue_id, v.name, v.country, COUNT(*) AS n
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        JOIN history.venues   v ON m.venue_id  = v.venue_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY v.venue_id, v.name, v.country
        HAVING COUNT(*) >= %s
        ORDER BY n DESC
    """, (raw_fmts, gender, min_deliveries))

    by_region = defaultdict(list)
    for vid, vname, country, cnt in rows:
        region = REGION_MAP.get(country, 'Other')
        by_region[region].append((vid, vname, country, region, cnt))

    regions = list(by_region)
    region_total = {r: sum(v[4] for v in vs) for r, vs in by_region.items()}
    grand_total  = sum(region_total.values()) or 1
    alloc = {r: max(1, round(n * region_total[r] / grand_total)) for r in regions}

    while sum(alloc.values()) > n:
        alloc[max(alloc, key=alloc.get)] -= 1
    while sum(alloc.values()) < n:
        cands = [r for r in regions if len(by_region[r]) > alloc[r]]
        if not cands: break
        alloc[min(cands, key=alloc.get)] += 1

    selected = []
    for region, k in alloc.items():
        venues  = by_region[region]
        weights = [math.sqrt(v[4]) for v in venues]
        selected.extend(_wsample(venues, weights, k, rng))
    return selected[:n]


def select_batters(repo, match_format, gender, n, rng, min_balls=200):
    raw_fmts = repo._raw_formats(match_format)
    rows = repo._run_query("""
        WITH first_ball AS (
            SELECT d.match_id, d.inning_number, d.batter_id,
                   MIN(d.over_number * 1000 + d.ball_number) AS first_key
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY d.match_id, d.inning_number, d.batter_id
        ),
        ranked AS (
            SELECT batter_id,
                   RANK() OVER (PARTITION BY match_id, inning_number ORDER BY first_key) AS pos
            FROM first_ball
        ),
        avg_pos AS (
            SELECT batter_id, AVG(pos) AS avg_pos
            FROM ranked
            GROUP BY batter_id HAVING COUNT(*) >= 5
        ),
        balls AS (
            SELECT d.batter_id, COUNT(*) AS ball_count
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY d.batter_id
        )
        SELECT p.player_id, p.name, ap.avg_pos, b.ball_count
        FROM avg_pos ap
        JOIN balls b ON b.batter_id = ap.batter_id
        JOIN history.players p ON p.player_id = ap.batter_id
        WHERE b.ball_count >= %s
        ORDER BY b.ball_count DESC
    """, (raw_fmts, gender, raw_fmts, gender, min_balls))

    groups = {'opener': [], 'top_order': [], 'middle_order': [], 'lower_order': [], 'tail': []}
    for pid, name, avg_pos, balls in rows:
        if avg_pos <= 2.0:      groups['opener'].append((pid, name, avg_pos, balls))
        elif avg_pos <= 3.5:    groups['top_order'].append((pid, name, avg_pos, balls))
        elif avg_pos <= 6.0:    groups['middle_order'].append((pid, name, avg_pos, balls))
        elif avg_pos <= 8.5:    groups['lower_order'].append((pid, name, avg_pos, balls))
        else:                   groups['tail'].append((pid, name, avg_pos, balls))

    shares = {'opener': 0.25, 'top_order': 0.20, 'middle_order': 0.30,
              'lower_order': 0.15, 'tail': 0.10}
    selected, seen = [], set()
    for grp, share in shares.items():
        k   = max(1, round(share * n))
        avl = groups[grp]
        if not avl: continue
        w = [math.sqrt(p[3]) for p in avl]
        for item in _wsample(avl, w, min(k, len(avl)), rng):
            if item[0] not in seen:
                selected.append((*item, grp))
                seen.add(item[0])
    if len(selected) < n:
        all_avl = [(*p, grp) for grp, ps in groups.items() for p in ps if p[0] not in seen]
        w = [math.sqrt(p[3]) for p in all_avl]
        for item in _wsample(all_avl, w, n - len(selected), rng):
            selected.append(item); seen.add(item[0])
    return selected[:n]


def select_bowlers(repo, match_format, gender, n, rng, min_balls=50):
    raw_fmts  = repo._raw_formats(match_format)
    threshold = BOWLER_FULLTIME_THRESHOLDS.get(match_format, 120)
    pp_end      = {'T20':  5, 'ODI':  9, 'Test': 20}[match_format]
    death_start = {'T20': 15, 'ODI': 40, 'Test': 60}[match_format]

    rows = repo._run_query("""
        SELECT p.player_id, p.name, COUNT(*) AS career_balls, AVG(d.over_number) AS avg_over
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        JOIN history.players p ON d.bowler_id = p.player_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY p.player_id, p.name
        HAVING COUNT(*) >= %s
        ORDER BY career_balls DESC
    """, (raw_fmts, gender, min_balls))

    all_ids  = [r[0] for r in rows]
    spin_ids = repo.get_spinner_ids(all_ids, gender) if all_ids else set()

    groups = defaultdict(list)
    for pid, name, career_balls, avg_over in rows:
        is_ft   = career_balls >= threshold
        style   = 'spin' if pid in spin_ids else 'pace'
        if is_ft:
            if avg_over <= pp_end:        phase = 'powerplay'
            elif avg_over >= death_start: phase = 'death'
            else:                         phase = 'middle'
            label = f"fulltime-{style}-{phase}"
        else:
            label = f"parttimer-{style}"
        groups[label].append((pid, name, int(career_balls), avg_over, label))

    per_group = max(1, n // max(len(groups), 1))
    selected, seen = [], set()
    for label, players in sorted(groups.items()):
        w = [math.sqrt(p[2]) for p in players]
        for item in _wsample(players, w, min(per_group, len(players)), rng):
            if item[0] not in seen:
                selected.append(item); seen.add(item[0])
    if len(selected) < n:
        all_avl = [p for ps in groups.values() for p in ps if p[0] not in seen]
        w = [math.sqrt(p[2]) for p in all_avl]
        for item in _wsample(all_avl, w, n - len(selected), rng):
            selected.append(item); seen.add(item[0])
    return selected[:n]


# ─────────────────────────────────────────────────────────────────────────────
# Historical match discovery
# ─────────────────────────────────────────────────────────────────────────────

def find_venue_matches(repo, venue_id, match_format, gender, n=25):
    raw_fmts = repo._raw_formats(match_format)
    rows = repo._run_query("""
        SELECT m.match_id
        FROM history.matches m
        JOIN (
            SELECT match_id, COUNT(*) AS n_del
            FROM history.deliveries
            WHERE inning_number <= 2
            GROUP BY match_id HAVING COUNT(*) >= 100
        ) d ON d.match_id = m.match_id
        WHERE m.venue_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
        ORDER BY m.date DESC NULLS LAST
        LIMIT %s
    """, (venue_id, raw_fmts, gender, n))
    return [r[0] for r in rows]


def find_player_matches(repo, player_id, match_format, gender, n=25):
    raw_fmts = repo._raw_formats(match_format)
    rows = repo._run_query("""
        SELECT sub.match_id
        FROM (
            SELECT mp.match_id, MAX(m.date) AS match_date
            FROM history.match_players mp
            JOIN history.matches m ON mp.match_id = m.match_id
            JOIN (
                SELECT match_id FROM history.deliveries
                WHERE inning_number <= 2
                GROUP BY match_id HAVING COUNT(*) >= 100
            ) d ON d.match_id = mp.match_id
            WHERE mp.player_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY mp.match_id
        ) sub
        ORDER BY sub.match_date DESC NULLS LAST
        LIMIT %s
    """, (player_id, raw_fmts, gender, n))
    return [r[0] for r in rows]


def batch_build_matches(repo, all_match_ids, match_format, _w=print):
    """
    Build match configs, bowling plans, and SimulationMatch objects for all IDs
    using 4 bulk queries instead of N×23 per-match queries.

    Returns:
        match_configs : {mid: {'_venue_id': vid, '_match_id': mid}}
        bowling_plans : {mid: {inning: {over_0indexed: bowler_id}}}
        resolved      : {mid: SimulationMatch}
    """
    from simulator.entities.match import SimulationMatch
    from simulator.entities.team import MatchTeam
    from simulator.entities.player import Player
    from db.entities.venue import Venue

    _FMT_SETTINGS = {
        'T20':  {'overs_per_innings': 20,   'innings_per_match': 2},
        'ODI':  {'overs_per_innings': 50,   'innings_per_match': 2},
        'Test': {'overs_per_innings': None,  'innings_per_match': 4},
    }
    fmt    = MatchRules.get_unified_format(match_format)
    fs     = _FMT_SETTINGS[fmt]
    mid_list = list(all_match_ids)

    # ── 1. Match metadata + venue ──────────────────────────────────────────────
    _w(f"  [Batch] Match metadata …")
    meta_rows = repo._run_query("""
        SELECT m.match_id, m.venue_id, v.name, v.country, m.home_team_id, m.away_team_id
        FROM history.matches m
        JOIN history.venues v ON m.venue_id = v.venue_id
        WHERE m.match_id = ANY(%s)
    """, (mid_list,))
    match_meta = {r[0]: r[1:] for r in meta_rows}

    # ── 2. All match players ───────────────────────────────────────────────────
    _w(f"  [Batch] Player lineups …")
    player_rows = repo._run_query("""
        SELECT mp.match_id, mp.team_id, t.name, mp.player_id, p.name
        FROM history.match_players mp
        JOIN history.players p ON mp.player_id = p.player_id
        JOIN history.teams   t ON mp.team_id   = t.team_id
        WHERE mp.match_id = ANY(%s)
    """, (mid_list,))

    # ── 3. Batting order (first appearance) for all matches ────────────────────
    _w(f"  [Batch] Batting order …")
    batting_rows = repo._run_query("""
        SELECT match_id, player_id, batting_team_id,
               MIN((inning_number * 10000 + over_number * 100 + ball_number) * 2 + role) AS sort_key
        FROM (
            SELECT match_id, batter_id     AS player_id, batting_team_id,
                   inning_number, over_number, ball_number, 0 AS role
            FROM history.deliveries WHERE match_id = ANY(%s) AND inning_number <= 2
            UNION ALL
            SELECT match_id, non_striker_id AS player_id, batting_team_id,
                   inning_number, over_number, ball_number, 1 AS role
            FROM history.deliveries WHERE match_id = ANY(%s) AND inning_number <= 2
        ) a
        GROUP BY match_id, player_id, batting_team_id
    """, (mid_list, mid_list))
    sort_keys: Dict[Tuple, int] = {}
    for mid, pid, tid, sk in batting_rows:
        sort_keys[(mid, pid, tid)] = sk

    # ── 4. Bowling plans (most-balls bowler wins each over) ────────────────────
    _w(f"  [Batch] Bowling plans …")
    bow_rows = repo._run_query("""
        SELECT match_id, inning_number, over_number, bowler_id
        FROM (
            SELECT match_id, inning_number, over_number, bowler_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY match_id, inning_number, over_number
                       ORDER BY COUNT(*) DESC
                   ) AS rn
            FROM history.deliveries
            WHERE match_id = ANY(%s) AND inning_number <= 2
            GROUP BY match_id, inning_number, over_number, bowler_id
        ) sub
        WHERE rn = 1
    """, (mid_list,))
    bowling_plans: Dict[int, Dict] = {}
    for mid, inning, over, bowler_id in bow_rows:
        bowling_plans.setdefault(mid, {}).setdefault(inning, {})[over] = bowler_id

    # ── Build Python objects ───────────────────────────────────────────────────
    match_players_raw: Dict[int, list] = {}
    for mid, tid, tname, pid, pname in player_rows:
        match_players_raw.setdefault(mid, []).append((tid, tname, pid, pname))

    match_configs: Dict[int, dict] = {}
    resolved:      Dict[int, object] = {}

    for mid, meta in match_meta.items():
        vid, vname, vcountry, home_tid, away_tid = meta
        raw_players = match_players_raw.get(mid, [])
        if not raw_players:
            continue

        sorted_players = sorted(
            raw_players,
            key=lambda x: (x[0], sort_keys.get((mid, x[2], x[0]), 999_999_999)),
        )

        teams: Dict[int, dict] = {}
        for tid, tname, pid, pname in sorted_players:
            teams.setdefault(tid, {'name': tname, 'players': []})['players'].append(
                Player(id=pid, name=pname)
            )

        ordered = []
        for tid in [home_tid, away_tid]:
            if tid in teams:
                ordered.append(teams.pop(tid))
        for t in teams.values():
            ordered.append(t)

        if len(ordered) < 2:
            continue

        venue = Venue(name=vname, id=vid, country=vcountry)
        match_configs[mid] = {'_venue_id': vid, '_match_id': mid}
        resolved[mid] = SimulationMatch(
            id=mid,
            home_team=MatchTeam(id=1, name=ordered[0]['name'], players=ordered[0]['players']),
            away_team=MatchTeam(id=2, name=ordered[1]['name'], players=ordered[1]['players']),
            venue=venue,
            match_format=fmt,
            balls_per_over=6,
            **fs,
        )

    _w(f"  [Batch] Done — {len(resolved)} matches ready.")
    return match_configs, bowling_plans, resolved


# ─────────────────────────────────────────────────────────────────────────────
# Venue cache pre-loading
# ─────────────────────────────────────────────────────────────────────────────

def preload_venue_caches(repo, unique_venues, all_player_ids, fmt, gender, is_test, _w):
    """
    Pre-loads venue-specific distributions for all unique venues in the match pool.
    Returns dict keyed by venue_id with all cache dicts the strategies need.
    Expensive per venue but run once, not per match.
    """
    from simulator.strategies.bowling.historical.base import _region_countries

    cache = {}
    n = len(unique_venues)
    _w(f"  Pre-loading venue caches for {n} unique venues …")
    t0 = time.perf_counter()

    for i, (vid, venue_obj) in enumerate(unique_venues.items(), 1):
        country = getattr(venue_obj, 'country', None)

        # Ball-outcome: general venue distribution
        venue_dist = repo.get_venue_distribution(vid, fmt, gender)
        if not venue_dist and country:
            venue_dist = repo.get_country_distribution(country, fmt, gender)

        # Ball-outcome: player-venue distribution
        pv_dist = repo.get_player_venue_distribution(all_player_ids, vid, fmt, gender)

        # Ball-outcome: player-country distribution (fallback to venue country/region)
        pc_dist = {}
        if country:
            country_group = _region_countries(country)
            if country_group:
                pc_dist = repo.get_player_country_distribution(
                    all_player_ids, country_group[0], fmt, gender,
                    countries=country_group, exclude_venue_id=vid,
                )

        # Bowling model: over-frequency caches (limited overs)
        over_freq      = {}
        over_freq_inn1 = {}
        over_freq_inn2 = {}
        test_phase_freq = {}

        if is_test:
            test_phase_freq = repo.get_bowler_test_phase_frequency(
                all_player_ids, gender, venue_id=vid
            ) if all_player_ids else {}
        else:
            over_freq      = repo.get_bowler_over_frequency(
                all_player_ids, fmt, gender, venue_id=vid
            ) if all_player_ids else {}
            over_freq_inn1 = repo.get_bowler_over_frequency(
                all_player_ids, fmt, gender, venue_id=vid, inning_number=1
            ) if all_player_ids else {}
            over_freq_inn2 = repo.get_bowler_over_frequency(
                all_player_ids, fmt, gender, venue_id=vid, inning_number=2
            ) if all_player_ids else {}

        cache[vid] = {
            'venue':            venue_dist or {},
            'player_venue':     pv_dist    or {},
            'player_country':   pc_dist    or {},
            'over_freq':        over_freq,
            'over_freq_inn1':   over_freq_inn1,
            'over_freq_inn2':   over_freq_inn2,
            'test_phase_freq':  test_phase_freq,
        }

    elapsed = time.perf_counter() - t0
    _w(f"  Venue cache pre-load done  ({elapsed:.1f}s)")
    return cache


def apply_venue_caches(out_strat, bow_strat, venue_id, venue_caches):
    """Swap venue-specific caches on both strategies (no DB queries)."""
    vc = venue_caches.get(venue_id)
    if not vc:
        return
    out_strat.venue_cache         = vc['venue']
    out_strat.player_venue_cache  = vc['player_venue']
    out_strat.player_country_cache = vc['player_country']
    bow_strat.venue_over_freq_cache      = vc['over_freq']
    bow_strat.venue_over_freq_cache_inn1 = vc['over_freq_inn1']
    bow_strat.venue_over_freq_cache_inn2 = vc['over_freq_inn2']
    bow_strat.venue_test_phase_freq_cache = vc['test_phase_freq']


# ─────────────────────────────────────────────────────────────────────────────
# Historical ground truth loaders
# ─────────────────────────────────────────────────────────────────────────────

def load_hist_batter_stats(repo, player_id, match_format, gender):
    raw_fmts = repo._raw_formats(match_format)
    rows = repo._run_query("""
        SELECT d.over_number, d.runs_batter, d.outcome_type, d.runs_extras
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.batter_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
    """, (player_id, raw_fmts, gender))
    overall  = ProfileStats()
    by_phase = defaultdict(ProfileStats)
    for over0, rb, ot, rx in rows:
        wkt   = ot == 'Wicket'
        phase = MatchRules.get_fine_grained_phase(over0 + 1, match_format)
        for acc in (overall, by_phase[phase]):
            acc.n          += 1
            acc.total_runs += rb + rx
            if rb >= 4: acc.n_boundary += 1
            if wkt:     acc.n_wicket   += 1
            if rb == 0 and rx == 0 and not wkt: acc.n_dot += 1
    return overall, dict(by_phase)


def load_hist_bowler_stats(repo, player_id, match_format, gender):
    raw_fmts = repo._raw_formats(match_format)
    rows = repo._run_query("""
        SELECT d.over_number, d.runs_batter, d.runs_extras, d.outcome_type
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE d.bowler_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
    """, (player_id, raw_fmts, gender))
    overall  = ProfileStats()
    by_phase = defaultdict(ProfileStats)
    for over0, rb, rx, ot in rows:
        wkt   = ot == 'Wicket'
        phase = MatchRules.get_fine_grained_phase(over0 + 1, match_format)
        for acc in (overall, by_phase[phase]):
            acc.n          += 1
            acc.total_runs += rb + rx
            if rb >= 4: acc.n_boundary += 1
            if wkt:     acc.n_wicket   += 1
            if rb == 0 and rx == 0 and not wkt: acc.n_dot += 1
    return overall, dict(by_phase)


# ─────────────────────────────────────────────────────────────────────────────
# Reporting helpers
# ─────────────────────────────────────────────────────────────────────────────

def _stat_row(label, sim: ProfileStats, hist: ProfileStats, min_n=30):
    if sim.n < min_n or hist.n < min_n:
        return None
    b_ok = '✓' if abs(sim.boundary_rate - hist.boundary_rate) < TOL_BOUNDARY else '✗'
    w_ok = '✓' if abs(sim.wicket_rate   - hist.wicket_rate)   < TOL_WICKET   else '✗'
    e_ok = '✓' if abs(sim.economy       - hist.economy)        < TOL_ECONOMY  else '✗'
    d_ok = '✓' if abs(sim.dot_rate      - hist.dot_rate)       < TOL_DOT      else '✗'
    return (f"  {label:<18}  n={sim.n:>6}/{hist.n:<8}"
            f"  bnd {sim.boundary_rate:.3f}/{hist.boundary_rate:.3f}{b_ok}"
            f"  wkt {sim.wicket_rate:.3f}/{hist.wicket_rate:.3f}{w_ok}"
            f"  eco {sim.economy:.2f}/{hist.economy:.2f}{e_ok}"
            f"  dot {sim.dot_rate:.3f}/{hist.dot_rate:.3f}{d_ok}")


@dataclass
class AccTracker:
    label: str
    checks: list = field(default_factory=list)

    def add(self, sim_val, hist_val, tol):
        self.checks.append(abs(sim_val - hist_val) < tol)

    def collect(self, sim: ProfileStats, hist: ProfileStats, min_n=30):
        if sim.n < min_n or hist.n < min_n:
            return
        self.add(sim.boundary_rate, hist.boundary_rate, TOL_BOUNDARY)
        self.add(sim.wicket_rate,   hist.wicket_rate,   TOL_WICKET)
        self.add(sim.economy,       hist.economy,       TOL_ECONOMY)
        self.add(sim.dot_rate,      hist.dot_rate,      TOL_DOT)

    @property
    def pass_rate(self):
        if not self.checks: return None
        return sum(self.checks) / len(self.checks)

    def summary_line(self):
        if not self.checks: return f"  {self.label:<54}  no data"
        n_pass = sum(self.checks)
        n_tot  = len(self.checks)
        pct    = 100 * n_pass / n_tot
        bar    = '█' * int(pct / 10) + '░' * (10 - int(pct / 10))
        return f"  {self.label:<54}  {bar}  {n_pass}/{n_tot} ({pct:.0f}%)"


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main(seed=42, outdir='validation_results', gender='male'):
    from simulator.match_logger import MatchLogger
    MatchLogger.SILENT = True

    from simulator.simulate_driver import _OUTCOME_STRATEGIES, _BOWLING_STRATEGY_FACTORIES
    from simulator.engines.engine_factory import EngineFactory
    from simulator.entities.match import SimulationMatch
    from simulator.entities.team import MatchTeam

    rng  = random.Random(seed)
    repo = StatsRepository()

    ts      = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(outdir, ts)
    os.makedirs(run_dir, exist_ok=True)

    # Console-only writer for progress (no file)
    def _progress(line=''):
        print(line, flush=True)

    _progress(f"\n{'═'*84}")
    _progress(f"  COMPREHENSIVE MODEL VALIDATION")
    _progress(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}   Seed: {seed}   Gender: {gender}")
    _progress(f"  Output dir: {run_dir}")
    _progress(f"{'═'*84}")

    all_trackers: List[AccTracker] = []

    for match_format, cfg in FORMAT_SETTINGS.items():
        R              = cfg['R']
        venue_matches  = cfg['venue_matches']
        player_matches = cfg['player_matches']
        n_venues       = cfg['n_venues']
        n_batters      = cfg['n_batters']
        n_bowlers      = cfg['n_bowlers']
        fmt            = MatchRules.get_unified_format(match_format)
        is_test        = (match_format == 'Test')

        # Per-format output file
        fmt_path = os.path.join(run_dir, f'{match_format}.txt')
        fmt_fh   = open(fmt_path, 'w', encoding='utf-8')

        def _w(line='', fh=fmt_fh):
            print(line, flush=True)
            print(line, file=fh, flush=True)

        _w(f"\n\n{'━'*84}")
        _w(f"  FORMAT: {match_format}   ({R} sims/match, {venue_matches} matches/venue, {player_matches} matches/player)")
        _w(f"{'━'*84}")

        # ── Select targets ────────────────────────────────────────────────────
        venues  = select_venues (repo, fmt, gender, n_venues,  rng)
        batters = select_batters(repo, fmt, gender, n_batters, rng)
        bowlers = select_bowlers(repo, fmt, gender, n_bowlers, rng)

        target_vids   = {v[0] for v in venues}
        target_bids   = {b[0] for b in batters}
        target_bowids = {b[0] for b in bowlers}

        _w(f"\n  Targets selected:")
        _w(f"    Venues  ({n_venues}): " + ", ".join(v[1][:25] for v in venues))
        _w(f"    Batters ({n_batters}): " + ", ".join(b[1] for b in batters))
        _w(f"    Bowlers ({n_bowlers}): " + ", ".join(b[1] for b in bowlers))

        # ── Discover historical matches ───────────────────────────────────────
        venue_match_pool:  Dict[int, List[int]] = {}
        player_match_pool: Dict[int, List[int]] = {}

        for vid, vname, *_ in venues:
            venue_match_pool[vid] = find_venue_matches(repo, vid, fmt, gender, n=venue_matches)

        for pid, *_ in batters + bowlers:
            player_match_pool[pid] = find_player_matches(repo, pid, fmt, gender, n=player_matches)

        all_match_ids: Set[int] = set()
        for ids in venue_match_pool.values():  all_match_ids.update(ids)
        for ids in player_match_pool.values(): all_match_ids.update(ids)

        _w(f"\n  {len(all_match_ids)} unique historical matches to simulate ({R} times each = "
           f"{len(all_match_ids) * R} total simulations)")

        # ── Batch-build all match configs, bowling plans, resolved matches ──────
        match_configs, bowling_plans, resolved = batch_build_matches(
            repo, all_match_ids, match_format, _w
        )

        if not match_configs:
            _w("  ERROR: no valid match configs — skipping format")
            fmt_fh.close()
            continue

        if not resolved:
            _w("  ERROR: no matches resolved — skipping format")
            fmt_fh.close()
            continue

        # ── Union player set for one-shot player cache init ───────────────────
        seen_pids: set = set()
        union_home, union_away = [], []
        for m in resolved.values():
            for p in m.home_team.players:
                if p.id not in seen_pids: seen_pids.add(p.id); union_home.append(p)
            for p in m.away_team.players:
                if p.id not in seen_pids: seen_pids.add(p.id); union_away.append(p)

        first = next(iter(resolved.values()))
        union_match = SimulationMatch(
            id=0,
            home_team=MatchTeam(id=1, name='_uh', players=union_home),
            away_team=MatchTeam(id=2, name='_ua', players=union_away),
            venue=first.venue, match_format=fmt, balls_per_over=6,
            overs_per_innings=first.overs_per_innings,
            innings_per_match=first.innings_per_match,
        )

        _w(f"  Initialising player caches for {len(seen_pids)} unique players …")
        out_strat = _OUTCOME_STRATEGIES['enhanced'][fmt]()
        bow_strat = _BOWLING_STRATEGY_FACTORIES['historical'](fmt)
        out_strat.init_model(union_match)
        bow_strat.init_model(union_match)
        _w("  Player caches ready.")

        # ── Pre-load venue-specific caches for all unique venues ──────────────
        unique_venues_in_pool: Dict[int, object] = {}
        for mid, m in resolved.items():
            v = m.venue
            if v and v.id and v.id not in unique_venues_in_pool:
                unique_venues_in_pool[v.id] = v

        all_pids_list = list(seen_pids)
        venue_caches = preload_venue_caches(
            repo, unique_venues_in_pool, all_pids_list, fmt, gender, is_test, _w
        )

        # ── Accumulators ───────────────────────────────────────────────────────
        sim_venue: Dict[int, Dict[str, ProfileStats]] = {
            vid: defaultdict(ProfileStats) for vid in target_vids
        }
        sim_venue_scores: Dict[int, List[int]] = {vid: [] for vid in target_vids}

        def _empty_player_acc():
            return {'overall': ProfileStats(), 'by_phase': defaultdict(ProfileStats)}

        sim_bat: Dict[int, dict] = {pid: _empty_player_acc() for pid in target_bids}
        sim_bow: Dict[int, dict] = {pid: _empty_player_acc() for pid in target_bowids}

        mid_to_vid = {mid: cfg['_venue_id'] for mid, cfg in match_configs.items()}
        max_inning = 2

        # ── Simulation loop ────────────────────────────────────────────────────
        total_sims  = len(resolved) * R
        sims_done   = 0
        t_sim_start = time.perf_counter()

        for mid, resolved_match in resolved.items():
            vid    = mid_to_vid.get(mid)
            hn     = resolved_match.home_team.name
            hp     = list(resolved_match.home_team.players)
            an     = resolved_match.away_team.name
            ap     = list(resolved_match.away_team.players)
            v_obj  = resolved_match.venue
            fs     = {'overs_per_innings': resolved_match.overs_per_innings,
                      'innings_per_match': resolved_match.innings_per_match}

            # Swap venue-specific caches for this match (no DB queries)
            if v_obj and v_obj.id:
                apply_venue_caches(out_strat, bow_strat, v_obj.id, venue_caches)

            bow_plan = bowling_plans.get(mid, {})
            hist_bow_strat = HistoricalBowlingOrder(bow_plan)

            for r in range(R):
                match = SimulationMatch(
                    id=sims_done + 1,
                    home_team=MatchTeam(id=1, name=hn, players=hp),
                    away_team=MatchTeam(id=2, name=an, players=ap),
                    venue=v_obj, match_format=fmt, balls_per_over=6, **fs,
                )
                try:
                    EngineFactory.create(match, out_strat, hist_bow_strat).simulate()
                except Exception as e:
                    _w(f"  WARN: sim {sims_done+1} failed: {e}")
                    sims_done += 1
                    continue

                for inning in match.innings:
                    if inning.inning_number > max_inning:
                        continue
                    if vid in sim_venue_scores and inning.batting_team:
                        sim_venue_scores[vid].append(inning.batting_team.total_runs)

                    for delivery in inning.deliveries:
                        rb    = delivery.runs_batter
                        rx    = delivery.runs_extras
                        wkt   = delivery.is_wicket
                        dot   = (rb == 0 and rx == 0 and not wkt)
                        over  = delivery.over_number
                        phase = MatchRules.get_fine_grained_phase(over + 1, fmt)

                        def _push(acc: ProfileStats):
                            acc.n          += 1
                            acc.total_runs += rb + rx
                            if rb >= 4: acc.n_boundary += 1
                            if wkt:     acc.n_wicket   += 1
                            if dot:     acc.n_dot      += 1

                        if vid in sim_venue:
                            _push(sim_venue[vid][phase])

                        bid = delivery.batter.id if delivery.batter else None
                        if bid in sim_bat:
                            _push(sim_bat[bid]['overall'])
                            _push(sim_bat[bid]['by_phase'][phase])

                        bowid = delivery.bowler.id if delivery.bowler else None
                        if bowid in sim_bow:
                            _push(sim_bow[bowid]['overall'])
                            _push(sim_bow[bowid]['by_phase'][phase])

                sims_done += 1
                if sims_done % 50 == 0 or sims_done == total_sims:
                    elapsed = time.perf_counter() - t_sim_start
                    _w(f"  [{match_format}] {sims_done}/{total_sims} sims done  ({elapsed:.0f}s)")

        # ── Report: venues ────────────────────────────────────────────────────
        _w(f"\n\n  {'─'*80}")
        _w(f"  VENUE RESULTS  ({match_format})")
        _w(f"  {'─'*80}")
        for (vid, vname, country, region, hist_n) in venues:
            tracker = AccTracker(f"[{match_format}] Venue: {vname[:32]}")
            _w(f"\n  {vname}  ({country} / {region})  hist_deliveries={hist_n:,}"
               f"  sim_matches={len(venue_match_pool.get(vid, []))*R}")
            try:
                hist_phases = load_historical_phase_stats(repo, vid, fmt, gender)
                sim_phases  = sim_venue[vid]
                for phase in sorted(set(hist_phases) | set(sim_phases)):
                    s = sim_phases.get(phase, ProfileStats())
                    h = hist_phases.get(phase, ProfileStats())
                    row = _stat_row(phase, s, h, min_n=20)
                    if row: _w(row); tracker.collect(s, h, min_n=20)

                sim_scores = sim_venue_scores[vid]
                if sim_scores:
                    hist_scores_rows = repo._run_query("""
                        SELECT SUM(d.runs_batter + d.runs_extras)
                        FROM history.deliveries d
                        JOIN history.matches m ON d.match_id = m.match_id
                        WHERE m.venue_id = %s AND m.match_format = ANY(%s)
                          AND m.gender = %s AND d.inning_number <= 2
                        GROUP BY d.match_id, d.inning_number
                    """, (vid, repo._raw_formats(fmt), gender))
                    hist_scores = [int(r[0]) for r in hist_scores_rows if r[0]]
                    sim_avg  = sum(sim_scores)  / len(sim_scores)
                    hist_avg = sum(hist_scores) / len(hist_scores) if hist_scores else 0
                    ok = '✓' if abs(sim_avg - hist_avg) < 10 else '✗'
                    _w(f"  {'score_avg':<18}  sim={sim_avg:.1f}  hist={hist_avg:.1f}  {ok}")
            except Exception as e:
                _w(f"  ERROR: {e}"); traceback.print_exc(file=fmt_fh)
            all_trackers.append(tracker)

        # ── Report: batters ───────────────────────────────────────────────────
        _w(f"\n\n  {'─'*80}")
        _w(f"  BATTER RESULTS  ({match_format})")
        _w(f"  {'─'*80}")
        for (pid, pname, avg_pos, balls, pos_grp) in batters:
            tracker = AccTracker(f"[{match_format}] Batter: {pname[:27]} ({pos_grp})")
            _w(f"\n  {pname}  pos_group={pos_grp}  avg_pos={avg_pos:.1f}  hist_balls={balls:,}"
               f"  sim_matches={len(player_match_pool.get(pid, []))*R}")
            try:
                hist_ov, hist_ph = load_hist_batter_stats(repo, pid, fmt, gender)
                sim_ov  = sim_bat[pid]['overall']
                sim_ph  = sim_bat[pid]['by_phase']
                row = _stat_row('overall', sim_ov, hist_ov, min_n=20)
                if row: _w(row); tracker.collect(sim_ov, hist_ov, min_n=20)
                for phase in sorted(set(hist_ph) | set(sim_ph)):
                    s = sim_ph.get(phase, ProfileStats())
                    h = hist_ph.get(phase, ProfileStats())
                    row = _stat_row(phase, s, h, min_n=15)
                    if row: _w(row); tracker.collect(s, h, min_n=15)
            except Exception as e:
                _w(f"  ERROR: {e}"); traceback.print_exc(file=fmt_fh)
            all_trackers.append(tracker)

        # ── Report: bowlers ───────────────────────────────────────────────────
        _w(f"\n\n  {'─'*80}")
        _w(f"  BOWLER RESULTS  ({match_format})")
        _w(f"  {'─'*80}")
        for (pid, pname, career_balls, avg_over, btype) in bowlers:
            tracker = AccTracker(f"[{match_format}] Bowler: {pname[:27]} ({btype})")
            _w(f"\n  {pname}  type={btype}  career_balls={career_balls:,}  avg_over={avg_over:.1f}"
               f"  sim_matches={len(player_match_pool.get(pid, []))*R}")
            try:
                hist_ov, hist_ph = load_hist_bowler_stats(repo, pid, fmt, gender)
                sim_ov  = sim_bow[pid]['overall']
                sim_ph  = sim_bow[pid]['by_phase']
                row = _stat_row('overall', sim_ov, hist_ov, min_n=20)
                if row: _w(row); tracker.collect(sim_ov, hist_ov, min_n=20)
                for phase in sorted(set(hist_ph) | set(sim_ph)):
                    s = sim_ph.get(phase, ProfileStats())
                    h = hist_ph.get(phase, ProfileStats())
                    row = _stat_row(phase, s, h, min_n=15)
                    if row: _w(row); tracker.collect(s, h, min_n=15)
            except Exception as e:
                _w(f"  ERROR: {e}"); traceback.print_exc(file=fmt_fh)
            all_trackers.append(tracker)

        fmt_fh.close()
        _progress(f"  [{match_format}] Written to {fmt_path}")

    # ── Overall summary (separate file + stdout) ───────────────────────────────
    summary_path = os.path.join(run_dir, 'summary.txt')
    with open(summary_path, 'w', encoding='utf-8') as sfh:
        def _s(line=''):
            print(line, flush=True)
            print(line, file=sfh, flush=True)

        _s(f"\n\n{'═'*84}")
        _s("  OVERALL ACCURACY SUMMARY")
        _s(f"{'═'*84}")
        _s(f"\n  {'Target':<56}  {'Accuracy':>12}  Pass/Total")
        _s(f"  {'─'*56}  {'─'*12}  {'─'*10}")

        fmt_rates:  Dict[str, List[float]] = defaultdict(list)
        type_rates: Dict[str, List[float]] = defaultdict(list)

        for t in all_trackers:
            if t.pass_rate is None: continue
            _s(t.summary_line())
            prefix = t.label.split(']')[0].lstrip('[')
            fmt_rates[prefix].append(t.pass_rate)
            for word in ('Venue', 'Batter', 'Bowler'):
                if word in t.label:
                    type_rates[word].append(t.pass_rate)

        _s(f"\n  Per-format averages:")
        for fk in ('T20', 'ODI', 'Test'):
            rates = fmt_rates.get(fk, [])
            if rates:
                avg = 100 * sum(rates) / len(rates)
                _s(f"    {fk:<6}  {avg:.1f}%  ({len(rates)} validations)")

        _s(f"\n  Per-type averages:")
        for tk in ('Venue', 'Batter', 'Bowler'):
            rates = type_rates.get(tk, [])
            if rates:
                avg = 100 * sum(rates) / len(rates)
                _s(f"    {tk:<8}  {avg:.1f}%  ({len(rates)} validations)")

        _s(f"\n  Output files:")
        for fmt_key in FORMAT_SETTINGS:
            _s(f"    {os.path.join(run_dir, fmt_key + '.txt')}")
        _s(f"    {summary_path}")
        _s(f"{'═'*84}\n")

    print(f"\nValidation complete. Results in: {run_dir}", flush=True)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--seed',   type=int, default=42)
    p.add_argument('--outdir', default='validation_results')
    p.add_argument('--gender', default='male', choices=['male', 'female'])
    args = p.parse_args()
    main(seed=args.seed, outdir=args.outdir, gender=args.gender)
