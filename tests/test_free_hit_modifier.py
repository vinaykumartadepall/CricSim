"""Unit tests for the apply_free_hit_modifier utility."""
import pytest
from simulator.strategies.ball_outcome_prediction.common.utils import apply_free_hit_modifier


def _normalise(weights, keys):
    total = sum(weights)
    return {k: w / total for k, w in zip(keys, weights)} if total else {}


_SAMPLE_KEYS = [
    (0, 0, 'Dot',    None),
    (1, 0, 'Runs',   None),
    (2, 0, 'Runs',   None),
    (4, 0, 'Runs',   None),
    (6, 0, 'Runs',   None),
    (0, 0, 'Wicket', 'bowled'),
    (0, 0, 'Wicket', 'run out'),
    (0, 1, 'Extras', 'Wide'),
]
_UNIFORM = [1.0] * len(_SAMPLE_KEYS)


class TestApplyFreeHitModifier:
    def setup_method(self):
        self.adjusted = apply_free_hit_modifier(_UNIFORM, _SAMPLE_KEYS)
        self.norm = _normalise(self.adjusted, _SAMPLE_KEYS)

    def test_six_weight_greater_than_four(self):
        six_w = self.adjusted[_SAMPLE_KEYS.index((6, 0, 'Runs', None))]
        four_w = self.adjusted[_SAMPLE_KEYS.index((4, 0, 'Runs', None))]
        assert six_w > four_w

    def test_four_weight_greater_than_singles(self):
        four_w = self.adjusted[_SAMPLE_KEYS.index((4, 0, 'Runs', None))]
        one_w = self.adjusted[_SAMPLE_KEYS.index((1, 0, 'Runs', None))]
        assert four_w > one_w

    def test_dots_less_than_singles(self):
        dot_w = self.adjusted[_SAMPLE_KEYS.index((0, 0, 'Dot', None))]
        one_w = self.adjusted[_SAMPLE_KEYS.index((1, 0, 'Runs', None))]
        assert dot_w < one_w

    def test_non_runout_wicket_heavily_suppressed(self):
        bowled_w = self.adjusted[_SAMPLE_KEYS.index((0, 0, 'Wicket', 'bowled'))]
        runout_w = self.adjusted[_SAMPLE_KEYS.index((0, 0, 'Wicket', 'run out'))]
        assert bowled_w < runout_w

    def test_run_out_unmodified(self):
        idx = _SAMPLE_KEYS.index((0, 0, 'Wicket', 'run out'))
        assert self.adjusted[idx] == pytest.approx(_UNIFORM[idx])

    def test_extras_unmodified(self):
        idx = _SAMPLE_KEYS.index((0, 1, 'Extras', 'Wide'))
        assert self.adjusted[idx] == pytest.approx(_UNIFORM[idx])

    def test_boundary_rate_increases_significantly(self):
        # Boundary (4s+6s) share should increase by at least 50% after the modifier.
        original_boundary = (
            _UNIFORM[_SAMPLE_KEYS.index((4, 0, 'Runs', None))]
            + _UNIFORM[_SAMPLE_KEYS.index((6, 0, 'Runs', None))]
        ) / len(_SAMPLE_KEYS)
        adjusted_boundary = (
            self.norm.get((4, 0, 'Runs', None), 0)
            + self.norm.get((6, 0, 'Runs', None), 0)
        )
        assert adjusted_boundary > original_boundary * 1.5

    def test_dot_rate_decreases(self):
        original_dot = 1.0 / len(_SAMPLE_KEYS)
        adjusted_dot = self.norm.get((0, 0, 'Dot', None), 0)
        assert adjusted_dot < original_dot

    def test_output_length_equals_input(self):
        assert len(self.adjusted) == len(_SAMPLE_KEYS)

    def test_all_weights_non_negative(self):
        assert all(w >= 0 for w in self.adjusted)

    def test_zero_input_stays_zero(self):
        zero_weights = [0.0] * len(_SAMPLE_KEYS)
        result = apply_free_hit_modifier(zero_weights, _SAMPLE_KEYS)
        assert all(w == 0.0 for w in result)
