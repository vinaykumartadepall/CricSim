"""
Tests for:
  - log_context ContextVar isolation and nesting
  - StatsRepository singleton connection
  - get_batter_death_stats derivation from precomputed cache (no DB)
  - get_bowler_phase_stats derivation from precomputed cache (no DB)
"""
import pytest
import threading
import db.stats_repository as sr_mod
from db.stats_repository import StatsRepository, _PRECOMPUTED_CACHE
from simulator.logger import (
    _sim_id_var, _match_id_var, log_context,
    get_logger, configure_logger, set_log_level, get_current_log_level,
)


# ---------------------------------------------------------------------------
# log_context
# ---------------------------------------------------------------------------

class TestLogContext:

    def test_sets_sim_id_in_scope(self):
        with log_context(sim_id="abc"):
            assert _sim_id_var.get('') == "abc"

    def test_restores_sim_id_after_scope(self):
        _sim_id_var.set('')
        with log_context(sim_id="abc"):
            pass
        assert _sim_id_var.get('') == ''

    def test_does_not_clobber_match_id_when_only_sim_set(self):
        _match_id_var.set(7)
        with log_context(sim_id="xyz"):
            assert _match_id_var.get(0) == 7
        _match_id_var.set(0)

    def test_does_not_clobber_sim_id_when_only_match_set(self):
        _sim_id_var.set("outer-sim")
        with log_context(match_id=3):
            assert _sim_id_var.get('') == "outer-sim"
        _sim_id_var.set('')

    def test_nested_contexts_restore_outer_values(self):
        with log_context(sim_id="outer", match_id=1):
            with log_context(sim_id="inner", match_id=2):
                assert _sim_id_var.get('') == "inner"
                assert _match_id_var.get(0) == 2
            assert _sim_id_var.get('') == "outer"
            assert _match_id_var.get(0) == 1

    def test_context_restored_on_exception(self):
        _sim_id_var.set("before")
        try:
            with log_context(sim_id="during"):
                raise ValueError("boom")
        except ValueError:
            pass
        assert _sim_id_var.get('') == "before"
        _sim_id_var.set('')


# ---------------------------------------------------------------------------
# StatsRepository singleton
# ---------------------------------------------------------------------------

class TestStatsRepositorySingleton:

    def setup_method(self):
        # Reset singleton so we test the double-checked init path cleanly.
        # We DON'T actually open a DB; just verify the class-level sharing.
        self._original_conn = StatsRepository._conn

    def teardown_method(self):
        StatsRepository._conn = self._original_conn

    def test_two_instances_share_same_conn_object(self):
        # Plant a sentinel so we don't need a real DB
        sentinel = object()
        StatsRepository._conn = sentinel

        r1 = StatsRepository.__new__(StatsRepository)
        r1.conn = StatsRepository._conn
        r2 = StatsRepository.__new__(StatsRepository)
        r2.conn = StatsRepository._conn

        assert r1.conn is r2.conn is sentinel

    def test_new_instance_reuses_existing_conn(self):
        sentinel = object()
        StatsRepository._conn = sentinel

        # Constructing normally should not replace an existing connection
        r = StatsRepository()
        assert r.conn is sentinel


# ---------------------------------------------------------------------------
# get_batter_death_stats — from precomputed cache, no DB
# ---------------------------------------------------------------------------

class TestBatterDeathStats:

    def setup_method(self):
        # Stash and clear relevant cache keys so tests are isolated
        self._saved = {}
        for k in list(_PRECOMPUTED_CACHE.keys()):
            if k[0] in ('pos', 'batter_death_stats'):
                self._saved[k] = _PRECOMPUTED_CACHE.pop(k)

    def teardown_method(self):
        for k in list(_PRECOMPUTED_CACHE.keys()):
            if k[0] in ('pos', 'batter_death_stats'):
                del _PRECOMPUTED_CACHE[k]
        _PRECOMPUTED_CACHE.update(self._saved)

    def _make_repo(self):
        r = StatsRepository.__new__(StatsRepository)
        r.conn = None
        return r

    def _seed_phase_cache(self, match_format, stat_type, entries):
        """entries: {pid: (probs_dict, era, balls)}"""
        _PRECOMPUTED_CACHE[('pos', match_format, stat_type)] = entries

    def test_returns_empty_for_unknown_player(self):
        self._seed_phase_cache('T20', 'phase_death1', {})
        self._seed_phase_cache('T20', 'phase_death2', {})
        repo = self._make_repo()
        assert repo.get_batter_death_stats([999], 'T20') == {}

    def test_death_sr_computed_correctly(self):
        # Player 1: 50% dot (rb=0), 50% four (rb=4); 10 balls
        probs = {
            (0, 0, 'Dot', None): 0.5,
            (4, 0, 'Runs', None): 0.5,
        }
        self._seed_phase_cache('T20', 'phase_death1', {1: (probs, None, 10)})
        self._seed_phase_cache('T20', 'phase_death2', {})
        repo = self._make_repo()
        result = repo.get_batter_death_stats([1], 'T20')
        assert 1 in result
        # expected runs = 0*0.5 + 4*0.5 = 2.0; non_extra_prob = 1.0; SR = 200
        assert result[1]['death_sr'] == pytest.approx(200.0)
        assert result[1]['boundary_rate'] == pytest.approx(0.5)

    def test_skips_players_with_fewer_than_6_balls(self):
        probs = {(4, 0, 'Runs', None): 1.0}
        self._seed_phase_cache('T20', 'phase_death1', {2: (probs, None, 5)})
        self._seed_phase_cache('T20', 'phase_death2', {})
        repo = self._make_repo()
        assert repo.get_batter_death_stats([2], 'T20') == {}

    def test_higher_ball_count_phase_wins_on_merge(self):
        probs_low  = {(0, 0, 'Dot', None): 1.0}
        probs_high = {(6, 0, 'Runs', None): 1.0}
        self._seed_phase_cache('T20', 'phase_death1', {3: (probs_low,  None, 8)})
        self._seed_phase_cache('T20', 'phase_death2', {3: (probs_high, None, 20)})
        repo = self._make_repo()
        result = repo.get_batter_death_stats([3], 'T20')
        # death2 has more balls; its death_sr = 600
        assert result[3]['death_sr'] == pytest.approx(600.0)

    def test_extras_excluded_from_non_extra_prob(self):
        probs = {
            (0, 1, 'Extras', 'Wide'):  0.3,
            (0, 0, 'Dot',   None):     0.4,
            (4, 0, 'Runs',  None):     0.3,
        }
        self._seed_phase_cache('T20', 'phase_death1', {4: (probs, None, 10)})
        self._seed_phase_cache('T20', 'phase_death2', {})
        repo = self._make_repo()
        result = repo.get_batter_death_stats([4], 'T20')
        # non_extra_prob = 0.4 + 0.3 = 0.7
        # exp_rb = 0*0.4 + 4*0.3 = 1.2 (extras rb=0 included in numerator)
        # death_sr = (1.2 / 0.7) * 100
        assert result[4]['death_sr'] == pytest.approx((1.2 / 0.7) * 100.0)


# ---------------------------------------------------------------------------
# get_bowler_phase_stats — from precomputed cache, no DB
# ---------------------------------------------------------------------------

class TestBowlerPhaseStats:

    def setup_method(self):
        self._saved = {}
        for k in list(_PRECOMPUTED_CACHE.keys()):
            if k[0] in ('pos', 'bowler_phase_stats'):
                self._saved[k] = _PRECOMPUTED_CACHE.pop(k)

    def teardown_method(self):
        for k in list(_PRECOMPUTED_CACHE.keys()):
            if k[0] in ('pos', 'bowler_phase_stats'):
                del _PRECOMPUTED_CACHE[k]
        _PRECOMPUTED_CACHE.update(self._saved)

    def _make_repo(self):
        r = StatsRepository.__new__(StatsRepository)
        r.conn = None
        return r

    def _seed(self, match_format, stat_type, entries):
        _PRECOMPUTED_CACHE[('pos', match_format, stat_type)] = entries

    def _clear_phase_seeds(self, match_format):
        phase_types = sr_mod._PHASE_STAT_TYPES.get(match_format, [])
        for st in phase_types:
            _PRECOMPUTED_CACHE.setdefault(('pos', match_format, st), {})

    def test_returns_empty_for_unknown_player(self):
        self._clear_phase_seeds('T20')
        repo = self._make_repo()
        assert repo.get_bowler_phase_stats([999], 'T20') == {}

    def test_economy_computed_correctly(self):
        # All dot balls — economy should be 0
        probs = {(0, 0, 'Dot', None): 1.0}
        self._seed('T20', 'phase_pp1', {5: (probs, None, 10)})
        # ensure other phase keys don't interfere
        for st in ('phase_pp2', 'phase_mid1', 'phase_mid2', 'phase_death1', 'phase_death2'):
            _PRECOMPUTED_CACHE.setdefault(('pos', 'T20', st), {})
        repo = self._make_repo()
        result = repo.get_bowler_phase_stats([5], 'T20')
        assert 5 in result
        assert 'powerplay' in result[5]
        assert result[5]['powerplay']['economy'] == pytest.approx(0.0)

    def test_wicket_rate_computed_correctly(self):
        probs = {
            (0, 0, 'Dot',    None):     0.6,
            (0, 0, 'Wicket', 'bowled'): 0.4,
        }
        self._seed('T20', 'phase_death1', {6: (probs, None, 15)})
        for st in ('phase_pp1', 'phase_pp2', 'phase_mid1', 'phase_mid2', 'phase_death2'):
            _PRECOMPUTED_CACHE.setdefault(('pos', 'T20', st), {})
        repo = self._make_repo()
        result = repo.get_bowler_phase_stats([6], 'T20')
        assert result[6]['death']['wicket_rate'] == pytest.approx(0.4)

    def test_broad_phase_mapped_correctly(self):
        # phase_pp2 → 'powerplay'; phase_mid1 → 'middle'; phase_death2 → 'death'
        probs_pp  = {(0, 0, 'Dot', None): 1.0}
        probs_mid = {(1, 0, 'Runs', None): 1.0}
        probs_d   = {(0, 0, 'Wicket', 'caught'): 1.0}
        self._seed('T20', 'phase_pp2',    {7: (probs_pp,  None, 10)})
        self._seed('T20', 'phase_mid1',   {7: (probs_mid, None, 10)})
        self._seed('T20', 'phase_death2', {7: (probs_d,   None, 10)})
        for st in ('phase_pp1', 'phase_mid2', 'phase_death1'):
            _PRECOMPUTED_CACHE.setdefault(('pos', 'T20', st), {})
        repo = self._make_repo()
        result = repo.get_bowler_phase_stats([7], 'T20')
        assert set(result[7].keys()) == {'powerplay', 'middle', 'death'}

    def test_higher_ball_count_phase_wins_on_same_broad_bucket(self):
        probs_low  = {(0, 0, 'Dot', None): 1.0}   # economy 0
        probs_high = {(6, 0, 'Runs', None): 1.0}  # economy 36
        self._seed('T20', 'phase_death1', {8: (probs_low,  None, 8)})
        self._seed('T20', 'phase_death2', {8: (probs_high, None, 20)})
        for st in ('phase_pp1', 'phase_pp2', 'phase_mid1', 'phase_mid2'):
            _PRECOMPUTED_CACHE.setdefault(('pos', 'T20', st), {})
        repo = self._make_repo()
        result = repo.get_bowler_phase_stats([8], 'T20')
        # death2 has 20 balls > death1's 8 balls; economy should be 6*6=36
        assert result[8]['death']['economy'] == pytest.approx(36.0)
