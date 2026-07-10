"""
Tests for TournamentLeaderboards: stat accumulation and leaderboard queries.

Uses lightweight mock objects that replicate the field access patterns of the
real SimulationMatch / Inning / InningTeam / InningPlayer hierarchy.
"""

import pytest
from unittest.mock import MagicMock

from simulator.tournament.leaderboards import BatterStats, BowlerStats, TournamentLeaderboards


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_player(pid: int, name: str):
    p = MagicMock()
    p.id   = pid
    p.name = name
    return p


def _make_inning_player(
    pid, name, *,
    runs=0, balls=0, fours=0, sixes=0, is_out=True,
    balls_bowled=0, runs_conceded=0, wickets=0, maidens=0,
):
    ip = MagicMock()
    ip.id            = pid
    ip.name          = name
    ip.runs_scored   = runs
    ip.balls_faced   = balls
    ip.fours         = fours
    ip.sixes         = sixes
    ip.is_out        = is_out
    ip.balls_bowled  = balls_bowled
    ip.runs_conceded = runs_conceded
    ip.wickets_taken = wickets
    ip.maidens       = maidens
    return ip


def _make_inning(batting_ips, bowling_ips):
    """Build a mock Inning object."""
    batting_team = MagicMock()
    batting_team.inning_players = batting_ips

    bowling_team = MagicMock()
    bowling_team.inning_players = bowling_ips

    inning = MagicMock()
    inning.batting_team = batting_team
    inning.bowling_team = bowling_team
    return inning


def _make_match(home_players, away_players, innings):
    m = MagicMock()
    m.home_team = MagicMock()
    m.home_team.players = home_players
    m.away_team = MagicMock()
    m.away_team.players = away_players
    m.innings = innings
    return m


# ── Batting accumulation ───────────────────────────────────────────────────────

def test_batting_runs_accumulated():
    lb = TournamentLeaderboards()
    p1 = _make_player(1, "Alice")
    ip = _make_inning_player(1, "Alice", runs=75, balls=50, fours=8, sixes=3)
    match = _make_match([p1], [], [_make_inning([ip], [])])
    lb.add_match(match, "TeamA", "TeamB")
    assert lb._batting[1].runs == 75
    assert lb._batting[1].balls == 50
    assert lb._batting[1].fours == 8
    assert lb._batting[1].sixes == 3


def test_batting_not_out_counted():
    lb = TournamentLeaderboards()
    p1 = _make_player(1, "Alice")
    ip = _make_inning_player(1, "Alice", runs=30, balls=25, is_out=False)
    match = _make_match([p1], [], [_make_inning([ip], [])])
    lb.add_match(match, "TeamA", "TeamB")
    assert lb._batting[1].not_outs == 1


def test_batting_highest_score_updated():
    lb = TournamentLeaderboards()
    p1 = _make_player(1, "Alice")
    ip1 = _make_inning_player(1, "Alice", runs=45, balls=35)
    ip2 = _make_inning_player(1, "Alice", runs=80, balls=60)
    m1 = _make_match([p1], [], [_make_inning([ip1], [])])
    m2 = _make_match([p1], [], [_make_inning([ip2], [])])
    lb.add_match(m1, "TeamA", "TeamB")
    lb.add_match(m2, "TeamA", "TeamB")
    assert lb._batting[1].highest_score == 80


def test_batting_zero_ball_player_excluded():
    lb = TournamentLeaderboards()
    p1 = _make_player(1, "Alice")
    ip = _make_inning_player(1, "Alice", runs=0, balls=0)
    match = _make_match([p1], [], [_make_inning([ip], [])])
    lb.add_match(match, "TeamA", "TeamB")
    assert 1 not in lb._batting


# ── Bowling accumulation ───────────────────────────────────────────────────────

def test_bowling_stats_accumulated():
    lb = TournamentLeaderboards()
    p1 = _make_player(1, "Bob")
    bp = _make_inning_player(1, "Bob", balls_bowled=24, runs_conceded=30, wickets=2, maidens=1)
    match = _make_match([], [p1], [_make_inning([], [bp])])
    lb.add_match(match, "TeamA", "TeamB")
    assert lb._bowling[1].balls   == 24
    assert lb._bowling[1].runs    == 30
    assert lb._bowling[1].wickets == 2
    assert lb._bowling[1].maidens == 1


def test_bowling_overs_display():
    lb = TournamentLeaderboards()
    p1 = _make_player(1, "Bob")
    # 16 balls = 2 overs 4 balls → displayed as 2.4
    bp = _make_inning_player(1, "Bob", balls_bowled=16, runs_conceded=20)
    match = _make_match([], [p1], [_make_inning([], [bp])])
    lb.add_match(match, "TeamA", "TeamB")
    assert lb._bowling[1].overs == pytest.approx(2.4)


def test_bowling_best_figures_updated():
    lb = TournamentLeaderboards()
    p1 = _make_player(1, "Bob")
    bp1 = _make_inning_player(1, "Bob", balls_bowled=24, runs_conceded=30, wickets=2)
    bp2 = _make_inning_player(1, "Bob", balls_bowled=24, runs_conceded=20, wickets=3)
    m1 = _make_match([], [p1], [_make_inning([], [bp1])])
    m2 = _make_match([], [p1], [_make_inning([], [bp2])])
    lb.add_match(m1, "TeamA", "TeamB")
    lb.add_match(m2, "TeamA", "TeamB")
    assert lb._bowling[1].best_wickets == 3
    assert lb._bowling[1].best_runs    == 20


# ── Leaderboard queries ────────────────────────────────────────────────────────

def test_most_runs_sorted():
    lb = TournamentLeaderboards()
    for pid, runs in [(1, 400), (2, 600), (3, 300)]:
        p = _make_player(pid, f"P{pid}")
        ip = _make_inning_player(pid, f"P{pid}", runs=runs, balls=runs)
        m = _make_match([p], [], [_make_inning([ip], [])])
        lb.add_match(m, "TeamA", "TeamB")
    top = lb.most_runs(top_n=3)
    assert [s.runs for s in top] == [600, 400, 300]


def test_most_wickets_sorted():
    lb = TournamentLeaderboards()
    for pid, wkts in [(1, 5), (2, 12), (3, 8)]:
        p = _make_player(pid, f"P{pid}")
        bp = _make_inning_player(pid, f"P{pid}", balls_bowled=60, runs_conceded=50, wickets=wkts)
        m = _make_match([], [p], [_make_inning([], [bp])])
        lb.add_match(m, "TeamA", "TeamB")
    top = lb.most_wickets(top_n=3)
    assert [s.wickets for s in top] == [12, 8, 5]


def test_best_economy_filters_min_balls():
    lb = TournamentLeaderboards()
    # p1: 30 balls (below min 60), p2: 60 balls
    p1 = _make_player(1, "Cheap")
    p2 = _make_player(2, "Regular")
    bp1 = _make_inning_player(1, "Cheap",   balls_bowled=30, runs_conceded=10)
    bp2 = _make_inning_player(2, "Regular", balls_bowled=60, runs_conceded=40)
    m = _make_match([], [p1, p2], [_make_inning([], [bp1, bp2])])
    lb.add_match(m, "TeamA", "TeamB")
    eco = lb.best_economy(min_balls=60)
    assert len(eco) == 1
    assert eco[0].player_id == 2


def test_batting_average_excludes_all_not_outs():
    lb = TournamentLeaderboards()
    p = _make_player(1, "Alice")
    # 3 innings, all not out - average is ∞
    for _ in range(3):
        ip = _make_inning_player(1, "Alice", runs=50, balls=40, is_out=False)
        m = _make_match([p], [], [_make_inning([ip], [])])
        lb.add_match(m, "TeamA", "TeamB")
    stats = lb._batting[1]
    assert stats.average == float('inf')
    assert stats.average_display == "∞"


# ── Derived stat properties ────────────────────────────────────────────────────

def test_batter_strike_rate():
    s = BatterStats(1, "A", "T", runs=100, balls=80)
    assert s.strike_rate == pytest.approx(125.0)


def test_bowler_economy():
    s = BowlerStats(1, "B", "T", balls=24, runs=30)
    assert s.economy == pytest.approx(7.5)


def test_bowler_best_figures_string():
    s = BowlerStats(1, "B", "T", best_wickets=3, best_runs=22)
    assert s.best_figures == "3/22"
