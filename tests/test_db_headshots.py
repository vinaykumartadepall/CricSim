"""
db/headshots.py - single source of truth for deriving a player's ESPN
headshot URL from their cricinfo_id, previously duplicated verbatim in
db/player_repository.py and db/squad_repository.py.
"""
from db.headshots import headshot_url, with_headshot_url


class TestHeadshotUrl:
    def test_builds_espn_cdn_url_from_cricinfo_id(self):
        assert headshot_url(34102) == "https://a.espncdn.com/i/headshots/cricket/players/full/34102.png"

    def test_none_when_cricinfo_id_missing(self):
        assert headshot_url(None) is None

    def test_none_when_cricinfo_id_falsy(self):
        assert headshot_url(0) is None
        assert headshot_url("") is None


class TestWithHeadshotUrl:
    """The row-conversion helper - applied at API-response-build time (not
    before, e.g. not at cache-write time) so persisted data (like
    simulation.leaderboard_cache) stores the raw cricinfo_id, not a URL
    string baked to today's CDN path."""

    def test_replaces_cricinfo_id_with_headshot_url(self):
        row = {"player": "Virat Kohli", "cricinfo_id": 253802}
        out = with_headshot_url(row)
        assert out["headshot_url"] == "https://a.espncdn.com/i/headshots/cricket/players/full/253802.png"
        assert "cricinfo_id" not in out
        assert out["player"] == "Virat Kohli"

    def test_missing_cricinfo_id_key_becomes_none_not_a_crash(self):
        """Old cache entries written before cricinfo_id existed on this row
        at all - must degrade to a missing photo, not a KeyError."""
        row = {"player": "Anonymous Player"}
        out = with_headshot_url(row)
        assert out["headshot_url"] is None

    def test_does_not_mutate_the_input_row(self):
        row = {"player": "Virat Kohli", "cricinfo_id": 253802}
        with_headshot_url(row)
        assert row == {"player": "Virat Kohli", "cricinfo_id": 253802}
