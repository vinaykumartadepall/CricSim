"""
Single source for the human-readable suffix describing how a playoff
tiebreak decided a knockout fixture's winner ("India advanced on
first-innings lead", "India advanced due to better group stage finish").

Used by both TournamentEngine (simulator/tournament/engine.py - the live
in-memory match.result.description, shown in CLI output) and
_build_result_description (simulator/serializers/match.py - reconstructs the
description from persisted simulation.matches columns for every API
response), so the wording can only drift by editing this one function - the
exact class of bug that let the caught-and-bowled commentary text disagree
with the scorecard before dismissals.py consolidated it the same way.

The frontend (frontend/src/lib/parseResult.ts) still needs its own regex to
parse this text back out of the API response - that duplication is inherent
to the description being a prose string rather than a structured field, the
same situation the pre-existing "X won Super Over" pattern is already in.
"""

from __future__ import annotations


def describe_tiebreak_winner(reason: str, winner: str) -> str:
    """reason: 'first_innings_lead' | 'group_stage_rank' | 'super_over_tied_rank'."""
    if reason == "first_innings_lead":
        return f"{winner} advanced on first-innings lead"
    return f"{winner} advanced due to better group stage finish"
