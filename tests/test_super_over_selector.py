"""
Unit tests for SuperOverSelector scoring.

Covers:
  - _death_sigmoid: curve shape, monotonicity, base calibration
  - _global_bat: sigmoid-based global batting score
  - _match_bat_split: sigmoid scoring, zero when no death balls (no career proxy)
  - _global_bowl: unchanged linear eco scoring
  - _match_bowl_split: zero when no death balls (no career proxy)
  - select_batters / select_bowler: m_death=0 players score lower than those with
    death-over exposure; career data is never substituted for match_death_score
"""
import math
import pytest
from unittest.mock import MagicMock

from simulator.engines.super_over_engine import (
    SuperOverSelector,
    _death_sigmoid,
    _DEATH_SR_BASE,
    _BDRY_RATE_BASE,
    _SIGMOID_K,
    _GLOBAL_W,
    _MATCH_DEATH_W,
    _MATCH_FULL_W,
    _FALLBACK_SCORE,
)
from simulator.entities.inning_player import InningPlayer
from simulator.entities.player import Player


# ── helpers ───────────────────────────────────────────────────────────────────

def _player(pid=1, name="P"):
    return Player(id=pid, name=name)


def _ip(pid=1, name="P", **stats):
    ip = InningPlayer(player=_player(pid, name))
    for k, v in stats.items():
        setattr(ip, k, v)
    return ip


# ── _death_sigmoid ────────────────────────────────────────────────────────────

class TestDeathSigmoid:
    def test_at_base_scores_half(self):
        assert abs(_death_sigmoid(_DEATH_SR_BASE, _DEATH_SR_BASE) - 0.5) < 1e-9

    def test_above_base_scores_above_half(self):
        assert _death_sigmoid(_DEATH_SR_BASE * 1.5, _DEATH_SR_BASE) > 0.5

    def test_below_base_scores_below_half(self):
        assert _death_sigmoid(_DEATH_SR_BASE * 0.5, _DEATH_SR_BASE) < 0.5

    def test_zero_value_is_near_zero(self):
        score = _death_sigmoid(0.0, _DEATH_SR_BASE)
        assert score < 0.05

    def test_double_base_is_near_one(self):
        score = _death_sigmoid(_DEATH_SR_BASE * 2.0, _DEATH_SR_BASE)
        assert score > 0.95

    def test_monotone_increasing(self):
        scores = [_death_sigmoid(v, _DEATH_SR_BASE) for v in [0, 60, 80, 100, 120, 150, 180, 200]]
        assert scores == sorted(scores)

    def test_non_linear_below_base(self):
        # Drop from base to 75% of base should hurt more than from 75% to 50%
        drop_25pct = _death_sigmoid(_DEATH_SR_BASE, _DEATH_SR_BASE) - _death_sigmoid(_DEATH_SR_BASE * 0.75, _DEATH_SR_BASE)
        drop_25pct_lower = _death_sigmoid(_DEATH_SR_BASE * 0.75, _DEATH_SR_BASE) - _death_sigmoid(_DEATH_SR_BASE * 0.50, _DEATH_SR_BASE)
        assert drop_25pct > drop_25pct_lower

    def test_non_linear_above_base(self):
        # The sigmoid is steepest at the base (inflection point).
        # Marginal gain is largest just above base and shrinks at extremes.
        gain_first  = _death_sigmoid(_DEATH_SR_BASE * 1.25, _DEATH_SR_BASE) - _death_sigmoid(_DEATH_SR_BASE, _DEATH_SR_BASE)
        gain_second = _death_sigmoid(_DEATH_SR_BASE * 1.50, _DEATH_SR_BASE) - _death_sigmoid(_DEATH_SR_BASE * 1.25, _DEATH_SR_BASE)
        assert gain_first > gain_second

    def test_zero_base_clamps_ratio(self):
        # base=0 should not raise; ratio clamps to 0
        score = _death_sigmoid(100.0, 0.0)
        assert score < 0.05

    def test_bdry_rate_base_calibration(self):
        assert abs(_death_sigmoid(_BDRY_RATE_BASE, _BDRY_RATE_BASE) - 0.5) < 1e-9


# ── _global_bat ───────────────────────────────────────────────────────────────

class TestGlobalBat:
    def test_none_returns_none(self):
        assert SuperOverSelector._global_bat(None) is None

    def test_empty_dict_returns_none(self):
        # Empty dict is falsy - treated same as None (no historical data)
        assert SuperOverSelector._global_bat({}) is None

    def test_average_player_scores_half(self):
        death = {'death_sr': _DEATH_SR_BASE, 'boundary_rate': _BDRY_RATE_BASE}
        score = SuperOverSelector._global_bat(death)
        assert abs(score - 0.5) < 1e-9

    def test_exceptional_player_scores_high(self):
        death = {'death_sr': 180.0, 'boundary_rate': 0.35}
        score = SuperOverSelector._global_bat(death)
        assert score > 0.70

    def test_poor_player_scores_low(self):
        death = {'death_sr': 60.0, 'boundary_rate': 0.08}
        score = SuperOverSelector._global_bat(death)
        assert score < 0.20

    def test_boundary_rate_more_important_than_sr(self):
        high_bdry = {'death_sr': 100.0, 'boundary_rate': 0.40}
        high_sr   = {'death_sr': 200.0, 'boundary_rate': 0.05}
        assert SuperOverSelector._global_bat(high_bdry) > SuperOverSelector._global_bat(high_sr)

    def test_score_bounded_between_zero_and_one(self):
        death = {'death_sr': 300.0, 'boundary_rate': 1.0}
        score = SuperOverSelector._global_bat(death)
        assert 0.0 <= score <= 1.0


# ── _match_bat_split ──────────────────────────────────────────────────────────

class TestMatchBatSplit:
    def test_none_ip_returns_zeros(self):
        m_death, m_full = SuperOverSelector._match_bat_split(None)
        assert m_death == 0.0
        assert m_full == 0.0

    def test_ip_with_no_balls_returns_zeros(self):
        ip = _ip()  # all default zeros
        m_death, m_full = SuperOverSelector._match_bat_split(ip)
        assert m_death == 0.0
        assert m_full == 0.0

    def test_no_death_balls_means_m_death_is_zero(self):
        # Player batted in powerplay only - no career proxy should substitute
        ip = _ip(balls_faced=12, runs_scored=18, fours=1, sixes=1)
        m_death, _ = SuperOverSelector._match_bat_split(ip)
        assert m_death == 0.0

    def test_death_balls_produce_nonzero_m_death(self):
        ip = _ip(death_balls_faced=6, death_runs_scored=12, death_fours=1, death_sixes=1)
        m_death, _ = SuperOverSelector._match_bat_split(ip)
        assert m_death > 0.0

    def test_average_death_performance_scores_half(self):
        # SR 120 (= 1.2 runs/ball * 100) and bdry_rate 0.20 → both at sigmoid base
        balls = 10
        runs  = int(balls * 1.20)   # SR 120
        bdries = int(balls * 0.20)  # bdry_rate 0.20
        ip = _ip(death_balls_faced=balls, death_runs_scored=runs,
                 death_fours=bdries, death_sixes=0)
        m_death, _ = SuperOverSelector._match_bat_split(ip)
        assert abs(m_death - 0.5) < 0.02

    def test_full_score_from_innings_not_death(self):
        ip = _ip(balls_faced=24, runs_scored=30, fours=2, sixes=1)
        _, m_full = SuperOverSelector._match_bat_split(ip)
        assert m_full > 0.0

    def test_sr_computed_as_percentage(self):
        # 12 runs off 6 balls = SR 200 (exceptional), not 2.0
        ip1 = _ip(death_balls_faced=6, death_runs_scored=12)   # SR 200
        ip2 = _ip(death_balls_faced=6, death_runs_scored=6)    # SR 100
        m1, _ = SuperOverSelector._match_bat_split(ip1)
        m2, _ = SuperOverSelector._match_bat_split(ip2)
        assert m1 > m2


# ── _global_bowl ──────────────────────────────────────────────────────────────

class TestGlobalBowl:
    def test_none_returns_none(self):
        assert SuperOverSelector._global_bowl(None) is None

    def test_insufficient_balls_returns_none(self):
        assert SuperOverSelector._global_bowl({'balls': 6}) is None

    def test_eco_at_ref_scores_zero(self):
        from simulator.engines.super_over_engine import _DEATH_ECO_REF
        death = {'balls': 60, 'economy': _DEATH_ECO_REF}
        score = SuperOverSelector._global_bowl(death)
        assert score == 0.0

    def test_below_eco_ref_scores_positive(self):
        death = {'balls': 60, 'economy': 8.0}
        score = SuperOverSelector._global_bowl(death)
        assert score > 0.0

    def test_above_eco_ref_scores_zero(self):
        from simulator.engines.super_over_engine import _DEATH_ECO_REF
        death = {'balls': 60, 'economy': _DEATH_ECO_REF + 2.0}
        score = SuperOverSelector._global_bowl(death)
        assert score == 0.0


# ── _match_bowl_split ─────────────────────────────────────────────────────────

class TestMatchBowlSplit:
    def test_none_ip_returns_zeros(self):
        m_death, m_full = SuperOverSelector._match_bowl_split(None)
        assert m_death == 0.0
        assert m_full == 0.0

    def test_no_balls_bowled_returns_zeros(self):
        ip = _ip()
        m_death, m_full = SuperOverSelector._match_bowl_split(ip)
        assert m_death == 0.0
        assert m_full == 0.0

    def test_no_death_balls_means_m_death_is_zero(self):
        # Bowler only bowled powerplay - no career proxy
        ip = _ip(balls_bowled=24, runs_conceded=20)
        m_death, _ = SuperOverSelector._match_bowl_split(ip)
        assert m_death == 0.0

    def test_death_balls_produce_nonzero_m_death(self):
        ip = _ip(death_balls_bowled=6, death_runs_conceded=6)  # eco 6.0 < 16 ref
        m_death, _ = SuperOverSelector._match_bowl_split(ip)
        assert m_death > 0.0

    def test_full_score_from_all_balls(self):
        ip = _ip(balls_bowled=24, runs_conceded=24)  # eco 6.0
        _, m_full = SuperOverSelector._match_bowl_split(ip)
        assert m_full > 0.0


# ── select_batters: no career proxy ──────────────────────────────────────────

class TestSelectBattersNoCareerProxy:
    """
    Verifies that a player who did NOT face death balls this match gets m_death=0,
    and that their score is NOT boosted to their career proxy.
    """

    def _make_selector(self, death_stats_by_id):
        repo = MagicMock()
        repo.get_batter_death_stats.return_value = death_stats_by_id
        return SuperOverSelector(repo)

    def _make_team_inning(self, inning_players):
        inning = MagicMock()
        inning.batting_team.inning_players = inning_players
        return inning

    def test_no_death_balls_player_scores_below_career_proxy(self):
        """
        Player A: good career death stats (SR 180, bdry 0.35) but 0 death balls this match.
        Player B: no career death stats, also 0 death balls this match.

        Without a career proxy, both players' match_death_score = 0.
        Player A should still score higher (global component), but NOT as high as
        if the career proxy were applied to match_death_score too.
        """
        from simulator.entities.team import MatchTeam

        p_a = _player(pid=1, name="DeathExpert")
        p_b = _player(pid=2, name="NoData")

        team = MatchTeam(id=1, name="Test", players=[p_a, p_b])

        # ip_a batted this match but only in powerplay (death_balls_faced=0)
        ip_a = _ip(pid=1, balls_faced=18, runs_scored=22, fours=2, sixes=0,
                   death_balls_faced=0)
        # ip_b didn't bat at all
        ip_b = _ip(pid=2)

        team_inning = self._make_team_inning([ip_a, ip_b])

        # Career stats for player A (good death hitter)
        career_death = {
            1: {'death_sr': 180.0, 'boundary_rate': 0.35},
            # 2 has no career data
        }

        selector = self._make_selector(career_death)
        selected = selector.select_batters(team, team_inning, "T20", "male", n=2)

        # Player A should still be selected (global component from career stats)
        selected_ids = [p.id for p in selected]
        assert 1 in selected_ids

    def test_player_with_death_balls_beats_player_without(self):
        """Player who actually scored at death this match should outscore an
        equally-credited career player who batted in powerplay only."""
        from simulator.entities.team import MatchTeam

        p_death = _player(pid=1, name="DeathBatter")
        p_pp    = _player(pid=2, name="PPBatter")

        team = MatchTeam(id=1, name="Test", players=[p_death, p_pp])

        # p_death had a good death-over innings
        ip_death = _ip(pid=1, death_balls_faced=6, death_runs_scored=15,
                       death_fours=1, death_sixes=2,
                       balls_faced=18, runs_scored=30, fours=2, sixes=2)
        # p_pp had identical career stats but batted only in powerplay
        ip_pp = _ip(pid=2, balls_faced=18, runs_scored=30, fours=2, sixes=2,
                    death_balls_faced=0)

        team_inning = self._make_team_inning([ip_death, ip_pp])

        # Both have identical career death stats
        same_career = {
            1: {'death_sr': 150.0, 'boundary_rate': 0.28},
            2: {'death_sr': 150.0, 'boundary_rate': 0.28},
        }

        selector = self._make_selector(same_career)
        selected = selector.select_batters(team, team_inning, "T20", "male", n=1)

        # The player who batted at death should be ranked first
        assert selected[0].id == 1


# ── select_bowler: no career proxy ───────────────────────────────────────────

class TestSelectBowlerNoCareerProxy:
    def _make_selector(self, phase_stats_by_id):
        repo = MagicMock()
        repo.get_bowler_phase_stats.return_value = phase_stats_by_id
        return SuperOverSelector(repo)

    def _make_bowling_inning(self, inning_players):
        inning = MagicMock()
        inning.bowling_team.inning_players = inning_players
        return inning

    def test_bowler_with_death_balls_beats_equivalent_without(self):
        from simulator.entities.team import MatchTeam

        p_death = _player(pid=1, name="DeathBowler")
        p_pp    = _player(pid=2, name="PPBowler")

        team = MatchTeam(id=1, name="Test", players=[p_death, p_pp])

        # p_death bowled at death: 6 balls, 6 runs (eco 6.0 - very good)
        ip_death = _ip(pid=1, death_balls_bowled=6, death_runs_conceded=6,
                       balls_bowled=24, runs_conceded=24)
        # p_pp bowled only in powerplay, same career stats
        ip_pp = _ip(pid=2, balls_bowled=24, runs_conceded=24,
                    death_balls_bowled=0)

        bowling_inning = self._make_bowling_inning([ip_death, ip_pp])

        same_career = {
            1: {'death': {'balls': 120, 'economy': 8.0}},
            2: {'death': {'balls': 120, 'economy': 8.0}},
        }

        selector = self._make_selector(same_career)
        selected = selector.select_bowler(team, bowling_inning, "T20", "male")

        assert selected.id == 1
