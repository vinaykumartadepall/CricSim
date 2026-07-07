"""Unit tests for simulator.entities.rules.MatchRules."""
import pytest
from simulator.entities.rules import MatchRules
from enums.constants import ExtraType


class TestGetUnifiedFormat:
    def test_known_aliases(self):
        assert MatchRules.get_unified_format("IT20") == "T20"
        assert MatchRules.get_unified_format("ODM") == "ODI"
        assert MatchRules.get_unified_format("MDM") == "Test"
        assert MatchRules.get_unified_format("ONE DAY") == "ODI"

    def test_canonical_names_pass_through(self):
        assert MatchRules.get_unified_format("T20") == "T20"
        assert MatchRules.get_unified_format("ODI") == "ODI"
        assert MatchRules.get_unified_format("Test") == "Test"

    def test_unknown_returns_itself(self):
        assert MatchRules.get_unified_format("CUSTOM") == "CUSTOM"

    def test_empty_string(self):
        assert MatchRules.get_unified_format("") == "UNKNOWN"

    def test_none_returns_unknown(self):
        assert MatchRules.get_unified_format(None) == "UNKNOWN"


class TestIsLegalDelivery:
    def test_wide_is_illegal(self):
        assert not MatchRules.is_legal_delivery(ExtraType.WIDE)

    def test_noball_is_illegal(self):
        assert not MatchRules.is_legal_delivery(ExtraType.NOBALL)

    def test_none_is_legal(self):
        assert MatchRules.is_legal_delivery(None)

    def test_legbyes_is_legal(self):
        assert MatchRules.is_legal_delivery(ExtraType.LEGBYES)

    def test_byes_is_legal(self):
        assert MatchRules.is_legal_delivery(ExtraType.BYES)


class TestFreeHitRules:
    def test_noball_awards_free_hit(self):
        assert MatchRules.is_free_hit_awarded(ExtraType.NOBALL)

    def test_wide_does_not_award_free_hit(self):
        assert not MatchRules.is_free_hit_awarded(ExtraType.WIDE)

    def test_none_does_not_award_free_hit(self):
        assert not MatchRules.is_free_hit_awarded(None)

    def test_t20_supports_free_hit(self):
        assert MatchRules.supports_free_hit("T20")

    def test_odi_supports_free_hit(self):
        assert MatchRules.supports_free_hit("ODI")

    def test_test_does_not_support_free_hit(self):
        assert not MatchRules.supports_free_hit("Test")


class TestIsDeathOver:
    @pytest.mark.parametrize("over,expected", [
        (15, False),
        (16, True),
        (19, True),
    ])
    def test_t20_death(self, over, expected):
        assert MatchRules.is_death_over(over, "T20") == expected

    @pytest.mark.parametrize("over,expected", [
        (39, False),
        (40, True),
        (49, True),
    ])
    def test_odi_death(self, over, expected):
        assert MatchRules.is_death_over(over, "ODI") == expected

    def test_test_never_death(self):
        for over in (0, 50, 100, 200):
            assert not MatchRules.is_death_over(over, "Test")


class TestGetPhase:
    def test_t20_powerplay(self):
        for over in range(6):
            assert MatchRules.get_phase(over, "T20") == "powerplay"

    def test_t20_middle(self):
        for over in range(6, 16):
            assert MatchRules.get_phase(over, "T20") == "middle"

    def test_t20_death(self):
        for over in range(16, 20):
            assert MatchRules.get_phase(over, "T20") == "death"

    def test_odi_powerplay(self):
        for over in range(10):
            assert MatchRules.get_phase(over, "ODI") == "powerplay"

    def test_odi_death_default_50(self):
        for over in range(40, 50):
            assert MatchRules.get_phase(over, "ODI") == "death"

    def test_test_returns_none(self):
        assert MatchRules.get_phase(0, "Test") == "none"
        assert MatchRules.get_phase(50, "Test") == "none"


class TestGetFineGrainedPhase:
    @pytest.mark.parametrize("over,expected", [
        (1, "pp1"), (3, "pp1"),
        (4, "pp2"), (6, "pp2"),
        (7, "mid1"), (11, "mid1"),
        (12, "mid2"), (15, "mid2"),
        (16, "death1"), (17, "death1"),
        (18, "death2"), (20, "death2"),
    ])
    def test_t20_phases(self, over, expected):
        assert MatchRules.get_fine_grained_phase(over, "T20") == expected

    @pytest.mark.parametrize("over,expected", [
        (1, "pp1"), (5, "pp1"),
        (6, "pp2"), (10, "pp2"),
        (11, "mid1"), (20, "mid1"),
        (21, "mid2"), (30, "mid2"),
        (31, "mid3"), (40, "mid3"),
        (41, "death1"), (45, "death1"),
        (46, "death2"), (50, "death2"),
    ])
    def test_odi_phases(self, over, expected):
        assert MatchRules.get_fine_grained_phase(over, "ODI") == expected

    @pytest.mark.parametrize("over,expected", [
        (1, "new"), (10, "new"),
        (11, "early"), (30, "early"),
        (31, "middle"), (80, "middle"),
        (81, "late"), (120, "late"),
    ])
    def test_test_phases(self, over, expected):
        assert MatchRules.get_fine_grained_phase(over, "Test") == expected


class TestIsBowlerCreditedWicket:
    @pytest.mark.parametrize("kind", ["bowled", "caught", "lbw", "stumped", "caught and bowled", "c and b"])
    def test_credited_kinds(self, kind):
        assert MatchRules.is_bowler_credited_wicket(kind)

    @pytest.mark.parametrize("kind", ["run out", "retired hurt", "obstructing the field",
                                       "handled the ball", "hit the ball twice", "timed out"])
    def test_uncredited_kinds(self, kind):
        assert not MatchRules.is_bowler_credited_wicket(kind)

    def test_none_is_not_credited(self):
        assert not MatchRules.is_bowler_credited_wicket(None)


class TestNrrAdjustedBalls:
    def test_all_out_inside_quota_credited_full_quota(self):
        # Bowled out in 16.3 overs (99 balls) of a 20-over (120-ball) innings.
        assert MatchRules.nrr_adjusted_balls(legal_balls=99, wickets=10, max_balls=120) == 120

    def test_not_all_out_uses_actual_balls_faced(self):
        # Chased down in 12.2 overs (74 balls), 2 wickets down — no adjustment.
        assert MatchRules.nrr_adjusted_balls(legal_balls=74, wickets=2, max_balls=120) == 74

    def test_all_out_using_full_quota_is_a_noop(self):
        assert MatchRules.nrr_adjusted_balls(legal_balls=120, wickets=10, max_balls=120) == 120

    def test_no_max_balls_is_a_noop(self):
        # Test cricket: no fixed overs quota to credit against.
        assert MatchRules.nrr_adjusted_balls(legal_balls=250, wickets=10, max_balls=None) == 250

    def test_zero_max_balls_is_a_noop(self):
        assert MatchRules.nrr_adjusted_balls(legal_balls=50, wickets=10, max_balls=0) == 50


class TestNetRunRate:
    def test_matches_hand_verified_rajasthan_royals_example(self):
        # Cross-checked by hand against a real production sim's 14-match group
        # stage (see conversation history) — the ICC all-out-rule-correct
        # answer is +0.390, which is what the app displayed and what this
        # formula must reproduce given the same adjusted totals.
        nrr = MatchRules.net_run_rate(
            runs_for=2471, balls_for=1622,       # 270.3333 overs
            runs_against=2386, balls_against=1636,  # 272.6667 overs
        )
        assert nrr == 0.390

    def test_zero_balls_faced_does_not_divide_by_zero(self):
        assert MatchRules.net_run_rate(0, 0, 50, 120) == round(0.0 - 50 / 120 * 6, 3)

    def test_zero_balls_bowled_does_not_divide_by_zero(self):
        assert MatchRules.net_run_rate(50, 120, 0, 0) == round(50 / 120 * 6, 3)

    def test_equal_rates_give_zero_nrr(self):
        assert MatchRules.net_run_rate(120, 120, 120, 120) == 0.0
