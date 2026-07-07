#!/usr/bin/env python3
"""
Comprehensive Model Validation v2  —  T20 / ODI / Test
=======================================================
Improvements over v1:
  • 30 venues, 30 batters, 30 bowlers per format (vs 10/15/5)
  • International-biased player + venue selection (70% international, 30% domestic)
  • All position types covered: openers, top, middle, lower, tail; pace/spin/parttimer
  • Batter-bowler matchup analysis (tracked live during simulation)
  • Format-level phase summary (aggregated across all entities)
  • Format-level overall score + wicket accuracy
  • 15 sims/match for better statistical power
  • Root-cause analysis section in summary

Architecture
------------
For each format:
  1. Select targets: 30 venues (region-diverse, intl-biased)
                     30 batters (position-stratified, intl-biased)
                     30 bowlers (type/phase-stratified, intl-biased)
  2. Discover historical match pools (20 matches/venue or player).
  3. Pool + deduplicate → unique simulation set.
  4. Batch-build all match configs + bowling plans (4 bulk queries).
  5. Init ball-outcome + bowling strategies ONCE; pre-load all venue caches.
  6. Simulate each unique match 15 times.
     Every delivery attributed to: venue, batter, bowler, batter-bowler pair.
  7. Report: venue phase stats, batter/bowler phase stats, matchup analysis,
     format-level phase/score/wicket summary.
  8. Write per-format files + overall summary + root-cause analysis.
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
from simulator.predictors.bowling.historical.replay import HistoricalBowlingOrder
from validation.simulation_validator import (
    ProfileStats,
    load_historical_phase_stats,
)

# ── Format settings ────────────────────────────────────────────────────────────
FORMAT_SETTINGS = {
    # min_intl_venue_del  : deliveries at venue in international matches (keeps famous grounds)
    # min_dom_venue_del   : deliveries at venue across all cricket (keeps IPL/BBL/PSL grade, not village)
    # min_intl_player_balls: balls faced/bowled in intl cricket (keeps established internationals)
    # min_dom_player_balls : balls total (keeps established domestic pros, not one-off players)
    # min_intl_*: high threshold keeps only established regulars from major nations
    # min_dom_*: high threshold keeps IPL/BBL/PSL-grade domestic, not village cricket
    # intl_slots use deterministic top-N by ball_count; dom_slots use weighted random
    'T20':  dict(R=15, venue_matches=20, player_matches=20,
                 n_venues=30, n_batters=30, n_bowlers=30,
                 intl_frac=0.70,
                 min_intl_venue_del=12000, min_dom_venue_del=15000,
                 min_intl_player_balls=2000, min_dom_player_balls=3000),
    'ODI':  dict(R=15, venue_matches=20, player_matches=20,
                 n_venues=30, n_batters=30, n_bowlers=30,
                 intl_frac=0.70,
                 min_intl_venue_del=15000, min_dom_venue_del=12000,
                 min_intl_player_balls=3000, min_dom_player_balls=4000),
    'Test': dict(R=15, venue_matches=20, player_matches=20,
                 n_venues=15, n_batters=30, n_bowlers=20,
                 intl_frac=0.80,
                 min_intl_venue_del=15000, min_dom_venue_del=15000,
                 min_intl_player_balls=5000, min_dom_player_balls=6000),
}

BOWLER_FULLTIME_THRESHOLDS = {'T20': 120, 'ODI': 180, 'Test': 300}

REGION_MAP = {
    'India': 'South Asia',        'Bangladesh': 'South Asia',
    'Sri Lanka': 'South Asia',    'Pakistan': 'South Asia',
    'Afghanistan': 'South Asia',  'Nepal': 'South Asia',
    'United Arab Emirates': 'Middle East', 'Oman': 'Middle East', 'Kuwait': 'Middle East',
    'Australia': 'Oceania',       'New Zealand': 'Oceania',  'Papua New Guinea': 'Oceania',
    'United Kingdom': 'Europe',   'Ireland': 'Europe',       'Netherlands': 'Europe',
    'Scotland': 'Europe',
    'West Indies': 'Americas',    'USA': 'Americas',         'Barbados': 'Americas',
    'Trinidad and Tobago': 'Americas', 'Jamaica': 'Americas', 'Guyana': 'Americas',
    'South Africa': 'Africa',     'Zimbabwe': 'Africa',
    'Kenya': 'Africa',            'Namibia': 'Africa',
}

# Tolerance windows
TOL_BOUNDARY = 0.020
TOL_WICKET   = 0.010
TOL_ECONOMY  = 0.50
TOL_DOT      = 0.025


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
        if total == 0:
            break
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
# Target selection — venues (international-biased, region-diverse)
# ─────────────────────────────────────────────────────────────────────────────

def select_venues(repo, match_format, gender, n, rng,
                  min_intl_venue_del=5000, min_dom_venue_del=10000, intl_frac=0.70):
    """
    Select n venues with regional diversity and a bias toward famous international venues.
    intl_frac fraction of slots filled from venues hosting international matches (high threshold).
    Remaining slots from high-volume domestic venues (IPL/BBL/PSL grade, not village cricket).
    """
    raw_fmts = repo._raw_formats(match_format)
    n_intl = max(1, round(n * intl_frac))
    n_dom  = n - n_intl

    intl_rows = repo._run_query("""
        SELECT v.venue_id, v.name, v.country, COUNT(*) AS n
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        JOIN history.venues   v ON m.venue_id  = v.venue_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s
          AND m.match_type = 'international'
        GROUP BY v.venue_id, v.name, v.country
        HAVING COUNT(*) >= %s
        ORDER BY n DESC
    """, (raw_fmts, gender, min_intl_venue_del))

    all_rows = repo._run_query("""
        SELECT v.venue_id, v.name, v.country, COUNT(*) AS n
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        JOIN history.venues   v ON m.venue_id  = v.venue_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s
        GROUP BY v.venue_id, v.name, v.country
        HAVING COUNT(*) >= %s
        ORDER BY n DESC
    """, (raw_fmts, gender, min_dom_venue_del))

    def _region_diverse(rows, k, deterministic=False):
        by_region = defaultdict(list)
        for vid, vname, country, cnt in rows:
            region = REGION_MAP.get(country, 'Other')
            by_region[region].append((vid, vname, country, region, cnt))

        regions = list(by_region)
        region_total = {r: sum(v[4] for v in vs) for r, vs in by_region.items()}
        grand_total  = sum(region_total.values()) or 1
        alloc = {r: max(1, round(k * region_total[r] / grand_total)) for r in regions}
        while sum(alloc.values()) > k:
            alloc[max(alloc, key=alloc.get)] -= 1
        while sum(alloc.values()) < k:
            cands = [r for r in regions if len(by_region[r]) > alloc[r]]
            if not cands: break
            alloc[min(cands, key=alloc.get)] += 1

        selected = []
        for region, quota in alloc.items():
            venues = sorted(by_region[region], key=lambda x: x[4], reverse=True)
            if deterministic:
                selected.extend(venues[:quota])
            else:
                weights = [math.sqrt(v[4]) for v in venues]
                selected.extend(_wsample(venues, weights, quota, rng))
        return selected

    intl_selected = _region_diverse(intl_rows, n_intl, deterministic=True)
    intl_ids = {v[0] for v in intl_selected}

    dom_rows = [(vid, vname, country, cnt) for vid, vname, country, cnt in all_rows
                if vid not in intl_ids]
    dom_selected = _region_diverse(dom_rows, n_dom) if dom_rows and n_dom > 0 else []

    combined = intl_selected + dom_selected
    # De-dup by venue_id
    seen = set()
    result = []
    for v in combined:
        if v[0] not in seen:
            seen.add(v[0])
            result.append(v)

    # Top up if short
    if len(result) < n:
        extra_rows = [(vid, vname, country, region, cnt) for vid, vname, country, region, cnt
                      in _region_diverse(all_rows, n)
                      if vid not in seen]
        result += extra_rows[:n - len(result)]

    return result[:n]


# ─────────────────────────────────────────────────────────────────────────────
# Target selection — batters (position-stratified, international-biased)
# ─────────────────────────────────────────────────────────────────────────────

def select_batters(repo, match_format, gender, n, rng,
                   min_intl_player_balls=500, min_dom_player_balls=800, intl_frac=0.70):
    raw_fmts = repo._raw_formats(match_format)
    n_intl = max(1, round(n * intl_frac))
    n_dom  = n - n_intl

    def _query(match_type_clause, min_b):
        return repo._run_query(f"""
            WITH first_ball AS (
                SELECT d.match_id, d.inning_number, d.batter_id,
                       MIN(d.over_number * 1000 + d.ball_number) AS first_key
                FROM history.deliveries d
                JOIN history.matches m ON d.match_id = m.match_id
                WHERE m.match_format = ANY(%s) AND m.gender = %s {match_type_clause}
                GROUP BY d.match_id, d.inning_number, d.batter_id
            ),
            ranked AS (
                SELECT batter_id,
                       RANK() OVER (PARTITION BY match_id, inning_number ORDER BY first_key) AS pos
                FROM first_ball
            ),
            avg_pos AS (
                SELECT batter_id, AVG(pos) AS avg_pos
                FROM ranked GROUP BY batter_id HAVING COUNT(*) >= 5
            ),
            balls AS (
                SELECT d.batter_id, COUNT(*) AS ball_count
                FROM history.deliveries d
                JOIN history.matches m ON d.match_id = m.match_id
                WHERE m.match_format = ANY(%s) AND m.gender = %s {match_type_clause}
                GROUP BY d.batter_id
            )
            SELECT p.player_id, p.name, ap.avg_pos, b.ball_count
            FROM avg_pos ap
            JOIN balls b ON b.batter_id = ap.batter_id
            JOIN history.players p ON p.player_id = ap.batter_id
            WHERE b.ball_count >= %s
            ORDER BY b.ball_count DESC
        """, (raw_fmts, gender, raw_fmts, gender, min_b))

    intl_rows = _query("AND m.match_type = 'international'", min_intl_player_balls)
    all_rows  = _query("", min_dom_player_balls)

    def _position_stratified(rows, k, seen=None, deterministic=False):
        """
        deterministic=True: take top-k by ball_count from each group (no randomness).
                            Used for international slots to guarantee famous players.
        deterministic=False: weighted random. Used for domestic slots.
        """
        seen = seen or set()
        groups = {'opener': [], 'top_order': [], 'middle_order': [], 'lower_order': [], 'tail': []}
        for pid, name, avg_pos, balls in rows:
            if pid in seen: continue
            if   avg_pos <= 2.0: groups['opener'].append((pid, name, avg_pos, balls))
            elif avg_pos <= 3.5: groups['top_order'].append((pid, name, avg_pos, balls))
            elif avg_pos <= 6.0: groups['middle_order'].append((pid, name, avg_pos, balls))
            elif avg_pos <= 8.5: groups['lower_order'].append((pid, name, avg_pos, balls))
            else:                groups['tail'].append((pid, name, avg_pos, balls))

        shares = {'opener': 0.20, 'top_order': 0.20, 'middle_order': 0.30,
                  'lower_order': 0.20, 'tail': 0.10}
        selected = []
        for grp, share in shares.items():
            quota = max(1, round(share * k))
            avl = sorted(groups[grp], key=lambda x: x[3], reverse=True)  # sorted by balls desc
            if not avl: continue
            if deterministic:
                chosen = avl[:min(quota, len(avl))]
            else:
                w = [math.sqrt(p[3]) for p in avl]
                chosen = _wsample(avl, w, min(quota, len(avl)), rng)
            for item in chosen:
                selected.append((*item, grp))
                seen.add(item[0])
        if len(selected) < k:
            all_avl = sorted(
                [(*p, grp) for grp, ps in groups.items() for p in ps if p[0] not in seen],
                key=lambda x: x[3], reverse=True
            )
            if deterministic:
                for item in all_avl[:k - len(selected)]:
                    selected.append(item); seen.add(item[0])
            else:
                w = [math.sqrt(p[3]) for p in all_avl]
                for item in _wsample(all_avl, w, k - len(selected), rng):
                    selected.append(item); seen.add(item[0])
        return selected

    intl_selected = _position_stratified(intl_rows, n_intl, deterministic=True)
    intl_ids = {p[0] for p in intl_selected}
    dom_selected  = _position_stratified(all_rows, n_dom, seen=set(intl_ids), deterministic=False)

    combined = intl_selected + dom_selected
    # De-dup
    seen = set()
    result = []
    for p in combined:
        if p[0] not in seen:
            seen.add(p[0])
            result.append(p)
    return result[:n]


# ─────────────────────────────────────────────────────────────────────────────
# Target selection — bowlers (type/phase-stratified, international-biased)
# ─────────────────────────────────────────────────────────────────────────────

def select_bowlers(repo, match_format, gender, n, rng,
                   min_intl_player_balls=300, min_dom_player_balls=500, intl_frac=0.70):
    raw_fmts  = repo._raw_formats(match_format)
    threshold = BOWLER_FULLTIME_THRESHOLDS.get(match_format, 120)
    pp_end      = {'T20':  5, 'ODI':  9, 'Test': 20}[match_format]
    death_start = {'T20': 15, 'ODI': 40, 'Test': 60}[match_format]
    n_intl = max(1, round(n * intl_frac))
    n_dom  = n - n_intl

    def _query(match_type_clause, min_b):
        return repo._run_query(f"""
            SELECT p.player_id, p.name, COUNT(*) AS career_balls, AVG(d.over_number) AS avg_over
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            JOIN history.players p ON d.bowler_id = p.player_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s {match_type_clause}
            GROUP BY p.player_id, p.name
            HAVING COUNT(*) >= %s
            ORDER BY career_balls DESC
        """, (raw_fmts, gender, min_b))

    intl_rows = _query("AND m.match_type = 'international'", min_intl_player_balls)
    all_rows  = _query("", min_dom_player_balls)

    all_ids  = list({r[0] for r in intl_rows} | {r[0] for r in all_rows})
    spin_ids = repo.get_spinner_ids(all_ids, gender, match_format=match_format) if all_ids else set()

    def _classify(rows):
        groups = defaultdict(list)
        for pid, name, career_balls, avg_over in rows:
            is_ft = career_balls >= threshold
            style = 'spin' if pid in spin_ids else 'pace'
            if is_ft:
                if avg_over <= pp_end:        phase = 'powerplay'
                elif avg_over >= death_start: phase = 'death'
                else:                         phase = 'middle'
                label = f"fulltime-{style}-{phase}"
            else:
                label = f"parttimer-{style}"
            groups[label].append((pid, name, int(career_balls), avg_over, label))
        return groups

    def _type_stratified(rows, k, seen=None, deterministic=False):
        seen = seen or set()
        groups = _classify([(r[0], r[1], r[2], r[3]) for r in rows if r[0] not in seen])
        per_group = max(1, k // max(len(groups), 1))
        selected = []
        for label, players in sorted(groups.items()):
            avl = sorted(players, key=lambda x: x[2], reverse=True)
            if deterministic:
                chosen = avl[:min(per_group, len(avl))]
            else:
                w = [math.sqrt(p[2]) for p in avl]
                chosen = _wsample(avl, w, min(per_group, len(avl)), rng)
            for item in chosen:
                if item[0] not in seen:
                    selected.append(item)
                    seen.add(item[0])
        if len(selected) < k:
            all_avl = sorted(
                [p for ps in groups.values() for p in ps if p[0] not in seen],
                key=lambda x: x[2], reverse=True
            )
            if deterministic:
                for item in all_avl[:k - len(selected)]:
                    selected.append(item); seen.add(item[0])
            else:
                w = [math.sqrt(p[2]) for p in all_avl]
                for item in _wsample(all_avl, w, k - len(selected), rng):
                    selected.append(item); seen.add(item[0])
        return selected

    intl_selected = _type_stratified(intl_rows, n_intl, deterministic=True)
    intl_ids_set = {p[0] for p in intl_selected}
    dom_selected  = _type_stratified(all_rows, n_dom, seen=set(intl_ids_set), deterministic=False)

    combined = intl_selected + dom_selected
    seen = set()
    result = []
    for p in combined:
        if p[0] not in seen:
            seen.add(p[0])
            result.append(p)
    return result[:n]


# ─────────────────────────────────────────────────────────────────────────────
# Historical match discovery
# ─────────────────────────────────────────────────────────────────────────────

def find_venue_matches(repo, venue_id, match_format, gender, n=20):
    raw_fmts = repo._raw_formats(match_format)
    rows = repo._run_query("""
        SELECT m.match_id
        FROM history.matches m
        JOIN (SELECT match_id FROM history.deliveries
              WHERE inning_number <= 2 GROUP BY match_id HAVING COUNT(*) >= 100) d
          ON d.match_id = m.match_id
        WHERE m.venue_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
        ORDER BY m.date DESC NULLS LAST
        LIMIT %s
    """, (venue_id, raw_fmts, gender, n))
    return [r[0] for r in rows]


def find_player_matches(repo, player_id, match_format, gender, n=20):
    raw_fmts = repo._raw_formats(match_format)
    rows = repo._run_query("""
        SELECT sub.match_id
        FROM (
            SELECT mp.match_id, MAX(m.date) AS match_date
            FROM history.match_players mp
            JOIN history.matches m ON mp.match_id = m.match_id
            JOIN (SELECT match_id FROM history.deliveries
                  WHERE inning_number <= 2 GROUP BY match_id HAVING COUNT(*) >= 100) d
              ON d.match_id = mp.match_id
            WHERE mp.player_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY mp.match_id
        ) sub
        ORDER BY sub.match_date DESC NULLS LAST
        LIMIT %s
    """, (player_id, raw_fmts, gender, n))
    return [r[0] for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Batch match builder (reused from v1)
# ─────────────────────────────────────────────────────────────────────────────

def batch_build_matches(repo, all_match_ids, match_format, _w=print):
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

    _w("  [Batch] Match metadata …")
    meta_rows = repo._run_query("""
        SELECT m.match_id, m.venue_id, v.name, v.country, m.home_team_id, m.away_team_id
        FROM history.matches m
        JOIN history.venues v ON m.venue_id = v.venue_id
        WHERE m.match_id = ANY(%s)
    """, (mid_list,))
    match_meta = {r[0]: r[1:] for r in meta_rows}

    _w("  [Batch] Player lineups …")
    player_rows = repo._run_query("""
        SELECT mp.match_id, mp.team_id, t.name, mp.player_id, p.name
        FROM history.match_players mp
        JOIN history.players p ON mp.player_id = p.player_id
        JOIN history.teams   t ON mp.team_id   = t.team_id
        WHERE mp.match_id = ANY(%s)
    """, (mid_list,))

    _w("  [Batch] Batting order …")
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

    _w("  [Batch] Bowling plans …")
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
        ) sub WHERE rn = 1
    """, (mid_list,))
    bowling_plans: Dict[int, Dict] = {}
    for mid, inning, over, bowler_id in bow_rows:
        bowling_plans.setdefault(mid, {}).setdefault(inning, {})[over] = bowler_id

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
        from simulator.entities.match import SimulationMatch
        from simulator.entities.team import MatchTeam
        resolved[mid] = SimulationMatch(
            id=mid,
            home_team=MatchTeam(id=1, name=ordered[0]['name'], players=ordered[0]['players']),
            away_team=MatchTeam(id=2, name=ordered[1]['name'], players=ordered[1]['players']),
            venue=venue, match_format=fmt, balls_per_over=6, **fs,
        )

    _w(f"  [Batch] Done — {len(resolved)} matches ready.")
    return match_configs, bowling_plans, resolved


# ─────────────────────────────────────────────────────────────────────────────
# Venue cache pre-loading
# ─────────────────────────────────────────────────────────────────────────────

def preload_venue_caches(repo, unique_venues, all_player_ids, fmt, gender, is_test, _w):
    from simulator.predictors.bowling.historical.base import _region_countries
    cache = {}
    n = len(unique_venues)
    _w(f"  Pre-loading venue caches for {n} unique venues …")
    t0 = time.perf_counter()

    for i, (vid, venue_obj) in enumerate(unique_venues.items(), 1):
        country = getattr(venue_obj, 'country', None)
        venue_dist = repo.get_venue_distribution(vid, fmt, gender)
        if not venue_dist and country:
            venue_dist = repo.get_country_distribution(country, fmt, gender)
        pv_dist = repo.get_player_venue_distribution(all_player_ids, vid, fmt, gender)
        pc_dist = {}
        if country:
            country_group = _region_countries(country)
            if country_group:
                pc_dist = repo.get_player_country_distribution(
                    all_player_ids, country_group[0], fmt, gender,
                    countries=country_group,
                )
        over_freq = over_freq_inn1 = over_freq_inn2 = {}
        test_phase_freq = {}
        if is_test:
            test_phase_freq = repo.get_bowler_test_phase_frequency(
                all_player_ids, gender, venue_id=vid) if all_player_ids else {}
        else:
            over_freq      = repo.get_bowler_over_frequency(
                all_player_ids, fmt, gender, venue_id=vid) if all_player_ids else {}
            over_freq_inn1 = repo.get_bowler_over_frequency(
                all_player_ids, fmt, gender, venue_id=vid, inning_number=1) if all_player_ids else {}
            over_freq_inn2 = repo.get_bowler_over_frequency(
                all_player_ids, fmt, gender, venue_id=vid, inning_number=2) if all_player_ids else {}

        cache[vid] = {
            'venue': venue_dist or {},           'player_venue': pv_dist or {},
            'player_country': pc_dist or {},     'over_freq': over_freq,
            'over_freq_inn1': over_freq_inn1,    'over_freq_inn2': over_freq_inn2,
            'test_phase_freq': test_phase_freq,
        }

    elapsed = time.perf_counter() - t0
    _w(f"  Venue cache pre-load done  ({elapsed:.1f}s)")
    return cache


def apply_venue_caches(out_strat, venue_id, venue_caches):
    vc = venue_caches.get(venue_id)
    if not vc:
        return
    out_strat.venue_cache          = vc['venue']
    out_strat.player_venue_cache   = vc['player_venue']
    out_strat.player_country_cache = vc['player_country']


# ─────────────────────────────────────────────────────────────────────────────
# Historical ground truth loaders
# ─────────────────────────────────────────────────────────────────────────────

def _accumulate_deliveries(rows, phase_fn, fmt):
    """Accumulate deliveries into (overall, by_phase) ProfileStats."""
    overall  = ProfileStats()
    by_phase = defaultdict(ProfileStats)
    for over0, rb, rx_or_ot, ot_or_None in rows:
        if ot_or_None is None:
            rb, rx, ot = over0, rx_or_ot, ot_or_None
        rb, rx, ot = rb, rx_or_ot, ot_or_None
        wkt   = ot == 'Wicket'
        dot   = (rb == 0 and rx == 0 and not wkt)
        phase = MatchRules.get_fine_grained_phase(over0 + 1, fmt)
        for acc in (overall, by_phase[phase]):
            acc.n          += 1
            acc.total_runs += rb + rx
            if rb >= 4: acc.n_boundary += 1
            if wkt:     acc.n_wicket   += 1
            if dot:     acc.n_dot      += 1
    return overall, dict(by_phase)


def load_hist_batter_stats(repo, player_id, match_format, gender, match_ids=None):
    raw_fmts = repo._raw_formats(match_format)
    if match_ids:
        rows = repo._run_query("""
            SELECT d.over_number, d.runs_batter, d.runs_extras, d.outcome_type
            FROM history.deliveries d
            WHERE d.batter_id = %s AND d.match_id = ANY(%s)
        """, (player_id, match_ids))
    else:
        rows = repo._run_query("""
            SELECT d.over_number, d.runs_batter, d.runs_extras, d.outcome_type
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE d.batter_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
        """, (player_id, raw_fmts, gender))
    overall  = ProfileStats()
    by_phase = defaultdict(ProfileStats)
    for over0, rb, rx, ot in rows:
        wkt   = ot == 'Wicket'
        dot   = (rb == 0 and rx == 0 and not wkt)
        phase = MatchRules.get_fine_grained_phase(over0 + 1, match_format)
        for acc in (overall, by_phase[phase]):
            acc.n          += 1
            acc.total_runs += rb + rx
            if rb >= 4: acc.n_boundary += 1
            if wkt:     acc.n_wicket   += 1
            if dot:     acc.n_dot      += 1
    return overall, dict(by_phase)


def load_hist_bowler_stats(repo, player_id, match_format, gender, match_ids=None):
    raw_fmts = repo._raw_formats(match_format)
    if match_ids:
        rows = repo._run_query("""
            SELECT d.over_number, d.runs_batter, d.runs_extras, d.outcome_type
            FROM history.deliveries d
            WHERE d.bowler_id = %s AND d.match_id = ANY(%s)
        """, (player_id, match_ids))
    else:
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
        dot   = (rb == 0 and rx == 0 and not wkt)
        phase = MatchRules.get_fine_grained_phase(over0 + 1, match_format)
        for acc in (overall, by_phase[phase]):
            acc.n          += 1
            acc.total_runs += rb + rx
            if rb >= 4: acc.n_boundary += 1
            if wkt:     acc.n_wicket   += 1
            if dot:     acc.n_dot      += 1
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
    return (f"  {label:<20}  n={sim.n:>8}/{hist.n:<8}"
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
        if not self.checks: return f"  {self.label:<60}  no data"
        n_pass = sum(self.checks)
        n_tot  = len(self.checks)
        pct    = 100 * n_pass / n_tot
        bar    = '█' * int(pct / 10) + '░' * (10 - int(pct / 10))
        return f"  {self.label:<60}  {bar}  {n_pass}/{n_tot} ({pct:.0f}%)"


# ─────────────────────────────────────────────────────────────────────────────
# Historical-only reporter  (no simulation, just DB ground truth)
# ─────────────────────────────────────────────────────────────────────────────

def _report_hist_only(
    repo, fmt, gender, match_format,
    all_match_ids, venue_match_pool, player_match_pool,
    venues, batters, bowlers,
    target_bids, target_bowids,
    _w, fmt_fh,
):
    _w(f"\n\n{'━'*90}")
    _w(f"  HISTORICAL GROUND TRUTH  ({match_format}) — from simulated match pools only")
    _w(f"{'━'*90}")

    all_mid_list = list(all_match_ids)
    venue_pool_sets  = {vid: set(mids) for vid, mids in venue_match_pool.items()}
    player_pool_sets = {pid: set(mids) for pid, mids in player_match_pool.items()}

    # match → venue map (lightweight)
    meta_rows = repo._run_query("""
        SELECT match_id, venue_id FROM history.matches WHERE match_id = ANY(%s)
    """, (all_mid_list,))
    mid_to_vid = {r[0]: r[1] for r in meta_rows}

    # Bulk deliveries for all simulated matches
    _w("  Loading deliveries …")
    all_del_rows = repo._run_query("""
        SELECT d.match_id, d.inning_number, d.over_number,
               d.runs_batter, d.runs_extras, d.outcome_type
        FROM history.deliveries d
        WHERE d.match_id = ANY(%s) AND d.inning_number <= 2
    """, (all_mid_list,))

    _inning_runs:  Dict[Tuple, int] = defaultdict(int)
    _inning_wkts:  Dict[Tuple, int] = defaultdict(int)
    fmt_phase: Dict[str, ProfileStats] = defaultdict(ProfileStats)
    venue_phases: Dict[int, Dict[str, ProfileStats]] = {
        v[0]: defaultdict(ProfileStats) for v in venues
    }

    for mid, inn_num, over0, rb, rx, ot in all_del_rows:
        wkt   = ot == 'Wicket'
        dot   = (rb == 0 and rx == 0 and not wkt)
        runs  = rb + rx
        phase = MatchRules.get_fine_grained_phase(over0 + 1, fmt)
        key   = (mid, inn_num)
        _inning_runs[key] += runs
        if wkt: _inning_wkts[key] += 1
        acc = fmt_phase[phase]
        acc.n += 1; acc.total_runs += runs
        if rb >= 4: acc.n_boundary += 1
        if wkt:     acc.n_wicket   += 1
        if dot:     acc.n_dot      += 1
        vid = mid_to_vid.get(mid)
        if vid and vid in venue_phases and mid in venue_pool_sets.get(vid, set()):
            vacc = venue_phases[vid][phase]
            vacc.n += 1; vacc.total_runs += runs
            if rb >= 4: vacc.n_boundary += 1
            if wkt:     vacc.n_wicket   += 1
            if dot:     vacc.n_dot      += 1

    scores_all   = list(_inning_runs.values())
    wkts_per_inn = [_inning_wkts.get(k, 0) for k in _inning_runs]
    venue_scores: Dict[int, List[int]] = defaultdict(list)
    for (mid, inn_num), runs in _inning_runs.items():
        vid = mid_to_vid.get(mid)
        if vid and mid in venue_pool_sets.get(vid, set()):
            venue_scores[vid].append(runs)

    # Batter stats
    _w("  Loading batter stats …")
    all_player_mids = set()
    for mids in player_match_pool.values(): all_player_mids.update(mids)
    all_player_mids_list = list(all_player_mids)

    bat_rows = repo._run_query("""
        SELECT d.batter_id, d.match_id, d.over_number,
               d.runs_batter, d.runs_extras, d.outcome_type
        FROM history.deliveries d
        WHERE d.batter_id = ANY(%s) AND d.match_id = ANY(%s) AND d.inning_number <= 2
    """, (list(target_bids), all_player_mids_list)) if all_player_mids_list else []

    bat_acc: Dict[int, list] = {
        pid: [ProfileStats(), defaultdict(ProfileStats)] for pid in target_bids
    }
    for bid, mid, over0, rb, rx, ot in bat_rows:
        if bid not in bat_acc: continue
        if mid not in player_pool_sets.get(bid, set()): continue
        wkt   = ot == 'Wicket'
        dot   = (rb == 0 and rx == 0 and not wkt)
        runs  = rb + rx
        phase = MatchRules.get_fine_grained_phase(over0 + 1, fmt)
        ov_a, ph_a = bat_acc[bid]
        for acc in (ov_a, ph_a[phase]):
            acc.n += 1; acc.total_runs += runs
            if rb >= 4: acc.n_boundary += 1
            if wkt:     acc.n_wicket   += 1
            if dot:     acc.n_dot      += 1

    # Bowler stats
    _w("  Loading bowler stats …")
    bow_rows = repo._run_query("""
        SELECT d.bowler_id, d.match_id, d.over_number,
               d.runs_batter, d.runs_extras, d.outcome_type
        FROM history.deliveries d
        WHERE d.bowler_id = ANY(%s) AND d.match_id = ANY(%s) AND d.inning_number <= 2
    """, (list(target_bowids), all_player_mids_list)) if all_player_mids_list else []

    bow_acc: Dict[int, list] = {
        pid: [ProfileStats(), defaultdict(ProfileStats)] for pid in target_bowids
    }
    for bowid, mid, over0, rb, rx, ot in bow_rows:
        if bowid not in bow_acc: continue
        if mid not in player_pool_sets.get(bowid, set()): continue
        wkt   = ot == 'Wicket'
        dot   = (rb == 0 and rx == 0 and not wkt)
        runs  = rb + rx
        phase = MatchRules.get_fine_grained_phase(over0 + 1, fmt)
        ov_a, ph_a = bow_acc[bowid]
        for acc in (ov_a, ph_a[phase]):
            acc.n += 1; acc.total_runs += runs
            if rb >= 4: acc.n_boundary += 1
            if wkt:     acc.n_wicket   += 1
            if dot:     acc.n_dot      += 1

    # Matchup stats
    _w("  Loading matchup data …")
    hist_matchups = repo.get_batter_bowler_matchups(
        list(target_bids), list(target_bowids), fmt, gender, match_ids=all_mid_list)
    player_names = repo.get_player_names(list(target_bids) + list(target_bowids))

    # ── Print: format-level ────────────────────────────────────────────────────
    def _ph(acc: ProfileStats):
        if acc.n == 0: return '—'
        return (f"n={acc.n:>7,}  eco={acc.economy:.2f}"
                f"  bnd={acc.boundary_rate:.3f}  wkt={acc.wicket_rate:.3f}"
                f"  dot={acc.dot_rate:.3f}")

    _w(f"\n  {'─'*88}")
    _w(f"  FORMAT-LEVEL  ({match_format})")
    _w(f"  {'─'*88}")
    if scores_all:
        _w(f"  Avg score/inn : {sum(scores_all)/len(scores_all):.1f}"
           f"  (n={len(scores_all)} innings from {len(all_mid_list)} matches)")
    if wkts_per_inn:
        _w(f"  Avg wickets/inn: {sum(wkts_per_inn)/len(wkts_per_inn):.2f}")
    _w(f"\n  {'Phase':<12}  {'n':>8}  {'economy':>8}  {'bnd%':>7}  {'wkt%':>7}  {'dot%':>7}")
    _w(f"  {'-'*12}  {'-'*8}  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*7}")
    for phase in sorted(fmt_phase):
        h = fmt_phase[phase]
        if h.n == 0: continue
        _w(f"  {phase:<12}  {h.n:>8,}  {h.economy:>8.2f}"
           f"  {h.boundary_rate:>7.3f}  {h.wicket_rate:>7.3f}  {h.dot_rate:>7.3f}")

    # ── Print: venues ──────────────────────────────────────────────────────────
    _w(f"\n\n  {'─'*88}")
    _w(f"  VENUES  ({match_format})")
    _w(f"  {'─'*88}")
    for v_entry in venues:
        vid, vname, country, region, hist_n = v_entry
        ph = venue_phases.get(vid, {})
        sc = venue_scores.get(vid, [])
        pool_n = len(venue_match_pool.get(vid, []))
        _w(f"\n  {vname}  ({country})  pool={pool_n} matches"
           + (f"  avg_score={sum(sc)/len(sc):.1f}" if sc else ''))
        _w(f"  {'Phase':<12}  {'n':>7}  {'economy':>8}  {'bnd%':>7}  {'wkt%':>7}  {'dot%':>7}")
        for phase in sorted(ph):
            h = ph[phase]
            if h.n < 10: continue
            _w(f"  {phase:<12}  {h.n:>7,}  {h.economy:>8.2f}"
               f"  {h.boundary_rate:>7.3f}  {h.wicket_rate:>7.3f}  {h.dot_rate:>7.3f}")

    # ── Print: batters ─────────────────────────────────────────────────────────
    _w(f"\n\n  {'─'*88}")
    _w(f"  BATTERS  ({match_format})")
    _w(f"  {'─'*88}")
    for batter_entry in batters:
        pid, pname, avg_pos, balls, pos_grp = batter_entry
        ov_a, ph_a = bat_acc.get(pid, [ProfileStats(), {}])
        pool_n = len(player_match_pool.get(pid, []))
        _w(f"\n  {pname}  ({pos_grp}, avg_pos={avg_pos:.1f})  pool={pool_n} matches")
        _w(f"  {'Phase':<12}  {'n':>7}  {'economy':>8}  {'bnd%':>7}  {'wkt%':>7}  {'dot%':>7}")
        if ov_a.n > 0:
            _w(f"  {'overall':<12}  {ov_a.n:>7,}  {ov_a.economy:>8.2f}"
               f"  {ov_a.boundary_rate:>7.3f}  {ov_a.wicket_rate:>7.3f}"
               f"  {ov_a.dot_rate:>7.3f}")
        for phase in sorted(ph_a):
            h = ph_a[phase]
            if h.n < 5: continue
            _w(f"  {phase:<12}  {h.n:>7,}  {h.economy:>8.2f}"
               f"  {h.boundary_rate:>7.3f}  {h.wicket_rate:>7.3f}  {h.dot_rate:>7.3f}")

    # ── Print: bowlers ─────────────────────────────────────────────────────────
    _w(f"\n\n  {'─'*88}")
    _w(f"  BOWLERS  ({match_format})")
    _w(f"  {'─'*88}")
    for bowler_entry in bowlers:
        pid, pname, career_balls, avg_over, btype = bowler_entry
        ov_a, ph_a = bow_acc.get(pid, [ProfileStats(), {}])
        pool_n = len(player_match_pool.get(pid, []))
        _w(f"\n  {pname}  ({btype}, avg_over={avg_over:.1f})  pool={pool_n} matches")
        _w(f"  {'Phase':<12}  {'n':>7}  {'economy':>8}  {'bnd%':>7}  {'wkt%':>7}  {'dot%':>7}")
        if ov_a.n > 0:
            _w(f"  {'overall':<12}  {ov_a.n:>7,}  {ov_a.economy:>8.2f}"
               f"  {ov_a.boundary_rate:>7.3f}  {ov_a.wicket_rate:>7.3f}"
               f"  {ov_a.dot_rate:>7.3f}")
        for phase in sorted(ph_a):
            h = ph_a[phase]
            if h.n < 5: continue
            _w(f"  {phase:<12}  {h.n:>7,}  {h.economy:>8.2f}"
               f"  {h.boundary_rate:>7.3f}  {h.wicket_rate:>7.3f}  {h.dot_rate:>7.3f}")

    # ── Print: matchups ────────────────────────────────────────────────────────
    _w(f"\n\n  {'─'*88}")
    _w(f"  BATTER-BOWLER MATCHUPS  ({match_format}) — top 50 by balls")
    _w(f"  {'─'*88}")
    _w(f"  {'Batter':<25}  {'Bowler':<25}  {'balls':>6}"
       f"  {'economy':>8}  {'bnd%':>7}  {'wkt%':>7}  {'dot%':>7}")
    _w(f"  {'-'*25}  {'-'*25}  {'-'*6}  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*7}")
    sorted_mu = sorted(hist_matchups.items(), key=lambda x: x[1]['balls'], reverse=True)
    for (bid, bowid), stats in sorted_mu[:50]:
        bname   = player_names.get(bid,   str(bid))[:25]
        bowname = player_names.get(bowid, str(bowid))[:25]
        _w(f"  {bname:<25}  {bowname:<25}  {stats['balls']:>6}"
           f"  {stats['economy']:>8.2f}  {stats['boundary_rate']:>7.3f}"
           f"  {stats['wicket_rate']:>7.3f}  {stats['dot_rate']:>7.3f}")

    _w(f"\n  Total matchup pairs: {len(hist_matchups)}"
       f"  (showing top {min(50, len(hist_matchups))} by balls)")


# ─────────────────────────────────────────────────────────────────────────────
# Per-format worker  (runs in a subprocess for parallel execution)
# ─────────────────────────────────────────────────────────────────────────────

def run_format(match_format, cfg, run_dir, seed, gender, hist_only=False):
    """Validate one format end-to-end. Designed to run in a subprocess."""
    from simulator.match_logger import MatchLogger
    MatchLogger.SILENT = True
    from simulator.predictors.factory import OutcomeStrategyFactory
    from simulator.engines.engine_factory import EngineFactory
    from simulator.entities.match import SimulationMatch
    from simulator.entities.team import MatchTeam

    rng  = random.Random(seed)
    repo = StatsRepository()

    R              = cfg['R']
    venue_matches  = cfg['venue_matches']
    player_matches = cfg['player_matches']
    n_venues       = cfg['n_venues']
    n_batters      = cfg['n_batters']
    n_bowlers      = cfg['n_bowlers']
    intl_frac      = cfg['intl_frac']
    fmt            = MatchRules.get_unified_format(match_format)
    is_test        = (match_format == 'Test')

    pfx      = f'[{match_format}]'
    fmt_path = os.path.join(run_dir, f'{match_format}.txt')
    fmt_fh   = open(fmt_path, 'w', encoding='utf-8')

    def _w(line=''):
        out = f'{pfx} {line}' if line else ''
        print(out, flush=True)
        print(line, file=fmt_fh, flush=True)

    _w(f"\n\n{'━'*90}")
    _w(f"  FORMAT: {match_format}   ({R} sims/match, {venue_matches} matches/venue,"
       f" {player_matches} matches/player, intl_bias={int(intl_frac*100)}%)")
    _w(f"{'━'*90}")

    # ── Select targets ─────────────────────────────────────────────────────────
    _w("\n  Selecting targets …")
    venues  = select_venues (repo, fmt, gender, n_venues,  rng,
                             min_intl_venue_del=cfg['min_intl_venue_del'],
                             min_dom_venue_del=cfg['min_dom_venue_del'],
                             intl_frac=intl_frac)
    batters = select_batters(repo, fmt, gender, n_batters, rng,
                             min_intl_player_balls=cfg['min_intl_player_balls'],
                             min_dom_player_balls=cfg['min_dom_player_balls'],
                             intl_frac=intl_frac)
    bowlers = select_bowlers(repo, fmt, gender, n_bowlers, rng,
                             min_intl_player_balls=cfg['min_intl_player_balls'] // 2,
                             min_dom_player_balls=cfg['min_dom_player_balls'] // 2,
                             intl_frac=intl_frac)

    target_vids   = {v[0] for v in venues}
    target_bids   = {b[0] for b in batters}
    target_bowids = {b[0] for b in bowlers}

    _w(f"\n  Targets selected:")
    _w(f"    Venues  ({len(venues)}): " + ", ".join(v[1][:22] for v in venues))
    _w(f"    Batters ({len(batters)}): " + ", ".join(b[1] for b in batters))
    _w(f"    Bowlers ({len(bowlers)}): " + ", ".join(b[1] for b in bowlers))

    # ── Discover historical matches ────────────────────────────────────────────
    venue_match_pool:  Dict[int, List[int]] = {}
    player_match_pool: Dict[int, List[int]] = {}
    for vid, *_ in venues:
        venue_match_pool[vid] = find_venue_matches(repo, vid, fmt, gender, n=venue_matches)
    for pid, *_ in batters + bowlers:
        player_match_pool[pid] = find_player_matches(repo, pid, fmt, gender, n=player_matches)

    all_match_ids: Set[int] = set()
    for ids in venue_match_pool.values():  all_match_ids.update(ids)
    for ids in player_match_pool.values(): all_match_ids.update(ids)

    _w(f"\n  {len(all_match_ids)} unique historical matches"
       + (f" to simulate ({R} times each = {len(all_match_ids) * R} total simulations)"
          if not hist_only else " (hist-only — no simulations)"))

    # ── Hist-only: compute and print historical ground truth, then return ──────
    if hist_only:
        _report_hist_only(
            repo, fmt, gender, match_format,
            all_match_ids, venue_match_pool, player_match_pool,
            venues, batters, bowlers,
            target_bids, target_bowids,
            _w, fmt_fh,
        )
        fmt_fh.close()
        return [], {}, fmt_path

    match_configs, bowling_plans, resolved = batch_build_matches(
        repo, all_match_ids, match_format, _w)
    if not resolved:
        _w("  ERROR: no matches resolved — skipping format")
        fmt_fh.close()
        return [], {}, fmt_path

    # ── Union player set for one-shot cache init ───────────────────────────────
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
    out_strat = OutcomeStrategyFactory.for_name('enhanced', fmt)
    out_strat.init_model(union_match)
    _w("  Player caches ready.")

    unique_venues_in_pool: Dict[int, object] = {}
    for m in resolved.values():
        v = m.venue
        if v and v.id and v.id not in unique_venues_in_pool:
            unique_venues_in_pool[v.id] = v

    all_pids_list = list(seen_pids)
    venue_caches = preload_venue_caches(
        repo, unique_venues_in_pool, all_pids_list, fmt, gender, is_test, _w)

    # ── Pre-compute all historical stats (before simulation) ──────────────────
    _w("  Pre-computing historical stats from selected matches …")
    t_hist = time.perf_counter()

    all_mid_list = list(resolved.keys())
    mid_to_vid   = {mid: mc['_venue_id'] for mid, mc in match_configs.items()}

    venue_pool_sets  = {vid: set(mids) for vid, mids in venue_match_pool.items()}
    player_pool_sets = {pid: set(mids) for pid, mids in player_match_pool.items()}

    # One bulk query: all deliveries for all simulated matches
    _w("    Loading all deliveries for simulated matches …")
    all_del_rows = repo._run_query("""
        SELECT d.match_id, d.inning_number, d.over_number,
               d.runs_batter, d.runs_extras, d.outcome_type
        FROM history.deliveries d
        WHERE d.match_id = ANY(%s) AND d.inning_number <= 2
    """, (all_mid_list,))

    _inning_runs:  Dict[Tuple, int]                  = defaultdict(int)
    _inning_wkts:  Dict[Tuple, int]                  = defaultdict(int)
    hist_phase_acc: Dict[str, ProfileStats]           = defaultdict(ProfileStats)
    hist_inning_phase_acc: Dict[Tuple, ProfileStats]  = defaultdict(ProfileStats)  # (inn_num, phase)
    _hist_venue_phases: Dict[int, Dict]               = {
        v[0]: defaultdict(ProfileStats) for v in venues
    }

    for mid, inn_num, over0, rb, rx, ot in all_del_rows:
        wkt   = ot == 'Wicket'
        dot   = (rb == 0 and rx == 0 and not wkt)
        runs  = rb + rx
        phase = MatchRules.get_fine_grained_phase(over0 + 1, fmt)
        key   = (mid, inn_num)
        _inning_runs[key] += runs
        if wkt:
            _inning_wkts[key] += 1
        # format-level phase (combined + by inning)
        acc = hist_phase_acc[phase]
        acc.n += 1; acc.total_runs += runs
        if rb >= 4: acc.n_boundary += 1
        if wkt:     acc.n_wicket   += 1
        if dot:     acc.n_dot      += 1
        inn_phase_key = (inn_num, phase)
        iacc = hist_inning_phase_acc[inn_phase_key]
        iacc.n += 1; iacc.total_runs += runs
        if rb >= 4: iacc.n_boundary += 1
        if wkt:     iacc.n_wicket   += 1
        if dot:     iacc.n_dot      += 1
        # venue phase — only for matches in that venue's own pool
        vid = mid_to_vid.get(mid)
        if vid and vid in _hist_venue_phases and mid in venue_pool_sets.get(vid, set()):
            vacc = _hist_venue_phases[vid][phase]
            vacc.n += 1; vacc.total_runs += runs
            if rb >= 4: vacc.n_boundary += 1
            if wkt:     vacc.n_wicket   += 1
            if dot:     vacc.n_dot      += 1

    hist_scores_all   = list(_inning_runs.values())
    hist_wkts_per_inn = [_inning_wkts.get(k, 0) for k in _inning_runs]
    hist_venue_phases = {vid: dict(ph) for vid, ph in _hist_venue_phases.items()}
    hist_venue_scores: Dict[int, List[int]] = defaultdict(list)
    for (mid, inn_num), runs in _inning_runs.items():
        vid = mid_to_vid.get(mid)
        if vid and mid in venue_pool_sets.get(vid, set()):
            hist_venue_scores[vid].append(runs)

    # Batter stats — one bulk query, distribute by player pool
    _w("    Loading batter stats …")
    all_player_mids = set()
    for mids in player_match_pool.values(): all_player_mids.update(mids)
    all_player_mids_list = list(all_player_mids)

    bat_del_rows = repo._run_query("""
        SELECT d.batter_id, d.match_id, d.over_number,
               d.runs_batter, d.runs_extras, d.outcome_type
        FROM history.deliveries d
        WHERE d.batter_id = ANY(%s) AND d.match_id = ANY(%s) AND d.inning_number <= 2
    """, (list(target_bids), all_player_mids_list)) if all_player_mids_list else []

    _bat_acc: Dict[int, list] = {
        pid: [ProfileStats(), defaultdict(ProfileStats)] for pid in target_bids
    }
    for bid, mid, over0, rb, rx, ot in bat_del_rows:
        if bid not in _bat_acc: continue
        if mid not in player_pool_sets.get(bid, set()): continue
        wkt   = ot == 'Wicket'
        dot   = (rb == 0 and rx == 0 and not wkt)
        runs  = rb + rx
        phase = MatchRules.get_fine_grained_phase(over0 + 1, fmt)
        ov_acc, ph_acc = _bat_acc[bid]
        for acc in (ov_acc, ph_acc[phase]):
            acc.n += 1; acc.total_runs += runs
            if rb >= 4: acc.n_boundary += 1
            if wkt:     acc.n_wicket   += 1
            if dot:     acc.n_dot      += 1
    hist_bat_stats: Dict[int, Tuple] = {
        pid: (ov, dict(ph)) for pid, (ov, ph) in _bat_acc.items()
    }

    # Bowler stats — one bulk query, distribute by player pool
    _w("    Loading bowler stats …")
    bow_del_rows = repo._run_query("""
        SELECT d.bowler_id, d.match_id, d.over_number,
               d.runs_batter, d.runs_extras, d.outcome_type
        FROM history.deliveries d
        WHERE d.bowler_id = ANY(%s) AND d.match_id = ANY(%s) AND d.inning_number <= 2
    """, (list(target_bowids), all_player_mids_list)) if all_player_mids_list else []

    _bow_acc: Dict[int, list] = {
        pid: [ProfileStats(), defaultdict(ProfileStats)] for pid in target_bowids
    }
    for bowid, mid, over0, rb, rx, ot in bow_del_rows:
        if bowid not in _bow_acc: continue
        if mid not in player_pool_sets.get(bowid, set()): continue
        wkt   = ot == 'Wicket'
        dot   = (rb == 0 and rx == 0 and not wkt)
        runs  = rb + rx
        phase = MatchRules.get_fine_grained_phase(over0 + 1, fmt)
        ov_acc, ph_acc = _bow_acc[bowid]
        for acc in (ov_acc, ph_acc[phase]):
            acc.n += 1; acc.total_runs += runs
            if rb >= 4: acc.n_boundary += 1
            if wkt:     acc.n_wicket   += 1
            if dot:     acc.n_dot      += 1
    hist_bow_stats: Dict[int, Tuple] = {
        pid: (ov, dict(ph)) for pid, (ov, ph) in _bow_acc.items()
    }

    # Matchup stats and player names
    _w("    Loading matchup and player name data …")
    hist_matchups_pre = repo.get_batter_bowler_matchups(
        list(target_bids), list(target_bowids), fmt, gender, match_ids=list(all_match_ids))
    player_names_pre  = repo.get_player_names(list(target_bids) + list(target_bowids))

    _w(f"  Historical stats ready  ({time.perf_counter()-t_hist:.1f}s)")

    # ── Accumulators ───────────────────────────────────────────────────────────
    sim_venue: Dict[int, Dict[str, ProfileStats]] = {
        vid: defaultdict(ProfileStats) for vid in target_vids
    }
    sim_venue_scores: Dict[int, List[int]] = {vid: [] for vid in target_vids}

    def _empty_player_acc():
        return {'overall': ProfileStats(), 'by_phase': defaultdict(ProfileStats)}

    sim_bat: Dict[int, dict] = {pid: _empty_player_acc() for pid in target_bids}
    sim_bow: Dict[int, dict] = {pid: _empty_player_acc() for pid in target_bowids}

    sim_matchup: Dict[Tuple[int,int], ProfileStats] = defaultdict(ProfileStats)

    fmt_phase_acc: Dict[str, ProfileStats] = defaultdict(ProfileStats)
    sim_inning_phase_acc: Dict[Tuple, ProfileStats] = defaultdict(ProfileStats)  # (inn_num, phase)
    fmt_all_scores: List[int] = []
    fmt_all_wickets: List[int] = []

    max_inning = 2

    # ── Simulation loop ────────────────────────────────────────────────────────
    total_sims    = len(resolved) * R
    sims_done     = 0
    matches_done  = 0
    total_matches = len(resolved)
    t_sim_start   = time.perf_counter()

    def _print_progress():
        elapsed = time.perf_counter() - t_sim_start
        pct     = sims_done / total_sims if total_sims else 0
        bar_w   = 30
        filled  = int(bar_w * pct)
        bar     = '█' * filled + '░' * (bar_w - filled)
        eta_str = ''
        if sims_done > 0 and pct < 1.0:
            eta_s = elapsed / pct * (1 - pct)
            m, s  = divmod(int(eta_s), 60)
            eta_str = f'  ETA {m}m{s:02d}s'
        _w(f"  |{bar}| {sims_done}/{total_sims} sims"
           f"  ({pct*100:.1f}%)  match {matches_done}/{total_matches}"
           f"  elapsed {int(elapsed//60)}m{int(elapsed%60):02d}s{eta_str}")

    for mid, resolved_match in resolved.items():
        vid    = mid_to_vid.get(mid)
        hn, hp = resolved_match.home_team.name, list(resolved_match.home_team.players)
        an, ap = resolved_match.away_team.name, list(resolved_match.away_team.players)
        v_obj  = resolved_match.venue
        fs     = {'overs_per_innings': resolved_match.overs_per_innings,
                  'innings_per_match': resolved_match.innings_per_match}

        if v_obj and v_obj.id:
            apply_venue_caches(out_strat, v_obj.id, venue_caches)

        bow_plan     = bowling_plans.get(mid, {})
        hist_bow_str = HistoricalBowlingOrder(bow_plan)

        for r in range(R):
            match = SimulationMatch(
                id=sims_done + 1,
                home_team=MatchTeam(id=1, name=hn, players=hp),
                away_team=MatchTeam(id=2, name=an, players=ap),
                venue=v_obj, match_format=fmt, balls_per_over=6, **fs,
            )
            try:
                EngineFactory.create(match, out_strat, hist_bow_str).simulate()
            except Exception as e:
                _w(f"  WARN: sim {sims_done+1} failed: {e}")
                sims_done += 1; continue

            for inning in match.innings:
                if inning.inning_number > max_inning:
                    continue
                if vid in sim_venue_scores and inning.batting_team:
                    sim_venue_scores[vid].append(inning.batting_team.total_runs)

                if inning.batting_team:
                    fmt_all_scores.append(inning.batting_team.total_runs)
                wkt_count = sum(1 for d in inning.deliveries if d.is_wicket)
                fmt_all_wickets.append(wkt_count)

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

                    _push(fmt_phase_acc[phase])
                    _push(sim_inning_phase_acc[(inning.inning_number, phase)])

                    if vid in sim_venue:
                        _push(sim_venue[vid][phase])

                    bid = delivery.batter.id if delivery.batter else None
                    if bid in sim_bat:
                        _push(sim_bat[bid]['overall'])
                        _push(sim_bat[bid]['by_phase'][phase])

                    bowid = delivery.bowler.id if delivery.bowler else None
                    plan_bowler = bow_plan.get(inning.inning_number, {}).get(delivery.over_number)
                    if bowid in sim_bow and plan_bowler == bowid:
                        _push(sim_bow[bowid]['overall'])
                        _push(sim_bow[bowid]['by_phase'][phase])

                    if bid in target_bids and bowid in target_bowids and plan_bowler == bowid:
                        _push(sim_matchup[(bid, bowid)])

            sims_done += 1
            if sims_done % 50 == 0 or sims_done == total_sims:
                _print_progress()

        matches_done += 1

    # ── Report: format-level overall ──────────────────────────────────────────
    _w(f"\n\n  {'─'*88}")
    _w(f"  FORMAT-LEVEL OVERALL ACCURACY  ({match_format})")
    _w(f"  {'─'*88}")

    if hist_scores_all and fmt_all_scores:
        sim_avg_score  = sum(fmt_all_scores)  / len(fmt_all_scores)
        hist_avg_score = sum(hist_scores_all) / len(hist_scores_all)
        score_ok = '✓' if abs(sim_avg_score - hist_avg_score) < 10 else '✗'
        _w(f"  Score/innings:   sim={sim_avg_score:.1f}  hist={hist_avg_score:.1f}  {score_ok}"
           f"  (sim_n={len(fmt_all_scores)}, hist_n={len(hist_scores_all)})")

    if hist_wkts_per_inn and fmt_all_wickets:
        sim_avg_wkt  = sum(fmt_all_wickets)   / len(fmt_all_wickets)
        hist_avg_wkt = sum(hist_wkts_per_inn) / len(hist_wkts_per_inn)
        wkt_ok = '✓' if abs(sim_avg_wkt - hist_avg_wkt) < 0.5 else '✗'
        _w(f"  Wickets/innings: sim={sim_avg_wkt:.2f}  hist={hist_avg_wkt:.2f}  {wkt_ok}"
           f"  (sim_n={len(fmt_all_wickets)}, hist_n={len(hist_wkts_per_inn)})")

    # ── Report: format-level phase summary ────────────────────────────────────
    _w(f"\n\n  {'─'*88}")
    _w(f"  FORMAT-LEVEL PHASE SUMMARY  ({match_format})")
    _w(f"  {'─'*88}")
    _w(f"  {'Phase':<12}  {'n_sim':>8}  {'bnd_sim/hist':>14}  "
       f"{'wkt_sim/hist':>14}  {'eco_sim/hist':>14}  {'dot_sim/hist':>14}")
    phase_tracker = AccTracker(f"[{match_format}] Phase summary")

    phase_errors: Dict[str, dict] = {}
    for phase in sorted(set(hist_phase_acc) | set(fmt_phase_acc)):
        s = fmt_phase_acc.get(phase, ProfileStats())
        h = hist_phase_acc.get(phase, ProfileStats())
        row = _stat_row(phase, s, h, min_n=100)
        if row:
            _w(row)
            phase_tracker.collect(s, h, min_n=100)
            phase_errors[phase] = {
                'bnd_err': s.boundary_rate - h.boundary_rate,
                'wkt_err': s.wicket_rate   - h.wicket_rate,
                'eco_err': s.economy       - h.economy,
                'dot_err': s.dot_rate      - h.dot_rate,
                'n_sim': s.n, 'n_hist': h.n,
            }
    all_trackers_for_fmt = [phase_tracker]

    # ── Report: format-level phase by innings ─────────────────────────────────
    max_inn = 2 if fmt != 'Test' else 4
    for inn_num in range(1, max_inn + 1):
        inn_phases = [k[1] for k in hist_inning_phase_acc if k[0] == inn_num]
        sim_inn_phases = [k[1] for k in sim_inning_phase_acc if k[0] == inn_num]
        all_phases_inn = sorted(set(inn_phases) | set(sim_inn_phases))
        if not all_phases_inn:
            continue
        _w(f"\n\n  {'─'*88}")
        _w(f"  INNINGS {inn_num} PHASE BREAKDOWN  ({match_format})")
        _w(f"  {'─'*88}")
        _w(f"  {'Phase':<12}  {'n_sim':>8}  {'bnd_sim/hist':>14}  "
           f"{'wkt_sim/hist':>14}  {'eco_sim/hist':>14}  {'dot_sim/hist':>14}")
        for phase in all_phases_inn:
            s = sim_inning_phase_acc.get((inn_num, phase), ProfileStats())
            h = hist_inning_phase_acc.get((inn_num, phase), ProfileStats())
            row = _stat_row(phase, s, h, min_n=50)
            if row:
                _w(row)

    # ── Report: venues ────────────────────────────────────────────────────────
    _w(f"\n\n  {'─'*88}")
    _w(f"  VENUE RESULTS  ({match_format})")
    _w(f"  {'─'*88}")
    for v_entry in venues:
        vid, vname, country, region, hist_n = v_entry
        tracker = AccTracker(f"[{match_format}] Venue: {vname[:35]}")
        _w(f"\n  {vname}  ({country} / {region})  hist_deliveries={hist_n:,}"
           f"  sim_matches={len(venue_match_pool.get(vid, []))*R}")
        try:
            hist_phases = hist_venue_phases.get(vid, {})
            sim_phases  = sim_venue[vid]
            for phase in sorted(set(hist_phases) | set(sim_phases)):
                s = sim_phases.get(phase, ProfileStats())
                h = hist_phases.get(phase, ProfileStats())
                row = _stat_row(phase, s, h, min_n=20)
                if row: _w(row); tracker.collect(s, h, min_n=20)

            sim_scores = sim_venue_scores[vid]
            hist_sc    = hist_venue_scores.get(vid, [])
            if sim_scores and hist_sc:
                sim_avg  = sum(sim_scores) / len(sim_scores)
                hist_avg = sum(hist_sc)    / len(hist_sc)
                ok = '✓' if abs(sim_avg - hist_avg) < 10 else '✗'
                _w(f"  {'score_avg':<20}  sim={sim_avg:.1f}  hist={hist_avg:.1f}  {ok}")
        except Exception as e:
            _w(f"  ERROR: {e}"); traceback.print_exc(file=fmt_fh)
        all_trackers_for_fmt.append(tracker)

    # ── Report: batters ───────────────────────────────────────────────────────
    _w(f"\n\n  {'─'*88}")
    _w(f"  BATTER RESULTS  ({match_format})")
    _w(f"  {'─'*88}")
    for batter_entry in batters:
        pid, pname, avg_pos, balls, pos_grp = batter_entry
        tracker = AccTracker(f"[{match_format}] Batter: {pname[:30]} ({pos_grp})")
        _w(f"\n  {pname}  pos_group={pos_grp}  avg_pos={avg_pos:.1f}  hist_balls={balls:,}"
           f"  sim_matches={len(player_match_pool.get(pid, []))*R}")
        try:
            hist_ov, hist_ph = hist_bat_stats.get(pid, (ProfileStats(), {}))
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
        all_trackers_for_fmt.append(tracker)

    # ── Report: bowlers ───────────────────────────────────────────────────────
    _w(f"\n\n  {'─'*88}")
    _w(f"  BOWLER RESULTS  ({match_format})")
    _w(f"  {'─'*88}")
    for bowler_entry in bowlers:
        pid, pname, career_balls, avg_over, btype = bowler_entry
        tracker = AccTracker(f"[{match_format}] Bowler: {pname[:30]} ({btype})")
        _w(f"\n  {pname}  type={btype}  career_balls={career_balls:,}  avg_over={avg_over:.1f}"
           f"  sim_matches={len(player_match_pool.get(pid, []))*R}")
        try:
            hist_ov, hist_ph = hist_bow_stats.get(pid, (ProfileStats(), {}))
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
        all_trackers_for_fmt.append(tracker)

    # ── Report: batter-bowler matchups ────────────────────────────────────────
    _w(f"\n\n  {'─'*88}")
    _w(f"  BATTER-BOWLER MATCHUP ANALYSIS  ({match_format})")
    _w(f"  {'─'*88}")
    _w(f"  (Pairs from target batter × target bowler sets with ≥30 sim balls and ≥12 hist balls)")

    hist_matchups = hist_matchups_pre
    player_names  = player_names_pre

    matchup_pairs = []
    for (bid, bowid), sim_acc in sim_matchup.items():
        if sim_acc.n < 30:
            continue
        hist = hist_matchups.get((bid, bowid))
        if not hist or hist['balls'] < 12:
            continue
        matchup_pairs.append((bid, bowid, sim_acc, hist))
    matchup_pairs.sort(key=lambda x: x[3]['balls'], reverse=True)

    matchup_tracker = AccTracker(f"[{match_format}] Matchup")
    _w(f"\n  {'Batter':<25}  {'Bowler':<25}  "
       f"{'h_balls':>7}  {'sim_balls':>9}  "
       f"{'eco_s/h':>12}  {'wkt_s/h':>12}  {'bnd_s/h':>12}  {'dot_s/h':>12}")
    _w(f"  {'-'*25}  {'-'*25}  {'-'*7}  {'-'*9}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*12}")

    for bid, bowid, sim_acc, hist in matchup_pairs[:50]:
        bname   = player_names.get(bid,   str(bid))[:25]
        bowname = player_names.get(bowid, str(bowid))[:25]
        h_eco   = hist['economy']
        h_wkt   = hist['wicket_rate']
        h_bnd   = hist['boundary_rate']
        h_dot   = hist['dot_rate']
        eco_ok  = '✓' if abs(sim_acc.economy       - h_eco) < TOL_ECONOMY  else '✗'
        wkt_ok  = '✓' if abs(sim_acc.wicket_rate   - h_wkt) < TOL_WICKET   else '✗'
        bnd_ok  = '✓' if abs(sim_acc.boundary_rate - h_bnd) < TOL_BOUNDARY else '✗'
        dot_ok  = '✓' if abs(sim_acc.dot_rate      - h_dot) < TOL_DOT      else '✗'
        _w(f"  {bname:<25}  {bowname:<25}  "
           f"{hist['balls']:>7}  {sim_acc.n:>9}  "
           f"  {sim_acc.economy:.2f}/{h_eco:.2f}{eco_ok}"
           f"  {sim_acc.wicket_rate:.3f}/{h_wkt:.3f}{wkt_ok}"
           f"  {sim_acc.boundary_rate:.3f}/{h_bnd:.3f}{bnd_ok}"
           f"  {sim_acc.dot_rate:.3f}/{h_dot:.3f}{dot_ok}")
        matchup_tracker.add(sim_acc.economy,       h_eco, TOL_ECONOMY)
        matchup_tracker.add(sim_acc.wicket_rate,   h_wkt, TOL_WICKET)
        matchup_tracker.add(sim_acc.boundary_rate, h_bnd, TOL_BOUNDARY)
        matchup_tracker.add(sim_acc.dot_rate,      h_dot, TOL_DOT)

    _w(f"\n  Total matchup pairs with sufficient data: {len(matchup_pairs)}"
       f"  (showing top {min(50, len(matchup_pairs))} by hist_balls)")
    if matchup_tracker.checks:
        mpr = 100 * sum(matchup_tracker.checks) / len(matchup_tracker.checks)
        _w(f"  Matchup overall accuracy: {mpr:.1f}%"
           f"  ({sum(matchup_tracker.checks)}/{len(matchup_tracker.checks)})")

    matchup_summary = AccTracker(f"[{match_format}] Matchup summary")
    if matchup_tracker.checks:
        matchup_summary.checks = matchup_tracker.checks
    all_trackers_for_fmt.append(matchup_summary)

    # ── Format summary for root-cause analysis ─────────────────────────────────
    format_summary_entry = {
        'phase_errors':    phase_errors,
        'sim_avg_score':   sum(fmt_all_scores)  / len(fmt_all_scores)  if fmt_all_scores  else 0,
        'hist_avg_score':  sum(hist_scores_all) / len(hist_scores_all) if hist_scores_all else 0,
        'sim_avg_wkt':     sum(fmt_all_wickets)  / len(fmt_all_wickets)  if fmt_all_wickets  else 0,
        'hist_avg_wkt':    sum(hist_wkts_per_inn) / len(hist_wkts_per_inn) if hist_wkts_per_inn else 0,
    }

    fmt_fh.close()
    return all_trackers_for_fmt, format_summary_entry, fmt_path


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main(seed=42, outdir='validation_results', gender='male', hist_only=False):
    from concurrent.futures import ProcessPoolExecutor, as_completed

    ts      = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(outdir, ts)
    os.makedirs(run_dir, exist_ok=True)

    def _progress(line=''):
        print(line, flush=True)

    _progress(f"\n{'═'*90}")
    _progress(f"  COMPREHENSIVE MODEL VALIDATION v2")
    _progress(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}   Seed: {seed}   Gender: {gender}")
    _progress(f"  Output dir: {run_dir}")
    _progress(f"  Formats: {', '.join(FORMAT_SETTINGS)}"
              + ("  — HIST-ONLY (no simulations)" if hist_only else "  — running all in parallel"))
    _progress(f"{'═'*90}")

    all_trackers:   List[AccTracker] = []
    format_summary: Dict[str, dict]  = {}

    results: Dict[str, tuple] = {}
    with ProcessPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_format, match_format, cfg, run_dir, seed + i, gender, hist_only): match_format
            for i, (match_format, cfg) in enumerate(FORMAT_SETTINGS.items())
        }
        for future in as_completed(futures):
            match_format = futures[future]
            try:
                trackers, fmt_summary, fmt_path = future.result()
                results[match_format] = (trackers, fmt_summary)
                _progress(f"  [{match_format}] Complete → {fmt_path}")
            except Exception as exc:
                _progress(f"  [{match_format}] FAILED: {exc}")
                traceback.print_exc()

    for match_format in FORMAT_SETTINGS:
        if match_format in results:
            trackers, fmt_summary = results[match_format]
            all_trackers.extend(trackers)
            format_summary[match_format] = fmt_summary


    # ── Overall summary ────────────────────────────────────────────────────────
    summary_path = os.path.join(run_dir, 'summary.txt')
    with open(summary_path, 'w', encoding='utf-8') as sfh:
        def _s(line=''):
            print(line, flush=True)
            print(line, file=sfh, flush=True)

        _s(f"\n\n{'═'*90}")
        _s("  OVERALL ACCURACY SUMMARY")
        _s(f"{'═'*90}")
        _s(f"\n  {'Target':<62}  {'Accuracy':>12}  Pass/Total")
        _s(f"  {'─'*62}  {'─'*12}  {'─'*10}")

        fmt_rates:  Dict[str, List[float]] = defaultdict(list)
        type_rates: Dict[str, List[float]] = defaultdict(list)

        for t in all_trackers:
            if t.pass_rate is None: continue
            _s(t.summary_line())
            prefix = t.label.split(']')[0].lstrip('[')
            fmt_rates[prefix].append(t.pass_rate)
            for word in ('Venue', 'Batter', 'Bowler', 'Phase', 'Matchup'):
                if word in t.label:
                    type_rates[word].append(t.pass_rate)

        _s(f"\n  Per-format averages:")
        for fk in ('T20', 'ODI', 'Test'):
            rates = fmt_rates.get(fk, [])
            if rates:
                avg = 100 * sum(rates) / len(rates)
                _s(f"    {fk:<6}  {avg:.1f}%  ({len(rates)} validations)")

        _s(f"\n  Per-type averages:")
        for tk in ('Venue', 'Batter', 'Bowler', 'Phase', 'Matchup'):
            rates = type_rates.get(tk, [])
            if rates:
                avg = 100 * sum(rates) / len(rates)
                _s(f"    {tk:<8}  {avg:.1f}%  ({len(rates)} validations)")

        # ── Root-cause analysis ───────────────────────────────────────────────
        _s(f"\n\n{'═'*90}")
        _s("  ROOT-CAUSE ANALYSIS")
        _s(f"{'═'*90}")

        _s("\n  FORMAT-LEVEL SCORE AND WICKET ACCURACY:")
        for fmt_key, fs in format_summary.items():
            if 'sim_avg_score' not in fs: continue
            score_err = fs['sim_avg_score'] - fs['hist_avg_score']
            wkt_err   = fs['sim_avg_wkt']   - fs['hist_avg_wkt']
            _s(f"  {fmt_key:<6}  score: sim={fs['sim_avg_score']:.1f} hist={fs['hist_avg_score']:.1f}"
               f"  err={score_err:+.1f}  |  wickets: sim={fs['sim_avg_wkt']:.2f}"
               f" hist={fs['hist_avg_wkt']:.2f}  err={wkt_err:+.2f}")

        _s("\n  PHASE-LEVEL BIAS ACROSS FORMATS:")
        _s(f"  {'Phase':<12}  {'Format':<6}  {'bnd_err':>8}  {'wkt_err':>8}  "
           f"{'eco_err':>8}  {'dot_err':>8}")
        _s(f"  {'-'*12}  {'-'*6}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}")
        for fmt_key, fs in format_summary.items():
            if 'phase_errors' not in fs: continue
            for phase, errs in sorted(fs['phase_errors'].items()):
                _s(f"  {phase:<12}  {fmt_key:<6}"
                   f"  {errs['bnd_err']:>+8.4f}  {errs['wkt_err']:>+8.4f}"
                   f"  {errs['eco_err']:>+8.4f}  {errs['dot_err']:>+8.4f}")

        _s(f"\n  KEY STRENGTHS / KEY WEAKNESSES (automated):")
        metric_outcomes = {'bnd': [], 'wkt': [], 'eco': [], 'dot': []}
        for fmt_key, fs in format_summary.items():
            if 'phase_errors' not in fs: continue
            for phase, errs in fs['phase_errors'].items():
                for m, key in [('bnd','bnd_err'),('wkt','wkt_err'),('eco','eco_err'),('dot','dot_err')]:
                    metric_outcomes[m].append(errs[key])

        for m, errs in metric_outcomes.items():
            if not errs: continue
            mean_e = sum(errs) / len(errs)
            max_e  = max(errs, key=abs)
            direction = "OVER" if mean_e > 0 else "under"
            _s(f"  {m:<4}  mean_err={mean_e:+.4f}  max_err={max_e:+.4f}  direction={direction}")

        _s(f"\n  INTERPRETATION NOTES:")
        _s(f"  • eco > 0  → simulator produces too many runs in that phase (aggressive batters)")
        _s(f"  • dot < 0  → simulator doesn't produce enough dots (batters too active)")
        _s(f"  • wkt > 0  → simulator dismisses batters too often in that phase")
        _s(f"  • death2 eco < 0 → simulator under-accelerates in final death overs")
        _s(f"  • Large inter-phase variance in a single player → model applies wrong phase-specific")
        _s(f"    profile (possible: sparse historical data → fallback to generic distribution)")

        _s(f"\n  Output files:")
        for fmt_key in FORMAT_SETTINGS:
            _s(f"    {os.path.join(run_dir, fmt_key + '.txt')}")
        _s(f"    {summary_path}")
        _s(f"{'═'*90}\n")

    print(f"\nValidation complete. Results in: {run_dir}", flush=True)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--seed',      type=int, default=42)
    p.add_argument('--outdir',    default='validation_results')
    p.add_argument('--gender',    default='male', choices=['male', 'female'])
    p.add_argument('--formats',   nargs='+', choices=['T20', 'ODI', 'Test'],
                   help='Formats to validate (default: all)')
    p.add_argument('--hist-only', action='store_true',
                   help='Print historical ground truth only; skip all simulations')
    args = p.parse_args()
    if args.formats:
        for _f in list(FORMAT_SETTINGS):
            if _f not in args.formats:
                del FORMAT_SETTINGS[_f]
    main(seed=args.seed, outdir=args.outdir, gender=args.gender,
         hist_only=args.hist_only)
