"""
Fixture schedule generation for a tournament.

Supported schedule types:
  round_robin        — every team plays every other team once
  double_round_robin — every team plays every other team twice (home/away swapped)

Venue assignment:
  - If neutral_venues=True (default): cycle through the venues list
  - If neutral_venues=False: home team plays at their home_venue (falls back to cycling)
"""

from __future__ import annotations

import random
from typing import List, Optional

from simulator.tournament.config import Fixture, ScheduleConfig, TeamConfig, TournamentConfig


def generate_fixtures(
    config: TournamentConfig,
    rng: Optional[random.Random] = None,
) -> List[Fixture]:
    """Return a randomly shuffled list of fixtures for the group stage."""
    schedule = config.schedule

    if isinstance(schedule, list):
        # Explicit fixture list provided in config — use as-is
        for i, f in enumerate(schedule):
            if f.match_number == 0:
                f.match_number = i + 1
        return schedule

    # Auto-generate from ScheduleConfig
    pairs = _all_pairs(config.teams, schedule)
    (rng or random).shuffle(pairs)

    fixtures: List[Fixture] = []
    venue_cycle = 0
    for i, (home, away) in enumerate(pairs):
        venue = _pick_venue(home, away, config, schedule.neutral_venues, venue_cycle)
        venue_cycle += 1
        fixtures.append(Fixture(
            home=home.name,
            away=away.name,
            venue=venue,
            match_number=i + 1,
        ))
    return fixtures


def generate_playoffs(
    config: TournamentConfig,
    standings: List[str],
    start_match_number: int,
) -> List[Fixture]:
    """
    Generate playoff fixtures from the final group-stage standings.
    standings: team names ordered by rank (index 0 = 1st place).
    Returns an ordered list of playoff fixtures.
    """
    fmt = config.playoffs.format
    top_n = config.playoffs.top_n
    qualified = standings[:top_n]
    venues = config.venue_names
    neutral = venues[0] if venues else None

    if fmt == "none" or not qualified:
        return []

    if fmt == "two_teams":
        return [Fixture(home=qualified[0], away=qualified[1], venue=neutral,
                        match_number=start_match_number)]

    if fmt == "semis_final":
        # 1v4, 2v3 → winners meet in final
        return [
            Fixture(home=qualified[0], away=qualified[3], venue=neutral,
                    match_number=start_match_number,     match_label="Semi-final 1"),
            Fixture(home=qualified[1], away=qualified[2], venue=neutral,
                    match_number=start_match_number + 1, match_label="Semi-final 2"),
            Fixture(home="TBD", away="TBD", venue=neutral,
                    match_number=start_match_number + 2, match_label="Final"),
        ]

    if fmt == "ipl":
        # Qualifier 1: 1v2 (winner → final; loser → Q2)
        # Eliminator: 3v4 (winner → Q2; loser eliminated)
        # Qualifier 2: loser(Q1) vs winner(Elim) → winner → final
        return [
            Fixture(home=qualified[0], away=qualified[1], venue=neutral,
                    match_number=start_match_number,     match_label="Qualifier 1"),
            Fixture(home=qualified[2], away=qualified[3], venue=neutral,
                    match_number=start_match_number + 1, match_label="Eliminator"),
            Fixture(home="TBD", away="TBD", venue=neutral,
                    match_number=start_match_number + 2, match_label="Qualifier 2"),
            Fixture(home="TBD", away="TBD", venue=neutral,
                    match_number=start_match_number + 3, match_label="Final"),
        ]

    if fmt == "quarters_semis_final":
        # Top 8: 1v8, 2v7, 3v6, 4v5 → winners → semis → final
        q = qualified[:8]
        while len(q) < 8:
            q.append("TBD")
        return [
            Fixture(home=q[0], away=q[7], venue=neutral,
                    match_number=start_match_number,     match_label="QF 1"),
            Fixture(home=q[1], away=q[6], venue=neutral,
                    match_number=start_match_number + 1, match_label="QF 2"),
            Fixture(home=q[2], away=q[5], venue=neutral,
                    match_number=start_match_number + 2, match_label="QF 3"),
            Fixture(home=q[3], away=q[4], venue=neutral,
                    match_number=start_match_number + 3, match_label="QF 4"),
            Fixture(home="TBD", away="TBD", venue=neutral,
                    match_number=start_match_number + 4, match_label="SF 1"),
            Fixture(home="TBD", away="TBD", venue=neutral,
                    match_number=start_match_number + 5, match_label="SF 2"),
            Fixture(home="TBD", away="TBD", venue=neutral,
                    match_number=start_match_number + 6, match_label="Final"),
        ]

    return []


# ── Internals ──────────────────────────────────────────────────────────────────

def _all_pairs(teams: List[TeamConfig], schedule: ScheduleConfig):
    """Generate all (home, away) pairs according to the schedule type."""
    if schedule.type == "two_group_hybrid":
        return _two_group_hybrid_pairs(teams, schedule)

    pairs = []
    n = len(teams)
    for i in range(n):
        for j in range(i + 1, n):
            pairs.append((teams[i], teams[j]))
            if schedule.type == "double_round_robin" or schedule.matches_per_pair >= 2:
                pairs.append((teams[j], teams[i]))
    return pairs


def _two_group_hybrid_pairs(teams: List[TeamConfig], schedule: ScheduleConfig):
    """
    Two-group hybrid schedule (e.g. IPL 2022+).
    Teams in the same group play each other `within_matches_per_pair` times.
    Teams across groups play each other `cross_matches_per_pair` times (home/away alternated).
    Any team not found in the groups config is treated as group 0.
    """
    group_of: dict = {}
    for idx, group_names in enumerate(schedule.groups or []):
        for name in group_names:
            group_of[name] = idx

    pairs = []
    n = len(teams)
    for i in range(n):
        for j in range(i + 1, n):
            gi = group_of.get(teams[i].name, 0)
            gj = group_of.get(teams[j].name, 0)
            if gi == gj:
                for _ in range(schedule.within_matches_per_pair):
                    pairs.append((teams[i], teams[j]))
            else:
                for k in range(schedule.cross_matches_per_pair):
                    if k % 2 == 0:
                        pairs.append((teams[i], teams[j]))
                    else:
                        pairs.append((teams[j], teams[i]))
    return pairs


def _pick_venue(
    home: TeamConfig,
    away: TeamConfig,
    config: TournamentConfig,
    neutral_venues: bool,
    cycle_idx: int,
) -> Optional[str]:
    venues = config.venue_names
    if not neutral_venues and home.home_venue:
        return home.home_venue
    if venues:
        return venues[cycle_idx % len(venues)]
    return None


