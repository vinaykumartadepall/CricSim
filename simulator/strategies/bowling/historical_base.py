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
from typing import Dict, Optional, Tuple

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
# Used to derive fatigue_weight so |fatigue| == continuity exactly at avg spell.
_AVG_SPELL_RATIO   = 0.85
# Fatigue decays at 1/8 the rate it accumulates (recovery is 8x slower).
_RECOVERY_RATE     = 0.13

_MIN_CAREER_BALLS = 6
_MIN_H2H_BALLS    = 6

# Asymmetric eco scoring: reward for bowling below neutral is 3x the penalty
# for bowling above it, so any career bowler organically outscores a non-bowler.
_ECO_NEUTRAL      = 8.0   # reference economy (T20-ish average; format weights scale the rest)
_ECO_BASE         = 2.5   # score at exactly the neutral economy
_ECO_BONUS_RATE   = 0.6   # points gained per run/over below neutral
_ECO_PENALTY_RATE = 0.2   # points lost per run/over above neutral (3x smaller → asymmetric)
_ECO_FLOOR        = 0.5   # minimum for any bowler with career data


def _eco_score(eco: float) -> float:
    diff = _ECO_NEUTRAL - eco
    if diff >= 0:
        return _ECO_BASE + diff * _ECO_BONUS_RATE
    return max(_ECO_FLOOR, _ECO_BASE + diff * _ECO_PENALTY_RATE)

_COUNTRY_WEIGHT  = 0.70   # weight given to country-specific phase frequency
_GLOBAL_WEIGHT   = 0.30   # weight given to global phase frequency

# Death-reservation penalty scales.
# Hard block: when pre_death_budget==0, penalty = -death_reserved * _RESERVE_SCALE.
# At 10.0 × 2 reserved = -20, beats F1 (max ~16) in any middle-over scenario.
_RESERVE_SCALE      = 10.0
# Soft gradient: when budget < slots (idle overs will be wasted), apply a mild
# proportional penalty to conserve overs.  (1-slack) × reserved × _SOFT_SCALE.
# 3.0 → budget=1 of 3 slots → -2.0; budget=1 of 2 → -1.0; budget=1 of 1 → 0.
_SOFT_RESERVE_SCALE = 3.0
# Minimum death_target (avg death overs) before reservation kicks in.
_DEATH_THRESHOLD    = 0.5

# Phase-transition half-width for Test ball-age phases only.
# T20/ODI no longer use soft transitions — per-over data is fine-grained enough.
_TEST_TRANSITION_W = 3.0   # 6-over blend zone per boundary (out of 10-over phases)


class HistoricalBowlingBase(BowlingStrategy):
    """
    Loads per-bowler caches from DB and exposes four scoring factors.
    Subclasses implement _quota(), _eligible(), and _score_and_breakdown().
    """

    def __init__(self):
        from db.stats_repository import StatsRepository
        self.repo = StatsRepository()

        self.career_cache:          Dict[int, Dict]              = {}
        self.phase_cache:           Dict[int, Dict[str, Dict]]   = {}
        # T20/ODI: per-over (T20) or per-5-over-bin (ODI) frequency, keyed by int
        self.over_freq_cache:         Dict[int, Dict[int, float]] = {}  # country/intl, all innings
        self.over_freq_cache_inn1:    Dict[int, Dict[int, float]] = {}  # country/intl, inning 1
        self.over_freq_cache_inn2:    Dict[int, Dict[int, float]] = {}  # country/intl, inning 2
        self.global_over_freq_cache:  Dict[int, Dict[int, float]] = {}  # worldwide prior, all innings
        # T20/ODI: 3-phase avg-overs distribution for quota pacing (F5)
        self.phase_dist_cache:        Dict[int, Dict[str, float]] = {}  # all innings
        self.phase_dist_cache_inn1:   Dict[int, Dict[str, float]] = {}  # inning 1
        self.phase_dist_cache_inn2:   Dict[int, Dict[str, float]] = {}  # inning 2
        # Test: ball-age phase frequency, keyed by {innings_bucket: {phase_idx: float}}
        self.test_phase_freq_cache:        Dict[int, Dict] = {}  # country-specific
        self.global_test_phase_freq_cache: Dict[int, Dict] = {}  # worldwide prior
        self.matchup_cache:         Dict[Tuple[int,int], Dict]   = {}
        self.workload_cache:        Dict[int, Dict]              = {}
        self.form_cache:            Dict[int, Dict]              = {}

        self._fmt    = "T20"
        self._gender = "male"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def init_model(self, match: SimulationMatch) -> None:
        self._fmt    = MatchRules.get_unified_format(match.match_format)
        self._gender = getattr(match, "gender", "male").lower()

        home_ids = [p.id for p in match.home_team.players] if match.home_team else []
        away_ids = [p.id for p in match.away_team.players] if match.away_team else []
        all_ids  = home_ids + away_ids

        venue   = getattr(match, "venue", None)
        country = venue.country if venue else None

        log.console("[BowlingModel] Loading caches — format=%s  gender=%s  players=%d  country=%s",
                    self._fmt, self._gender, len(all_ids), country or "global")
        t0 = time.perf_counter()

        def _timed(label, fn, *args, **kwargs):
            t = time.perf_counter()
            result = fn(*args, **kwargs)
            log.info("[BowlingModel]   %-38s  %.2fs", label, time.perf_counter() - t)
            return result

        self.career_cache  = _timed("career_stats",  self.repo.get_bowler_career_stats,   all_ids, self._fmt, self._gender)
        self.phase_cache   = _timed("phase_stats",   self.repo.get_bowler_phase_stats,    all_ids, self._fmt, self._gender)
        self.matchup_cache = _timed("batter_matchups", self.repo.get_batter_bowler_matchups, all_ids, all_ids, self._fmt, self._gender)
        # T20: international-only workload keeps domestic part-timers (IPL/BBL appearances)
        # from inflating avg_overs_per_innings and F5 scores for batters who rarely bowl.
        _wl_match_type = 'international' if self._fmt == 'T20' else None
        self.workload_cache = _timed("workload_stats", self.repo.get_bowler_workload_stats, all_ids, self._fmt, self._gender, match_type=_wl_match_type)
        self.form_cache     = _timed("recent_form",    self.repo.get_bowler_recent_form,    all_ids, self._fmt, self._gender)

        if self._fmt == "Test":
            self.global_test_phase_freq_cache = _timed(
                "test_phase_freq_global",
                self.repo.get_bowler_test_phase_frequency, all_ids, self._gender,
            )
            self.test_phase_freq_cache = _timed(
                "test_phase_freq_country",
                self.repo.get_bowler_test_phase_frequency, all_ids, self._gender, country=country,
            ) if country else {}
        elif self._fmt == "T20":
            # global = all T20 (domestic + international); primary = international only
            self.global_over_freq_cache = _timed(
                "over_freq_global",
                self.repo.get_bowler_over_frequency, all_ids, self._fmt, self._gender,
            )
            self.over_freq_cache = _timed(
                "over_freq_intl",
                self.repo.get_bowler_over_frequency, all_ids, self._fmt, self._gender,
                match_type='international',
            )
            self.over_freq_cache_inn1 = _timed(
                "over_freq_intl_inn1",
                self.repo.get_bowler_over_frequency, all_ids, self._fmt, self._gender,
                match_type='international', inning_number=1,
            )
            self.over_freq_cache_inn2 = _timed(
                "over_freq_intl_inn2",
                self.repo.get_bowler_over_frequency, all_ids, self._fmt, self._gender,
                match_type='international', inning_number=2,
            )
            self.phase_dist_cache = _timed(
                "phase_dist_intl",
                self.repo.get_bowler_phase_overs_distribution, all_ids, self._fmt, self._gender,
                match_type='international',
            )
            self.phase_dist_cache_inn1 = _timed(
                "phase_dist_intl_inn1",
                self.repo.get_bowler_phase_overs_distribution, all_ids, self._fmt, self._gender,
                match_type='international', inning_number=1,
            )
            self.phase_dist_cache_inn2 = _timed(
                "phase_dist_intl_inn2",
                self.repo.get_bowler_phase_overs_distribution, all_ids, self._fmt, self._gender,
                match_type='international', inning_number=2,
            )
        else:  # ODI
            self.global_over_freq_cache = _timed(
                "over_freq_global",
                self.repo.get_bowler_over_frequency, all_ids, self._fmt, self._gender,
            )
            self.over_freq_cache = _timed(
                "over_freq_country",
                self.repo.get_bowler_over_frequency, all_ids, self._fmt, self._gender, country=country,
            ) if country else {}
            self.over_freq_cache_inn1 = _timed(
                "over_freq_country_inn1",
                self.repo.get_bowler_over_frequency, all_ids, self._fmt, self._gender,
                country=country, inning_number=1,
            ) if country else {}
            self.over_freq_cache_inn2 = _timed(
                "over_freq_country_inn2",
                self.repo.get_bowler_over_frequency, all_ids, self._fmt, self._gender,
                country=country, inning_number=2,
            ) if country else {}
            self.phase_dist_cache = _timed(
                "phase_dist",
                self.repo.get_bowler_phase_overs_distribution, all_ids, self._fmt, self._gender,
            )
            self.phase_dist_cache_inn1 = _timed(
                "phase_dist_inn1",
                self.repo.get_bowler_phase_overs_distribution, all_ids, self._fmt, self._gender,
                inning_number=1,
            )
            self.phase_dist_cache_inn2 = _timed(
                "phase_dist_inn2",
                self.repo.get_bowler_phase_overs_distribution, all_ids, self._fmt, self._gender,
                inning_number=2,
            )

        log.console("[BowlingModel] All caches ready — total %.2fs", time.perf_counter() - t0)

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
        exps   = [math.exp(min(s - max_s, 0)) for s in scores]  # clamp to avoid overflow on -1000
        total  = sum(exps)
        probs  = [e / total * 100 for e in exps]

        lines = []
        for (ip, s), prob in zip(scored, probs):
            overs = ip.balls_bowled // 6
            bd    = breakdown.get(ip.id, {})
            f_str = "  ".join(
                f"{k}={v:+.2f}" for k, v in bd.items()
            ) if bd else ""
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

    def _quota(self) -> Optional[int]:
        raise NotImplementedError

    def _eligible(self, team, current_bowler, match: SimulationMatch):
        raise NotImplementedError

    def _score_and_breakdown(self, ip: InningPlayer, match: SimulationMatch) -> Tuple[float, dict]:
        """
        Returns (total_score, factor_breakdown).
        factor_breakdown is a dict with keys F1, F2, F3, F4 and their contributions.
        Hard-capped bowlers return (-1000, {}).
        """
        raise NotImplementedError

    # ── Hard cap ─────────────────────────────────────────────────────────────

    def _hard_cap(self, ip: InningPlayer) -> bool:
        """True if bowler exceeded 2x their expected innings overs. Caller returns -1000."""
        workload = self.workload_cache.get(ip.id, _DEFAULT_WORKLOAD)
        return ip.balls_bowled // 6 >= workload['avg_overs_per_innings'] * 2.0

    # ── Factor 1: Phase affinity ──────────────────────────────────────────────

    @staticmethod
    def _phase_rw(over: float, boundary: float, width: float) -> float:
        """
        Right-phase weight for a linear soft boundary centred at `boundary`.
        Returns 0 at (boundary - width), 0.5 at boundary, 1 at (boundary + width).
        Clamped to [0, 1] outside the transition window.
        """
        return max(0.0, min(1.0, (over - (boundary - width)) / (2.0 * width)))

    def _f_over_affinity(self, ip: InningPlayer, key: int, phase_weight: float,
                         inning_num: Optional[int] = None) -> float:
        """
        Fraction of innings appearances where the bowler bowled in over `key` (T20) or
        5-over bin `key` (ODI), blended 70/30 country/global.
        inning_num: 1 or 2 — uses inning-specific cache when available; falls back to combined.
        """
        if inning_num == 1 and self.over_freq_cache_inn1:
            c_entry = self.over_freq_cache_inn1.get(ip.id)
        elif inning_num == 2 and self.over_freq_cache_inn2:
            c_entry = self.over_freq_cache_inn2.get(ip.id)
        else:
            c_entry = self.over_freq_cache.get(ip.id)
        g_freq  = self.global_over_freq_cache.get(ip.id, {}).get(key, 0.0)
        if c_entry is not None:
            c_freq = c_entry.get(key, 0.0)
            freq   = _COUNTRY_WEIGHT * c_freq + _GLOBAL_WEIGHT * g_freq
        else:
            freq = g_freq
        return freq * phase_weight

    def _f_test_phase_affinity(self, ip: InningPlayer, ball_age: int,
                               innings_bucket: int, phase_weight: float) -> float:
        """
        Soft Test phase affinity with gradual transitions at phase boundaries.

        Phases are 10-over windows (0-7) within the 80-over new-ball cycle.
        Within _TEST_TRANSITION_W overs of a boundary the two adjacent phases
        are linearly blended; the midpoint of the transition is 50/50.
        Each phase frequency is itself a 70/30 country/global blend (falls back
        to pure global when no country data exists for the bowler).
        """
        W         = _TEST_TRANSITION_W
        phase_idx = ball_age // 10
        dist_prev = ball_age - phase_idx * 10          # overs past previous boundary (0-9)
        dist_next = (phase_idx + 1) * 10 - ball_age    # overs to next boundary (1-10)

        def _freq(ph: int) -> float:
            ph = max(0, min(7, ph))
            c  = self.test_phase_freq_cache.get(ip.id, {})
            g  = self.global_test_phase_freq_cache.get(ip.id, {})
            cf = c.get('buckets', {}).get(innings_bucket, {}).get(ph, 0.0)
            gf = g.get('buckets', {}).get(innings_bucket, {}).get(ph, 0.0)
            return (_COUNTRY_WEIGHT * cf + _GLOBAL_WEIGHT * gf) if c.get('n', 0) > 0 else gf

        if dist_prev < W and phase_idx > 0:
            # Within W overs after the previous boundary: blend phase_idx-1 → phase_idx
            B  = phase_idx * 10
            rw = self._phase_rw(ball_age, B, W)
            return ((1 - rw) * _freq(phase_idx - 1) + rw * _freq(phase_idx)) * phase_weight

        if dist_next <= W and phase_idx < 7:
            # Within W overs before the next boundary: blend phase_idx → phase_idx+1
            B  = (phase_idx + 1) * 10
            rw = self._phase_rw(ball_age, B, W)
            return ((1 - rw) * _freq(phase_idx) + rw * _freq(phase_idx + 1)) * phase_weight

        return _freq(phase_idx) * phase_weight

    _PACE_SCALE = 3.0

    # ── Factor 5: Projected-total deviation (T20 / ODI only) ─────────────────

    def _f_phase_pacing(self, ip: InningPlayer, quota: int, match: SimulationMatch) -> float:
        """
        Projected-total deviation.

        projected_total = overs_bowled + expected_remaining_scaled
        F5 = -(projected_total - avg_overs_per_match) * _PACE_SCALE

          projected > avg  →  on track to over-bowl historically  →  save  →  negative F5
          projected < avg  →  under-bowling historically           →  bowl  →  positive F5

        expected_remaining is the blended (country/global) sum of per-over (T20) or
        per-5-over-bin (ODI) frequencies for all future slots.

        ODI bin correction: the freq cache stores binary "appeared in bin" fractions,
        so their sum (~4–5) underestimates avg_overs_per_match (~8–9). A scale factor
        (avg_overs_per_match / total_freq_sum) corrects this so expected_remaining is
        expressed in actual overs, matching the avg_overs_per_match reference point.
        For T20 (per-over keys) the correction is ~1.0 and has no meaningful effect.

        Signal strength scales with avg_overs_per_match:
          ODI specialists (avg ≈ 8–9): moderate signals, enforces phase distribution
          T20 specialists  (avg ≈ 3–4): strong signals relative to quota
          Part-timers      (avg ≈ 1–2): near-zero signals, F1 drives selection
        """
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

        current_over      = match.current_over   # 0-indexed
        overs_per_innings = match.overs_per_innings or (20 if self._fmt == 'T20' else 50)

        def _blended(key: int) -> float:
            g = g_entry.get(key, 0.0)
            return (_COUNTRY_WEIGHT * c_entry.get(key, 0.0) + _GLOBAL_WEIGHT * g
                    if c_entry else g)

        # Sum blended freq for all bins (for scale correction) and future bins.
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

        # Scale expected_remaining so its units match avg_overs_per_match.
        # For T20 (per-over freq) scale ≈ 1.0; for ODI (per-5-over-bin) scale ≈ 1.7–1.9.
        if total_freq > 0:
            expected_remaining *= expected_avg / total_freq

        projected_total = ip.balls_bowled // 6 + expected_remaining
        return -(projected_total - expected_avg) * self._PACE_SCALE

    # ── Factor 6: Death-phase reservation (T20 / ODI only) ───────────────────

    def _f_death_reservation(self, ip: InningPlayer, quota: int,
                             match: SimulationMatch) -> float:
        """
        Reserve overs for the death phase.

        Uses phase_dist_cache (avg overs per phase from DB) to learn how many
        overs the bowler historically bowls in death.  Before the death phase
        begins, those overs are "locked" — bowling any of them pre-death incurs
        a penalty proportional to how many must be saved.

        Penalty = -ceil(death_target) * _RESERVE_SCALE   when pre_death_budget == 0
        Neutral  = 0.0                                    when the bowler has budget
                                                          or is not a death specialist

        This means:
          • Top death specialists (death_target ≈ 3) face a hard pre-death block
            once their remaining overs equal death_target.
          • A lighter death bowler (death_target ≈ 1) gets blocked only in the
            final 1–2 pre-death overs, finishing quota earlier.
          • Part-timers (death_target < _DEATH_THRESHOLD) are unrestricted.
        """
        current_over = match.current_over  # 0-indexed

        # Phase boundaries (0-indexed)
        death_start = 15 if self._fmt == 'T20' else 39

        if current_over >= death_start:
            return 0.0  # in death phase — no reservation needed

        overs_bowled     = ip.balls_bowled // 6
        overs_remaining  = quota - overs_bowled
        if overs_remaining <= 0:
            return -1000.0

        # Pick inning-specific phase distribution if available
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
            return 0.0  # not a death bowler

        # Integer overs to reserve (ceiling → conservative)
        death_reserved = min(math.ceil(death_target), overs_remaining)

        # Overs available to bowl before death
        pre_death_budget = overs_remaining - death_reserved
        pre_death_slots  = death_start - current_over  # remaining overs before death phase

        if pre_death_budget <= 0:
            # No budget left for pre-death — must save everything for death
            return -death_reserved * _RESERVE_SCALE

        if pre_death_slots <= 0 or pre_death_budget >= pre_death_slots:
            # More budget than remaining pre-death slots → use them now, no penalty
            return 0.0

        # Urgency = how close we are to death (0 at start of innings → 1 just before death).
        # Penalty grows as death approaches so the bowler is nudged to bowl pre-death overs
        # in mid-overs rather than being blocked in the powerplay when there's no rush.
        urgency = 1.0 - pre_death_slots / max(1, death_start)
        return -urgency * death_reserved * _SOFT_RESERVE_SCALE

    # ── Factor 2: Match form ──────────────────────────────────────────────────

    def _f_match_form(self, ip: InningPlayer) -> float:
        """
        Economy + wickets this match (blended with career as sample grows).
        Cold-start: career economy when fewer than 6 balls bowled.

        Eco scoring is asymmetric: reward for bowling below the neutral line is
        3x the penalty for bowling above it, so even an expensive career bowler
        scores well above a non-bowler (who gets 0).
        Returns roughly 0–15.
        """
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
            eco_score = 0.0  # no career data → non-bowler, no reward

        wicket_score  = ip.wickets_taken * 2.0
        if career_balls >= 30:
            wicket_score += career_wr * 30.0

        return eco_score + wicket_score

    # ── Factor 3: Spell management ────────────────────────────────────────────

    def _f_spell_breakdown(self, ip: InningPlayer, match: SimulationMatch,
                           continuity_weight: float,
                           workload_harshness: float) -> Tuple[float, float, float]:
        """
        Returns (continuity, fatigue, workload) individually.
        Single source of truth — _f_spell delegates here.

        Continuity:
          cw x max(0, 2 - spell/limit)  while in active spell (overs_since ≤ 2).
          Reaches zero at 2xlimit, still equals cw at the spell limit — "still high".

        Fatigue:
          -(eff_spell / limit) x fw  where fw is derived from continuity_weight so that
          |fatigue| == continuity at avg_spell (≈ _AVG_SPELL_RATIO x spell_limit).
          Accumulates 1 over/over during spell; recovers at _RECOVERY_RATE (4x slower).
          Persists after the spell ends — continuity snaps to 0 but fatigue lingers.

        Workload:
          Permanent linear ramp after avg_overs_per_innings, reaching -workload_harshness
          at p75_overs.

        Derivation of fatigue_weight (fw):
          At spell = r x sl  (r = _AVG_SPELL_RATIO):
            continuity = cw x (2 - r)
            fatigue    = -r x fw
          Setting |fatigue| = continuity:
            r x fw = cw x (2 - r)
            fw     = cw x (2 - r) / r
        """
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
        """
        H2H vs striker (full) + non-striker (0.5x — faces ~40% of balls).
        Returns roughly 0–12 when strong matchup data exists.
        """
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
