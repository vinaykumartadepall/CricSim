#!/usr/bin/env python3
"""
Run one innings of the simulator from match_config.json and plot bowling-model
scores at every over selection point.

Usage:
    python -m tools.plot_sim_scores
    python -m tools.plot_sim_scores --config match_config.json --inning 1 --out sim_bowling

Outputs:
    <out>_f3.png       — 4 subplots: continuity / fatigue / workload / combined F3
    <out>_affinity.png — phase-affinity heatmap for the bowling team
    <out>_scores.png   — total score (F1+F2+F3+F4) per bowler vs over
"""

import argparse
import json
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from db.stats_repository import StatsRepository
from simulator.entities.match import SimulationMatch
from simulator.entities.team import MatchTeam
from simulator.entities.rules import MatchRules
from simulator.engines.innings_simulator import InningsSimulator
from simulator.match_logger import MatchLogger
from simulator.logger import get_logger
from simulator.strategies.factory import FORMAT_SETTINGS, OutcomeStrategyFactory, resolve_player, resolve_venue
from simulator.engines.base_engine import BaseEngine


# ── Score-capturing bowling strategy wrapper ──────────────────────────────────

class CapturingBowlingStrategy:
    """
    Wraps a HistoricalBowlingBase strategy, intercepting each select_bowler call
    to record the full score breakdown for every eligible player before delegating
    to the real strategy for the actual selection.
    """

    def __init__(self, real_strategy):
        self._real    = real_strategy
        self.records  = []   # list of dicts, one per (over, player) evaluation

    # Proxy attribute access to the real strategy so engine code can call
    # init_model, _hard_cap, etc. directly on this wrapper if needed.
    def __getattr__(self, name):
        return getattr(self._real, name)

    def init_model(self, match):
        self._real.init_model(match)

    def select_bowler(self, match):
        team     = match.current_bowling_team
        eligible = self._real._eligible(team, match.current_bowler, match)
        over     = match.current_over

        selected_id = None   # fill after real call
        over_records = []

        for ip in eligible:
            if self._real._hard_cap(ip):
                continue
            try:
                total, factors = self._real._score_and_breakdown(ip, match)
            except Exception:
                continue
            if total <= -900:
                continue
            over_records.append({
                'over':    over,
                'name':    ip.name,
                'id':      ip.id,
                'f1':      factors.get('F1_phase', 0),
                'f2':      factors.get('F2_form', 0),
                'f3_cont': factors.get('F3_cont', 0),
                'f3_fat':  factors.get('F3_fat', 0),
                'f3_wl':   factors.get('F3_wl', 0),
                'f4':      factors.get('F4_matchup', 0),
                'total':   total,
                'selected': False,
            })

        chosen = self._real.select_bowler(match)

        # Mark the chosen bowler
        for r in over_records:
            if r['id'] == chosen.id:
                r['selected'] = True
                break

        self.records.extend(over_records)
        return chosen



# ── Single-innings simulation ─────────────────────────────────────────────────

def run_one_inning(config, capturing_strategy, inning_number):
    """
    Sets up a match from config and runs exactly one innings through InningsSimulator.
    Returns the match object (for phase affinity inspection) and the capturing_strategy.
    The toss is forced so that the requested inning_number determines batting/bowling order.
    """
    fmt      = MatchRules.get_unified_format(config.get('format', 'Test'))
    gender   = config.get('gender', 'male')
    repo     = StatsRepository()

    team_a = MatchTeam(id=1, name=config['team_a']['name'],
                       players=[resolve_player(repo, n) for n in config['team_a']['players']])
    team_b = MatchTeam(id=2, name=config['team_b']['name'],
                       players=[resolve_player(repo, n) for n in config['team_b']['players']])

    venue = resolve_venue(repo, config.get('venue'))

    fmt_settings = dict(FORMAT_SETTINGS[fmt])
    match = SimulationMatch(
        id=config.get('match_id', 1),
        home_team=team_a,
        away_team=team_b,
        venue=venue,
        match_format=fmt,
        balls_per_over=6,
        gender=gender,
        **fmt_settings,
    )

    ball_outcomes = OutcomeStrategyFactory.for_name('historical', fmt)

    print(f'Initialising models ({fmt}, {gender})…')
    ball_outcomes.init_model(match)
    capturing_strategy.init_model(match)

    logger = MatchLogger(match_id=match.id)
    from simulator.entities.match import MatchStatus
    match.status = MatchStatus.IN_PROGRESS

    # Force batting/bowling assignment for the requested inning number
    # Inning 1 → team_a bats, team_b bowls
    # Inning 2 → team_b bats, team_a bowls
    if inning_number % 2 == 1:
        batting_team, bowling_team = team_a, team_b
    else:
        batting_team, bowling_team = team_b, team_a

    print(f'Inning {inning_number}: {batting_team.name} bat, {bowling_team.name} bowl')

    from simulator.entities.inning import Inning
    from simulator.entities.inning_team import InningTeam

    batting_it  = InningTeam.from_match_team(batting_team)
    bowling_it  = InningTeam.from_match_team(bowling_team)
    inning      = Inning(inning_number, batting_it, bowling_it)
    match.innings.append(inning)

    match.current_inning        = inning_number
    match.current_batting_team  = batting_it
    match.current_bowling_team  = bowling_it

    match.event_bus.clear()
    match.event_bus.subscribe(batting_it)
    match.event_bus.subscribe(bowling_it)
    for ip in batting_it.inning_players:
        match.event_bus.subscribe(ip)
    for ip in bowling_it.inning_players:
        match.event_bus.subscribe(ip)

    match.current_over = 0
    match.current_ball = 0
    match.striker, match.non_striker = batting_it.get_openers()
    match.current_bowler = capturing_strategy.select_bowler(match)

    sim = InningsSimulator(match, ball_outcomes, logger, capturing_strategy)
    max_overs = fmt_settings.get('overs_per_innings')   # None for Test
    sim.run(max_overs=max_overs)

    return match


# ── Colour assignment ─────────────────────────────────────────────────────────

def _assign_colors(names):
    cmap   = plt.cm.tab20
    unique = sorted(set(names))
    return {n: cmap(i / max(len(unique) - 1, 1)) for i, n in enumerate(unique)}


# ── PNG 1: F3 component breakdown ─────────────────────────────────────────────

def plot_f3(records, out_path, title_suffix=''):
    names   = sorted({r['name'] for r in records})
    colors  = _assign_colors(names)
    metrics = [('f3_cont', 'Continuity'), ('f3_fat', 'Fatigue'),
               ('f3_wl',  'Workload'),    ('f3_combined', 'F3 Combined')]

    fig, axes = plt.subplots(2, 2, figsize=(18, 12), sharex=True)
    fig.suptitle(f'F3 Spell Score Components — per over{title_suffix}',
                 fontsize=13, fontweight='bold')
    axes_flat = [axes[0,0], axes[0,1], axes[1,0], axes[1,1]]

    by_name_over = defaultdict(dict)
    for r in records:
        by_name_over[r['name']][r['over']] = r

    for ax, (metric, label) in zip(axes_flat, metrics):
        for name in names:
            d     = by_name_over[name]
            overs = sorted(d.keys())
            if metric == 'f3_combined':
                vals = [d[o]['f3_cont'] + d[o]['f3_fat'] + d[o]['f3_wl'] for o in overs]
            else:
                vals = [d[o][metric] for o in overs]

            ax.plot(overs, vals, '-', color=colors[name], linewidth=1.4, alpha=0.85, label=name)

            sel_overs = [o for o in overs if d[o]['selected']]
            sel_vals  = ([d[o][metric] if metric != 'f3_combined'
                          else d[o]['f3_cont'] + d[o]['f3_fat'] + d[o]['f3_wl']
                          for o in sel_overs])
            ax.scatter(sel_overs, sel_vals, color=colors[name], s=40, zorder=5, marker='o')

        ax.axhline(0, color='black', linewidth=0.7, linestyle='--')
        ax.set_title(label, fontsize=10)
        ax.set_ylabel('Score contribution')
        ax.grid(True, alpha=0.2)

    axes[1,0].set_xlabel('Over')
    axes[1,1].set_xlabel('Over')

    handles = [mpatches.Patch(color=colors[n], label=n) for n in names]
    fig.legend(handles=handles, loc='lower center', ncol=min(len(names), 6),
               fontsize=8, bbox_to_anchor=(0.5, -0.02))
    plt.tight_layout(rect=[0, 0.04, 1, 1])
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f'Saved: {out_path}')
    plt.close()


# ── PNG 2: Phase affinity heatmap ─────────────────────────────────────────────

def plot_affinity(strategy, fmt, player_ids, out_path, title_suffix=''):
    real = strategy._real if hasattr(strategy, '_real') else strategy

    if fmt == 'Test':
        phases     = [f'Ph{i}\n({i*10}-{i*10+9})' for i in range(8)]
        phase_keys = list(range(8))
        def freq(pid, k): return real.test_phase_freq_cache.get(pid, {}).get(k, 0.0)
        ph_weight = 25.0
    elif fmt == 'T20':
        phases     = [f'Ov{k+1}' for k in range(20)]
        phase_keys = list(range(20))
        def freq(pid, k): return real.global_over_freq_cache.get(pid, {}).get(k, 0.0)
        ph_weight = 20.0
    else:  # ODI
        phases     = [f'Ov{k*5+1}-{k*5+5}' for k in range(10)]
        phase_keys = list(range(10))
        def freq(pid, k): return real.global_over_freq_cache.get(pid, {}).get(k, 0.0)
        ph_weight = 20.0

    # Resolve names from career_cache / workload_cache keys
    name_map = {}
    for pid in player_ids:
        c = real.career_cache.get(pid, {})
        if 'name' in c:
            name_map[pid] = c['name']

    # Fallback: get names from DB
    missing = [p for p in player_ids if p not in name_map]
    if missing:
        from db.stats_repository import StatsRepository
        names = StatsRepository().get_player_names(missing)
        name_map.update(names)

    active = [(pid, name_map.get(pid, str(pid))) for pid in player_ids
              if any(freq(pid, k) > 0 for k in phase_keys)]
    active.sort(key=lambda x: -sum(freq(x[0], k) for k in phase_keys))

    if not active:
        print('No phase affinity data — skipping affinity plot.')
        return

    matrix = np.array([[freq(pid, k) * ph_weight for k in phase_keys]
                        for pid, _ in active])
    labels = [name for _, name in active]

    fig, ax = plt.subplots(figsize=(max(8, len(phases)), max(5, len(active) * 0.55)))
    im = ax.imshow(matrix, aspect='auto', cmap='YlOrRd', vmin=0)

    ax.set_xticks(range(len(phases)))
    ax.set_xticklabels(phases, fontsize=9)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=9)

    for i in range(len(labels)):
        for j in range(len(phases)):
            val = matrix[i, j]
            ax.text(j, i, f'{val:.1f}', ha='center', va='center',
                    fontsize=7, color='black' if val < matrix.max() * 0.6 else 'white')

    plt.colorbar(im, ax=ax, label='Phase affinity score (freq × weight)')
    ax.set_title(f'Phase Affinity — {fmt} (F1 score at 0 workload){title_suffix}',
                 fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f'Saved: {out_path}')
    plt.close()


# ── PNG 3: Total scores per over ──────────────────────────────────────────────

def plot_total_scores(records, out_path, title_suffix=''):
    names  = sorted({r['name'] for r in records})
    colors = _assign_colors(names)

    fig, ax = plt.subplots(figsize=(18, 7))
    fig.suptitle(f'Total Bowling Score (F1+F2+F3+F4) — per over{title_suffix}',
                 fontsize=13, fontweight='bold')

    by_name_over = defaultdict(dict)
    for r in records:
        by_name_over[r['name']][r['over']] = r

    for name in names:
        d     = by_name_over[name]
        overs = sorted(d.keys())
        vals  = [d[o]['total'] for o in overs]
        ax.plot(overs, vals, '-', color=colors[name], linewidth=1.5, alpha=0.85, label=name)

        sel_overs = [o for o in overs if d[o]['selected']]
        sel_vals  = [d[o]['total'] for o in sel_overs]
        ax.scatter(sel_overs, sel_vals, color=colors[name], s=60, zorder=5, marker='*')

    ax.axhline(0, color='black', linewidth=0.7, linestyle='--')
    ax.set_xlabel('Over', fontsize=11)
    ax.set_ylabel('Total score', fontsize=11)
    ax.grid(True, alpha=0.2)

    handles = [mpatches.Patch(color=colors[n], label=n) for n in names]
    fig.legend(handles=handles, loc='lower center', ncol=min(len(names), 6),
               fontsize=8, bbox_to_anchor=(0.5, -0.04))

    note = '★ = selected to bowl that over'
    ax.text(0.01, 0.01, note, transform=ax.transAxes, fontsize=8, color='grey')

    plt.tight_layout(rect=[0, 0.05, 1, 1])
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f'Saved: {out_path}')
    plt.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Simulate a match and plot bowling scores')
    parser.add_argument('--config', default='match_config.json')
    parser.add_argument('--inning', type=int, default=1,
                        help='Which inning to simulate (1 or 2, default: 1)')
    parser.add_argument('--out',    default='sim_bowling',
                        help='Output file prefix (default: sim_bowling)')
    args = parser.parse_args()

    config_path = args.config if os.path.isabs(args.config) else \
        os.path.join(os.path.dirname(os.path.dirname(__file__)), args.config)
    with open(config_path) as f:
        config = json.load(f)

    fmt = MatchRules.get_unified_format(config.get('format', 'Test'))

    real_strategy      = create_historical_bowling_strategy(fmt)
    capturing_strategy = CapturingBowlingStrategy(real_strategy)

    match = run_one_inning(config, capturing_strategy, args.inning)

    records = capturing_strategy.records
    if not records:
        print('No records captured.')
        return

    # Keep only bowlers who were selected at least once
    selected_names = {r['name'] for r in records if r['selected']}
    records = [r for r in records if r['name'] in selected_names]

    print(f'Captured {len(records)} evaluations across '
          f'{len(selected_names)} bowlers, '
          f'{len({r["over"] for r in records})} overs.')

    title_suffix = (f' — {match.current_bowling_team.name} bowling '
                    f'(simulated {fmt})')

    plot_f3(records, f'{args.out}_f3.png', title_suffix)

    bowling_pids = list({r['id'] for r in records})
    plot_affinity(capturing_strategy, fmt, bowling_pids, f'{args.out}_affinity.png', title_suffix)

    plot_total_scores(records, f'{args.out}_scores.png', title_suffix)

    print('Done.')


if __name__ == '__main__':
    main()
