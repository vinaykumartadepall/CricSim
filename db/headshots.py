"""
Single source of truth for turning a player's cricinfo_id into their ESPN
headshot URL. db/player_repository.py and db/squad_repository.py each had
their own copy of this exact same one-liner before this module existed -
import from here instead of adding a third (or fourth, fifth...) copy.
"""

from __future__ import annotations


def headshot_url(cricinfo_id) -> str | None:
    if not cricinfo_id:
        return None
    return f"https://a.espncdn.com/i/headshots/cricket/players/full/{cricinfo_id}.png"


def with_headshot_url(row: dict) -> dict:
    """Replace a raw cricinfo_id with a ready-to-use headshot_url. Call this
    right before a row leaves the server as an API response - not any
    earlier - so anything persisted before that point (e.g. leaderboard
    caching in api/worker.py) stores the small stable id rather than a URL
    string baked to today's CDN path format. If that path ever changes, every
    already-cached row heals for free the next time it's read, instead of
    needing every cache entry regenerated."""
    row = dict(row)
    row['headshot_url'] = headshot_url(row.pop('cricinfo_id', None))
    return row
