"""
Shared utilities for all historical ball-outcome prediction strategies.
"""

import time
from typing import List

from simulator.entities.match import SimulationMatch

# Approximate empirical cricket delivery distribution used when no historical DB data is available.
# Probabilities sum to 1.0. Derived from typical first-class / List-A aggregates.
BASELINE_FALLBACK: dict = {
    (0, 0, 'Dot',    None):      0.320,
    (1, 0, 'Runs',   None):      0.250,
    (2, 0, 'Runs',   None):      0.072,
    (4, 0, 'Runs',   None):      0.100,
    (6, 0, 'Runs',   None):      0.050,
    (0, 1, 'Extras', 'Wide'):    0.060,
    (0, 1, 'Extras', 'Noball'):  0.020,
    (0, 1, 'Extras', 'Legbyes'): 0.010,
    (0, 1, 'Extras', 'Byes'):    0.010,
    (0, 0, 'Wicket', 'caught'):  0.050,
    (0, 0, 'Wicket', 'bowled'):  0.020,
    (0, 0, 'Wicket', 'lbw'):     0.023,
    (0, 0, 'Wicket', 'run out'): 0.015,
}


def collect_player_ids(match: SimulationMatch) -> List[int]:
    """Returns all player IDs from both teams."""
    ids = []
    if match.home_team:
        ids.extend(p.id for p in match.home_team.players)
    if match.away_team:
        ids.extend(p.id for p in match.away_team.players)
    return ids


def timed_load(log, label: str, fn, *args, **kwargs):
    """Calls fn(*args, **kwargs), logs elapsed time, and returns the result."""
    t = time.perf_counter()
    result = fn(*args, **kwargs)
    log.info("[Model]   %-40s  %.2fs", label, time.perf_counter() - t)
    return result


def load_venue_distribution(repo, match: SimulationMatch, match_format: str,
                            gender: str, timed_fn, log) -> dict:
    """
    Loads venue distribution, falling back to country distribution when the
    specific venue has no recorded data. Returns an empty dict when no venue is set.
    """
    venue = getattr(match, 'venue', None)
    if not venue or not venue.id:
        return {}

    cache = timed_fn("venue_distribution", repo.get_venue_distribution,
                     venue.id, match_format, gender)
    if not cache and getattr(venue, 'country', None):
        cache = timed_fn("country_distribution", repo.get_country_distribution,
                         venue.country, match_format, gender)
        log.info("[Model] Venue absent — using country distribution (%s)", venue.country)
    return cache


def load_tournament_distribution(repo, match: SimulationMatch, timed_fn) -> dict:
    """Loads tournament distribution, returning empty dict when no tournament is set."""
    tournament = getattr(match, 'tournament', None)
    if not tournament or not tournament.id:
        return {}
    return timed_fn("tournament_distribution", repo.get_tournament_distribution,
                    tournament.id)
