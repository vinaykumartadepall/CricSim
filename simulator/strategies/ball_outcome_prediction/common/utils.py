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


def apply_free_hit_modifier(weights: list, ordered_keys: list) -> list:
    """
    Applies a free-hit scoring adjustment to an already-computed probability weight list.

    Free hits produce ~40% boundary rate (vs ~17% on normal balls) because batters swing
    hard knowing they cannot be dismissed by most wicket types.  This modifier is applied
    on top of a batter-centric distribution (matchup weight nullified upstream), so the
    two effects compound.  Wickets (non run-out) are also cancelled by InningsSimulator;
    the near-zero multiplier here reduces wasted resamples.

    Multipliers are calibrated to produce ~40% boundary rate on free hits (vs ~17% baseline).
    The distribution is also computed with matchup weight nullified upstream (batter-centric),
    so these multipliers act on a profile that already reflects the batter's attacking tendencies.

      6s: ×4.0  |  4s: ×3.0  |  1–3 runs: ×1.0  |  dots: ×0.3
      wickets (non run-out): ×0.05  |  run-out / extras: ×1.0

    The result must be renormalised by the caller.
    """
    adjusted = []
    for w, key in zip(weights, ordered_keys):
        runs_batter, _, outcome_type, outcome_kind = key
        if runs_batter >= 6:
            m = 4.0
        elif runs_batter == 4:
            m = 3.0
        elif runs_batter in (1, 2, 3):
            m = 1.0
        elif outcome_type == 'Dot':
            m = 0.3
        elif outcome_type == 'Wicket' and outcome_kind != 'run out':
            m = 0.05
        else:
            m = 1.0
        adjusted.append(w * m)
    return adjusted


def load_tournament_distribution(repo, match: SimulationMatch, timed_fn) -> dict:
    """Loads tournament distribution, returning empty dict when no tournament is set."""
    tournament = getattr(match, 'tournament', None)
    if not tournament or not tournament.id:
        return {}
    return timed_fn("tournament_distribution", repo.get_tournament_distribution,
                    tournament.id)
