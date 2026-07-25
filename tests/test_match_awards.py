"""
Tests for MatchAwards / TournamentAwards (simulator/awards/match_awards.py) -
strategy-agnostic orchestration. These deliberately use a tiny fake
MvpStrategy rather than StatisticalAwardsStrategy for most cases, to prove
orchestration (picking POTM, ranking, accumulating across matches) doesn't
depend on any particular scoring rubric's internals. One integration test
at the bottom uses the real default strategy end-to-end.

No DB or real match engine required.
"""
import pytest

from simulator.awards.match_awards import MatchAwards, TournamentAwards
from simulator.awards.mvp_strategy import MvpStrategy, PlayerAward


class _FixedStrategy(MvpStrategy):
    """Returns a pre-baked list of PlayerAwards regardless of the match passed in."""
    def __init__(self, awards):
        self._awards = awards

    def compute(self, match):
        return self._awards


def _played(awards_list) -> MatchAwards:
    """A MatchAwards that's already recorded a fixed set of PlayerAwards."""
    ma = MatchAwards(strategy=_FixedStrategy(awards_list))
    ma.record_from_match(match=object())
    return ma


# ── PlayerAward.match_score ─────────────────────────────────────────────────────

class TestPlayerAwardMatchScore:
    def test_defaults_to_total_when_not_set(self):
        a = PlayerAward(1, "Alice", total=50.0)
        assert a.match_score == pytest.approx(50.0)

    def test_can_be_set_independently_of_total(self):
        a = PlayerAward(1, "Alice", total=50.0, match_score=62.5)
        assert a.total == pytest.approx(50.0)
        assert a.match_score == pytest.approx(62.5)


# ── MatchAwards ─────────────────────────────────────────────────────────────────

class TestMatchAwardsPotm:
    def test_potm_returns_highest_total(self):
        strategy = _FixedStrategy([
            PlayerAward(1, "Alice", team="A", total=50.0),
            PlayerAward(2, "Bob", team="B", total=80.0),
        ])
        awards = MatchAwards(strategy=strategy)
        awards.record_from_match(match=object())
        assert awards.potm().player_id == 2

    def test_potm_none_when_no_players(self):
        awards = MatchAwards(strategy=_FixedStrategy([]))
        awards.record_from_match(match=object())
        assert awards.potm() is None

    def test_all_sorted_descending(self):
        strategy = _FixedStrategy([
            PlayerAward(1, "Alice", total=10.0),
            PlayerAward(2, "Bob", total=90.0),
            PlayerAward(3, "Carl", total=40.0),
        ])
        awards = MatchAwards(strategy=strategy)
        awards.record_from_match(match=object())
        ranked = awards.all_sorted()
        assert [a.player_id for a in ranked] == [2, 3, 1]

    def test_potm_selects_by_match_score_not_total(self):
        # Bob has the higher raw total, but Alice's match_score (a
        # match-local bonus a strategy applied, e.g. a winning-team
        # multiplier) overtakes it - POTM must follow match_score.
        strategy = _FixedStrategy([
            PlayerAward(1, "Alice", team="A", total=50.0, match_score=90.0),
            PlayerAward(2, "Bob", team="B", total=80.0),  # match_score defaults to total
        ])
        awards = MatchAwards(strategy=strategy)
        awards.record_from_match(match=object())
        assert awards.potm().player_id == 1
        assert [a.player_id for a in awards.all_sorted()] == [1, 2]

    def test_record_from_match_replaces_previous_results(self):
        awards = MatchAwards(strategy=_FixedStrategy([PlayerAward(1, "Alice", total=10.0)]))
        awards.record_from_match(match=object())
        awards._strategy = _FixedStrategy([PlayerAward(2, "Bob", total=20.0)])
        awards.record_from_match(match=object())
        assert [a.player_id for a in awards.all_sorted()] == [2]


# ── TournamentAwards ───────────────────────────────────────────────────────────

class TestTournamentAwardsAccumulation:
    def test_accumulates_total_across_matches(self):
        ta = TournamentAwards()
        ta.add_match(_played([PlayerAward(1, "Alice", team="A", total=30.0)]))
        ta.add_match(_played([PlayerAward(1, "Alice", team="A", total=25.0)]))
        ta.add_match(_played([PlayerAward(2, "Bob", team="B", total=60.0)]))

        assert ta._totals[1].total == pytest.approx(55.0)
        assert ta._totals[2].total == pytest.approx(60.0)

    def test_merges_breakdown_keys_generically_for_any_strategy_shape(self):
        # No hardcoded 'batting_pts'/'bowling_pts' assumption - whatever keys
        # a strategy's breakdown uses get summed the same way.
        ta = TournamentAwards()
        a1 = PlayerAward(1, "Alice", team="A", total=10.0, breakdown={"win_probability_added": 0.10})
        a2 = PlayerAward(1, "Alice", team="A", total=15.0, breakdown={"win_probability_added": 0.05, "clutch_factor": 2.0})
        ta.add_match(_played([a1]))
        ta.add_match(_played([a2]))

        assert ta._totals[1].total == pytest.approx(25.0)
        assert ta._totals[1].breakdown == {"win_probability_added": pytest.approx(0.15), "clutch_factor": pytest.approx(2.0)}

    def test_team_filled_in_from_first_match_that_has_it(self):
        ta = TournamentAwards()
        ta.add_match(_played([PlayerAward(1, "Alice", team="", total=10.0)]))
        ta.add_match(_played([PlayerAward(1, "Alice", team="A", total=5.0)]))
        assert ta._totals[1].team == "A"

    def test_accumulation_ignores_match_score_a_potm_only_bonus_never_leaks_into_the_tournament_total(self):
        ta = TournamentAwards()
        ta.add_match(_played([
            PlayerAward(1, "Alice", team="A", total=30.0, match_score=37.5),  # e.g. winner-boosted for POTM
            PlayerAward(2, "Bob", team="B", total=60.0),  # lost this match, no boost
        ]))
        # Tournament total must reflect only the true, unmultiplied totals -
        # Bob still leads the tournament sum despite losing this one match.
        assert ta._totals[1].total == pytest.approx(30.0)
        assert ta._totals[2].total == pytest.approx(60.0)
        assert ta.pott().player_id == 2

    def test_pott_returns_highest_cumulative(self):
        ta = TournamentAwards()
        ta.add_match(_played([]))  # empty match
        ta.add_match(_played([
            PlayerAward(1, "Alice", total=100.0),
            PlayerAward(2, "Bob", total=80.0),
        ]))
        assert ta.pott().player_id == 1

    def test_pott_none_when_no_matches(self):
        assert TournamentAwards().pott() is None

    def test_leaderboard_top_n(self):
        ta = TournamentAwards()
        awards_list = [PlayerAward(i, f"P{i}", total=float(i)) for i in range(15)]
        ta.add_match(_played(awards_list))
        assert len(ta.leaderboard(top_n=10)) == 10
        assert ta.leaderboard(top_n=10)[0].player_id == 14  # highest total first


# ── End-to-end with the real default strategy ─────────────────────────────────

def test_match_awards_uses_statistical_awards_by_default():
    from unittest.mock import MagicMock

    bat = MagicMock(); bat.id = 1; bat.name = "Batter"
    bow = MagicMock(); bow.id = 2; bow.name = "Bowler"
    delivery = MagicMock()
    delivery.batter = bat
    delivery.bowler = bow
    delivery.over_number = 0
    delivery.runs_batter = 4
    delivery.runs_extras = 0
    delivery.extras_type = None
    delivery.is_wicket = False
    delivery.wicket_kind = None
    delivery.outcome_player = None

    batting_team = MagicMock(); batting_team.name = "TeamA"; batting_team.inning_players = []
    bowling_team = MagicMock(); bowling_team.name = "TeamB"; bowling_team.inning_players = []
    inning = MagicMock()
    inning.inning_number = 1
    inning.deliveries = [delivery]
    inning.batting_team = batting_team
    inning.bowling_team = bowling_team

    match = MagicMock()
    match.innings = [inning]
    match.match_format = "T20"

    awards = MatchAwards()  # default strategy - no explicit injection
    awards.record_from_match(match)

    assert awards.potm().player_id == 1
    assert awards.potm().breakdown['batting_pts'] > 0
