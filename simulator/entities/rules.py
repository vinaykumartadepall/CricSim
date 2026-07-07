from typing import Optional
from enums.constants import ExtraType, DismissalType


class MatchRules:
    """
    Centralized business logic describing the rules of a cricket match.
    Prevents scattered validation logic globally across the simulator.
    """

    FORMAT_MAPPING = {
        "ODI": "ODI",
        "ODM": "ODI",
        "ONE DAY": "ODI",
        "Test": "Test",
        "MDM": "Test",
        "T20": "T20",
        "IT20": "T20"
    }

    @staticmethod
    def get_unified_format(match_type: str) -> str:
        """
        Consolidates various nomenclature subsets into standard format bins.
        """
        if not match_type:
            return "UNKNOWN"

        m_type = match_type.strip()
        return MatchRules.FORMAT_MAPPING.get(m_type, m_type)

    @staticmethod
    def is_legal_delivery(extras_type: str) -> bool:
        """
        Determines if a ball counts legally towards an over limit.
        """
        return extras_type not in [ExtraType.WIDE, ExtraType.NOBALL]

    @staticmethod
    def is_free_hit_awarded(extras_type: str) -> bool:
        """
        Returns True if the outcome dictates the subsequent ball is a free hit.
        """
        return extras_type == ExtraType.NOBALL

    @staticmethod
    def supports_free_hit(match_format: str) -> bool:
        """Free-hit after a no-ball applies only in limited-overs formats."""
        return match_format in ('T20', 'ODI')

    # First 0-indexed over considered "death" per format
    _DEATH_OVER_START: dict = {'T20': 16, 'ODI': 40, 'Test': 999}

    @staticmethod
    def is_death_over(over_0indexed: int, match_format: str) -> bool:
        """Returns True if the given over is in the death phase for the format."""
        return over_0indexed >= MatchRules._DEATH_OVER_START.get(match_format, 999)

    @staticmethod
    def get_phase(current_over_0indexed: int, match_format: str,
                  overs_per_innings: Optional[int] = None) -> str:
        """
        Returns the broad phase name for bowling strategy: 'powerplay', 'middle', 'death', or 'none'.
        current_over_0indexed: 0-based over number (the upcoming over).
        """
        fmt = match_format
        if fmt == 'T20':
            if current_over_0indexed < 6:
                return 'powerplay'
            if current_over_0indexed >= 16:
                return 'death'
            return 'middle'
        if fmt == 'ODI':
            if current_over_0indexed < 10:
                return 'powerplay'
            cap = overs_per_innings or 50
            if current_over_0indexed >= cap - 10:
                return 'death'
            return 'middle'
        return 'none'  # Test — no distinct phases

    @staticmethod
    def get_fine_grained_phase(over_1indexed: int, match_format: str) -> str:
        """
        Returns a fine-grained phase bucket for ball-outcome probability lookup.
        T20: pp1/pp2/mid1/mid2/death1/death2
        ODI: pp1/pp2/mid1/mid2/mid3/death1/death2
        Test: new/early/middle/late
        """
        if match_format == 'T20':
            if over_1indexed <= 3:  return 'pp1'
            if over_1indexed <= 6:  return 'pp2'
            if over_1indexed <= 11: return 'mid1'
            if over_1indexed <= 15: return 'mid2'
            if over_1indexed <= 17: return 'death1'
            return 'death2'
        if match_format == 'ODI':
            if over_1indexed <= 5:  return 'pp1'
            if over_1indexed <= 10: return 'pp2'
            if over_1indexed <= 20: return 'mid1'
            if over_1indexed <= 30: return 'mid2'
            if over_1indexed <= 40: return 'mid3'
            if over_1indexed <= 45: return 'death1'
            return 'death2'
        # Test
        if over_1indexed <= 10: return 'new'
        if over_1indexed <= 30: return 'early'
        if over_1indexed <= 80: return 'middle'
        return 'late'

    @staticmethod
    def nrr_adjusted_balls(legal_balls: int, wickets: int, max_balls: Optional[int]) -> int:
        """
        ICC all-out rule: a side dismissed inside its full overs quota is credited
        the full quota for NRR purposes, not just the balls it actually faced.
        No-op (returns legal_balls unchanged) when there's no fixed quota to credit
        against — e.g. Test cricket, where max_balls is None and NRR/all-out-rule
        don't apply in the first place.

        Single source of truth for this adjustment — every NRR computation (live
        tournament engine, results-page display) must go through this, not
        reimplement the CASE WHEN wickets >= 10 ... check independently.
        """
        if max_balls and wickets >= 10:
            return max_balls
        return legal_balls

    @staticmethod
    def net_run_rate(runs_for: int, balls_for: int, runs_against: int, balls_against: int) -> float:
        """
        NRR = (runs scored / legal balls faced * 6) - (runs conceded / legal balls bowled * 6).
        balls_for/balls_against should already have nrr_adjusted_balls() applied by the caller.
        """
        off = (runs_for / balls_for * 6) if balls_for else 0.0
        de = (runs_against / balls_against * 6) if balls_against else 0.0
        return round(off - de, 3)

    @staticmethod
    def is_bowler_credited_wicket(wicket_kind: str) -> bool:
        """
        Returns whether the bowler receives credit for a given wicket type.
        Run outs, retired hurts, obstructing field etc. are not credited to the bowler.
        """
        if not wicket_kind:
            return False

        uncredited = [
            DismissalType.RUN_OUT,
            DismissalType.RETIRED_HURT,
            DismissalType.OBSTRUCTING_FIELD,
            DismissalType.HANDLED_BALL,
            DismissalType.HIT_BALL_TWICE,
            DismissalType.TIMED_OUT,
        ]
        return wicket_kind not in uncredited
