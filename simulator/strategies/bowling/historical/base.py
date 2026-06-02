"""
Shared base for all historical bowling strategies.

Scoring is decomposed into four explicit factors, applied by each subclass:

  F1  phase_venue  — how often this bowler bowls in this phase (data-driven),
                     quality in that phase, plus venue modifier.
                     Dominant factor in all formats.

  F2  match_form   — economy + wickets this match, blended with career as
                     match sample grows. Career stats are the cold-start baseline.

  F3  spell        — positive ramp while within spell limit (continuity bonus);
                     escalating quadratic penalty once spell limit is exceeded.

  F4  matchup      — H2H economy + wicket-rate vs the striker (full)
                     and non-striker (half, faces ~40% of balls).
                     Least-weighted factor in every format.

Format-specific weights live entirely in each subclass's _score_and_breakdown() method.
"""

import logging
import math
import time
from abc import abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional, Tuple

from db.stats_repository import StatsRepository
from simulator.entities.inning_player import InningPlayer
from simulator.entities.match import SimulationMatch
from simulator.entities.rules import MatchRules
from simulator.strategies.bowling.strategy_interface import BowlingStrategy
from simulator.logger import get_logger

log = get_logger()

_DEFAULT_WORKLOAD = {
    'avg_overs_per_innings': 5.0,
    'p75_overs_per_innings': 6.0,
    'p75_spell':             4.0,
}

# avg spell is typically ~65 % of the p75 spell limit (empirical estimate).
_AVG_SPELL_RATIO   = 0.85
# Fatigue decays at 1/8 the rate it accumulates (recovery is 8x slower).
_RECOVERY_RATE     = 0.13

_MIN_CAREER_BALLS = 6
_MIN_H2H_BALLS    = 6

# Asymmetric eco scoring: reward for bowling below neutral is 3x the penalty
_ECO_NEUTRAL      = 8.0
_ECO_BASE         = 2.5
_ECO_BONUS_RATE   = 0.6
_ECO_PENALTY_RATE = 0.2
_ECO_FLOOR        = 0.5


def _eco_score(eco: float) -> float:
    diff = _ECO_NEUTRAL - eco
    if diff >= 0:
        return _ECO_BASE + diff * _ECO_BONUS_RATE
    return max(_ECO_FLOOR, _ECO_BASE + diff * _ECO_PENALTY_RATE)


_RESERVE_SCALE      = 10.0
_SOFT_RESERVE_SCALE = 3.0
_DEATH_THRESHOLD    = 0.5

# Phase-transition half-width for Test ball-age phases only.
_TEST_TRANSITION_W = 3.0

# ── Three-level adaptive blending: venue → country → global ──────────────────
# Match counts at which each level saturates its maximum weight.
_VENUE_SAT   =  8   # saturates at 8 venue matches
_COUNTRY_SAT = 15   # saturates at 15 country/region matches
# Maximum weights when the level has sufficient data.
_VENUE_MAX_W   = 0.55
_COUNTRY_MAX_W = 0.85

# West Indies island countries that should be pooled into one regional dataset.
_WEST_INDIES_COUNTRIES = [
    'Antigua and Barbuda', 'Barbados', 'Dominica', 'Grenada', 'Guyana',
    'Jamaica', 'Saint Kitts and Nevis', 'Saint Lucia',
    'Saint Vincent and the Grenadines', 'Trinidad and Tobago',
]
# Maps each WI island → the full pool list so a Barbados venue gets all WI data.
_REGION_MAP = {c: _WEST_INDIES_COUNTRIES for c in _WEST_INDIES_COUNTRIES}


def _region_countries(country: str):
    """Returns the country pool to use for DB queries — WI islands get grouped."""
    return _REGION_MAP.get(country, [country])


def _three_level_blend(vf: float, n_v: int, cf: float, n_c: int, gf: float) -> float:
    """
    Adaptive venue→country→global blend.
    Weights grow with sample size up to their respective maxima.
    Falls through cleanly: no venue data → country+global; no country data → global.
    """
    vw = min(_VENUE_MAX_W, _VENUE_MAX_W * n_v / _VENUE_SAT) if n_v > 0 else 0.0
    remaining = 1.0 - vw
    cw = min(_COUNTRY_MAX_W * remaining,
             remaining * min(1.0, n_c / _COUNTRY_SAT)) if n_c > 0 else 0.0
    gw = 1.0 - vw - cw
    return vw * vf + cw * cf + gw * gf


class HistoricalBowlingBase(BowlingStrategy):
    """
    Loads per-bowler caches from DB and exposes four scoring factors.
    Subclasses must implement _quota(), _eligible(), and _score_and_breakdown().
    """

    def __init__(self, repo=None):
        if repo is None:
            repo = StatsRepository()
        self.repo = repo

        self.career_cache:          Dict[int, Dict]              = {}
        self.phase_cache:           Dict[int, Dict[str, Dict]]   = {}
        self.over_freq_cache:         Dict[int, Dict[int, float]] = {}
        self.over_freq_cache_inn1:    Dict[int, Dict[int, float]] = {}
        self.over_freq_cache_inn2:    Dict[int, Dict[int, float]] = {}
        self.global_over_freq_cache:  Dict[int, Dict[int, float]] = {}
        self.phase_dist_cache:        Dict[int, Dict[str, float]] = {}
        self.phase_dist_cache_inn1:   Dict[int, Dict[str, float]] = {}
        self.phase_dist_cache_inn2:   Dict[int, Dict[str, float]] = {}
        self.test_phase_freq_cache:        Dict[int, Dict] = {}
        self.global_test_phase_freq_cache: Dict[int, Dict] = {}
        self.venue_test_phase_freq_cache:  Dict[int, Dict] = {}
        self.venue_over_freq_cache:       Dict[int, Dict[int, float]] = {}
        self.venue_over_freq_cache_inn1:  Dict[int, Dict[int, float]] = {}
        self.venue_over_freq_cache_inn2:  Dict[int, Dict[int, float]] = {}
        self.matchup_cache:         Dict[Tuple[int,int], Dict]   = {}
        self.workload_cache:        Dict[int, Dict]              = {}
        self.form_cache:            Dict[int, Dict]              = {}

        self._fmt    = "T20"
        self._gender = "male"
        self._initialized = False
        self._loaded_ids: set = set()   # player IDs whose global caches are loaded

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def init_model(self, match: SimulationMatch) -> None:
        home_ids = [p.id for p in match.home_team.players] if match.home_team else []
        away_ids = [p.id for p in match.away_team.players] if match.away_team else []
        all_ids  = home_ids + away_ids

        if not self._initialized:
            # First call: full init including format/gender, all caches for this match.
            self._do_full_init(match, all_ids)
            self._loaded_ids.update(all_ids)
            self._initialized = True
            return

        # Subsequent calls (tournament): extend global caches for any new player IDs.
        new_ids = [pid for pid in all_ids if pid not in self._loaded_ids]
        if new_ids:
            self._extend_global_caches(new_ids)
            self._loaded_ids.update(new_ids)

    def _do_full_init(self, match: SimulationMatch, all_ids: list) -> None:
        """First-time full cache load for a match's player set and venue."""
        self._fmt    = MatchRules.get_unified_format(match.match_format)
        self._gender = getattr(match, "gender", "male").lower()

        venue    = getattr(match, "venue", None)
        country  = venue.country if venue else None
        venue_id = venue.id      if venue else None
        country_group = _region_countries(country) if country else None

        log.console("[BowlingModel] Loading caches — format=%s  gender=%s  players=%d  country=%s  venue_id=%s",
                    self._fmt, self._gender, len(all_ids), country or "global", venue_id)
        t0 = time.perf_counter()

        def _q(method, *args, **kw):
            return lambda repo: getattr(repo, method)(*args, **kw)

        tasks = [
            ("career_stats",    _q("get_bowler_career_stats",      all_ids, self._fmt, self._gender)),
            ("phase_stats",     _q("get_bowler_phase_stats",        all_ids, self._fmt, self._gender)),
            ("batter_matchups", _q("get_batter_bowler_matchups",    all_ids, all_ids, self._fmt, self._gender)),
            ("workload_stats",  _q("get_bowler_workload_stats",     all_ids, self._fmt, self._gender)),
            ("recent_form",     _q("get_bowler_recent_form",        all_ids, self._fmt, self._gender)),
        ]

        if self._fmt == "Test":
            tasks.append(("test_phase_freq_global", _q("get_bowler_test_phase_frequency", all_ids, self._gender)))
            if country_group:
                tasks.append(("test_phase_freq_country", _q("get_bowler_test_phase_frequency", all_ids, self._gender, countries=country_group)))
            if venue_id:
                tasks.append(("test_phase_freq_venue", _q("get_bowler_test_phase_frequency", all_ids, self._gender, venue_id=venue_id)))
        elif self._fmt == "T20":
            tasks += [
                ("over_freq_global",     _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender)),
                ("over_freq_intl",       _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender, match_type='international')),
                ("over_freq_intl_inn1",  _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender, match_type='international', inning_number=1)),
                ("over_freq_intl_inn2",  _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender, match_type='international', inning_number=2)),
                ("phase_dist_intl",      _q("get_bowler_phase_overs_distribution", all_ids, self._fmt, self._gender, match_type='international')),
                ("phase_dist_intl_inn1", _q("get_bowler_phase_overs_distribution", all_ids, self._fmt, self._gender, match_type='international', inning_number=1)),
                ("phase_dist_intl_inn2", _q("get_bowler_phase_overs_distribution", all_ids, self._fmt, self._gender, match_type='international', inning_number=2)),
            ]
            if venue_id:
                tasks += [
                    ("over_freq_venue",      _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender, venue_id=venue_id)),
                    ("over_freq_venue_inn1", _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender, venue_id=venue_id, inning_number=1)),
                    ("over_freq_venue_inn2", _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender, venue_id=venue_id, inning_number=2)),
                ]
        else:  # ODI
            tasks += [
                ("over_freq_global", _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender)),
                ("phase_dist",       _q("get_bowler_phase_overs_distribution", all_ids, self._fmt, self._gender)),
                ("phase_dist_inn1",  _q("get_bowler_phase_overs_distribution", all_ids, self._fmt, self._gender, inning_number=1)),
                ("phase_dist_inn2",  _q("get_bowler_phase_overs_distribution", all_ids, self._fmt, self._gender, inning_number=2)),
            ]
            if country_group:
                tasks += [
                    ("over_freq_country",      _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender, countries=country_group)),
                    ("over_freq_country_inn1", _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender, countries=country_group, inning_number=1)),
                    ("over_freq_country_inn2", _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender, countries=country_group, inning_number=2)),
                ]
            if venue_id:
                tasks += [
                    ("over_freq_venue",      _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender, venue_id=venue_id)),
                    ("over_freq_venue_inn1", _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender, venue_id=venue_id, inning_number=1)),
                    ("over_freq_venue_inn2", _q("get_bowler_over_frequency", all_ids, self._fmt, self._gender, venue_id=venue_id, inning_number=2)),
                ]

        def _run(label, fn):
            repo = StatsRepository()
            try:
                t = time.perf_counter()
                result = fn(repo)
                log.info("[BowlingModel]   %-38s  %.2fs", label, time.perf_counter() - t)
                return label, result
            finally:
                if getattr(repo, 'conn', None):
                    try:
                        repo.conn.close()
                    except Exception:
                        pass

        results = {}
        with ThreadPoolExecutor(max_workers=min(len(tasks), 8)) as pool:
            futures = {pool.submit(_run, label, fn): label for label, fn in tasks}
            for future in as_completed(futures):
                task_label = futures[future]
                try:
                    returned_label, result = future.result()
                    results[returned_label] = result
                except Exception as e:
                    log.warning("[BowlingModel] Cache '%s' failed: %s", task_label, e)
                    results[task_label] = {}

        self.career_cache   = results.get("career_stats",    {})
        self.phase_cache    = results.get("phase_stats",     {})
        self.matchup_cache  = results.get("batter_matchups", {})
        self.workload_cache = results.get("workload_stats",  {})
        self.form_cache     = results.get("recent_form",     {})

        if self._fmt == "Test":
            self.global_test_phase_freq_cache = results.get("test_phase_freq_global",  {})
            self.test_phase_freq_cache        = results.get("test_phase_freq_country", {})
            self.venue_test_phase_freq_cache  = results.get("test_phase_freq_venue",   {})
        elif self._fmt == "T20":
            self.global_over_freq_cache  = results.get("over_freq_global",     {})
            self.over_freq_cache         = results.get("over_freq_intl",       {})
            self.over_freq_cache_inn1    = results.get("over_freq_intl_inn1",  {})
            self.over_freq_cache_inn2    = results.get("over_freq_intl_inn2",  {})
            self.phase_dist_cache        = results.get("phase_dist_intl",      {})
            self.phase_dist_cache_inn1   = results.get("phase_dist_intl_inn1", {})
            self.phase_dist_cache_inn2   = results.get("phase_dist_intl_inn2", {})
            self.venue_over_freq_cache      = results.get("over_freq_venue",      {})
            self.venue_over_freq_cache_inn1 = results.get("over_freq_venue_inn1", {})
            self.venue_over_freq_cache_inn2 = results.get("over_freq_venue_inn2", {})
        else:  # ODI
            self.global_over_freq_cache  = results.get("over_freq_global",       {})
            self.over_freq_cache         = results.get("over_freq_country",      {})
            self.over_freq_cache_inn1    = results.get("over_freq_country_inn1", {})
            self.over_freq_cache_inn2    = results.get("over_freq_country_inn2", {})
            self.phase_dist_cache        = results.get("phase_dist",             {})
            self.phase_dist_cache_inn1   = results.get("phase_dist_inn1",        {})
            self.phase_dist_cache_inn2   = results.get("phase_dist_inn2",        {})
            self.venue_over_freq_cache      = results.get("over_freq_venue",      {})
            self.venue_over_freq_cache_inn1 = results.get("over_freq_venue_inn1", {})
            self.venue_over_freq_cache_inn2 = results.get("over_freq_venue_inn2", {})

        log.console("[BowlingModel] All caches ready — total %.2fs", time.perf_counter() - t0)

    def _extend_global_caches(self, new_ids: list) -> None:
        """
        Load format-level global caches for player IDs not seen in the first match.
        Called on each subsequent match in a tournament. Venue/country caches are
        not extended here — global data is the appropriate fallback across venues.
        """
        log.console("[BowlingModel] Extending caches for %d new players", len(new_ids))

        def _q(method, *args, **kw):
            return lambda repo: getattr(repo, method)(*args, **kw)

        tasks = [
            ("career_stats",   _q("get_bowler_career_stats",            new_ids, self._fmt, self._gender)),
            ("workload_stats", _q("get_bowler_workload_stats",           new_ids, self._fmt, self._gender)),
            ("recent_form",    _q("get_bowler_recent_form",              new_ids, self._fmt, self._gender)),
            ("matchups",       _q("get_batter_bowler_matchups",          new_ids, new_ids, self._fmt, self._gender)),
        ]
        if self._fmt == "Test":
            tasks.append(("global_test", _q("get_bowler_test_phase_frequency", new_ids, self._gender)))
        else:
            tasks.append(("global_freq", _q("get_bowler_over_frequency",       new_ids, self._fmt, self._gender)))
            if self._fmt != "Test":
                tasks.append(("phase_dist", _q("get_bowler_phase_overs_distribution", new_ids, self._fmt, self._gender)))

        def _run(label, fn):
            repo = StatsRepository()
            try:
                return label, fn(repo)
            finally:
                if getattr(repo, 'conn', None):
                    try: repo.conn.close()
                    except Exception: pass

        results = {}
        with ThreadPoolExecutor(max_workers=min(len(tasks), 4)) as pool:
            futures = {pool.submit(_run, label, fn): label for label, fn in tasks}
            for future in as_completed(futures):
                try:
                    label, result = future.result()
                    results[label] = result
                except Exception as e:
                    log.warning("[BowlingModel] Cache extend '%s' failed: %s", futures[future], e)

        # Merge into existing caches (existing entries not overwritten)
        self.career_cache.update(results.get("career_stats",  {}))
        self.workload_cache.update(results.get("workload_stats", {}))
        self.form_cache.update(results.get("recent_form",    {}))
        self.matchup_cache.update(results.get("matchups",    {}))
        if self._fmt == "Test":
            self.global_test_phase_freq_cache.update(results.get("global_test", {}))
        else:
            self.global_over_freq_cache.update(results.get("global_freq", {}))
            if self._fmt == "ODI":
                self.phase_dist_cache.update(results.get("phase_dist", {}))
            elif self._fmt == "T20":
                self.phase_dist_cache.update(results.get("phase_dist", {}))

    # ── Bowler selection ──────────────────────────────────────────────────────

    def select_bowler(self, match: SimulationMatch) -> Optional[InningPlayer]:
        team = match.current_bowling_team
        if not team or not team.inning_players:
            return match.current_bowler

        eligible = self._eligible(team, match.current_bowler, match)

        if not eligible:
            quota = self._quota()
            eligible = [
                ip for ip in team.inning_players
                if ip != match.current_bowler
                and (not quota or ip.balls_bowled // 6 < quota)
            ]

        if not eligible:
            return match.current_bowler

        debug = log.isEnabledFor(logging.DEBUG)
        scored    = []
        breakdown = {}

        for ip in eligible:
            total, factors = self._score_and_breakdown(ip, match)
            scored.append((ip, total))
            if debug:
                breakdown[ip.id] = factors

        scored.sort(key=lambda x: x[1], reverse=True)

        if debug:
            self._log_selection(match, scored, breakdown)

        return scored[0][0]

    def _log_selection(self, match: SimulationMatch, scored: list, breakdown: dict) -> None:
        scores = [s for _, s in scored]
        max_s  = max(scores)
        exps   = [math.exp(min(s - max_s, 0)) for s in scores]
        total  = sum(exps)
        probs  = [e / total * 100 for e in exps]

        lines = []
        for (ip, s), prob in zip(scored, probs):
            overs = ip.balls_bowled // 6
            bd    = breakdown.get(ip.id, {})
            f_str = "  ".join(f"{k}={v:+.2f}" for k, v in bd.items()) if bd else ""
            lines.append(
                f"    {ip.name:25s}  score={s:6.2f}  prob={prob:5.1f}%"
                f"  ({overs}ov)  {f_str}"
            )

        team_name = getattr(match.current_bowling_team, 'name', '?')
        log.debug(
            "[BowlingSelection] Inn%d Ov%d — %s:\n%s\n    → %s",
            len(match.innings), match.current_over + 1,
            team_name, "\n".join(lines), scored[0][0].name,
        )

    # ── Subclass contracts ────────────────────────────────────────────────────

    @abstractmethod
    def _quota(self) -> Optional[int]:
        """Overs cap per bowler per innings. Return None for unlimited (Test)."""

    @abstractmethod
    def _eligible(self, team, current_bowler, match: SimulationMatch):
        """Returns the list of InningPlayers eligible to bowl the next over."""

    @abstractmethod
    def _score_and_breakdown(self, ip: InningPlayer, match: SimulationMatch) -> Tuple[float, dict]:
        """
        Returns (total_score, factor_breakdown).
        factor_breakdown is a dict with keys F1, F2, F3, F4 and their contributions.
        Hard-capped bowlers return (-1000, {}).
        """

    # ── Hard cap ─────────────────────────────────────────────────────────────

    def _hard_cap(self, ip: InningPlayer) -> bool:
        """True if bowler exceeded 2x their expected innings overs. Caller returns -1000."""
        workload = self.workload_cache.get(ip.id, _DEFAULT_WORKLOAD)
        return ip.balls_bowled // 6 >= workload['avg_overs_per_innings'] * 2.0

    # ── Factor 1: Phase affinity ──────────────────────────────────────────────

    @staticmethod
    def _phase_rw(over: float, boundary: float, width: float) -> float:
        return max(0.0, min(1.0, (over - (boundary - width)) / (2.0 * width)))

    def _f_over_affinity(self, ip: InningPlayer, key: int, phase_weight: float,
                         inning_num: Optional[int] = None) -> float:
        if inning_num == 1:
            v_entry = self.venue_over_freq_cache_inn1.get(ip.id) or self.venue_over_freq_cache.get(ip.id)
            c_entry = self.over_freq_cache_inn1.get(ip.id)       or self.over_freq_cache.get(ip.id)
        elif inning_num == 2:
            v_entry = self.venue_over_freq_cache_inn2.get(ip.id) or self.venue_over_freq_cache.get(ip.id)
            c_entry = self.over_freq_cache_inn2.get(ip.id)       or self.over_freq_cache.get(ip.id)
        else:
            v_entry = self.venue_over_freq_cache.get(ip.id)
            c_entry = self.over_freq_cache.get(ip.id)

        gf = self.global_over_freq_cache.get(ip.id, {}).get(key, 0.0)
        cf = c_entry.get(key, 0.0) if c_entry is not None else 0.0
        vf = v_entry.get(key, 0.0) if v_entry is not None else 0.0

        # n counts not stored in over_freq cache — use presence as a binary signal,
        # so venue/country weights are fixed at their saturation values when data exists.
        n_v = _VENUE_SAT   if v_entry else 0
        n_c = _COUNTRY_SAT if c_entry else 0

        return _three_level_blend(vf, n_v, cf, n_c, gf) * phase_weight

    def _f_test_phase_affinity(self, ip: InningPlayer, ball_age: int,
                               innings_bucket: int, phase_weight: float) -> float:
        W         = _TEST_TRANSITION_W
        phase_idx = ball_age // 10
        dist_prev = ball_age - phase_idx * 10
        dist_next = (phase_idx + 1) * 10 - ball_age

        def _freq(ph: int) -> float:
            ph = max(0, min(7, ph))
            v  = self.venue_test_phase_freq_cache.get(ip.id, {})
            c  = self.test_phase_freq_cache.get(ip.id, {})
            g  = self.global_test_phase_freq_cache.get(ip.id, {})
            n_v = v.get('n', 0)
            n_c = c.get('n', 0)
            vf = v.get('buckets', {}).get(innings_bucket, {}).get(ph, 0.0)
            cf = c.get('buckets', {}).get(innings_bucket, {}).get(ph, 0.0)
            gf = g.get('buckets', {}).get(innings_bucket, {}).get(ph, 0.0)
            return _three_level_blend(vf, n_v, cf, n_c, gf)

        if dist_prev < W and phase_idx > 0:
            B  = phase_idx * 10
            rw = self._phase_rw(ball_age, B, W)
            return ((1 - rw) * _freq(phase_idx - 1) + rw * _freq(phase_idx)) * phase_weight

        if dist_next <= W and phase_idx < 7:
            B  = (phase_idx + 1) * 10
            rw = self._phase_rw(ball_age, B, W)
            return ((1 - rw) * _freq(phase_idx) + rw * _freq(phase_idx + 1)) * phase_weight

        return _freq(phase_idx) * phase_weight

    _PACE_SCALE = 3.0

    # ── Factor 5: Projected-total deviation (T20 / ODI only) ─────────────────

    def _f_phase_pacing(self, ip: InningPlayer, quota: int, match: SimulationMatch) -> float:
        inning_num = getattr(match, 'current_inning', None)

        if inning_num == 1 and self.over_freq_cache_inn1:
            c_entry = self.over_freq_cache_inn1.get(ip.id, {})
        elif inning_num == 2 and self.over_freq_cache_inn2:
            c_entry = self.over_freq_cache_inn2.get(ip.id, {})
        else:
            c_entry = self.over_freq_cache.get(ip.id, {})
        g_entry = self.global_over_freq_cache.get(ip.id, {})

        if not c_entry and not g_entry:
            return 0.0

        if (quota - ip.balls_bowled // 6) <= 0:
            return -1000.0

        expected_avg = self.workload_cache.get(ip.id, {}).get('avg_overs_per_match', 0.0)
        if expected_avg == 0.0:
            return 0.0

        current_over      = match.current_over
        overs_per_innings = match.overs_per_innings or (20 if self._fmt == 'T20' else 50)

        def _blended(key: int) -> float:
            g = g_entry.get(key, 0.0)
            c = c_entry.get(key, 0.0)
            # Simple 70/30 country/global blend; venue not available in freq context
            return (0.70 * c + 0.30 * g) if c_entry else g

        total_freq = 0.0
        expected_remaining = 0.0
        seen_all: set = set()
        seen_future: set = set()
        for k in range(overs_per_innings):
            key = k // 5 if self._fmt == 'ODI' else k
            if key not in seen_all:
                seen_all.add(key)
                total_freq += _blended(key)
            if k > current_over and key not in seen_future:
                seen_future.add(key)
                expected_remaining += _blended(key)

        if total_freq > 0:
            expected_remaining *= expected_avg / total_freq

        projected_total = ip.balls_bowled // 6 + expected_remaining
        return -(projected_total - expected_avg) * self._PACE_SCALE

    # ── Factor 6: Death-phase reservation (T20 / ODI only) ───────────────────

    def _f_death_reservation(self, ip: InningPlayer, quota: int,
                             match: SimulationMatch) -> float:
        current_over = match.current_over

        # 0-indexed over where the death phase begins
        death_start = 15 if self._fmt == 'T20' else 39

        if current_over >= death_start:
            return 0.0

        overs_bowled     = ip.balls_bowled // 6
        overs_remaining  = quota - overs_bowled
        if overs_remaining <= 0:
            return -1000.0

        inning_num = getattr(match, 'current_inning', None)
        if inning_num == 1 and self.phase_dist_cache_inn1:
            phase_dist = self.phase_dist_cache_inn1.get(ip.id)
        elif inning_num == 2 and self.phase_dist_cache_inn2:
            phase_dist = self.phase_dist_cache_inn2.get(ip.id)
        else:
            phase_dist = self.phase_dist_cache.get(ip.id)

        if not phase_dist:
            return 0.0

        death_target = phase_dist.get('death', 0.0)
        if death_target < _DEATH_THRESHOLD:
            return 0.0

        death_reserved   = min(math.ceil(death_target), overs_remaining)
        pre_death_budget = overs_remaining - death_reserved
        pre_death_slots  = death_start - current_over

        if pre_death_budget <= 0:
            return -death_reserved * _RESERVE_SCALE

        if pre_death_slots <= 0 or pre_death_budget >= pre_death_slots:
            return 0.0

        urgency = 1.0 - pre_death_slots / max(1, death_start)
        return -urgency * death_reserved * _SOFT_RESERVE_SCALE

    # ── Factor 2: Match form ──────────────────────────────────────────────────

    def _f_match_form(self, ip: InningPlayer) -> float:
        career       = self.career_cache.get(ip.id, {})
        career_balls = career.get("balls", 0)
        career_eco   = career.get("economy")        if career_balls >= _MIN_CAREER_BALLS else None
        career_wr    = career.get("wicket_rate", 0) if career_balls >= _MIN_CAREER_BALLS else 0.0

        if ip.balls_bowled >= 6:
            match_eco = ip.runs_conceded / (ip.balls_bowled / 6)
            alpha     = min(1.0, ip.balls_bowled / 30)
            eco       = alpha * match_eco + (1.0 - alpha) * (career_eco or match_eco)
            eco_score = _eco_score(eco)
        elif career_eco is not None:
            eco_score = _eco_score(career_eco)
        else:
            eco_score = 0.0

        wicket_score  = ip.wickets_taken * 2.0
        if career_balls >= 30:
            wicket_score += career_wr * 30.0

        return eco_score + wicket_score

    # ── Factor 3: Spell management ────────────────────────────────────────────

    def _f_spell_breakdown(self, ip: InningPlayer, match: SimulationMatch,
                           continuity_weight: float,
                           workload_harshness: float) -> Tuple[float, float, float]:
        wl          = self.workload_cache.get(ip.id, _DEFAULT_WORKLOAD)
        spell_limit = max(3, int(round(wl['p75_spell'])))
        avg_overs   = max(1.0, wl['avg_overs_per_innings'])
        p75_overs   = max(avg_overs + 1.0, wl['p75_overs_per_innings'])

        r              = _AVG_SPELL_RATIO
        fatigue_weight = continuity_weight * (2.0 - r) / r

        current_spell = self._last_spell_length(ip.id, match)
        overs_since   = self._overs_since_bowled(ip.id, match)
        total_overs   = ip.balls_bowled // 6

        rest_overs = max(0.0, overs_since - 2)
        eff_spell  = max(0.0, current_spell - rest_overs * _RECOVERY_RATE)

        continuity = (
            continuity_weight * max(0.0, 2.0 - current_spell / spell_limit)
            if current_spell > 0 and overs_since <= 2 else 0.0
        )
        fatigue  = -(eff_spell / spell_limit) * fatigue_weight
        excess   = max(0.0, total_overs - avg_overs)
        workload = -(excess / (p75_overs - avg_overs)) * workload_harshness

        return continuity, fatigue, workload

    def _f_spell(self, ip: InningPlayer, match: SimulationMatch,
                 continuity_weight: float,
                 workload_harshness: float) -> float:
        c, f, w = self._f_spell_breakdown(ip, match, continuity_weight, workload_harshness)
        return c + f + w

    # ── Factor 4: Matchup ─────────────────────────────────────────────────────

    def _f_matchup(self, ip: InningPlayer, match: SimulationMatch) -> float:
        def _h2h(batter) -> float:
            if not batter:
                return 0.0
            data = self.matchup_cache.get((batter.id, ip.id))
            if not data or data.get("balls", 0) < _MIN_H2H_BALLS:
                return 0.0
            return max(0.0, 7.0 - data["economy"]) * 0.3 + data["wicket_rate"] * 25.0

        return _h2h(match.striker) + _h2h(match.non_striker) * 0.5

    # ── Test spell helpers ────────────────────────────────────────────────────

    def _last_spell_length(self, player_id: int, match: SimulationMatch) -> int:
        """Consecutive same-end overs at the tail of the bowler's innings history."""
        overs = sorted({
            d.over_number
            for d in match.innings[-1].deliveries
            if d.bowler and d.bowler.id == player_id
        })
        if not overs:
            return 0
        spells = [[overs[0]]]
        for ov in overs[1:]:
            if ov - spells[-1][-1] == 2:
                spells[-1].append(ov)
            else:
                spells.append([ov])
        return len(spells[-1])

    def _overs_since_bowled(self, player_id: int, match: SimulationMatch) -> int:
        bowled = {
            d.over_number
            for d in match.innings[-1].deliveries
            if d.bowler and d.bowler.id == player_id
        }
        if not bowled:
            return 999
        return match.current_over - max(bowled)
