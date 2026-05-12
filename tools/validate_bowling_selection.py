#!/usr/bin/env python3
"""
Validate bowling-selection accuracy against historical match data.

For every over in a sample of historical matches the strategy is asked to
select the next bowler given the match state up to that point, then
compared to who actually bowled.

Usage:
    python -m tools.validate_bowling_selection --format Test --n 30
    python -m tools.validate_bowling_selection --format T20  --n 50 --gender female

Output:
    Console summary: top-1 and top-3 accuracy, breakdown by phase.
"""

import argparse
import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.stats_repository import StatsRepository
from simulator.entities.rules import MatchRules
from simulator.strategies.bowling.historical import create_historical_bowling_strategy


# ── Lightweight mock objects ──────────────────────────────────────────────────

class _P:
    """Minimal player stub used in mock deliveries."""
    __slots__ = ('id',)
    def __init__(self, pid): self.id = pid


class _Del:
    """Minimal delivery stub for spell-history reconstruction."""
    __slots__ = ('bowler', 'over_number')
    def __init__(self, bowler_id, over_number):
        self.bowler      = _P(bowler_id)
        self.over_number = over_number


class _Inning:
    __slots__ = ('deliveries',)
    def __init__(self): self.deliveries = []


class _InningPlayer:
    """Mirrors the InningPlayer attributes read by the bowling strategy."""
    __slots__ = ('id', 'name', 'balls_bowled', 'runs_conceded', 'wickets_taken')
    def __init__(self, pid, name, balls, runs, wkts):
        self.id            = pid
        self.name          = name
        self.balls_bowled  = balls
        self.runs_conceded = runs
        self.wickets_taken = wkts


class _Team:
    __slots__ = ('inning_players',)
    def __init__(self, players): self.inning_players = players


class _Match:
    """Minimal SimulationMatch stub."""
    def __init__(self, bowling_team, current_bowler, current_over, inning, current_inning=1):
        self.current_bowling_team = bowling_team
        self.current_bowler       = current_bowler
        self.current_over         = current_over   # 0-indexed
        self.current_inning       = current_inning # 1-4 (match inning number)
        self.innings              = [inning]
        self.striker              = None
        self.non_striker          = None
        self.overs_per_innings    = None
        self.match_format         = None           # unused by scoring


# ── Phase label helper ────────────────────────────────────────────────────────

def _phase_label(over_0idx, fmt):
    """Return a readable phase name given a 0-indexed over number."""
    if fmt == 'Test':
        return f'phase{(over_0idx % 80) // 10}'
    if fmt == 'T20':
        if over_0idx < 6:  return 'powerplay'
        if over_0idx >= 15: return 'death'
        return 'middle'
    # ODI
    if over_0idx < 10:  return 'powerplay'
    if over_0idx >= 40: return 'death'
    return 'middle'


# ── Core validation loop ──────────────────────────────────────────────────────

def validate(repo, strategy, fmt, gender, match_ids):
    name_cache = {}

    def _name(pid):
        if pid not in name_cache:
            res = repo.get_player_names([pid])
            name_cache[pid] = res.get(pid, str(pid))
        return name_cache[pid]

    top1_total = top1_correct = 0
    top3_total = top3_correct = 0

    # phase → (correct, total)
    phase_stats  = defaultdict(lambda: [0, 0])
    # bowler_name → (correct, total, top3_correct)
    bowler_stats = defaultdict(lambda: [0, 0, 0])

    for match_id in match_ids:
        deliveries = repo.get_match_ball_log(match_id)
        if not deliveries:
            continue

        # Group by inning
        inning_dels = defaultdict(list)
        for row in deliveries:
            inning_dels[row[0]].append(row)

        for inning_num, rows in inning_dels.items():
            # Derive bowling team: first delivery's bowling_team_id
            bowling_team_id = rows[0][5]

            # All unique bowlers in this inning
            bowler_ids = list({r[3] for r in rows})

            # Build name map for this inning
            names = repo.get_player_names(bowler_ids)
            for pid, n in names.items():
                name_cache[pid] = n

            # Group rows by over (DB is 1-indexed; convert to 0-indexed)
            over_rows = defaultdict(list)
            for row in rows:
                over_rows[row[1]].append(row)   # key = DB over_number (1-indexed)

            sorted_overs = sorted(over_rows.keys())

            # Running stats: pid → [balls, runs, wickets]
            bstats = defaultdict(lambda: [0, 0, 0])

            # Build inning delivery history (0-indexed over numbers)
            mock_inning = _Inning()

            prev_over_bowler_id = None

            for over_db in sorted_overs:
                # over_db is 0-indexed (DB convention)
                # ── Build mock match state ────────────────────────────────────
                ips = [
                    _InningPlayer(pid, names.get(pid, str(pid)),
                                  bstats[pid][0], bstats[pid][1], bstats[pid][2])
                    for pid in bowler_ids
                ]
                ip_by_id = {ip.id: ip for ip in ips}

                current_bowler = ip_by_id.get(prev_over_bowler_id)
                team   = _Team(ips)
                match  = _Match(team, current_bowler, over_db, mock_inning, current_inning=inning_num)

                # ── Predict ────────────────────────────────────────────────────
                try:
                    scored = []
                    for ip in strategy._eligible(team, current_bowler, match):
                        total, _ = strategy._score_and_breakdown(ip, match)
                        scored.append((ip, total))
                    scored.sort(key=lambda x: x[1], reverse=True)
                except Exception:
                    scored = []

                actual_id = over_rows[over_db][0][3]  # first ball's bowler

                if scored:
                    top1_pred_id = scored[0][0].id
                    top3_ids     = {s[0].id for s in scored[:3]}

                    phase = _phase_label(over_db, fmt)
                    actual_name = names.get(actual_id, str(actual_id))

                    top1_total += 1
                    top3_total += 1
                    phase_stats[phase][1] += 1
                    bowler_stats[actual_name][1] += 1

                    if top1_pred_id == actual_id:
                        top1_correct += 1
                        phase_stats[phase][0] += 1
                        bowler_stats[actual_name][0] += 1

                    if actual_id in top3_ids:
                        top3_correct += 1
                        bowler_stats[actual_name][2] += 1

                # ── Advance state: accumulate this over's deliveries ───────────
                for row in over_rows[over_db]:
                    pid, runs_bat, runs_ext, is_wkt = row[3], row[6], row[7], row[8]
                    bstats[pid][0] += 1                     # balls
                    bstats[pid][1] += (runs_bat + runs_ext) # runs
                    bstats[pid][2] += is_wkt                # wickets
                    mock_inning.deliveries.append(_Del(pid, over_db))

                prev_over_bowler_id = over_rows[over_db][0][3]

    return {
        'top1': (top1_correct, top1_total),
        'top3': (top3_correct, top3_total),
        'by_phase':  dict(phase_stats),
        'by_bowler': dict(bowler_stats),
    }


# ── Pretty printing ───────────────────────────────────────────────────────────

def _pct(a, b): return f'{100*a/b:.1f}%' if b else 'n/a'


def print_results(results, fmt):
    c1, t1 = results['top1']
    c3, t3 = results['top3']
    print(f'\n{"="*55}')
    print(f'  Bowling Selection Validation — {fmt}')
    print(f'{"="*55}')
    print(f'  Overs evaluated : {t1}')
    print(f'  Top-1 accuracy  : {c1}/{t1}  ({_pct(c1,t1)})')
    print(f'  Top-3 accuracy  : {c3}/{t3}  ({_pct(c3,t3)})')

    print(f'\n  By phase:')
    for phase in sorted(results['by_phase']):
        c, t = results['by_phase'][phase]
        print(f'    {phase:12s}  {c:4d}/{t:4d}  ({_pct(c,t)})')

    print(f'\n  By bowler (top-20 by volume):')
    bs = sorted(results['by_bowler'].items(), key=lambda x: x[1][1], reverse=True)[:20]
    for name, (c1b, tb, c3b) in bs:
        print(f'    {name:28s}  top1={_pct(c1b,tb):6s}  top3={_pct(c3b,tb):6s}  ({tb} overs)')
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Validate bowling selection against history')
    parser.add_argument('--format', default='Test', choices=['T20', 'ODI', 'Test'])
    parser.add_argument('--gender', default='male')
    parser.add_argument('--n',      type=int, default=30, help='Number of matches to sample')
    args = parser.parse_args()

    fmt    = MatchRules.get_unified_format(args.format)
    gender = args.gender

    repo = StatsRepository()
    print(f'Sampling {args.n} {fmt} {gender} matches…')
    match_ids = repo.get_historical_match_ids(fmt, gender, args.n)
    if not match_ids:
        print('No matches found.')
        return
    print(f'Found {len(match_ids)} matches.')

    # Collect all player IDs across sampled matches
    all_pids = set()
    ball_logs = {}
    for mid in match_ids:
        rows = repo.get_match_ball_log(mid)
        ball_logs[mid] = rows
        for row in rows:
            all_pids.add(row[3])  # bowler_id
    all_pids = list(all_pids)

    print(f'Loading caches for {len(all_pids)} unique players…')
    strategy = create_historical_bowling_strategy(fmt)
    strategy._fmt    = fmt
    strategy._gender = gender
    strategy.career_cache               = repo.get_bowler_career_stats(all_pids, fmt, gender)
    strategy.workload_cache             = repo.get_bowler_workload_stats(all_pids, fmt, gender)
    strategy.form_cache                 = {}
    strategy.matchup_cache              = {}
    strategy.over_freq_cache            = {}
    strategy.over_freq_cache_inn1       = {}
    strategy.over_freq_cache_inn2       = {}
    strategy.global_over_freq_cache     = {}
    strategy.phase_dist_cache           = {}
    strategy.phase_dist_cache_inn1      = {}
    strategy.phase_dist_cache_inn2      = {}
    strategy.test_phase_freq_cache        = {}
    strategy.global_test_phase_freq_cache = {}
    if fmt == 'Test':
        strategy.global_test_phase_freq_cache = repo.get_bowler_test_phase_frequency(all_pids, gender)
    elif fmt == 'T20':
        strategy.global_over_freq_cache = repo.get_bowler_over_frequency(all_pids, fmt, gender)
        strategy.over_freq_cache        = repo.get_bowler_over_frequency(all_pids, fmt, gender, match_type='international')
        strategy.over_freq_cache_inn1   = repo.get_bowler_over_frequency(all_pids, fmt, gender, match_type='international', inning_number=1)
        strategy.over_freq_cache_inn2   = repo.get_bowler_over_frequency(all_pids, fmt, gender, match_type='international', inning_number=2)
        strategy.phase_dist_cache       = repo.get_bowler_phase_overs_distribution(all_pids, fmt, gender, match_type='international')
        strategy.phase_dist_cache_inn1  = repo.get_bowler_phase_overs_distribution(all_pids, fmt, gender, match_type='international', inning_number=1)
        strategy.phase_dist_cache_inn2  = repo.get_bowler_phase_overs_distribution(all_pids, fmt, gender, match_type='international', inning_number=2)
    else:  # ODI
        strategy.global_over_freq_cache = repo.get_bowler_over_frequency(all_pids, fmt, gender)
        strategy.over_freq_cache_inn1   = repo.get_bowler_over_frequency(all_pids, fmt, gender, inning_number=1)
        strategy.over_freq_cache_inn2   = repo.get_bowler_over_frequency(all_pids, fmt, gender, inning_number=2)
        strategy.phase_dist_cache       = repo.get_bowler_phase_overs_distribution(all_pids, fmt, gender)
        strategy.phase_dist_cache_inn1  = repo.get_bowler_phase_overs_distribution(all_pids, fmt, gender, inning_number=1)
        strategy.phase_dist_cache_inn2  = repo.get_bowler_phase_overs_distribution(all_pids, fmt, gender, inning_number=2)

    print('Running validation…')

    # Pass pre-fetched ball logs directly
    class _CachedRepo:
        """Thin wrapper so validate() can call get_match_ball_log without re-querying."""
        def __init__(self, logs, real_repo):
            self._logs = logs
            self._repo = real_repo
        def get_match_ball_log(self, mid): return self._logs.get(mid, [])
        def get_player_names(self, pids): return self._repo.get_player_names(pids)

    results = validate(_CachedRepo(ball_logs, repo), strategy, fmt, gender, match_ids)
    print_results(results, fmt)


if __name__ == '__main__':
    main()
