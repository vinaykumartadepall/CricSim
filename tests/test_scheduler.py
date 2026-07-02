"""
Tests for fixture generation: round-robin, double round-robin, explicit lists,
and all playoff bracket formats.
"""

import random

import pytest

from simulator.tournament.config import (
    Fixture,
    PlayoffConfig,
    ScheduleConfig,
    TeamConfig,
    TournamentConfig,
    VenueConfig,
)
from simulator.tournament.scheduler import generate_fixtures, generate_playoffs


# ── Config helpers ─────────────────────────────────────────────────────────────

def _team(name, home_venue=None):
    return TeamConfig(
        name=name,
        short_name=name[:3].upper(),
        players=[],
        home_venue=home_venue,
    )


def _config(
    teams,
    schedule_type="round_robin",
    matches_per_pair=1,
    neutral_venues=True,
    venues=None,
    playoffs_fmt="none",
    playoffs_top_n=4,
):
    return TournamentConfig(
        tournament_name="Test Cup",
        format="T20",
        gender="male",
        season="2025",
        venues=[VenueConfig(name=v) for v in (venues or ["NeutralGround"])],
        teams=teams,
        schedule=ScheduleConfig(
            type=schedule_type,
            matches_per_pair=matches_per_pair,
            neutral_venues=neutral_venues,
        ),
        playoffs=PlayoffConfig(format=playoffs_fmt, top_n=playoffs_top_n),
    )


FOUR_TEAMS = [_team("Alpha"), _team("Beta"), _team("Gamma"), _team("Delta")]
EIGHT_TEAMS = [_team(f"T{i}") for i in range(1, 9)]


# ── Round-robin ────────────────────────────────────────────────────────────────

def test_round_robin_fixture_count():
    cfg = _config(FOUR_TEAMS)
    fixtures = generate_fixtures(cfg)
    # C(4,2) = 6
    assert len(fixtures) == 6


def test_round_robin_all_pairs_covered():
    cfg = _config(FOUR_TEAMS)
    fixtures = generate_fixtures(cfg)
    pairs = {frozenset([f.home, f.away]) for f in fixtures}
    assert len(pairs) == 6


def test_round_robin_no_self_fixtures():
    cfg = _config(FOUR_TEAMS)
    fixtures = generate_fixtures(cfg)
    for f in fixtures:
        assert f.home != f.away


def test_round_robin_match_numbers_assigned():
    cfg = _config(FOUR_TEAMS)
    fixtures = generate_fixtures(cfg)
    numbers = [f.match_number for f in fixtures]
    assert sorted(numbers) == list(range(1, 7))


# ── Double round-robin ─────────────────────────────────────────────────────────

def test_double_round_robin_fixture_count():
    cfg = _config(FOUR_TEAMS, schedule_type="double_round_robin")
    fixtures = generate_fixtures(cfg)
    # 4×3 = 12
    assert len(fixtures) == 12


def test_double_round_robin_each_pair_twice():
    cfg = _config(FOUR_TEAMS, schedule_type="double_round_robin")
    fixtures = generate_fixtures(cfg)
    # Each ordered pair (A,B) and (B,A) both appear
    pairs = [(f.home, f.away) for f in fixtures]
    for a, b in [("Alpha", "Beta"), ("Beta", "Alpha")]:
        assert (a, b) in pairs


def test_matches_per_pair_2_same_as_double():
    cfg1 = _config(FOUR_TEAMS, schedule_type="double_round_robin")
    cfg2 = _config(FOUR_TEAMS, matches_per_pair=2)
    assert len(generate_fixtures(cfg1)) == len(generate_fixtures(cfg2))


# ── Venue assignment ───────────────────────────────────────────────────────────

def test_neutral_venue_cycles():
    venues = ["Ground1", "Ground2", "Ground3"]
    cfg = _config(FOUR_TEAMS, venues=venues, neutral_venues=True)
    fixtures = generate_fixtures(cfg)
    assigned = [f.venue for f in fixtures]
    assert all(v in venues for v in assigned)


def test_home_venue_used_when_not_neutral():
    teams = [
        _team("Alpha", home_venue="AlphaGround"),
        _team("Beta",  home_venue="BetaGround"),
    ]
    cfg = _config(teams, neutral_venues=False)
    fixtures = generate_fixtures(cfg)
    for f in fixtures:
        expected = "AlphaGround" if f.home == "Alpha" else "BetaGround"
        assert f.venue == expected


# ── Explicit fixture list ──────────────────────────────────────────────────────

def test_explicit_fixture_list_used_as_is():
    explicit = [
        Fixture(home="Alpha", away="Beta",  venue="Ground1", match_number=1),
        Fixture(home="Gamma", away="Delta", venue="Ground2", match_number=2),
    ]
    cfg = TournamentConfig(
        tournament_name="Cup", format="T20", gender="male", season="2025",
        venues=[VenueConfig("Ground1"), VenueConfig("Ground2")],
        teams=FOUR_TEAMS,
        schedule=explicit,
        playoffs=PlayoffConfig(format="none"),
    )
    fixtures = generate_fixtures(cfg)
    assert len(fixtures) == 2
    assert fixtures[0].home == "Alpha"
    assert fixtures[1].home == "Gamma"


def test_explicit_fixture_match_numbers_auto_assigned():
    explicit = [
        Fixture(home="Alpha", away="Beta",  venue="G", match_number=0),
        Fixture(home="Gamma", away="Delta", venue="G", match_number=0),
    ]
    cfg = TournamentConfig(
        tournament_name="Cup", format="T20", gender="male", season="2025",
        venues=[VenueConfig("G")],
        teams=FOUR_TEAMS,
        schedule=explicit,
        playoffs=PlayoffConfig(format="none"),
    )
    fixtures = generate_fixtures(cfg)
    assert fixtures[0].match_number == 1
    assert fixtures[1].match_number == 2


# ── Seeded shuffle ────────────────────────────────────────────────────────────

def test_seeded_rng_produces_deterministic_order():
    cfg = _config(FOUR_TEAMS)
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    f1 = generate_fixtures(cfg, rng=rng1)
    f2 = generate_fixtures(cfg, rng=rng2)
    assert [(x.home, x.away) for x in f1] == [(x.home, x.away) for x in f2]


# ── Playoffs: generate_playoffs ───────────────────────────────────────────────

STANDINGS_8 = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
STANDINGS_4 = STANDINGS_8[:4]


def test_playoffs_none_returns_empty():
    cfg = _config(FOUR_TEAMS, playoffs_fmt="none")
    assert generate_playoffs(cfg, STANDINGS_4, 10) == []


def test_playoffs_two_teams():
    cfg = _config(FOUR_TEAMS, playoffs_fmt="two_teams", playoffs_top_n=2)
    fixtures = generate_playoffs(cfg, STANDINGS_4, 10)
    assert len(fixtures) == 1
    assert fixtures[0].home == "T1"
    assert fixtures[0].away == "T2"


def test_playoffs_semis_final_structure():
    cfg = _config(FOUR_TEAMS, playoffs_fmt="semis_final", playoffs_top_n=4)
    fixtures = generate_playoffs(cfg, STANDINGS_4, 10)
    labels = [f.match_label for f in fixtures]
    assert labels == ["Semi-final 1", "Semi-final 2", "Final"]
    # 1 vs 4 and 2 vs 3
    assert fixtures[0].home == "T1" and fixtures[0].away == "T4"
    assert fixtures[1].home == "T2" and fixtures[1].away == "T3"
    # Final is TBD until resolved
    assert fixtures[2].home == "TBD"


def test_playoffs_ipl_structure():
    cfg = _config(FOUR_TEAMS, playoffs_fmt="ipl", playoffs_top_n=4)
    fixtures = generate_playoffs(cfg, STANDINGS_4, 10)
    labels = [f.match_label for f in fixtures]
    assert labels == ["Qualifier 1", "Eliminator", "Qualifier 2", "Final"]
    assert fixtures[0].home == "T1" and fixtures[0].away == "T2"
    assert fixtures[1].home == "T3" and fixtures[1].away == "T4"


def test_playoffs_quarters_semis_final_structure():
    cfg = _config(EIGHT_TEAMS, playoffs_fmt="quarters_semis_final", playoffs_top_n=8)
    fixtures = generate_playoffs(cfg, STANDINGS_8, 20)
    labels = [f.match_label for f in fixtures]
    assert labels[:4] == ["QF 1", "QF 2", "QF 3", "QF 4"]
    assert labels[4:6] == ["SF 1", "SF 2"]
    assert labels[6] == "Final"
    assert len(fixtures) == 7


def test_playoffs_match_numbers_sequential():
    cfg = _config(FOUR_TEAMS, playoffs_fmt="semis_final", playoffs_top_n=4)
    fixtures = generate_playoffs(cfg, STANDINGS_4, start_match_number=10)
    numbers = [f.match_number for f in fixtures]
    assert numbers == [10, 11, 12]
