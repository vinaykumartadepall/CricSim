"""
Unit tests for T20HistoricalBowlingStrategy._eligible.

The key invariants:
  1. Players with avg_overs_per_match >= MIN_AVG_OVERS are the primary candidate list.
  2. Players below the threshold (or absent from workload_cache) are excluded from
     the primary list — they only appear in the fallback when NO genuine bowler exists.
  3. The current bowler is always excluded.
  4. When the primary list is non-empty, only those players are returned (not the full
     under-quota roster).

Regression: before the workload query was changed to cover all T20 (not just
international), domestic-only players (e.g., IPL-only bowlers) would have no entry
in workload_cache and therefore be silently excluded from the primary candidate list
even when other genuine bowlers existed.  The fix ensures that workload_cache is
populated from all T20 data, so domestic bowlers have avg_overs_per_match >= 1.0
and appear correctly in the primary list.
"""
import pytest
from unittest.mock import MagicMock

from simulator.strategies.bowling.historical.strategies import T20HistoricalBowlingStrategy
from simulator.entities.inning_player import InningPlayer
from simulator.entities.player import Player


# ── helpers ───────────────────────────────────────────────────────────────────

def _player(pid):
    return Player(id=pid, name=f"P{pid}")


def _ip(pid, balls_bowled=0):
    ip = InningPlayer(player=_player(pid))
    ip.balls_bowled = balls_bowled
    return ip


def _make_strategy(workload_data: dict) -> T20HistoricalBowlingStrategy:
    """Create a T20 strategy with only workload_cache populated (enough for _eligible)."""
    s = object.__new__(T20HistoricalBowlingStrategy)
    s.workload_cache = workload_data
    return s


def _make_match():
    return MagicMock()


# ── tests ────────────────────────────────────────────────────────────────────

class TestT20Eligibility:
    QUOTA = 4  # T20HistoricalBowlingStrategy._quota()

    def _eligible(self, strategy, inning_players, current_bowler):
        team = MagicMock()
        team.inning_players = inning_players
        return strategy._eligible(team, current_bowler, _make_match())

    def test_genuine_bowlers_are_primary_list(self):
        """Players with avg >= MIN_AVG_OVERS appear in the primary candidate list."""
        s = _make_strategy({
            1: {'avg_overs_per_match': 3.5},
            2: {'avg_overs_per_match': 2.0},
        })
        ip1, ip2, ip3 = _ip(1), _ip(2), _ip(3)
        result = self._eligible(s, [ip1, ip2, ip3], current_bowler=None)
        assert ip1 in result
        assert ip2 in result

    def test_below_threshold_excluded_from_primary(self):
        """avg_overs < 1.0 → excluded when genuine bowlers exist."""
        s = _make_strategy({
            1: {'avg_overs_per_match': 3.5},
            2: {'avg_overs_per_match': 0.3},   # part-timer
        })
        ip1, ip2 = _ip(1), _ip(2)
        result = self._eligible(s, [ip1, ip2], current_bowler=None)
        assert ip2 not in result

    def test_not_in_cache_excluded_from_primary_when_others_exist(self):
        """
        Player not in workload_cache → defaults to avg 0.0 → excluded from primary.
        This documents the pre-fix behavior for domestic-only players when other
        international bowlers DID have cache entries.
        """
        s = _make_strategy({
            1: {'avg_overs_per_match': 3.5},
            # pid 2 has no entry (simulates pre-fix domestic-only state)
        })
        ip1, ip2 = _ip(1), _ip(2)
        result = self._eligible(s, [ip1, ip2], current_bowler=None)
        assert ip2 not in result

    def test_domestic_bowler_included_when_cache_has_data(self):
        """
        Post-fix: domestic-only bowler NOW appears in workload_cache (from all-T20 query).
        If their avg >= MIN_AVG_OVERS, they are in the primary list.
        """
        s = _make_strategy({
            1: {'avg_overs_per_match': 3.5},
            2: {'avg_overs_per_match': 2.8},   # was absent pre-fix; now loaded from all T20
        })
        ip1, ip2 = _ip(1), _ip(2)
        result = self._eligible(s, [ip1, ip2], current_bowler=None)
        assert ip2 in result

    def test_current_bowler_always_excluded(self):
        s = _make_strategy({1: {'avg_overs_per_match': 3.5}, 2: {'avg_overs_per_match': 3.0}})
        ip1, ip2 = _ip(1), _ip(2)
        result = self._eligible(s, [ip1, ip2], current_bowler=ip1)
        assert ip1 not in result
        assert ip2 in result

    def test_quota_exhausted_player_excluded(self):
        """Player who has already bowled quota overs is excluded regardless of workload."""
        s = _make_strategy({1: {'avg_overs_per_match': 3.5}, 2: {'avg_overs_per_match': 3.0}})
        ip1 = _ip(1, balls_bowled=self.QUOTA * 6)  # used all 4 overs
        ip2 = _ip(2)
        result = self._eligible(s, [ip1, ip2], current_bowler=None)
        assert ip1 not in result

    def test_fallback_to_all_under_quota_when_no_genuine_bowler(self):
        """If no player meets the workload threshold, all under-quota players are returned."""
        s = _make_strategy({
            1: {'avg_overs_per_match': 0.2},
            2: {'avg_overs_per_match': 0.1},
        })
        ip1, ip2 = _ip(1), _ip(2)
        result = self._eligible(s, [ip1, ip2], current_bowler=None)
        result_ids = {ip.id for ip in result}
        assert result_ids == {1, 2}

    def test_fallback_excludes_current_bowler(self):
        """Even in fallback mode, the current bowler is excluded."""
        s = _make_strategy({})  # empty cache → everyone is below threshold
        ip1, ip2, ip3 = _ip(1), _ip(2), _ip(3)
        result = self._eligible(s, [ip1, ip2, ip3], current_bowler=ip1)
        result_ids = {ip.id for ip in result}
        assert 1 not in result_ids
        assert {2, 3}.issubset(result_ids)

    def test_all_players_present_with_full_squad_of_genuine_bowlers(self):
        """Typical match: 5 dedicated bowlers all in cache with avg >= 1.0."""
        pids = [10, 20, 30, 40, 50]
        workload = {pid: {'avg_overs_per_match': float(i + 2)} for i, pid in enumerate(pids)}
        s = _make_strategy(workload)
        ips = [_ip(pid) for pid in pids]
        current = ips[0]
        result = self._eligible(s, ips, current_bowler=current)
        result_ids = {ip.id for ip in result}
        assert result_ids == set(pids) - {pids[0]}
