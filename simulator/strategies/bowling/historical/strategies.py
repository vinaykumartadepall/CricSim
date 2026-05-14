"""
Historical Bowling Strategies
==============================
Three concrete strategies — one per format.

Factors by format
─────────────────
                     T20        ODI        Test
  F1 phase-venue     dominant   dominant   dominant (ball-age phases)
  F2 match form      medium     medium     low-medium
  F3 spell mgmt      —          —          high (continuity/fatigue/workload)
  F4 matchup         low        least      very low
  F5 quota pacing    yes        yes        —

Eligibility:
  T20/ODI  hard quota (4/10 overs) enforced in _eligible; _hard_cap is a safety net
  Test     only constraint is no consecutive overs (current bowler excluded)
"""

from typing import Optional, Tuple

from simulator.entities.inning_player import InningPlayer
from simulator.entities.match import SimulationMatch
from simulator.strategies.bowling.historical.base import HistoricalBowlingBase


# ── T20 ───────────────────────────────────────────────────────────────────────

class T20HistoricalBowlingStrategy(HistoricalBowlingBase):

    def _quota(self) -> int:
        return 4

    # Minimum avg_overs_per_match to be a genuine bowling option.
    _MIN_AVG_OVERS = 1.0

    def _eligible(self, team, current_bowler, match: SimulationMatch):
        quota = self._quota()
        under_quota = [
            ip for ip in team.inning_players
            if ip != current_bowler and ip.balls_bowled // 6 < quota
        ]
        bowlers = [
            ip for ip in under_quota
            if self.workload_cache.get(ip.id, {}).get('avg_overs_per_match', 0.0) >= self._MIN_AVG_OVERS
        ]
        return bowlers if bowlers else under_quota

    def _score_and_breakdown(self, ip: InningPlayer, match: SimulationMatch) -> Tuple[float, dict]:
        if self._hard_cap(ip):
            return -1000.0, {}

        over       = match.current_over
        inning_num = match.current_inning
        f1 = self._f_over_affinity(ip, over, phase_weight=20.0, inning_num=inning_num)
        f2 = self._f_match_form(ip) * 0.45
        f4 = self._f_matchup(ip, match) * 0.35
        f5 = self._f_phase_pacing(ip, quota=4, match=match)
        f6 = self._f_death_reservation(ip, quota=4, match=match)

        return f1 + f2 + f4 + f5 + f6, {
            "F1_over": f1, "F2_form": f2, "F4_matchup": f4, "F5_pacing": f5, "F6_reserve": f6,
        }


# ── ODI ───────────────────────────────────────────────────────────────────────

class ODIHistoricalBowlingStrategy(HistoricalBowlingBase):

    def _quota(self) -> int:
        return 10

    _MIN_AVG_OVERS = 2.0

    def _eligible(self, team, current_bowler, match: SimulationMatch):
        quota = self._quota()
        under_quota = [
            ip for ip in team.inning_players
            if ip != current_bowler and ip.balls_bowled // 6 < quota
        ]
        bowlers = [
            ip for ip in under_quota
            if self.workload_cache.get(ip.id, {}).get('avg_overs_per_match', 0.0) >= self._MIN_AVG_OVERS
        ]
        return bowlers if bowlers else under_quota

    def _score_and_breakdown(self, ip: InningPlayer, match: SimulationMatch) -> Tuple[float, dict]:
        if self._hard_cap(ip):
            return -1000.0, {}

        over           = match.current_over
        overs_per_inns = match.overs_per_innings or 50
        inning_num     = match.current_inning

        bin_idx = over // 5
        quota   = overs_per_inns // 5
        f1 = self._f_over_affinity(ip, bin_idx, phase_weight=20.0, inning_num=inning_num)
        f2 = self._f_match_form(ip) * 0.4
        f4 = self._f_matchup(ip, match) * 0.25
        f5 = self._f_phase_pacing(ip, quota=quota, match=match)
        f6 = self._f_death_reservation(ip, quota=quota, match=match)

        return f1 + f2 + f4 + f5 + f6, {
            "F1_bin": f1, "F2_form": f2, "F4_matchup": f4, "F5_pacing": f5, "F6_reserve": f6,
        }


# ── Test ──────────────────────────────────────────────────────────────────────

class TestHistoricalBowlingStrategy(HistoricalBowlingBase):

    def _quota(self) -> Optional[int]:
        return None  # unlimited

    def _eligible(self, team, current_bowler, match: SimulationMatch):
        return [ip for ip in team.inning_players if ip != current_bowler]

    def _score_and_breakdown(self, ip: InningPlayer, match: SimulationMatch) -> Tuple[float, dict]:
        if self._hard_cap(ip):
            return -1000.0, {}

        ball_age       = match.current_over % 80
        innings_bucket = 1 if match.current_inning <= 2 else 2

        f1 = self._f_test_phase_affinity(ip, ball_age, innings_bucket, phase_weight=25.0)
        f2 = self._f_match_form(ip) * 0.35
        f3c, f3f, f3w = self._f_spell_breakdown(ip, match, continuity_weight=12.0, workload_harshness=12.0)
        f4 = self._f_matchup(ip, match) * 0.15

        return f1 + f2 + f3c + f3f + f3w + f4, {
            "F1_phase":   f1,
            "F2_form":    f2,
            "F3_cont":    f3c,
            "F3_fat":     f3f,
            "F3_wl":      f3w,
            "F4_matchup": f4,
        }


# ── Factory ───────────────────────────────────────────────────────────────────

_FORMAT_CLASSES = {
    "T20":  T20HistoricalBowlingStrategy,
    "ODI":  ODIHistoricalBowlingStrategy,
    "Test": TestHistoricalBowlingStrategy,
}


def create_historical_bowling_strategy(match_format: str) -> HistoricalBowlingBase:
    """Returns the right HistoricalBowlingStrategy subclass for the given unified format."""
    cls = _FORMAT_CLASSES.get(match_format)
    if cls is None:
        raise ValueError(
            f"No historical bowling strategy for format '{match_format}'. "
            f"Must be one of: {list(_FORMAT_CLASSES)}"
        )
    return cls()
