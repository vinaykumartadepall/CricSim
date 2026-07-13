"""
Ball-by-ball commentary text formatting (simulator/serializers/match.py).

Regression focus: outcome kinds stored as literal "Caught and Bowled" / "c and b"
(sampled from historical dismissal data) used to fall through to the generic
branch and render as "Caught and Bowled by Bumrah" instead of
"caught and bowled Bumrah" - the same gap _dismissal_text had already fixed.
"""

from simulator.serializers.match import _dismissal_text, _format_commentary_text


def _commentary(kind, outcome_player=None, bowler="Bumrah", batter="Kohli"):
    return _format_commentary_text(
        over=5, ball=3,
        bowler=bowler, batter=batter, outcome_player=outcome_player,
        runs_batter=0, runs_extras=0,
        outcome_type="Wicket", outcome_kind=kind,
        is_free_hit=False,
    )


class TestCaughtAndBowledCommentary:
    def test_literal_caught_and_bowled_kind(self):
        text = _commentary("Caught and Bowled")
        assert "caught and bowled Bumrah" in text
        assert "by" not in text.split("out - ")[1]

    def test_literal_c_and_b_kind(self):
        text = _commentary("c and b")
        assert "caught and bowled Bumrah" in text

    def test_caught_kind_with_bowler_as_catcher(self):
        text = _commentary("caught", outcome_player="Bumrah")
        assert "caught and bowled Bumrah" in text

    def test_caught_by_fielder_unaffected(self):
        text = _commentary("caught", outcome_player="Jadeja")
        assert "caught by Jadeja, bowled Bumrah" in text

    def test_unknown_kind_still_uses_generic_branch(self):
        text = _commentary("hit wicket")
        assert "hit wicket by Bumrah" in text


class TestDismissalTextStaysConsistent:
    def test_scorecard_and_commentary_agree_on_c_and_b(self):
        # Both display paths must recognise the same literal kinds.
        for kind in ("Caught and Bowled", "c and b"):
            assert _dismissal_text(kind, "Bumrah", None) == "c&b Bumrah"
            assert "caught and bowled Bumrah" in _commentary(kind)
