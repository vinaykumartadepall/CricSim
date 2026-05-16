"""
Worst-case analysis: match 1001526 (SA vs WI ODI, 2015-01-18 @ New Wanderers)
AB de Villiers scored 121 from 36 balls (eco 20.17) in death2 innings 1.
This is ABdV's highest-scoring death-over performance in his ODI pool.

This script:
1. Runs this match N times with EnhancedODI + HistoricalBowlingOrder
2. Breaks down death2 outcomes by inning and batter
3. Compares against historical deliveries
4. Prints phase distribution for the model's batter/bowler/phase contexts in death2
"""

import sys
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from db.stats_repository import StatsRepository
from simulator.entities.match import SimulationMatch
from simulator.entities.team import MatchTeam
from simulator.entities.player import Player
from simulator.entities.rules import MatchRules
from simulator.engines.engine_factory import EngineFactory
from simulator.strategies.ball_outcome_prediction.enhanced_historical_stats import (
    ODIEnhancedHistoricalStatsStrategy,
)
from simulator.strategies.bowling.historical import create_historical_bowling_strategy
from db.entities.venue import Venue
from typing import Dict as _Dict  # avoid shadowing


class HistoricalBowlingOrder:
    _initialized = True

    def __init__(self, plan):
        self._plan = plan

    def init_model(self, match):
        pass

    def select_bowler(self, match):
        inning_num = match.current_inning if match.current_inning else 1
        over_0 = match.current_over
        pid = self._plan.get(inning_num, {}).get(over_0)
        bowling_team = match.current_bowling_team
        if not bowling_team or not bowling_team.inning_players:
            return match.current_bowler
        if pid is not None:
            for ip in bowling_team.inning_players:
                if ip.id == pid:
                    return ip
        eligible = [ip for ip in bowling_team.inning_players if ip != match.current_bowler]
        return eligible[0] if eligible else match.current_bowler


MATCH_ID = 1001526
N_SIMS   = 50
ABDEV_ID = 101962


@dataclass
class Stats:
    n: int = 0
    runs: int = 0
    boundaries: int = 0
    wickets: int = 0
    dots: int = 0

    @property
    def eco(self): return self.runs / self.n * 6 if self.n else 0
    @property
    def bnd(self): return self.boundaries / self.n if self.n else 0
    @property
    def wkt(self): return self.wickets / self.n if self.n else 0
    @property
    def dot(self): return self.dots / self.n if self.n else 0

    def push(self, rb, rx, is_wkt):
        self.n      += 1
        self.runs   += rb + rx
        if rb >= 4: self.boundaries += 1
        if is_wkt:  self.wickets   += 1
        if rb == 0 and rx == 0 and not is_wkt:
            self.dots += 1

    def __repr__(self):
        return f"n={self.n:>5}  eco={self.eco:.2f}  bnd={self.bnd:.3f}  wkt={self.wkt:.3f}  dot={self.dot:.3f}"


def main():
    repo = StatsRepository()

    print(f"\n{'='*80}")
    print(f"  WORST-CASE ANALYSIS: match {MATCH_ID}")
    print(f"  SA vs WI ODI @ New Wanderers Stadium, 2015-01-18")
    print(f"  AB de Villiers hist death2 inn1: eco 20.17 (36 balls, 121 runs)")
    print(f"  Running {N_SIMS} simulations …")
    print(f"{'='*80}\n")

    # ── Historical deliveries ────────────────────────────────────────────────
    hist_rows = repo._run_query(
        "SELECT d.inning_number, d.over_number, d.batter_id, p.name, "
        "d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, d.bowler_id "
        "FROM history.deliveries d "
        "JOIN history.players p ON p.player_id = d.batter_id "
        "WHERE d.match_id = %s AND d.inning_number <= 2 "
        "ORDER BY d.inning_number, d.over_number, d.ball_number",
        (MATCH_ID,)
    )

    hist_by_inning: Dict[int, Stats] = {1: Stats(), 2: Stats()}
    hist_death2: Dict[int, Stats] = defaultdict(Stats)      # by inning
    hist_batter_death2: Dict[int, Stats] = defaultdict(Stats)  # by batter_id
    hist_batter_names: Dict[int, str] = {}

    fmt = 'ODI'
    for inn, ov0, bid, bname, rb, rx, ot, ok, bowid in hist_rows:
        is_wkt = ot == 'Wicket'
        hist_by_inning.setdefault(inn, Stats()).push(rb, rx, is_wkt)
        hist_batter_names[bid] = bname
        phase = MatchRules.get_fine_grained_phase(ov0 + 1, fmt)
        if phase == 'death2':
            hist_death2[inn].push(rb, rx, is_wkt)
            hist_batter_death2[bid].push(rb, rx, is_wkt)

    print("HISTORICAL – match summary")
    for inn in sorted(hist_by_inning):
        st = hist_by_inning[inn]
        print(f"  Inn {inn}:  {st}")

    print("\nHISTORICAL – death2 by inning")
    for inn in sorted(hist_death2):
        st = hist_death2[inn]
        print(f"  Inn {inn} death2:  {st}")

    print("\nHISTORICAL – death2 by batter (top scorers)")
    top_batters = sorted(hist_batter_death2.items(), key=lambda kv: kv[1].runs, reverse=True)
    for bid, st in top_batters[:8]:
        name = hist_batter_names.get(bid, str(bid))
        mark = " ← ABdV" if bid == ABDEV_ID else ""
        print(f"  {name:<25} {st}{mark}")

    # ── Build match config ───────────────────────────────────────────────────
    meta = repo._run_query(
        "SELECT m.venue_id, v.name, v.country, m.home_team_id, m.away_team_id "
        "FROM history.matches m JOIN history.venues v ON v.venue_id = m.venue_id "
        "WHERE m.match_id = %s", (MATCH_ID,)
    )[0]
    vid, vname, vcountry, htid, atid = meta

    player_rows = repo._run_query(
        "SELECT mp.match_id, mp.team_id, t.name, mp.player_id, p.name "
        "FROM history.match_players mp "
        "JOIN history.players p ON mp.player_id = p.player_id "
        "JOIN history.teams   t ON mp.team_id   = t.team_id "
        "WHERE mp.match_id = %s",
        (MATCH_ID,)
    )
    batting_rows = repo._run_query(
        "SELECT player_id, batting_team_id, "
        "MIN((inning_number * 10000 + over_number * 100 + ball_number) * 2 + role) AS sort_key "
        "FROM ("
        "  SELECT batter_id AS player_id, batting_team_id, inning_number, over_number, ball_number, 0 AS role "
        "  FROM history.deliveries WHERE match_id = %s AND inning_number <= 2 "
        "  UNION ALL "
        "  SELECT non_striker_id, batting_team_id, inning_number, over_number, ball_number, 1 "
        "  FROM history.deliveries WHERE match_id = %s AND inning_number <= 2"
        ") a GROUP BY player_id, batting_team_id",
        (MATCH_ID, MATCH_ID)
    )
    sort_keys = {(pid, tid): sk for pid, tid, sk in batting_rows}

    bow_rows = repo._run_query(
        "SELECT inning_number, over_number, bowler_id FROM ("
        "  SELECT inning_number, over_number, bowler_id, "
        "  ROW_NUMBER() OVER (PARTITION BY inning_number, over_number ORDER BY COUNT(*) DESC) rn "
        "  FROM history.deliveries WHERE match_id = %s AND inning_number <= 2 "
        "  GROUP BY inning_number, over_number, bowler_id"
        ") s WHERE rn = 1",
        (MATCH_ID,)
    )
    bow_plan: Dict[int, Dict[int, int]] = {}
    for inn, ov, bowid in bow_rows:
        bow_plan.setdefault(inn, {})[ov] = bowid

    raw_players: Dict[int, List] = {}
    for _, tid, tname, pid, pname in player_rows:
        raw_players.setdefault(tid, []).append((pid, pname))

    teams_ordered = []
    for tid in [htid, atid]:
        if tid in raw_players:
            team_players = sorted(raw_players.pop(tid), key=lambda x: sort_keys.get((x[0], tid), 999_999))
            teams_ordered.append((tid, team_players))
    for tid, plist in raw_players.items():
        teams_ordered.append((tid, sorted(plist, key=lambda x: sort_keys.get((x[0], tid), 999_999))))

    venue = Venue(name=vname, id=vid, country=vcountry)

    # ── Init strategy (once, shared) ─────────────────────────────────────────
    out_strat = ODIEnhancedHistoricalStatsStrategy()

    t0_pl = [Player(id=pid, name=pn) for pid, pn in teams_ordered[0][1]]
    t1_pl = [Player(id=pid, name=pn) for pid, pn in teams_ordered[1][1]]
    seed_match = SimulationMatch(
        id=0,
        home_team=MatchTeam(id=1, name="SA",  players=t0_pl),
        away_team=MatchTeam(id=2, name="WI",  players=t1_pl),
        venue=venue, match_format=fmt, balls_per_over=6,
        overs_per_innings=50, innings_per_match=2,
    )
    seed_match.gender = 'male'
    print(f"\n  Initialising ODI outcome strategy …")
    out_strat.init_model(seed_match)
    print(f"  Strategy ready.\n")

    # ── What does the phase/batter cache say about ABdV death2? ─────────────
    print("MODEL INTROSPECTION – ABdV in death2")
    baseline = out_strat.baseline_outcome_probs
    abdev_dist = out_strat.batter_cache.get(ABDEV_ID, {})
    abdev_balls = out_strat.batter_ball_counts.get(ABDEV_ID, 0)
    phase_dist = out_strat.phase_cache.get('death2', {})

    def _eco_from_dist(dist):
        total_runs = sum(k[0] * p for k, p in dist.items() if k[2] not in ('Wicket', 'Extras'))
        total_runs += sum(k[1] * p for k, p in dist.items() if k[2] == 'Extras')
        return total_runs * 6

    print(f"  ABdV batter_cache present: {bool(abdev_dist)}  ball_count={abdev_balls}")
    if abdev_dist:
        print(f"  ABdV career distribution implied eco:  {_eco_from_dist(abdev_dist):.2f}")
    print(f"  Baseline distribution implied eco:     {_eco_from_dist(baseline):.2f}")
    print(f"  Phase 'death2' distribution implied eco: {_eco_from_dist(phase_dist):.2f}")

    abdev_bnd  = sum(p for k, p in abdev_dist.items() if k[0] >= 4) if abdev_dist else 0
    phase_bnd  = sum(p for k, p in phase_dist.items() if k[0] >= 4)
    base_bnd   = sum(p for k, p in baseline.items() if k[0] >= 4)
    abdev_wkt  = sum(p for k, p in abdev_dist.items() if k[2] == 'Wicket') if abdev_dist else 0
    phase_wkt  = sum(p for k, p in phase_dist.items() if k[2] == 'Wicket')
    print(f"  ABdV career bnd={abdev_bnd:.3f}  phase_death2 bnd={phase_bnd:.3f}  baseline bnd={base_bnd:.3f}")
    print(f"  ABdV career wkt={abdev_wkt:.3f}  phase_death2 wkt={phase_wkt:.3f}")

    # ── Run simulations ──────────────────────────────────────────────────────
    sim_by_inning: Dict[int, Stats] = {1: Stats(), 2: Stats()}
    sim_death2: Dict[int, Stats] = defaultdict(Stats)
    sim_batter_death2: Dict[int, Stats] = defaultdict(Stats)
    sim_batter_names: Dict[int, str] = {}

    hist_bow_str = HistoricalBowlingOrder(bow_plan)

    for r in range(N_SIMS):
        t0_pl2 = [Player(id=pid, name=pn) for pid, pn in teams_ordered[0][1]]
        t1_pl2 = [Player(id=pid, name=pn) for pid, pn in teams_ordered[1][1]]
        match = SimulationMatch(
            id=r + 1,
            home_team=MatchTeam(id=1, name="SA",  players=t0_pl2),
            away_team=MatchTeam(id=2, name="WI",  players=t1_pl2),
            venue=venue, match_format=fmt, balls_per_over=6,
            overs_per_innings=50, innings_per_match=2,
        )
        match.gender = 'male'
        try:
            EngineFactory.create(match, out_strat, hist_bow_str).simulate()
        except Exception as e:
            print(f"  WARN sim {r+1}: {e}")
            continue

        for inning in match.innings:
            if inning.inning_number > 2:
                continue
            for d in inning.deliveries:
                rb, rx = d.runs_batter, d.runs_extras
                is_wkt = d.is_wicket
                inn = inning.inning_number
                ov0 = d.over_number
                phase = MatchRules.get_fine_grained_phase(ov0 + 1, fmt)
                sim_by_inning.setdefault(inn, Stats()).push(rb, rx, is_wkt)
                if phase == 'death2':
                    sim_death2[inn].push(rb, rx, is_wkt)
                    bid = d.batter.id if d.batter else None
                    if bid:
                        sim_batter_death2[bid].push(rb, rx, is_wkt)
                        if bid not in sim_batter_names and d.batter:
                            sim_batter_names[bid] = d.batter.name

        if (r + 1) % 10 == 0:
            print(f"  {r+1}/{N_SIMS} done …")

    # ── Results ──────────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("SIMULATION RESULTS\n")

    print("Match summary (all phases)")
    for inn in sorted(sim_by_inning):
        st = sim_by_inning[inn]
        h  = hist_by_inning.get(inn, Stats())
        print(f"  Inn {inn}:  sim: {st}  |  hist: {h}")

    print("\nDeath2 by inning  (sim vs hist)")
    for inn in [1, 2]:
        s = sim_death2.get(inn, Stats())
        h = hist_death2.get(inn, Stats())
        print(f"  Inn {inn}:  sim: {s}  |  hist: {h}")

    print("\nDeath2 by batter  (sim vs hist)")
    all_bids = set(sim_batter_death2) | set(hist_batter_death2)
    batter_eco_diff = []
    for bid in all_bids:
        s = sim_batter_death2.get(bid, Stats())
        h = hist_batter_death2.get(bid, Stats())
        name = sim_batter_names.get(bid) or hist_batter_names.get(bid, str(bid))
        if h.n >= 5 or s.n >= 10:
            batter_eco_diff.append((bid, name, s, h))
    batter_eco_diff.sort(key=lambda x: x[3].eco, reverse=True)
    for bid, name, s, h in batter_eco_diff:
        mark = " ← ABdV" if bid == ABDEV_ID else ""
        print(f"  {name:<25} sim: {s}  |  hist: {h}{mark}")

    print(f"\n{'='*80}")
    print("INTERPRETATION")
    abdev_s = sim_batter_death2.get(ABDEV_ID, Stats())
    abdev_h = hist_batter_death2.get(ABDEV_ID, Stats())
    print(f"  ABdV sim eco={abdev_s.eco:.2f}  hist eco={abdev_h.eco:.2f}  diff={abdev_s.eco-abdev_h.eco:+.2f}")
    print(f"  ABdV sim bnd={abdev_s.bnd:.3f}  hist bnd={abdev_h.bnd:.3f}")
    inn1_s = sim_death2.get(1, Stats())
    inn1_h = hist_death2.get(1, Stats())
    inn2_s = sim_death2.get(2, Stats())
    inn2_h = hist_death2.get(2, Stats())
    print(f"\n  Inn1 death2 eco: sim={inn1_s.eco:.2f}  hist={inn1_h.eco:.2f}  diff={inn1_s.eco-inn1_h.eco:+.2f}")
    print(f"  Inn2 death2 eco: sim={inn2_s.eco:.2f}  hist={inn2_h.eco:.2f}  diff={inn2_s.eco-inn2_h.eco:+.2f}")


if __name__ == '__main__':
    main()
