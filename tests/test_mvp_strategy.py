"""
Tests for the MvpStrategy contract itself (simulator/awards/mvp_strategy.py).

This is the extension point every future scoring algorithm (statistical
awards today, something like win-probability-added later) must satisfy —
one method, compute(match) -> List[PlayerAward]. Concrete rubric coverage
lives in test_statistical_awards.py; this file only pins down the contract
and proves it's genuinely swappable.
"""
import pytest

from simulator.awards.mvp_strategy import MvpStrategy, PlayerAward


class TestPlayerAward:
    def test_defaults(self):
        a = PlayerAward(player_id=1, player_name="Alice")
        assert a.team == ""
        assert a.total == 0.0
        assert a.breakdown == {}

    def test_breakdown_dict_is_independent_per_instance(self):
        # Mutable-default pitfall check for the field(default_factory=dict).
        a = PlayerAward(1, "Alice")
        b = PlayerAward(2, "Bob")
        a.breakdown["x"] = 1.0
        assert b.breakdown == {}


class TestMvpStrategyIsSwappable:
    def test_a_new_strategy_only_needs_to_implement_compute(self):
        # Proves the extension point: a whole new scoring algorithm — with no
        # ball-by-ball hooks, no fixed batting/bowling/fielding categories,
        # nothing shared with StatisticalAwardsStrategy — is just this.
        class FixedScoreStrategy(MvpStrategy):
            def compute(self, match):
                return [PlayerAward(player_id=1, player_name="Solo", team="X", total=99.0)]

        results = FixedScoreStrategy().compute(match=object())
        assert results == [PlayerAward(player_id=1, player_name="Solo", team="X", total=99.0)]

    def test_cannot_instantiate_without_implementing_compute(self):
        with pytest.raises(TypeError):
            MvpStrategy()  # abstract — compute() has no default implementation
