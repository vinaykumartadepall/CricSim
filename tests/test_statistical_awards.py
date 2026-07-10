"""
Tests for StatisticalAwardsStrategy - the default MvpStrategy, scoring every
ball against a fixed, per-format point table.

Point values are format-specific and come from StatisticalAwardsStrategy's
own _RULES - most tests here read expected values off that table directly
(via the module-level T20/ODI/TEST constants below) rather than repeating
the numbers, to stay correct automatically if the rubric's numbers ever
change, while still catching format-selection bugs, milestone-stacking
bugs, and innings-scoping bugs the table alone can't verify.

_PlayerTally (the internal per-ball accumulator) is imported directly for
granular rule-level tests - it's private to statistical_awards.py, but
testing it in isolation is far more targeted than building a full mock
match for every single-rule check. Integration-level tests (does compute()
correctly wire deliveries -> tallies -> PlayerAward) build real mock
matches and go through the public compute() entry point.

Uses lightweight delivery mocks - no DB or real match engine required.
"""

import pytest
from unittest.mock import MagicMock

from enums.constants import ExtraType
from simulator.awards.mvp_strategy import PlayerAward
from simulator.awards.statistical_awards import StatisticalAwardsStrategy, _PlayerTally

T20 = StatisticalAwardsStrategy()._rules_for('T20')
ODI = StatisticalAwardsStrategy()._rules_for('ODI')
TEST = StatisticalAwardsStrategy()._rules_for('Test')


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


def _inning(deliveries, batting_ips=None, bowling_ips=None, inning_number=1):
    batting_team = MagicMock()
    batting_team.name          = "TeamA"
    batting_team.inning_players = batting_ips or []

    bowling_team = MagicMock()
    bowling_team.name           = "TeamB"
    bowling_team.inning_players = bowling_ips or []

    inn = MagicMock()
    inn.inning_number = inning_number
    inn.deliveries    = deliveries
    inn.batting_team  = batting_team
    inn.bowling_team  = bowling_team
    return inn


def _match(innings, match_format="T20"):
    m = MagicMock()
    m.innings       = innings
    m.match_format  = match_format
    return m


# ── Format resolution ──────────────────────────────────────────────────────────

class TestFormatResolution:
    def test_canonical_formats_return_distinct_rules(self):
        assert T20.wicket != TEST.wicket
        assert T20.dot_ball != ODI.dot_ball
        assert ODI.dot_ball != TEST.dot_ball

    def test_format_aliases_resolve_to_canonical(self):
        strategy = StatisticalAwardsStrategy()
        assert strategy._rules_for('MDM') == strategy._rules_for('Test')
        assert strategy._rules_for('IT20') == strategy._rules_for('T20')
        assert strategy._rules_for('ODM') == strategy._rules_for('ODI')

    def test_unknown_format_falls_back_to_t20(self):
        assert StatisticalAwardsStrategy()._rules_for('CUSTOM') == T20


# ── Batting point rules (via _PlayerTally directly) ────────────────────────────

def test_run_points():
    t = _PlayerTally(1, "Alice", rules=T20)
    t.on_batting_ball(1, 20, False, None)
    assert t.batting_pts == pytest.approx(20 * T20.run)


def test_four_bonus_varies_by_format():
    t20 = _PlayerTally(1, "Alice", rules=T20)
    t20.on_batting_ball(1, 4, False, None)
    assert t20.batting_pts == pytest.approx(4 * T20.run + T20.boundary_bonus)

    odi = _PlayerTally(1, "Alice", rules=ODI)
    odi.on_batting_ball(1, 4, False, None)
    assert odi.batting_pts == pytest.approx(4 * ODI.run + ODI.boundary_bonus)
    assert T20.boundary_bonus != ODI.boundary_bonus  # sanity: formats actually differ


def test_six_bonus_varies_by_format():
    t20 = _PlayerTally(1, "Alice", rules=T20)
    t20.on_batting_ball(1, 6, False, None)
    assert t20.batting_pts == pytest.approx(6 * T20.run + T20.six_bonus)

    test_fmt = _PlayerTally(1, "Alice", rules=TEST)
    test_fmt.on_batting_ball(1, 6, False, None)
    assert test_fmt.batting_pts == pytest.approx(6 * TEST.run + TEST.six_bonus)


def test_30_run_bonus_only_exists_in_t20():
    assert any(threshold == 30 for threshold, _ in T20.batting_milestones)
    assert not any(threshold == 30 for threshold, _ in ODI.batting_milestones)
    assert not any(threshold == 30 for threshold, _ in TEST.batting_milestones)


def test_milestones_stack_within_an_innings():
    t = _PlayerTally(1, "Alice", rules=T20)
    for _ in range(24):
        t.on_batting_ball(1, 5, False, None)  # 120 runs, one innings
    milestone_bonus = sum(b for th, b in T20.batting_milestones if th <= 120)
    assert t.batting_pts == pytest.approx(120 * T20.run + milestone_bonus)


def test_milestones_reset_between_innings():
    t = _PlayerTally(1, "Alice", rules=TEST)
    for _ in range(10):
        t.on_batting_ball(1, 5, False, None)  # 50 in innings 1 -> 50-bonus
    pts_after_first_innings = t.batting_pts
    assert pts_after_first_innings == pytest.approx(50 * TEST.run + TEST.batting_milestones[0][1])

    for _ in range(10):
        t.on_batting_ball(2, 5, False, None)  # fresh 50 in innings 2 -> 50-bonus again
    assert t.batting_pts == pytest.approx(pts_after_first_innings + 50 * TEST.run + TEST.batting_milestones[0][1])


def test_wide_does_not_award_batting_points():
    t = _PlayerTally(1, "Alice", rules=T20)
    t.on_batting_ball(1, 1, False, ExtraType.WIDE)
    assert t.batting_pts == 0.0


# ── Bowling point rules ────────────────────────────────────────────────────────

def test_wicket_points_vary_by_format():
    t20 = _PlayerTally(1, "Bob", rules=T20)
    t20.on_bowling_ball(1, 0, 0, None, True, "caught")
    assert t20.bowling_pts == pytest.approx(T20.wicket)

    test_fmt = _PlayerTally(1, "Bob", rules=TEST)
    test_fmt.on_bowling_ball(1, 0, 0, None, True, "caught")
    assert test_fmt.bowling_pts == pytest.approx(TEST.wicket)
    assert T20.wicket != TEST.wicket  # sanity


def test_bowled_and_lbw_earn_dismissal_bonus():
    for kind in ("bowled", "lbw"):
        t = _PlayerTally(1, "Bob", rules=T20)
        t.on_bowling_ball(1, 0, 0, None, True, kind)
        assert t.bowling_pts == pytest.approx(T20.wicket + T20.dismissal_bonus)


def test_caught_does_not_earn_dismissal_bonus():
    t = _PlayerTally(1, "Bob", rules=T20)
    t.on_bowling_ball(1, 0, 0, None, True, "caught")
    assert t.bowling_pts == pytest.approx(T20.wicket)


def test_dot_ball_points_vary_by_format_and_zero_for_test():
    t20 = _PlayerTally(1, "Bob", rules=T20)
    t20.on_bowling_ball(1, 0, 0, None, False, "")
    assert t20.bowling_pts == pytest.approx(T20.dot_ball)

    test_fmt = _PlayerTally(1, "Bob", rules=TEST)
    test_fmt.on_bowling_ball(1, 0, 0, None, False, "")
    assert test_fmt.bowling_pts == pytest.approx(TEST.dot_ball) == 0.0


def test_wide_and_noball_give_no_bowling_points_either_way():
    t = _PlayerTally(1, "Bob", rules=T20)
    t.on_bowling_ball(1, 0, 1, ExtraType.WIDE, False, "")
    t.on_bowling_ball(1, 0, 1, ExtraType.NOBALL, False, "")
    assert t.bowling_pts == 0.0


def test_maiden_over_points_vary_by_format():
    for rules in (T20, ODI, TEST):
        t = _PlayerTally(1, "Bob", rules=rules)
        for _ in range(6):
            t.on_bowling_ball(1, 0, 0, None, False, "")
        t.on_over_end_bowler()
        expected = rules.dot_ball * 6 + rules.maiden
        assert t.bowling_pts == pytest.approx(expected)


def test_maiden_not_awarded_if_runs_conceded():
    t = _PlayerTally(1, "Bob", rules=T20)
    t.on_bowling_ball(1, 4, 0, None, False, "")  # boundary conceded - not a dot, breaks the maiden
    for _ in range(5):
        t.on_bowling_ball(1, 0, 0, None, False, "")
    t.on_over_end_bowler()
    assert t.bowling_pts == pytest.approx(T20.dot_ball * 5)  # 5 dots, no maiden bonus


def test_wicket_haul_milestones_stack_within_an_innings():
    t = _PlayerTally(1, "Bob", rules=T20)
    for _ in range(4):
        t.on_bowling_ball(1, 0, 0, None, True, "bowled")
    per_wicket = T20.wicket + T20.dismissal_bonus
    haul_bonus = sum(b for th, b in T20.bowling_milestones if th <= 4)
    assert t.bowling_pts == pytest.approx(4 * per_wicket + haul_bonus)


def test_wicket_haul_resets_between_innings():
    t = _PlayerTally(1, "Bob", rules=TEST)
    for _ in range(3):
        t.on_bowling_ball(1, 0, 0, None, True, "caught")  # 3-wicket haul, innings 1
    pts_after_first = t.bowling_pts
    haul_bonus_3 = next(b for th, b in TEST.bowling_milestones if th == 3)
    assert pts_after_first == pytest.approx(3 * TEST.wicket + haul_bonus_3)

    for _ in range(3):
        t.on_bowling_ball(2, 0, 0, None, True, "caught")  # fresh 3-wicket haul, innings 2
    assert t.bowling_pts == pytest.approx(pts_after_first + 3 * TEST.wicket + haul_bonus_3)


def test_ten_wicket_match_bonus_only_for_test_and_spans_both_innings():
    t = _PlayerTally(1, "Bob", rules=TEST)
    for _ in range(6):
        t.on_bowling_ball(1, 0, 0, None, True, "caught")  # 6 wickets, innings 1
    for _ in range(4):
        t.on_bowling_ball(2, 0, 0, None, True, "caught")  # 4 more, innings 2 -> 10 total
    haul_bonus_innings1 = sum(b for th, b in TEST.bowling_milestones if th <= 6)
    haul_bonus_innings2 = sum(b for th, b in TEST.bowling_milestones if th <= 4)
    expected = (10 * TEST.wicket) + haul_bonus_innings1 + haul_bonus_innings2 + TEST.ten_wicket_match_bonus
    assert t.bowling_pts == pytest.approx(expected)
    assert TEST.ten_wicket_match_bonus > 0
    assert T20.ten_wicket_match_bonus == 0
    assert ODI.ten_wicket_match_bonus == 0


# ── Fielding points ────────────────────────────────────────────────────────────

def test_catch_points_and_milestone_bonus():
    t = _PlayerTally(1, "Charlie", rules=T20)
    for _ in range(3):
        t.on_fielding_event("catch")
    assert t.fielding_pts == pytest.approx(3 * T20.catch + T20.catch_milestone_bonus)


def test_catch_milestone_bonus_awarded_only_once():
    t = _PlayerTally(1, "Charlie", rules=T20)
    for _ in range(5):
        t.on_fielding_event("catch")
    assert t.fielding_pts == pytest.approx(5 * T20.catch + T20.catch_milestone_bonus)


def test_runout_points():
    t = _PlayerTally(1, "Charlie", rules=T20)
    t.on_fielding_event("run_out")
    assert t.fielding_pts == pytest.approx(T20.runout)


def test_stumping_points():
    t = _PlayerTally(1, "Charlie", rules=T20)
    t.on_fielding_event("stumping")
    assert t.fielding_pts == pytest.approx(T20.stumping)


# ── compute() integration ──────────────────────────────────────────────────────

def test_compute_returns_player_award_with_breakdown():
    bat = _player(1, "Batter")
    bow = _player(2, "Bowler")
    deliveries = [_delivery(bat, bow, runs_batter=4)]
    bat_ip = MagicMock(); bat_ip.id = 1; bat_ip.is_out = False; bat_ip.balls_faced = 1
    bow_ip = MagicMock(); bow_ip.id = 2; bow_ip.is_out = False; bow_ip.balls_faced = 0

    results = StatisticalAwardsStrategy().compute(
        _match([_inning(deliveries, [bat_ip], [bow_ip])])
    )

    by_id = {a.player_id: a for a in results}
    assert isinstance(by_id[1], PlayerAward)
    assert by_id[1].team == "TeamA"
    assert by_id[1].breakdown['batting_pts'] == pytest.approx(4 * T20.run + T20.boundary_bonus)
    assert by_id[1].total == pytest.approx(by_id[1].breakdown['batting_pts'])


def test_compute_picks_highest_scorer_first_via_matchawards_potm():
    # MatchAwards.potm() picks the max by .total - verify compute()'s output
    # ranks the way MatchAwards relies on.
    bat = _player(1, "Batter")
    bow = _player(2, "Bowler")

    deliveries = []
    for _ in range(12):
        deliveries.append(_delivery(bat, bow, runs_batter=5))  # 60 runs
    deliveries.append(_delivery(bat, bow, is_wicket=True, wicket_kind="bowled"))  # 1 wicket

    bat_ip = MagicMock(); bat_ip.id = 1; bat_ip.is_out = True; bat_ip.balls_faced = 12
    bow_ip = MagicMock(); bow_ip.id = 2; bow_ip.is_out = True; bow_ip.balls_faced = 0

    results = StatisticalAwardsStrategy().compute(
        _match([_inning(deliveries, [bat_ip], [bow_ip])])
    )
    best = max(results, key=lambda a: a.total)
    assert best.player_id == 1  # 60 runs (+ 50-milestone) outscores one wicket


def test_mdm_format_resolves_to_test_rules():
    bat = _player(1, "Batter")
    bow = _player(2, "Bowler")
    deliveries = [_delivery(bat, bow, is_wicket=True, wicket_kind="bowled")]
    bat_ip = MagicMock(); bat_ip.id = 1; bat_ip.is_out = False; bat_ip.balls_faced = 0
    bow_ip = MagicMock(); bow_ip.id = 2; bow_ip.is_out = False; bow_ip.balls_faced = 0

    results = StatisticalAwardsStrategy().compute(
        _match([_inning(deliveries, [bat_ip], [bow_ip])], match_format="MDM")
    )

    bowler = next(a for a in results if a.player_id == 2)
    assert bowler.total == pytest.approx(TEST.wicket + TEST.dismissal_bonus)
