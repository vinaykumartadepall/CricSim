"""
Admin read/write repository for history.players metadata.

Player stats are keyed by player_id everywhere (precomputed tables, matchups,
simulation.deliveries), so editing these display/behavior attributes never
touches any statistics. Every update is recorded in simulation.admin_edits.
"""

from __future__ import annotations

import psycopg2.extras

from db.admin_edits import record_edit
from db.database import get_db_connection

_EDITABLE_FIELDS = (
    "name", "display_name", "player_role", "batting_style",
    "bowling_style", "country_id", "cricinfo_id", "gender",
)
_VALID_ROLES = {"Batter", "Bowler", "All-rounder", "Keeper"}
_VALID_GENDERS = {"male", "female"}


def _headshot_url(cricinfo_id) -> str | None:
    if not cricinfo_id:
        return None
    return f"https://a.espncdn.com/i/headshots/cricket/players/full/{cricinfo_id}.png"


class PlayerRepository:
    def __init__(self):
        self.conn = get_db_connection(autocommit=False)
        self.cur  = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def close(self):
        self.cur.close()
        self.conn.close()

    # ── Read ───────────────────────────────────────────────────────────────────

    def search_players_full(self, q: str = "", limit: int = 30) -> list[dict]:
        """Full-attribute search for the admin editor (the multiplayer search
        returns a trimmed, male-only shape - this one returns everything)."""
        self.cur.execute(
            """
            SELECT p.player_id, p.name, p.display_name, p.gender, p.player_role,
                   p.batting_style, p.bowling_style, p.country_id, p.cricinfo_id,
                   c.name AS country_name,
                   COALESCE(mp.matches_played, 0) AS matches_played
            FROM history.players p
            LEFT JOIN history.countries c ON c.country_id = p.country_id
            LEFT JOIN (
                SELECT player_id, COUNT(*) AS matches_played
                FROM history.match_players
                GROUP BY player_id
            ) mp ON mp.player_id = p.player_id
            WHERE p.display_name ILIKE %s OR p.name ILIKE %s
            ORDER BY COALESCE(mp.matches_played, 0) DESC
            LIMIT %s
            """,
            (f"%{q}%", f"%{q}%", limit),
        )
        rows = [dict(r) for r in self.cur.fetchall()]
        for r in rows:
            r["headshot_url"] = _headshot_url(r["cricinfo_id"])
        return rows

    def get_player(self, player_id: int) -> dict | None:
        self.cur.execute(
            """
            SELECT p.player_id, p.name, p.display_name, p.gender, p.player_role,
                   p.batting_style, p.bowling_style, p.country_id, p.cricinfo_id,
                   c.name AS country_name
            FROM history.players p
            LEFT JOIN history.countries c ON c.country_id = p.country_id
            WHERE p.player_id = %s
            """,
            (player_id,),
        )
        row = self.cur.fetchone()
        if not row:
            return None
        out = dict(row)
        out["headshot_url"] = _headshot_url(out["cricinfo_id"])
        return out

    def list_countries(self) -> list[dict]:
        self.cur.execute("SELECT country_id, name FROM history.countries ORDER BY name")
        return [dict(r) for r in self.cur.fetchall()]

    # ── Write ──────────────────────────────────────────────────────────────────

    def update_player(self, player_id: int, fields: dict, record: bool = True) -> dict:
        """Edit a player's metadata. Returns the fields actually written."""
        allowed = {k: v for k, v in fields.items() if k in _EDITABLE_FIELDS}
        if not allowed:
            raise ValueError("No editable fields provided")

        if "name" in allowed and not (allowed["name"] or "").strip():
            raise ValueError("name cannot be empty")
        if allowed.get("player_role") is not None and allowed["player_role"] not in _VALID_ROLES:
            raise ValueError(f"player_role must be one of {sorted(_VALID_ROLES)}")
        if allowed.get("gender") is not None and allowed["gender"] not in _VALID_GENDERS:
            raise ValueError(f"gender must be one of {sorted(_VALID_GENDERS)}")
        if allowed.get("country_id") is not None:
            self.cur.execute(
                "SELECT 1 FROM history.countries WHERE country_id = %s",
                (allowed["country_id"],),
            )
            if not self.cur.fetchone():
                raise ValueError(f"Unknown country_id: {allowed['country_id']}")

        sets = ", ".join(f"{k} = %s" for k in allowed)
        self.cur.execute(
            f"UPDATE history.players SET {sets} WHERE player_id = %s",
            (*allowed.values(), player_id),
        )
        if self.cur.rowcount == 0:
            raise ValueError(f"Unknown player_id: {player_id}")

        if record:
            record_edit(self.cur, "player", str(player_id),
                        {"player_id": player_id, "fields": allowed})
        self.conn.commit()
        return allowed
