"""Unit tests for InningsSimulator helpers (free-hit logic, over simulation)."""
import pytest
from dataclasses import replace
from simulator.entities.ball_outcome import BallOutcome
from simulator.engines.innings_simulator import InningsSimulator
from enums.constants import ExtraType


class TestApplyFreeHitRules:
    """Tests for the static _apply_free_hit_rules method."""

    def _call(self, outcome, is_free_hit, free_hit_supported=True):
        return InningsSimulator._apply_free_hit_rules(outcome, is_free_hit, free_hit_supported)

    # ── Free-hit state transitions ────────────────────────────────────────────

    def test_noball_sets_next_free_hit(self):
        outcome = BallOutcome(extras_type=ExtraType.NOBALL)
        _, next_free_hit = self._call(outcome, is_free_hit=False)
        assert next_free_hit is True

    def test_legal_delivery_clears_free_hit(self):
        outcome = BallOutcome(runs_batter=1)
        _, next_free_hit = self._call(outcome, is_free_hit=True)
        assert next_free_hit is False

    def test_wide_during_free_hit_carries_state(self):
        outcome = BallOutcome(extras_type=ExtraType.WIDE)
        _, next_free_hit = self._call(outcome, is_free_hit=True)
        assert next_free_hit is True

    def test_wide_when_not_free_hit_remains_false(self):
        outcome = BallOutcome(extras_type=ExtraType.WIDE)
        _, next_free_hit = self._call(outcome, is_free_hit=False)
        assert next_free_hit is False

    def test_legal_dot_clears_free_hit(self):
        outcome = BallOutcome(runs_batter=0)
        _, next_free_hit = self._call(outcome, is_free_hit=True)
        assert next_free_hit is False

    # ── Wicket cancellation on free hits ─────────────────────────────────────

    def test_wicket_cancelled_on_free_hit(self):
        outcome = BallOutcome(is_wicket=True, wicket_kind="bowled")
        result, _ = self._call(outcome, is_free_hit=True)
        assert not result.is_wicket
        assert result.wicket_kind is None

    def test_run_out_kept_on_free_hit(self):
        outcome = BallOutcome(is_wicket=True, wicket_kind="run out")
        result, _ = self._call(outcome, is_free_hit=True)
        assert result.is_wicket
        assert result.wicket_kind == "run out"

    def test_wicket_kept_when_not_free_hit(self):
        outcome = BallOutcome(is_wicket=True, wicket_kind="caught")
        result, _ = self._call(outcome, is_free_hit=False)
        assert result.is_wicket

    def test_wicket_kept_when_free_hit_not_supported(self):
        outcome = BallOutcome(is_wicket=True, wicket_kind="bowled")
        result, _ = self._call(outcome, is_free_hit=True, free_hit_supported=False)
        assert result.is_wicket

    # ── When format does not support free hits ────────────────────────────────

    def test_noball_in_test_does_not_set_free_hit(self):
        outcome = BallOutcome(extras_type=ExtraType.NOBALL)
        _, next_free_hit = self._call(outcome, is_free_hit=False, free_hit_supported=False)
        assert next_free_hit is False

    def test_free_hit_state_not_carried_in_test_on_wide(self):
        outcome = BallOutcome(extras_type=ExtraType.WIDE)
        _, next_free_hit = self._call(outcome, is_free_hit=True, free_hit_supported=False)
        assert next_free_hit is False
