#!/usr/bin/env python3
"""
Replay a historical match and plot bowling-model scores for every over.

Usage:
    python -m tools.plot_bowling_scores                           # match_id from match_config.json
    python -m tools.plot_bowling_scores --match-id 12345
    python -m tools.plot_bowling_scores --match-id 12345 --inning 2

Outputs (all in one run):
    bowling_f3.png       - 4 subplots: continuity / fatigue / workload / combined F3 vs over
    bowling_affinity.png - phase-affinity heatmap for all players in the match
    bowling_scores.png   - total score (F1+F2+F3+F4) per bowler vs over
"""

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from db.stats_repository import StatsRepository
from simulator.entities.rules import MatchRules
from simulator.predictors.bowling.historical import create_historical_bowling_strategy

# ── Minimal mock objects (same pattern as validate_bowling_selection) ─────────

class _P:
    __slots__ = ('id',)
    def __init__(self, pid): self.id = pid

class _Del:
    __slots__ = ('bowler', 'over_number')
    def __init__(self, bowler_id, over_0idx):
        self.bowler      = _P(bowler_id)
        self.over_number = over_0idx

class _Inning:
    __slots__ = ('deliveries',)
    def __init__(self): self.deliveries = []

class _IP:
    __slots__ = ('id', 'name', 'balls_bowled', 'runs_conceded', 'wickets_taken')
    def __init__(self, pid, name, balls, runs, wkts):
        self.id = pid; self.name = name
        self.balls_bowled = balls; self.runs_conceded = runs; self.wickets_taken = wkts

class _Team:
    __slots__ = ('inning_players',)
    def __init__(self, players): self.inning_players = players

class _Match:
    def __init__(self, team, current_bowler, over_0idx, inning, current_inning=1):
        self.current_bowling_team = team
        self.current_bowler       = current_bowler
        self.current_over         = over_0idx
        self.current_inning       = current_inning  # 1-4 (match inning number)
        self.innings              = [inning]
        self.striker = self.non_striker = None
        self.overs_per_innings = None


# ── Match replay → records ────────────────────────────────────────────────────

def replay_match(repo, strategy, match_id, target_inning):
    """
    Replay one inning of a historical match.
    Returns list of dicts - one per (over, bowler) evaluation.
    """
    rows = repo.get_match_ball_log(match_id)
    if not rows:
        raise RuntimeError(f'No deliveries found for match_id={match_id}')

    # Filter to target inning
    rows = [r for r in rows if r[0] == target_inning]
    if not rows:
        raise RuntimeError(f'No deliveries for inning {target_inning} in match {match_id}')

    # Group by over (DB over_number is 1-indexed)
    by_over = defaultdict(list)
    for r in rows:
        by_over[r[1]].append(r)

    bowling_team_id = rows[0][5]
    bowler_ids      = list({r[3] for r in rows})
    names           = repo.get_player_names(bowler_ids)

    bstats   = defaultdict(lambda: [0, 0, 0])   # pid → [balls, runs, wkts]
    mock_inn = _Inning()
    records  = []
    prev_bowler_id = None

    for over_db in sorted(by_over.keys()):
        over_0 = over_db - 1   # convert to 0-indexed

        # Build InningPlayer list
        ips       = [_IP(pid, names.get(pid, str(pid)),
                         bstats[pid][0], bstats[pid][1], bstats[pid][2])
                     for pid in bowler_ids]
        ip_by_id  = {ip.id: ip for ip in ips}
        cur_bowl  = ip_by_id.get(prev_bowler_id)
        team      = _Team(ips)
        mock_m    = _Match(team, cur_bowl, over_0, mock_inn, current_inning=target_inning)

        actual_id = by_over[over_db][0][3]

        # Evaluate every non-hard-capped player and record scores
        for ip in ips:
            if strategy._hard_cap(ip):
                continue
            try:
                total, factors = strategy._score_and_breakdown(ip, mock_m)
            except Exception:
                continue
            if total <= -900:
                continue

            records.append({
                'over':        over_0,
                'name':        ip.name,
                'id':          ip.id,
                'f1':          factors.get('F1_phase', 0),
                'f2':          factors.get('F2_form', 0),
                'f3_cont':     factors.get('F3_cont', 0),
                'f3_fat':      factors.get('F3_fat', 0),
                'f3_wl':       factors.get('F3_wl', 0),
                'f4':          factors.get('F4_matchup', 0),
                'total':       total,
                'actual':      (ip.id == actual_id),
            })

        # Accumulate this over's balls into state
        for r in by_over[over_db]:
            pid = r[3]
            bstats[pid][0] += 1
            bstats[pid][1] += r[6] + r[7]
            bstats[pid][2] += r[8]
            mock_inn.deliveries.append(_Del(pid, over_0))

        prev_bowler_id = actual_id

    return records, names


# ── Colour assignment ─────────────────────────────────────────────────────────

def _assign_colors(names):
    cmap   = plt.cm.tab20
    unique = sorted(set(names))
    return {n: cmap(i / max(len(unique) - 1, 1)) for i, n in enumerate(unique)}


# ── PNG 1: F3 component breakdown ─────────────────────────────────────────────

def plot_f3(records, out_path):
    names     = sorted({r['name'] for r in records})
    colors    = _assign_colors(names)
    metrics   = [('f3_cont', 'Continuity'), ('f3_fat', 'Fatigue'),
                 ('f3_wl',  'Workload'),    ('f3_combined', 'F3 Combined')]

    fig, axes = plt.subplots(2, 2, figsize=(18, 12), sharex=True)
    fig.suptitle('F3 Spell Score Components - per over (real match replay)', fontsize=13, fontweight='bold')
    axes_flat = [axes[0,0], axes[0,1], axes[1,0], axes[1,1]]

    # Build per-name, per-over lookup
    by_name_over = defaultdict(dict)
    for r in records:
        key = r['name']
        by_name_over[key][r['over']] = r

    all_overs = sorted({r['over'] for r in records})

    for ax, (metric, label) in zip(axes_flat, metrics):
        for name in names:
            d = by_name_over[name]
            overs = sorted(d.keys())
            if metric == 'f3_combined':
                vals = [d[o]['f3_cont'] + d[o]['f3_fat'] + d[o]['f3_wl'] for o in overs]
            else:
                vals = [d[o][metric] for o in overs]

            ax.plot(overs, vals, '-', color=colors[name], linewidth=1.4,
                    alpha=0.85, label=name)

            # Mark overs where this bowler actually bowled
            actual_overs = [o for o in overs if d[o]['actual']]
            actual_vals  = [d[o][metric] if metric != 'f3_combined'
                            else d[o]['f3_cont'] + d[o]['f3_fat'] + d[o]['f3_wl']
                            for o in actual_overs]
            ax.scatter(actual_overs, actual_vals, color=colors[name],
                       s=40, zorder=5, marker='o')

        ax.axhline(0, color='black', linewidth=0.7, linestyle='--')
        ax.set_title(label, fontsize=10)
        ax.set_ylabel('Score contribution')
        ax.grid(True, alpha=0.2)

    axes[1,0].set_xlabel('Over')
    axes[1,1].set_xlabel('Over')

    # Shared legend
    handles = [mpatches.Patch(color=colors[n], label=n) for n in names]
    fig.legend(handles=handles, loc='lower center', ncol=min(len(names), 6),
               fontsize=8, bbox_to_anchor=(0.5, -0.02))

    plt.tight_layout(rect=[0, 0.04, 1, 1])
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f'Saved: {out_path}')
    plt.close()


# ── PNG 2: Phase affinity heatmap ─────────────────────────────────────────────

def plot_affinity(strategy, fmt, player_ids, name_map, out_path):
    if fmt == 'Test':
        phases     = [f'Ph{i}\n({i*10}-{i*10+9})' for i in range(8)]
        phase_keys = list(range(8))
        def freq(pid, k): return strategy.test_phase_freq_cache.get(pid, {}).get(k, 0.0)
        ph_weight  = 25.0
    elif fmt == 'T20':
        phases     = [f'Ov{k+1}' for k in range(20)]
        phase_keys = list(range(20))
        def freq(pid, k): return strategy.global_over_freq_cache.get(pid, {}).get(k, 0.0)
        ph_weight  = 20.0
    else:  # ODI
        phases     = [f'Ov{k*5+1}-{k*5+5}' for k in range(10)]
        phase_keys = list(range(10))
        def freq(pid, k): return strategy.global_over_freq_cache.get(pid, {}).get(k, 0.0)
        ph_weight  = 20.0

    # Only players with any affinity data
    active = [(pid, name_map.get(pid, str(pid))) for pid in player_ids
              if any(freq(pid, k) > 0 for k in phase_keys)]
    active.sort(key=lambda x: -sum(freq(x[0], k) for k in phase_keys))

    if not active:
        print('No phase affinity data found - skipping affinity plot.')
        return

    matrix = np.array([[freq(pid, k) * ph_weight for k in phase_keys]
                        for pid, _ in active])
    labels = [name for _, name in active]

    fig, ax = plt.subplots(figsize=(max(8, len(phases)), max(5, len(active) * 0.5)))
    im = ax.imshow(matrix, aspect='auto', cmap='YlOrRd', vmin=0)

    ax.set_xticks(range(len(phases)))
    ax.set_xticklabels(phases, fontsize=9)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=9)

    # Annotate cells
    for i in range(len(labels)):
        for j in range(len(phases)):
            val = matrix[i, j]
            ax.text(j, i, f'{val:.1f}', ha='center', va='center',
                    fontsize=7, color='black' if val < matrix.max() * 0.6 else 'white')

    plt.colorbar(im, ax=ax, label=f'Phase affinity score (freq × weight)')
    ax.set_title(f'Phase Affinity - {fmt} (F1 score at 0 workload)', fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f'Saved: {out_path}')
    plt.close()


# ── PNG 3: Total scores per over ──────────────────────────────────────────────

def plot_total_scores(records, out_path):
    names     = sorted({r['name'] for r in records})
    colors    = _assign_colors(names)

    fig, ax = plt.subplots(figsize=(18, 7))
    fig.suptitle('Total Bowling Score (F1+F2+F3+F4) - per over (real match replay)',
                 fontsize=13, fontweight='bold')

    by_name_over = defaultdict(dict)
    for r in records:
        by_name_over[r['name']][r['over']] = r

    for name in names:
        d = by_name_over[name]
        overs = sorted(d.keys())
        vals  = [d[o]['total'] for o in overs]

        ax.plot(overs, vals, '-', color=colors[name], linewidth=1.5,
                alpha=0.85, label=name)

        # Stars on overs actually bowled
        ao = [o for o in overs if d[o]['actual']]
        av = [d[o]['total'] for o in ao]
        ax.scatter(ao, av, color=colors[name], s=60, zorder=5, marker='*')

    ax.axhline(0, color='black', linewidth=0.7, linestyle='--')
    ax.set_xlabel('Over', fontsize=11)
    ax.set_ylabel('Total score', fontsize=11)
    ax.grid(True, alpha=0.2)

    handles = [mpatches.Patch(color=colors[n], label=n) for n in names]
    fig.legend(handles=handles, loc='lower center', ncol=min(len(names), 6),
               fontsize=8, bbox_to_anchor=(0.5, -0.04))

    note = '★ = actually bowled that over  ● = F3 evaluation (not selected)'
    ax.text(0.01, 0.01, note, transform=ax.transAxes, fontsize=8, color='grey')

    plt.tight_layout(rect=[0, 0.05, 1, 1])
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f'Saved: {out_path}')
    plt.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Plot bowling scores from a real match replay')
    parser.add_argument('--config',   default='match_config.json')
    parser.add_argument('--match-id', type=int, default=None,
                        help='Override match_id from config')
    parser.add_argument('--inning',   type=int, default=1,
                        help='Which innings to replay (default: 1)')
    parser.add_argument('--out',      default='bowling',
                        help='Output file prefix')
    args = parser.parse_args()

    config_path = args.config if os.path.isabs(args.config) else \
        os.path.join(os.path.dirname(os.path.dirname(__file__)), args.config)
    with open(config_path) as f:
        config = json.load(f)

    fmt    = MatchRules.get_unified_format(config.get('format', 'Test'))
    gender = config.get('gender', 'male')

    match_id = args.match_id or config.get('match_id')
    if not match_id:
        print('No match_id found in config or CLI - pass --match-id <id>')
        return

    repo = StatsRepository()

    # Collect all player IDs from the match
    all_rows = repo.get_match_ball_log(match_id)
    if not all_rows:
        print(f'No data for match_id={match_id}')
        return

    all_pids = list({r[3] for r in all_rows})   # bowler IDs
    names    = repo.get_player_names(all_pids)

    print(f'Loading caches for {len(all_pids)} players ({fmt}, {gender})…')
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

    print(f'Replaying match {match_id}, inning {args.inning}…')
    records, _ = replay_match(repo, strategy, match_id, args.inning)

    if not records:
        print('No records generated - check match_id and inning.')
        return

    # Filter to bowlers only (skip players who never bowled)
    bowling_names = {r['name'] for r in records if r['actual']}
    records = [r for r in records if r['name'] in bowling_names]

    print(f'Plotting {len(bowling_names)} bowlers across {len({r["over"] for r in records})} overs…')

    plot_f3(records,  f'{args.out}_f3.png')
    plot_affinity(strategy, fmt, all_pids, names, f'{args.out}_affinity.png')
    plot_total_scores(records, f'{args.out}_scores.png')

    print('Done.')


if __name__ == '__main__':
    main()
