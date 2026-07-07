"""
Tests for LimitedOversEngine._nrr_summary() — the per-team (runs, NRR-adjusted
balls) summary used to feed the live points table. Verifies the ICC all-out
rule (MatchRules.nrr_adjusted_balls) is actually applied here, which is the
root fix for the NRR bug: the live tournament engine used to credit only
balls actually faced, disagreeing with the (already-correct) results-page
display and producing wrong real playoff standings.

Only _nrr_summary's inputs matter (self.match.innings[0/1], overs_per_innings),
so a lightweight SimpleNamespace stand-in is used instead of constructing a
full LimitedOversEngine (which needs strategies, loggers, etc. this method
never touches).
"""
from types import SimpleNamespace

from simulator.engines.limited_overs_engine import LimitedOversEngine


def _team(name, runs, balls, wickets):
    return SimpleNamespace(batting_team=SimpleNamespace(
        name=name, total_runs=runs, total_balls=balls, total_wickets=wickets,
    ))


def test_all_out_side_credited_full_overs_quota():
    fake_self = SimpleNamespace(
        match=SimpleNamespace(
            overs_per_innings=20,
            innings=[_team("Alpha", 106, 99, 10), _team("Beta", 107, 95, 4)],
        )
    )
    summary = LimitedOversEngine._nrr_summary(fake_self)
    # Bowled out in 99 balls (16.3 overs) of a 20-over innings -> credited 120.
    assert summary["Alpha"] == (106, 120)
    # Not all out -> actual balls faced, unchanged.
    assert summary["Beta"] == (107, 95)


def test_side_using_full_quota_unaffected():
    fake_self = SimpleNamespace(
        match=SimpleNamespace(
            overs_per_innings=20,
            innings=[_team("Alpha", 181, 120, 7), _team("Beta", 164, 114, 10)],
        )
    )
    summary = LimitedOversEngine._nrr_summary(fake_self)
    assert summary["Alpha"] == (181, 120)
    assert summary["Beta"] == (164, 120)  # all out but already had the full quota


def test_matches_hand_verified_rajasthan_royals_totals():
    # Same 14-match aggregate cross-checked by hand in conversation: correctly
    # adjusted totals give balls_for=1622 (270.3333 ov), balls_against=1636
    # (272.6667 ov) — reproduced here at the per-innings level for two of
    # those matches to pin the adjustment logic itself, not just the totals.
    fake_self = SimpleNamespace(
        match=SimpleNamespace(
            overs_per_innings=20,
            # Match vs KKR: KKR bowled out 202 in 19.3 overs (117 balls) -> credited 120.
            # RR bowled out 166 in 19.5 overs (119 balls) -> credited 120.
            innings=[_team("Rajasthan Royals", 166, 119, 10), _team("KKR", 202, 117, 10)],
        )
    )
    summary = LimitedOversEngine._nrr_summary(fake_self)
    assert summary["Rajasthan Royals"] == (166, 120)
    assert summary["KKR"] == (202, 120)
