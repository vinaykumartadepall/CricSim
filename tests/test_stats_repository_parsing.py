"""Unit tests for StatsRepository parsing helpers (no DB connection required)."""
import pytest
from collections import defaultdict
from db.stats_repository import StatsRepository


class TestParseRowsToProbs:
    """Tests for StatsRepository._parse_rows_to_probs (no DB needed)."""

    def setup_method(self):
        # Bypass DB connection by patching HAS_DB in the module namespace
        self.repo = StatsRepository.__new__(StatsRepository)
        self.repo.conn = None

    def test_empty_rows_returns_none(self):
        assert self.repo._parse_rows_to_probs([]) is None

    def test_single_row_prob_is_one(self):
        rows = [(0, 0, 'Dot', None, 100)]
        result = self.repo._parse_rows_to_probs(rows)
        assert result is not None
        assert result[(0, 0, 'Dot', None)] == pytest.approx(1.0)

    def test_probs_sum_to_one(self):
        rows = [
            (0, 0, 'Dot',    None,   320),
            (1, 0, 'Runs',   None,   250),
            (4, 0, 'Runs',   None,   100),
            (6, 0, 'Runs',   None,    50),
            (0, 0, 'Wicket', 'bowled', 50),
        ]
        result = self.repo._parse_rows_to_probs(rows)
        assert sum(result.values()) == pytest.approx(1.0)

    def test_duplicate_keys_are_merged(self):
        rows = [
            (0, 0, 'Dot', None, 100),
            (0, 0, 'Dot', None, 100),
        ]
        result = self.repo._parse_rows_to_probs(rows)
        assert result[(0, 0, 'Dot', None)] == pytest.approx(1.0)

    def test_proportions_correct(self):
        rows = [
            (0, 0, 'Dot',  None, 1),
            (4, 0, 'Runs', None, 3),
        ]
        result = self.repo._parse_rows_to_probs(rows)
        assert result[(0, 0, 'Dot',  None)] == pytest.approx(0.25)
        assert result[(4, 0, 'Runs', None)] == pytest.approx(0.75)


class TestParseRowsToPropsWithCount:
    def setup_method(self):
        self.repo = StatsRepository.__new__(StatsRepository)
        self.repo.conn = None

    def test_empty_returns_none_and_zero(self):
        probs, count = self.repo._parse_rows_to_probs_with_count([])
        assert probs is None
        assert count == 0

    def test_count_is_total_deliveries(self):
        rows = [
            (0, 0, 'Dot',  None, 50),
            (4, 0, 'Runs', None, 30),
        ]
        probs, count = self.repo._parse_rows_to_probs_with_count(rows)
        assert count == 80

    def test_probs_sum_to_one(self):
        rows = [
            (0, 0, 'Dot',  None, 50),
            (4, 0, 'Runs', None, 30),
            (6, 0, 'Runs', None, 20),
        ]
        probs, count = self.repo._parse_rows_to_probs_with_count(rows)
        assert sum(probs.values()) == pytest.approx(1.0)

    def test_count_and_probs_consistent(self):
        rows = [(1, 0, 'Runs', None, 100)]
        probs, count = self.repo._parse_rows_to_probs_with_count(rows)
        assert count == 100
        assert probs[(1, 0, 'Runs', None)] == pytest.approx(1.0)
