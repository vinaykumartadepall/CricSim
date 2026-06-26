"""
Tests for MatchAwards / TournamentAwards: POTM and POTT scoring logic.

Uses lightweight delivery mocks — no DB or real match engine required.
"""

import pytest
from unittest.mock import MagicMock

from enums.constants import ExtraType
from simulator.tournament.awards import MatchAwards, PlayerMatchPoints, TournamentAwards


# ── Delivery / match builder helpers ──────────────────────────────────────────

def _player(pid, name):
    p = MagicMock()
    p.id   = pid
    p.name = name
    return p


def _delivery(
    batter, bowler, *,
    over=0, ball=0,
    runs_batter=0, runs_extras=0,
    extras_type=None,
    is_wicket=False,
    wicket_kind=None,
    outcome_player=None,
):
    d = MagicMock()
    d.batter         = batter
    d.bowler         = bowler
    d.over_number    = over
    d.ball_number    = ball
    d.runs_batter    = runs_batter
    d.runs_extras    = runs_extras
    d.extras_type    = extras_type
    d.is_wicket      = is_wicket
    d.wicket_kind    = wicket_kind
    d.outcome_player = outcome_player
    return d


def _inning(deliveries, batting_ips=None, bowling_ips=None):
    batting_team = MagicMock()
    batting_team.name          = "TeamA"
    batting_team.inning_players = batting_ips or []

    bowling_team = MagicMock()
    bowling_team.name           = "TeamB"
    bowling_team.inning_players = bowling_ips or []

    inn = MagicMock()
    inn.deliveries   = deliveries
    inn.batting_team = batting_team
    inn.bowling_team = bowling_team
    return inn


def _match(innings, match_format="T20"):
    m = MagicMock()
    m.innings       = innings
    m.match_format  = match_format
    return m


# ── Batting point rules ────────────────────────────────────────────────────────

def test_run_points():
    pmp = PlayerMatchPoints(1, "Alice")
    pmp.on_batting_ball(20, False, None)
    assert pmp.batting_pts == pytest.approx(10.0)


def test_four_bonus():
    pmp = PlayerMatchPoints(1, "Alice")
    pmp.on_batting_ball(4, False, None)
    assert pmp.batting_pts == pytest.approx(4 * 0.5 + 1.0)


def test_six_bonus():
    pmp = PlayerMatchPoints(1, "Alice")
    pmp.on_batting_ball(6, False, None)
    assert pmp.batting_pts == pytest.approx(6 * 0.5 + 2.0)


def test_fifty_milestone():
    pmp = PlayerMatchPoints(1, "Alice")
    for _ in range(10):
        pmp.on_batting_ball(5, False, None)  # 50 runs over 10 balls
    assert pmp.batting_pts == pytest.approx(10 * 5 * 0.5 + 10.0)  # runs pts + milestone


def test_hundred_milestone_additional():
    pmp = PlayerMatchPoints(1, "Alice")
    for _ in range(20):
        pmp.on_batting_ball(5, False, None)  # 100 runs
    # 50-milestone already tested; the 100 adds +20 more
    assert pmp._100_awarded is True
    assert pmp.batting_pts == pytest.approx(100 * 0.5 + 10.0 + 20.0)


def test_cheap_dismissal_penalty():
    pmp = PlayerMatchPoints(1, "Alice")
    for _ in range(3):
        pmp.on_batting_ball(0, False, None)  # face 3 dot balls
    pmp.on_batting_ball(0, True, None)       # out for 0
    assert pmp.batting_pts < 0


def test_not_out_bonus():
    pmp = PlayerMatchPoints(1, "Alice")
    pmp.on_batting_ball(5, False, None)
    pmp.on_innings_end_batter()
    assert pmp.batting_pts == pytest.approx(5 * 0.5 + 2.0)


def test_wide_skips_batter_ball():
    pmp = PlayerMatchPoints(1, "Alice")
    pmp.on_batting_ball(1, False, ExtraType.WIDE)
    assert pmp._balls == 0  # wides not counted against batter


# ── Bowling point rules ────────────────────────────────────────────────────────

def test_wicket_points():
    pmp = PlayerMatchPoints(1, "Bob")
    pmp.on_bowling_ball(0, 0, None, True, "bowled")
    # Wicket earns 10 pts; the dot-ball bonus is NOT awarded on wicket deliveries
    assert pmp.bowling_pts == pytest.approx(10.0)


def test_dot_ball_points():
    pmp = PlayerMatchPoints(1, "Bob")
    pmp.on_bowling_ball(0, 0, None, False, "")
    assert pmp.bowling_pts == pytest.approx(1.0)


def test_wide_penalty():
    pmp = PlayerMatchPoints(1, "Bob")
    pmp.on_bowling_ball(0, 1, ExtraType.WIDE, False, "")
    assert pmp.bowling_pts == pytest.approx(-1.0)


def test_noball_penalty():
    pmp = PlayerMatchPoints(1, "Bob")
    pmp.on_bowling_ball(0, 1, ExtraType.NOBALL, False, "")
    assert pmp.bowling_pts == pytest.approx(-1.0)


def test_economy_bonus_applied():
    pmp = PlayerMatchPoints(1, "Bob")
    # Bowl 3 overs conceding 0 runs — economy = 0 (well below T20 threshold of 7.5)
    for over in range(3):
        for _ in range(6):
            pmp.on_bowling_ball(0, 0, None, False, "")
        pmp.on_over_end_bowler("T20")
    pmp.finalise_bowling("T20")
    # Base dots = 18 × 1 = 18; economy bonus on top
    assert pmp.bowling_pts > 18.0


def test_economy_bonus_not_applied_under_2_overs():
    pmp = PlayerMatchPoints(1, "Bob")
    # Only 1 over
    for _ in range(6):
        pmp.on_bowling_ball(0, 0, None, False, "")
    pmp.on_over_end_bowler("T20")
    before = pmp.bowling_pts
    pmp.finalise_bowling("T20")
    assert pmp.bowling_pts == before  # no bonus added


# ── Fielding points ────────────────────────────────────────────────────────────

def test_catch_points():
    pmp = PlayerMatchPoints(1, "Charlie")
    pmp.on_fielding_event("catch")
    assert pmp.fielding_pts == 5.0


def test_runout_points():
    pmp = PlayerMatchPoints(1, "Charlie")
    pmp.on_fielding_event("run_out")
    assert pmp.fielding_pts == 5.0


def test_stumping_points():
    pmp = PlayerMatchPoints(1, "Charlie")
    pmp.on_fielding_event("stumping")
    assert pmp.fielding_pts == 7.0


def test_total_is_sum_of_all_categories():
    pmp = PlayerMatchPoints(1, "Alice", batting_pts=20.0, bowling_pts=15.0, fielding_pts=5.0)
    assert pmp.total == 40.0


# ── MatchAwards integration ────────────────────────────────────────────────────

def test_potm_returns_highest_scorer():
    bat = _player(1, "Batter")
    bow = _player(2, "Bowler")

    deliveries = []
    # Batter scores 60 runs across 12 balls
    for _ in range(12):
        deliveries.append(_delivery(bat, bow, runs_batter=5))
    # Bowler takes 1 wicket
    deliveries.append(_delivery(bat, bow, is_wicket=True, wicket_kind="bowled"))

    bat_ip = MagicMock(); bat_ip.id = 1; bat_ip.is_out = True; bat_ip.balls_faced = 12
    bow_ip = MagicMock(); bow_ip.id = 2; bow_ip.is_out = True; bow_ip.balls_faced = 0

    awards = MatchAwards()
    awards.record_from_match(_match([_inning(deliveries, [bat_ip], [bow_ip])]))

    potm = awards.potm()
    assert potm is not None
    assert potm.player_id == 1   # batter scored 60 runs → more points


def test_potm_none_when_no_deliveries():
    awards = MatchAwards()
    awards.record_from_match(_match([_inning([])]))
    assert awards.potm() is None


def test_all_sorted_descending():
    bat = _player(1, "A")
    bow = _player(2, "B")
    deliveries = [
        _delivery(bat, bow, runs_batter=10),
        _delivery(bat, bow, is_wicket=True, wicket_kind="bowled"),
    ]
    bat_ip = MagicMock(); bat_ip.id = 1; bat_ip.is_out = True; bat_ip.balls_faced = 1
    bow_ip = MagicMock(); bow_ip.id = 2; bow_ip.is_out = False; bow_ip.balls_faced = 0

    awards = MatchAwards()
    awards.record_from_match(_match([_inning(deliveries, [bat_ip], [bow_ip])]))

    ranked = awards.all_sorted()
    assert ranked == sorted(ranked, key=lambda p: p.total, reverse=True)


# ── TournamentAwards ───────────────────────────────────────────────────────────

def test_tournament_awards_accumulate_across_matches():
    ta = TournamentAwards()

    def _awards_with(pid, name, batting=0.0, bowling=0.0):
        a = MatchAwards()
        a._players[pid] = PlayerMatchPoints(pid, name, batting_pts=batting, bowling_pts=bowling)
        return a

    ta.add_match(_awards_with(1, "Alice", batting=30.0))
    ta.add_match(_awards_with(1, "Alice", batting=25.0))
    ta.add_match(_awards_with(2, "Bob",   batting=60.0))

    assert ta._totals[1].batting_pts == pytest.approx(55.0)
    assert ta._totals[2].batting_pts == pytest.approx(60.0)


def test_pott_returns_highest_cumulative():
    ta = TournamentAwards()
    ta.add_match(MatchAwards())   # empty match
    a1 = MatchAwards()
    a1._players[1] = PlayerMatchPoints(1, "Alice", batting_pts=100.0)
    a1._players[2] = PlayerMatchPoints(2, "Bob",   batting_pts=80.0)
    ta.add_match(a1)
    assert ta.pott().player_id == 1


def test_pott_leaderboard_size():
    ta = TournamentAwards()
    awards = MatchAwards()
    for i in range(15):
        awards._players[i] = PlayerMatchPoints(i, f"P{i}", batting_pts=float(i))
    ta.add_match(awards)
    assert len(ta.leaderboard(top_n=10)) == 10
