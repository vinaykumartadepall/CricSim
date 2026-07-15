"""
_build_result_description (simulator/serializers/match.py) reconstructs the
display description from persisted simulation.matches columns. Covers the two
new playoff-tiebreak win_type sentinels (first_innings_lead, group_stage_rank)
plus every pre-existing branch, to lock down that the new checks - which must
run BEFORE the plain no-result/tie branches, or they'd never be reached -
don't change any existing case's output.

This function is also used by api/routes/simulations.py (imported directly,
not duplicated - see that module) so these tests cover both call sites.
"""
from simulator.serializers.match import _build_result_description


def _row(**over):
    base = {
        "result": None, "winner": None, "win_type": None, "win_by": None,
        "match_format": "T20", "is_super_over": False,
    }
    base.update(over)
    return base


class TestTiebreakSentinels:
    def test_first_innings_lead_on_a_drawn_test_match(self):
        # win_by (the lead margin) is still persisted for auditability but
        # deliberately not shown in the description text.
        row = _row(result="no result", match_format="Test", winner="Alpha",
                   win_type="first_innings_lead", win_by=50)
        assert _build_result_description(row) == "Match drawn · Alpha advanced on first-innings lead"

    def test_first_innings_lead_on_a_tied_test_match(self):
        row = _row(result="tie", match_format="Test", winner="Alpha",
                   win_type="first_innings_lead", win_by=12)
        assert _build_result_description(row) == "Match tied · Alpha advanced on first-innings lead"

    def test_group_stage_rank_on_a_drawn_test_match(self):
        row = _row(result="no result", match_format="Test", winner="Bravo",
                   win_type="group_stage_rank", win_by=None)
        assert _build_result_description(row) == "Match drawn · Bravo advanced due to better group stage finish"

    def test_group_stage_rank_on_a_tied_test_match(self):
        row = _row(result="tie", match_format="Test", winner="Bravo",
                   win_type="group_stage_rank", win_by=None)
        assert _build_result_description(row) == "Match tied · Bravo advanced due to better group stage finish"


class TestPreExistingBehaviorUnaffected:
    def test_genuine_test_draw_with_no_winner(self):
        row = _row(result="no result", match_format="Test")
        assert _build_result_description(row) == "Match drawn"

    def test_limited_overs_no_result_says_no_result(self):
        row = _row(result="no result", match_format="T20")
        assert _build_result_description(row) == "No result"

    def test_genuine_tie_with_no_winner(self):
        row = _row(result="tie")
        assert _build_result_description(row) == "Match tied"

    def test_super_over_tied_then_rank_advance_untouched(self):
        """The original mechanism this generalizes - relies on is_super_over,
        not a win_type sentinel, and must keep producing its exact string."""
        row = _row(result="tie", winner="Alpha", is_super_over=True)
        assert _build_result_description(row) == (
            "Match tied · Super Over tied · Alpha advanced due to better group stage finish"
        )

    def test_super_over_produced_a_clear_winner(self):
        row = _row(result="win", winner="Alpha", is_super_over=True)
        assert _build_result_description(row) == "Match tied · Alpha won Super Over"

    def test_decisive_win_by_runs(self):
        row = _row(result="win", winner="Alpha", win_type="runs", win_by=34)
        assert _build_result_description(row) == "Alpha won by 34 runs"

    def test_decisive_win_by_one_run_is_singular(self):
        row = _row(result="win", winner="Alpha", win_type="runs", win_by=1)
        assert _build_result_description(row) == "Alpha won by 1 run"

    def test_decisive_win_by_wickets(self):
        row = _row(result="win", winner="Alpha", win_type="wickets", win_by=4)
        assert _build_result_description(row) == "Alpha won by 4 wickets"

    def test_win_by_an_innings(self):
        row = _row(result="win", winner="Alpha", win_type="innings", win_by=45)
        assert _build_result_description(row) == "Alpha won by an innings and 45 runs"

    def test_no_winner_no_win_type_returns_none(self):
        row = _row(result="win")
        assert _build_result_description(row) is None
