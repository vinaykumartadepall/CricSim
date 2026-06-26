"""
Tests for PointsTable: result recording, NRR calculation, and standings sort order.
"""

import pytest
from simulator.tournament.points_table import PointsTable


@pytest.fixture
def table():
    return PointsTable(["Alpha", "Beta", "Gamma", "Delta"])


# ── Points accumulation ────────────────────────────────────────────────────────

def test_home_win_awards_points(table):
    table.record_result("Alpha", "Beta", "home_win", 180, 120, 160, 120)
    assert table["Alpha"].points == 2
    assert table["Beta"].points  == 0


def test_away_win_awards_points(table):
    table.record_result("Alpha", "Beta", "away_win", 160, 120, 180, 120)
    assert table["Beta"].points  == 2
    assert table["Alpha"].points == 0


def test_tie_awards_one_point_each(table):
    table.record_result("Alpha", "Beta", "tie", 150, 120, 150, 120)
    assert table["Alpha"].points == 1
    assert table["Beta"].points  == 1


def test_no_result_awards_one_point_each(table):
    table.record_result("Alpha", "Beta", "no_result", 0, 0, 0, 0)
    assert table["Alpha"].points == 1
    assert table["Beta"].points  == 1


def test_played_increments_for_both_teams(table):
    table.record_result("Alpha", "Beta", "home_win", 180, 120, 160, 120)
    assert table["Alpha"].played == 1
    assert table["Beta"].played  == 1


def test_won_lost_counters(table):
    table.record_result("Alpha", "Beta", "home_win", 180, 120, 160, 120)
    assert table["Alpha"].won  == 1
    assert table["Alpha"].lost == 0
    assert table["Beta"].won   == 0
    assert table["Beta"].lost  == 1


# ── NRR calculation ────────────────────────────────────────────────────────────

def test_nrr_positive_for_winning_team():
    table = PointsTable(["Alpha", "Beta"])
    # Alpha scores 180 in 120 balls (9.0 rpo), Beta scores 160 in 120 balls (8.0 rpo).
    table.record_result("Alpha", "Beta", "home_win", 180, 120, 160, 120)
    assert table["Alpha"].nrr > 0
    assert table["Beta"].nrr  < 0


def test_nrr_symmetry():
    table = PointsTable(["Alpha", "Beta"])
    table.record_result("Alpha", "Beta", "home_win", 180, 120, 160, 120)
    assert abs(table["Alpha"].nrr + table["Beta"].nrr) < 1e-9


def test_nrr_zero_with_no_balls_faced():
    table = PointsTable(["Alpha", "Beta"])
    table.record_result("Alpha", "Beta", "no_result", 0, 0, 0, 0)
    assert table["Alpha"].nrr == 0.0
    assert table["Beta"].nrr  == 0.0


def test_nrr_formula():
    table = PointsTable(["Alpha", "Beta"])
    # Alpha: 180 runs in 120 balls → 9.0 rpo; concedes 120 in 120 balls → 6.0 rpo
    table.record_result("Alpha", "Beta", "home_win", 180, 120, 120, 120)
    expected = round(180 / 120 * 6 - 120 / 120 * 6, 3)
    assert table["Alpha"].nrr == expected


def test_nrr_accumulates_across_matches():
    table = PointsTable(["Alpha", "Beta", "Gamma"])
    table.record_result("Alpha", "Beta",  "home_win", 180, 120, 160, 120)
    table.record_result("Alpha", "Gamma", "home_win", 200, 120, 150, 120)
    # Alpha has played 2 matches; NRR uses cumulative balls, not per-match
    off = (180 + 200) / (120 + 120) * 6
    def_ = (160 + 150) / (120 + 120) * 6
    assert table["Alpha"].nrr == round(off - def_, 3)


# ── Standings sort order ───────────────────────────────────────────────────────

def test_standings_sorted_by_points_descending(table):
    table.record_result("Alpha", "Beta",  "home_win", 170, 120, 150, 120)
    table.record_result("Alpha", "Gamma", "home_win", 175, 120, 155, 120)
    order = [r.name for r in table.standings()]
    assert order[0] == "Alpha"


def test_standings_nrr_breaks_points_tie():
    table = PointsTable(["Alpha", "Beta"])
    # Both get 1 point; Alpha has better NRR
    table.record_result("Alpha", "Beta", "tie", 200, 120, 150, 120)
    order = [r.name for r in table.standings()]
    assert order[0] == "Alpha"


def test_standings_returns_all_teams(table):
    assert len(table.standings()) == 4


def test_getitem_returns_record(table):
    rec = table["Alpha"]
    assert rec.name == "Alpha"
    assert rec.played == 0
