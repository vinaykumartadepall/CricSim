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
