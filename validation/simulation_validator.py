"""
Simulation-Based Validator
===========================
Tests the full pipeline — ball outcome prediction + bowling selection +
batting order — by running N simulations of real match configurations and
comparing aggregate phase statistics against actual historical delivery data
at the same venue + format.

This is distinct from the delivery-level validator (validate.py) in two ways:
  1. It tests _apply_pressure_modifier (which runs AFTER _compute_distribution,
     and is therefore invisible to the delivery-level validator).
  2. It tests bowling selection, batting order, and all engine logic together.

The comparison metric is not match outcome (which diverges stochastically)
but aggregate delivery statistics bucketed by phase:
  - Boundary rate
  - Wicket rate
  - Economy (runs/over)
  - Dot ball rate

Usage:
    python -m simulator.strategies.ball_outcome_prediction.historical_stats.validate_simulation \\
        --format T20 --venue "Shere Bangla" --simulations 100 --config match_config.json

    # Or auto-pick top venues for the format:
    python -m ... --format T20 --simulations 50 --auto-venues

How it works
------------
1. A match_config.json (or CLI-supplied config) provides team rosters and venue.
2. The match is simulated N times with the full engine.
3. Phase-level delivery stats are averaged across all N innings.
4. These are compared against historical deliveries from the same venue + format.

The expected output looks like:
    Phase     Sim_bnd  His_bnd  Sim_wkt  His_wkt  Sim_eco  His_eco
    pp1       0.162    0.159    0.046    0.038    6.8      6.5
    mid1      0.131    0.129    0.053    0.052    7.8      7.6
    death1    0.165    0.158    0.065    0.073    8.6      8.3

Why averages and not exact match?
  Cricket is a high-variance game.  Even with perfect parameters, a single
  simulated match can diverge wildly from the actual result.  With N=50-100
  simulations, the averaged phase statistics converge to the model's *expected*
  behaviour and can be compared to historical averages at the venue level.
  Match-level comparison requires hundreds of simulations per match to reduce
  noise enough to be meaningful.
"""

import json
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from db.stats_repository import StatsRepository
from simulator.entities.rules import MatchRules


# ── Phase stats container ──────────────────────────────────────────────────────

@dataclass
class PhaseStats:
    n:           int   = 0
    n_boundary:  int   = 0
    n_wicket:    int   = 0
    n_dot:       int   = 0
    total_runs:  float = 0.0

    @property
    def boundary_rate(self) -> float: return self.n_boundary / self.n if self.n else 0.0
    @property
    def wicket_rate(self)   -> float: return self.n_wicket   / self.n if self.n else 0.0
    @property
    def dot_rate(self)      -> float: return self.n_dot      / self.n if self.n else 0.0
    @property
    def economy(self)       -> float: return self.total_runs / self.n * 6 if self.n else 0.0

    def add(self, other: 'PhaseStats'):
        self.n          += other.n
        self.n_boundary += other.n_boundary
        self.n_wicket   += other.n_wicket
        self.n_dot      += other.n_dot
        self.total_runs += other.total_runs


_SCORE_BANDS = [
    (0,   99,  '<100'),
    (100, 119, '100-119'),
    (120, 139, '120-139'),
    (140, 159, '140-159'),
    (160, 179, '160-179'),
    (180, 199, '180-199'),
    (200, 219, '200-219'),
    (220, 9999,'220+'),
]

def _score_band(runs: int) -> str:
    for lo, hi, label in _SCORE_BANDS:
        if lo <= runs <= hi:
            return label
    return '220+'


@dataclass
class SimValidationResult:
    match_format:    str
    venue_name:      str
    n_simulations:   int
    n_historical:    int
    elapsed_s:       float
    simulated:            Dict[str, PhaseStats] = field(default_factory=dict)
    historical:           Dict[str, PhaseStats] = field(default_factory=dict)
    simulated_by_inning:  Dict[int, Dict[str, PhaseStats]] = field(default_factory=dict)
    historical_by_inning: Dict[int, Dict[str, PhaseStats]] = field(default_factory=dict)
    simulated_scores:     List[int] = field(default_factory=list)
    historical_scores:    List[int] = field(default_factory=list)

    def _phase_table(self, sim: Dict[str, PhaseStats], hist: Dict[str, PhaseStats]) -> List[str]:
        hdr = (
            f"  {'Phase':<10}  {'Sim_bnd':>7}  {'His_bnd':>7}  "
            f"{'Sim_wkt':>7}  {'His_wkt':>7}  {'Sim_eco':>7}  {'His_eco':>7}  "
            f"{'Sim_dot':>7}  {'His_dot':>7}"
        )
        rows = [hdr]
        for phase in sorted(set(sim) | set(hist)):
            s = sim.get(phase)
            h = hist.get(phase)
            if not s or not h or s.n < 10 or h.n < 50:
                continue
            bnd_ok = "✓" if abs(s.boundary_rate - h.boundary_rate) < 0.02 else "✗"
            wkt_ok = "✓" if abs(s.wicket_rate   - h.wicket_rate)   < 0.01 else "✗"
            eco_ok = "✓" if abs(s.economy        - h.economy)        < 0.50 else "✗"
            rows.append(
                f"  {phase:<10}  {s.boundary_rate:>7.3f}  {h.boundary_rate:>7.3f}  "
                f"{s.wicket_rate:>7.3f}  {h.wicket_rate:>7.3f}  "
                f"{s.economy:>7.2f}  {h.economy:>7.2f}  "
                f"{s.dot_rate:>7.3f}  {h.dot_rate:>7.3f}  "
                f"{bnd_ok}{wkt_ok}{eco_ok}"
            )
        return rows

    def _score_dist_table(self) -> List[str]:
        if not self.simulated_scores and not self.historical_scores:
            return []
        sim_total  = len(self.simulated_scores)  or 1
        hist_total = len(self.historical_scores) or 1
        all_labels = [label for _, _, label in _SCORE_BANDS]
        sim_counts  = {label: 0 for label in all_labels}
        hist_counts = {label: 0 for label in all_labels}
        for s in self.simulated_scores:
            sim_counts[_score_band(s)] += 1
        for s in self.historical_scores:
            hist_counts[_score_band(s)] += 1
        rows = [f"  {'Band':<10}  {'Sim%':>6}  {'His%':>6}  {'Sim_n':>5}  {'His_n':>5}"]
        for label in all_labels:
            sc = sim_counts[label]
            hc = hist_counts[label]
            if sc == 0 and hc == 0:
                continue
            sp = sc / sim_total  * 100
            hp = hc / hist_total * 100
            ok = "✓" if abs(sp - hp) < 5 else "✗"
            rows.append(f"  {label:<10}  {sp:>6.1f}  {hp:>6.1f}  {sc:>5}  {hc:>5}  {ok}")
        sim_avg  = sum(self.simulated_scores)  / sim_total  if self.simulated_scores  else 0
        hist_avg = sum(self.historical_scores) / hist_total if self.historical_scores else 0
        rows.append(f"  {'avg':<10}  {sim_avg:>6.1f}  {hist_avg:>6.1f}")
        return rows

    def report(self) -> str:
        lines = [
            "",
            f"  ══ Simulation Validation: {self.match_format} @ {self.venue_name} ══",
            f"  Simulations  : {self.n_simulations}",
            f"  Historical   : {self.n_historical:,} deliveries",
            f"  Elapsed      : {self.elapsed_s:.1f}s",
        ]

        lines += ["", "  ── Combined (all innings) ──────────────────────────────────────────"]
        lines += self._phase_table(self.simulated, self.historical)

        for inn_num in sorted(set(self.simulated_by_inning) | set(self.historical_by_inning)):
            label = {1: "Innings 1 (setting)", 2: "Innings 2 (chasing)"}.get(inn_num, f"Innings {inn_num}")
            lines += ["", f"  ── {label} ──────────────────────────────────────────────────"]
            lines += self._phase_table(
                self.simulated_by_inning.get(inn_num, {}),
                self.historical_by_inning.get(inn_num, {}),
            )

        score_rows = self._score_dist_table()
        if score_rows:
            lines += ["", "  ── Innings score distribution ──────────────────────────────────"]
            lines += score_rows

        lines.append("")
        text = "\n".join(lines)
        print(text)
        return text


# ── Historical data loader ─────────────────────────────────────────────────────

def _venue_delivery_rows(
    repo: StatsRepository,
    venue_id: int,
    match_format: str,
    gender: str,
    include_inning: bool = False,
    match_ids=None,
) -> list:
    """Fetches raw delivery rows for a venue/format. Reused by multiple loaders."""
    raw_fmts = repo._raw_formats(match_format)
    if match_ids:
        if include_inning:
            return repo._run_query("""
                SELECT d.inning_number, d.over_number, d.runs_batter, d.runs_extras, d.outcome_type
                FROM history.deliveries d
                WHERE d.match_id = ANY(%s) AND d.inning_number <= 2
            """, (match_ids,))
        else:
            return repo._run_query("""
                SELECT d.over_number, d.runs_batter, d.runs_extras, d.outcome_type
                FROM history.deliveries d
                WHERE d.match_id = ANY(%s)
            """, (match_ids,))
    if include_inning:
        return repo._run_query("""
            SELECT d.inning_number, d.over_number, d.runs_batter, d.runs_extras, d.outcome_type
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.venue_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
              AND d.inning_number <= 2
        """, (venue_id, raw_fmts, gender))
    else:
        return repo._run_query("""
            SELECT d.over_number, d.runs_batter, d.runs_extras, d.outcome_type
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            WHERE m.venue_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
        """, (venue_id, raw_fmts, gender))


def load_historical_phase_stats(
    repo: StatsRepository,
    venue_id: int,
    match_format: str,
    gender: str = 'male',
    match_ids=None,
) -> Dict[str, PhaseStats]:
    """
    Queries historical deliveries at a specific venue and aggregates them
    by fine-grained phase.  This is the ground truth to compare against.
    When match_ids is provided, restricts to those specific matches only.
    """
    stats: Dict[str, PhaseStats] = defaultdict(PhaseStats)
    for (over, rb, rx, ot) in _venue_delivery_rows(repo, venue_id, match_format, gender, match_ids=match_ids):
        phase = MatchRules.get_fine_grained_phase(over + 1, match_format)
        s = stats[phase]
        s.n          += 1
        s.total_runs += rb + rx
        if rb >= 4:        s.n_boundary += 1
        if ot == 'Wicket': s.n_wicket   += 1
        if ot == 'Dot':    s.n_dot      += 1
    return dict(stats)


def load_historical_phase_stats_by_inning(
    repo: StatsRepository,
    venue_id: int,
    match_format: str,
    gender: str = 'male',
) -> Dict[int, Dict[str, PhaseStats]]:
    """Historical phase stats split by innings (1 = setting, 2 = chasing)."""
    stats: Dict[int, Dict[str, PhaseStats]] = defaultdict(lambda: defaultdict(PhaseStats))
    for (inn, over, rb, rx, ot) in _venue_delivery_rows(
        repo, venue_id, match_format, gender, include_inning=True
    ):
        phase = MatchRules.get_fine_grained_phase(over + 1, match_format)
        s = stats[inn][phase]
        s.n          += 1
        s.total_runs += rb + rx
        if rb >= 4:        s.n_boundary += 1
        if ot == 'Wicket': s.n_wicket   += 1
        if ot == 'Dot':    s.n_dot      += 1
    return {inn: dict(phases) for inn, phases in stats.items()}


def load_historical_scores(
    repo: StatsRepository,
    venue_id: int,
    match_format: str,
    gender: str = 'male',
) -> List[int]:
    """Returns a list of innings totals (runs scored) at the venue, excluding super-overs."""
    raw_fmts = repo._raw_formats(match_format)
    rows = repo._run_query("""
        SELECT SUM(d.runs_batter + d.runs_extras)
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.venue_id = %s AND m.match_format = ANY(%s) AND m.gender = %s
          AND d.inning_number <= 2
        GROUP BY d.match_id, d.inning_number
    """, (venue_id, raw_fmts, gender))
    return [int(row[0]) for row in rows if row[0] is not None]


# ── Simulation runner ─────────────────────────────────────────────────────────

class SimulationValidator:
    """
    Runs N simulations of a match configuration and compares phase-level
    aggregate statistics against historical venue data.

    Usage:
        sv = SimulationValidator()
        result = sv.run_from_config('match_config.json', n_simulations=100)
        result.report()
    """

    def __init__(self, repo: Optional[StatsRepository] = None):
        self.repo = repo or StatsRepository()

    def run_from_config(
        self,
        config_path: str,
        n_simulations: int = 100,
        outcome_strategy_type: str = 'enhanced',
        bowling_strategy_type: str = 'historical',
    ) -> SimValidationResult:
        """
        Loads the match config, runs N simulations, and compares against
        historical data at the configured venue.
        """
        from simulator.simulate_driver import (
            _load_config, _build_match, _OUTCOME_STRATEGIES, _BOWLING_STRATEGY_FACTORIES,
        )
        from simulator.engines.engine_factory import EngineFactory
        from simulator.entities.team import MatchTeam
        from simulator.entities.match import SimulationMatch

        config = _load_config(config_path)
        match_format = config.get('match_format', config.get('format', 'T20'))
        match_fmt = MatchRules.get_unified_format(match_format)

        t_start = time.perf_counter()

        # Resolve players and venue once; use template as the init_model target.
        template_match = _build_match(config, self.repo)
        venue = getattr(template_match, 'venue', None)
        venue_id   = venue.id if venue else None
        venue_name = venue.name if venue else 'Unknown'
        gender     = getattr(template_match, 'gender', 'male')

        # Historical baseline (all three loaders share one venue query each)
        historical            = {}
        historical_by_inning  = {}
        historical_scores     = []
        n_historical          = 0
        if venue_id:
            historical = load_historical_phase_stats(
                self.repo, venue_id, match_format, gender
            )
            historical_by_inning = load_historical_phase_stats_by_inning(
                self.repo, venue_id, match_format, gender
            )
            historical_scores = load_historical_scores(
                self.repo, venue_id, match_format, gender
            )
            n_historical = sum(s.n for s in historical.values())

        # Create and initialise strategies once — all N simulations share the same caches.
        outcome_strat = _OUTCOME_STRATEGIES[outcome_strategy_type][match_fmt]()
        bowling_strat = _BOWLING_STRATEGY_FACTORIES[bowling_strategy_type](match_fmt)
        outcome_strat.init_model(template_match)
        bowling_strat.init_model(template_match)

        # Snapshot pre-resolved Player objects and match metadata.
        home_name    = template_match.home_team.name
        away_name    = template_match.away_team.name
        home_players = list(template_match.home_team.players)
        away_players = list(template_match.away_team.players)
        fmt_settings = {
            'overs_per_innings': template_match.overs_per_innings,
            'innings_per_match': template_match.innings_per_match,
        }

        # Simulate N times — no DB calls, no re-initialisation.
        simulated:            Dict[str, PhaseStats]                  = defaultdict(PhaseStats)
        simulated_by_inning:  Dict[int, Dict[str, PhaseStats]]       = defaultdict(lambda: defaultdict(PhaseStats))
        simulated_scores:     List[int]                              = []

        for i in range(n_simulations):
            match = SimulationMatch(
                id=i + 1,
                home_team=MatchTeam(id=1, name=home_name, players=home_players),
                away_team=MatchTeam(id=2, name=away_name, players=away_players),
                venue=venue,
                match_format=match_fmt,
                balls_per_over=6,
                **fmt_settings,
            )
            engine = EngineFactory.create(match, outcome_strat, bowling_strat)
            engine.simulate()

            max_inning = fmt_settings.get('innings_per_match', 2)
            for innings in match.innings:
                if innings.inning_number > max_inning:
                    continue  # skip super-over innings

                if innings.batting_team:
                    simulated_scores.append(innings.batting_team.total_runs)

                for delivery in innings.deliveries:
                    over = delivery.over_number if hasattr(delivery, 'over_number') else 0
                    phase = MatchRules.get_fine_grained_phase(over + 1, match_format)
                    rb = delivery.runs_batter
                    rx = delivery.runs_extras
                    wkt = delivery.is_wicket
                    dot = (rb == 0 and rx == 0 and not wkt)

                    s = simulated[phase]
                    s.n          += 1
                    s.total_runs += rb + rx
                    if rb >= 4: s.n_boundary += 1
                    if wkt:     s.n_wicket   += 1
                    if dot:     s.n_dot      += 1

                    si = simulated_by_inning[innings.inning_number][phase]
                    si.n          += 1
                    si.total_runs += rb + rx
                    if rb >= 4: si.n_boundary += 1
                    if wkt:     si.n_wicket   += 1
                    if dot:     si.n_dot      += 1

            if (i + 1) % 10 == 0:
                print(f"  [SimValidator] {i+1}/{n_simulations} simulations …")

        return SimValidationResult(
            match_format         = match_format,
            venue_name           = venue_name,
            n_simulations        = n_simulations,
            n_historical         = n_historical,
            elapsed_s            = time.perf_counter() - t_start,
            simulated            = dict(simulated),
            historical           = historical,
            simulated_by_inning  = {k: dict(v) for k, v in simulated_by_inning.items()},
            historical_by_inning = historical_by_inning,
            simulated_scores     = simulated_scores,
            historical_scores    = historical_scores,
        )

    def run_auto_venues(
        self,
        match_format: str,
        config_template: str,
        n_simulations: int = 50,
        gender: str = 'male',
        top_n: int = 3,
    ) -> List[SimValidationResult]:
        """
        Auto-selects the top N data-rich venues for the format and runs
        simulations for each.  Requires a match_config.json template where
        'venue' will be overridden per run.
        """
        raw_fmts = self.repo._raw_formats(MatchRules.get_unified_format(match_format))
        rows = self.repo._run_query("""
            SELECT v.venue_id, v.name, COUNT(*) as n
            FROM history.deliveries d
            JOIN history.matches m ON d.match_id = m.match_id
            JOIN history.venues  v ON m.venue_id = v.venue_id
            WHERE m.match_format = ANY(%s) AND m.gender = %s
            GROUP BY v.venue_id, v.name
            ORDER BY n DESC
            LIMIT %s
        """, (raw_fmts, gender, top_n))

        results = []
        for (vid, vname, n) in rows:
            print(f"\n[SimValidator] Running {n_simulations} simulations at {vname} …")
            try:
                import copy
                config = json.load(open(config_template))
                config['venue'] = vname
                tmp_path = '/tmp/_sim_validator_config.json'
                with open(tmp_path, 'w') as f:
                    json.dump(config, f)
                r = self.run_from_config(tmp_path, n_simulations)
                results.append(r)
            except Exception as e:
                print(f"  [SimValidator] Failed at {vname}: {e}")
        return results


# ── Player-profile containers ─────────────────────────────────────────────────

_PARTTIME_THRESHOLDS = {'T20': 120, 'ODI': 180, 'Test': 300}

_MILESTONE_BANDS = [
    ('fresh',       0,   9),
    ('building',   10,  44),
    ('tension_50', 45,  49),
    ('post_50',    50,  89),
    ('tension_100', 90, 99),
    ('century',   100, 9999),
]

def _milestone_label(score: int) -> str:
    for label, lo, hi in _MILESTONE_BANDS:
        if lo <= score <= hi:
            return label
    return 'building'

def _bowler_type_label(bowler_cumulative_balls: int, match_format: str) -> str:
    threshold = _PARTTIME_THRESHOLDS.get(match_format, 120)
    return 'genuine' if bowler_cumulative_balls >= threshold else 'parttimer'


@dataclass
class ProfileStats:
    """Delivery-level accumulator for one bucket of a player profile."""
    n:           int   = 0
    n_boundary:  int   = 0
    n_wicket:    int   = 0
    n_dot:       int   = 0
    total_runs:  float = 0.0

    @property
    def boundary_rate(self) -> float: return self.n_boundary / self.n if self.n else 0.0
    @property
    def wicket_rate(self)   -> float: return self.n_wicket   / self.n if self.n else 0.0
    @property
    def dot_rate(self)      -> float: return self.n_dot      / self.n if self.n else 0.0
    @property
    def economy(self)       -> float: return self.total_runs / self.n * 6 if self.n else 0.0

    def push(self, runs_batter: int, is_wicket: bool, runs_extras: int = 0):
        self.n          += 1
        self.total_runs += runs_batter + runs_extras
        if runs_batter >= 4:  self.n_boundary += 1
        if is_wicket:         self.n_wicket   += 1
        if runs_batter == 0 and runs_extras == 0 and not is_wicket:
            self.n_dot += 1

    def add(self, other: 'ProfileStats'):
        self.n          += other.n
        self.n_boundary += other.n_boundary
        self.n_wicket   += other.n_wicket
        self.n_dot      += other.n_dot
        self.total_runs += other.total_runs


def _fmt_stat_row(label: str, sim: ProfileStats, hist: ProfileStats, min_n: int = 10) -> Optional[str]:
    if sim.n < min_n or hist.n < min_n:
        return None
    bnd_ok = '✓' if abs(sim.boundary_rate - hist.boundary_rate) < 0.025 else '✗'
    wkt_ok = '✓' if abs(sim.wicket_rate   - hist.wicket_rate)   < 0.015 else '✗'
    eco_ok = '✓' if abs(sim.economy       - hist.economy)        < 0.80  else '✗'
    return (f"    {label:<20}  sim_n={sim.n:>5}  hist_n={hist.n:>6}"
            f"  bnd {sim.boundary_rate:.3f}/{hist.boundary_rate:.3f}{bnd_ok}"
            f"  wkt {sim.wicket_rate:.3f}/{hist.wicket_rate:.3f}{wkt_ok}"
            f"  eco {sim.economy:.1f}/{hist.economy:.1f}{eco_ok}")


@dataclass
class PlayerProfileResult:
    player_id:     int
    player_name:   str
    match_format:  str
    n_simulations: int
    elapsed_s:     float

    overall:         tuple  # (sim: ProfileStats, hist: ProfileStats)
    by_phase:        Dict[str, tuple]
    by_milestone:    Dict[str, tuple]
    by_bowler_type:  Dict[str, tuple]

    def report(self) -> str:
        sim_ov, hist_ov = self.overall
        lines = [
            "",
            f"  ══ Player Profile: {self.player_name} ({self.match_format}) ══",
            f"  Simulations : {self.n_simulations}  ·  Elapsed: {self.elapsed_s:.1f}s",
            f"  Deliveries  : sim={sim_ov.n}  hist={hist_ov.n}",
            "",
            f"  {'Bucket':<20}  {'sim_n':>6}  {'hist_n':>7}"
            f"  {'bnd sim/hist':>12}  {'wkt sim/hist':>12}  {'eco sim/hist':>12}",
        ]
        # Overall
        row = _fmt_stat_row("overall", sim_ov, hist_ov, min_n=20)
        if row: lines.append(row)

        lines.append("")
        lines.append("  By phase:")
        for key in sorted(self.by_phase):
            sim_s, hist_s = self.by_phase[key]
            row = _fmt_stat_row(key, sim_s, hist_s)
            if row: lines.append(row)

        lines.append("")
        lines.append("  By milestone:")
        for label, lo, hi in _MILESTONE_BANDS:
            if label not in self.by_milestone: continue
            sim_s, hist_s = self.by_milestone[label]
            row = _fmt_stat_row(label, sim_s, hist_s)
            if row: lines.append(row)

        lines.append("")
        lines.append("  By bowler type:")
        for key in ('genuine', 'parttimer'):
            if key not in self.by_bowler_type: continue
            sim_s, hist_s = self.by_bowler_type[key]
            row = _fmt_stat_row(key, sim_s, hist_s)
            if row: lines.append(row)

        lines.append("")
        text = "\n".join(lines)
        print(text)
        return text


# ── Player profile validator ───────────────────────────────────────────────────

class PlayerProfileValidator:
    """
    Simulates N matches and tracks a specific player's deliveries.
    Compares their simulated profile against historical data at the same
    granularity: overall, by phase, by milestone state, by bowler type.

    Two modes:
      config_path  — use a supplied JSON config (player must be in the lineup)
      auto         — query DB for recent real matches featuring the player,
                     reconstruct rosters, and run on those configs

    Usage:
        pv = PlayerProfileValidator()
        result = pv.run(player_name='V Kohli', match_format='T20', n_simulations=50)
        result.report()
    """

    def __init__(self, repo: Optional[StatsRepository] = None):
        self.repo = repo or StatsRepository()

    def run(
        self,
        player_name: str,
        match_format: str,
        n_simulations: int = 50,
        config_path: Optional[str] = None,
        gender: str = 'male',
        n_auto_matches: int = 5,
        outcome_strategy_type: str = 'enhanced',
        bowling_strategy_type: str = 'historical',
    ) -> PlayerProfileResult:
        from simulator.simulate_driver import (
            _build_match, _OUTCOME_STRATEGIES, _BOWLING_STRATEGY_FACTORIES,
        )
        from simulator.engines.engine_factory import EngineFactory

        fmt = MatchRules.get_unified_format(match_format)
        t_start = time.perf_counter()

        # Resolve player
        res = self.repo.get_player_by_name(player_name)
        if not res:
            raise ValueError(f"Player '{player_name}' not found in DB")
        player_id, resolved_name = res

        # Historical profile
        hist_rows = self.repo.get_player_historical_profile(player_id, fmt, gender)
        hist_overall, hist_phase, hist_milestone, hist_bowler = self._bucket_historical(
            hist_rows, fmt
        )

        # Build match configs
        if config_path:
            configs = [json.load(open(config_path))]
        else:
            configs = self._auto_configs(player_id, fmt, gender, n_auto_matches)

        if not configs:
            raise ValueError(
                f"No match configs available for {resolved_name}. "
                "Supply --config or ensure the player has recent DB matches."
            )

        from simulator.entities.team import MatchTeam
        from simulator.entities.match import SimulationMatch

        # Pre-resolve all configs once — no repeated DB calls per simulation.
        resolved_matches = [_build_match(cfg, self.repo) for cfg in configs]

        # Collect all unique player IDs from all configs in one pass.
        all_player_ids = list({
            p.id
            for m in resolved_matches
            for p in list(m.home_team.players) + list(m.away_team.players)
        })
        bowler_career_balls: Dict[int, int] = self.repo.get_bowler_career_balls(
            all_player_ids, fmt, gender
        )

        # Build a union match covering all unique players so init_model loads
        # stats for every player in one DB round-trip.
        seen: set = set()
        union_home, union_away = [], []
        for m in resolved_matches:
            for p in m.home_team.players:
                if p.id not in seen:
                    seen.add(p.id)
                    union_home.append(p)
            for p in m.away_team.players:
                if p.id not in seen:
                    seen.add(p.id)
                    union_away.append(p)

        first = resolved_matches[0]
        union_match = SimulationMatch(
            id=0,
            home_team=MatchTeam(id=1, name='_union_home', players=union_home),
            away_team=MatchTeam(id=2, name='_union_away', players=union_away),
            venue=first.venue,
            match_format=fmt,
            balls_per_over=6,
            overs_per_innings=first.overs_per_innings,
            innings_per_match=first.innings_per_match,
        )

        # Initialise strategies once.
        outcome_cls   = _OUTCOME_STRATEGIES[outcome_strategy_type][fmt]
        bowling_fn    = _BOWLING_STRATEGY_FACTORIES[bowling_strategy_type]
        outcome_strat = outcome_cls()
        bowling_strat = bowling_fn(fmt)
        outcome_strat.init_model(union_match)
        bowling_strat.init_model(union_match)

        # Snapshot per-config metadata so the loop does pure Python construction.
        config_snapshots = [
            (
                m.home_team.name, list(m.home_team.players),
                m.away_team.name, list(m.away_team.players),
                m.venue,
                {'overs_per_innings': m.overs_per_innings,
                 'innings_per_match': m.innings_per_match},
            )
            for m in resolved_matches
        ]

        sim_overall    : ProfileStats              = ProfileStats()
        sim_phase      : Dict[str, ProfileStats]   = defaultdict(ProfileStats)
        sim_milestone  : Dict[str, ProfileStats]   = defaultdict(ProfileStats)
        sim_bowler_type: Dict[str, ProfileStats]   = defaultdict(ProfileStats)

        sims_done = 0
        for sim_i in range(n_simulations):
            hn, hp, an, ap, v, fs = config_snapshots[sim_i % len(config_snapshots)]
            match = SimulationMatch(
                id=sim_i + 1,
                home_team=MatchTeam(id=1, name=hn, players=hp),
                away_team=MatchTeam(id=2, name=an, players=ap),
                venue=v,
                match_format=fmt,
                balls_per_over=6,
                **fs,
            )
            engine = EngineFactory.create(match, outcome_strat, bowling_strat)
            engine.simulate()

            for inning in match.innings:
                batter_runs_so_far: Dict[int, int] = {}
                for delivery in inning.deliveries:
                    if delivery.batter is None:
                        continue
                    bid = delivery.batter.id
                    if bid != player_id:
                        batter_runs_so_far[bid] = (
                            batter_runs_so_far.get(bid, 0) + delivery.runs_batter
                        )
                        continue

                    score_before = batter_runs_so_far.get(player_id, 0)
                    rb  = delivery.runs_batter
                    rx  = delivery.runs_extras
                    wkt = delivery.is_wicket

                    # Bowler type: use career ball count (same threshold as historical side)
                    bowler_id    = delivery.bowler.id if delivery.bowler else None
                    career_balls = bowler_career_balls.get(bowler_id, 0) if bowler_id else 0
                    btype = _bowler_type_label(career_balls, fmt)

                    phase = MatchRules.get_fine_grained_phase(delivery.over_number + 1, fmt)
                    mil   = _milestone_label(score_before)

                    sim_overall.push(rb, wkt, rx)
                    sim_phase[phase].push(rb, wkt, rx)
                    sim_milestone[mil].push(rb, wkt, rx)
                    sim_bowler_type[btype].push(rb, wkt, rx)

                    batter_runs_so_far[player_id] = score_before + rb

            sims_done += 1
            if sims_done % 10 == 0:
                print(f"  [PlayerProfileValidator] {sims_done}/{n_simulations} …")

        def _pair(sim_dict, hist_dict):
            keys = sorted(set(sim_dict) | set(hist_dict))
            return {k: (sim_dict.get(k, ProfileStats()), hist_dict.get(k, ProfileStats()))
                    for k in keys}

        return PlayerProfileResult(
            player_id    = player_id,
            player_name  = resolved_name,
            match_format = fmt,
            n_simulations= n_simulations,
            elapsed_s    = time.perf_counter() - t_start,
            overall      = (sim_overall, hist_overall),
            by_phase     = _pair(sim_phase,       hist_phase),
            by_milestone = _pair(sim_milestone,   hist_milestone),
            by_bowler_type = _pair(sim_bowler_type, hist_bowler),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _bucket_historical(
        self,
        rows: list,
        match_format: str,
    ):
        """
        Bucket historical delivery rows into overall / phase / milestone / bowler_type.
        Row format: (over_number, runs_batter, outcome_type,
                     batter_score_before, bowler_cumulative_balls)
        """
        overall    = ProfileStats()
        by_phase   : Dict[str, ProfileStats] = defaultdict(ProfileStats)
        by_mil     : Dict[str, ProfileStats] = defaultdict(ProfileStats)
        by_bowler  : Dict[str, ProfileStats] = defaultdict(ProfileStats)

        for (over_0idx, rb, ot, score_before, bowler_balls) in rows:
            is_wkt  = (ot == 'Wicket')
            is_bnd  = (rb >= 4)
            is_dot  = (rb == 0 and ot not in ('Wicket', 'Extras'))
            phase   = MatchRules.get_fine_grained_phase(over_0idx + 1, match_format)
            mil     = _milestone_label(int(score_before or 0))
            btype   = _bowler_type_label(int(bowler_balls or 0), match_format)

            for acc in (overall, by_phase[phase], by_mil[mil], by_bowler[btype]):
                acc.n          += 1
                acc.total_runs += rb
                if is_bnd: acc.n_boundary += 1
                if is_wkt: acc.n_wicket   += 1
                if is_dot: acc.n_dot      += 1

        return overall, dict(by_phase), dict(by_mil), dict(by_bowler)

    def _auto_configs(
        self,
        player_id: int,
        match_format: str,
        gender: str,
        n_matches: int,
    ) -> List[dict]:
        """
        Finds recent historical matches for the player and reconstructs
        match configs from the DB rosters.
        """
        recent = self.repo.get_player_recent_matches(player_id, match_format, gender, n_matches)
        configs = []
        for (match_id, venue_id, venue_name, venue_country,
             home_team_id, away_team_id, _date) in recent:
            roster = self.repo.get_match_lineup(match_id)
            teams: Dict[int, Dict] = {}
            for (tid, tname, pid, pname) in roster:
                if tid not in teams:
                    teams[tid] = {'name': tname, 'players': []}
                teams[tid]['players'].append(pname)

            team_list = list(teams.values())
            if len(team_list) < 2:
                continue
            # Put the player's team first so they always bat in a defined slot
            player_team_id = next(
                (tid for (tid, tname, pid, pname) in roster if pid == player_id),
                list(teams.keys())[0]
            )
            other_teams = [t for tid, t in teams.items() if tid != player_team_id]
            if not other_teams:
                continue

            configs.append({
                'format':   match_format,
                'venue':    venue_name,
                'team_a':   teams[player_team_id],
                'team_b':   other_teams[0],
            })
        return configs


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    import argparse
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

    parser = argparse.ArgumentParser(description="Simulation-based model validator")
    parser.add_argument('--format',       default='T20', choices=['T20', 'ODI', 'Test'])
    parser.add_argument('--config',       default=None,
                        help="Match config JSON (same format as simulate_driver.py)")
    parser.add_argument('--simulations',  default=50,    type=int)
    parser.add_argument('--outcome',      default='enhanced',
                        choices=['enhanced', 'historical'])
    parser.add_argument('--bowling',      default='historical',
                        choices=['historical', 'smart'])
    parser.add_argument('--auto-venues',  action='store_true',
                        help="Auto-pick top 3 data-rich venues and run simulations for each")
    parser.add_argument('--player',       default=None,
                        help="Player name for profile validation (e.g. 'V Kohli'). "
                             "Auto-constructs configs from DB unless --config is given.")
    parser.add_argument('--gender',       default='male', choices=['male', 'female'])
    args = parser.parse_args()

    repo = StatsRepository()

    if args.player:
        pv = PlayerProfileValidator(repo)
        result = pv.run(
            player_name          = args.player,
            match_format         = args.format,
            n_simulations        = args.simulations,
            config_path          = args.config,
            gender               = args.gender,
            outcome_strategy_type= args.outcome,
            bowling_strategy_type= args.bowling,
        )
        result.report()
        return

    sv = SimulationValidator(repo)
    if args.auto_venues:
        results = sv.run_auto_venues(
            args.format, args.config or 'match_config.json',
            n_simulations=args.simulations
        )
        for r in results:
            r.report()
    else:
        result = sv.run_from_config(
            args.config or 'match_config.json',
            n_simulations        = args.simulations,
            outcome_strategy_type= args.outcome,
            bowling_strategy_type= args.bowling,
        )
        result.report()


if __name__ == '__main__':
    _cli()
