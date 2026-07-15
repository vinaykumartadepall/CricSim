"""
describe_tiebreak_winner (simulator/presentation/tiebreak_text.py) is the one
function both TournamentEngine's live description and
_build_result_description's persisted-row reconstruction call for the
"X advanced on ..." suffix text - so the wording literally cannot drift
between the two, the same guarantee dismissals.py already gives dismissal
text. These tests pin the exact strings and prove both call sites route
through the shared function rather than independent copies.
"""
from unittest.mock import MagicMock

import simulator.serializers.match as match_mod
import simulator.tournament.engine as engine_mod
from simulator.presentation.tiebreak_text import describe_tiebreak_winner


class TestDescribeTiebreakWinner:
    def test_first_innings_lead_wording(self):
        assert describe_tiebreak_winner("first_innings_lead", "India") == "India advanced on first-innings lead"

    def test_group_stage_rank_wording(self):
        assert describe_tiebreak_winner("group_stage_rank", "India") == "India advanced due to better group stage finish"

    def test_super_over_tied_rank_uses_the_same_group_stage_wording(self):
        assert describe_tiebreak_winner("super_over_tied_rank", "India") == describe_tiebreak_winner("group_stage_rank", "India")

    def test_margin_is_not_part_of_the_text(self):
        """The lead margin is tracked separately (MatchResult.tiebreak_margin /
        simulation.matches.win_by) for auditability, but deliberately excluded
        from the display string."""
        text = describe_tiebreak_winner("first_innings_lead", "India")
        assert "run" not in text.split("advanced")[0]  # no "N-run" before "advanced"


class TestBothCallSitesUseTheSharedFunction:
    """Patch the shared function and confirm each module's own text changes
    with it - proof they call through it rather than formatting their own copy."""

    def test_engine_calls_shared_function(self, monkeypatch):
        sentinel = "SENTINEL TEXT FROM SHARED FUNCTION"
        monkeypatch.setattr(engine_mod, "describe_tiebreak_winner", lambda reason, winner: sentinel)

        match = MagicMock()
        match.result.description = "Match Drawn"
        # _resolve_drawn_playoff needs a real engine instance; reuse the
        # existing test module's fixture builders to avoid re-deriving them.
        from tests.test_playoff_drawn_test_match import _inning, _make_config, _make_engine
        from simulator.entities.match import MatchResult
        from simulator.entities.team import MatchTeam
        from simulator.entities.match import SimulationMatch
        from simulator.tournament.config import Fixture

        engine = _make_engine(_make_config(fmt="Test"))
        real_match = SimulationMatch(id=1, home_team=MatchTeam(id=1, name="Alpha"), away_team=MatchTeam(id=2, name="Bravo"))
        real_match.innings = [_inning(1, "Alpha", 300), _inning(2, "Bravo", 250)]
        real_match.result = MatchResult(winner=None, is_no_result=True, description="Match Drawn", team_innings_summary={})
        fixture = Fixture(home="Alpha", away="Bravo", venue=None, match_number=1, match_label="Semi-final 1")

        engine._resolve_drawn_playoff(real_match, fixture)

        assert real_match.result.description == f"Match Drawn · {sentinel}"

    def test_serializer_calls_shared_function(self, monkeypatch):
        sentinel = "SENTINEL TEXT FROM SHARED FUNCTION"
        monkeypatch.setattr(match_mod, "describe_tiebreak_winner", lambda reason, winner: sentinel)

        row = {
            "result": "no result", "winner": "Alpha", "win_type": "first_innings_lead",
            "win_by": 50, "match_format": "Test", "is_super_over": False,
        }

        assert match_mod._build_result_description(row) == f"Match drawn · {sentinel}"
