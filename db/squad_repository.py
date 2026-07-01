"""
Read/write repository for simulation.tournament_seeded.

Uses the single `config` JSONB column (TournamentConfig-compatible format).
Used by both the LOV endpoint (read) and the admin squad editor (read+write).
"""

from __future__ import annotations

import json
from typing import Any

import psycopg2.extras

from db.database import get_db_connection

def _headshot_url(cricinfo_id) -> str | None:
    if not cricinfo_id:
        return None
    return f"https://a.espncdn.com/i/headshots/cricket/players/full/{cricinfo_id}.png"


class SquadRepository:
    def __init__(self):
        self.conn = get_db_connection(autocommit=False)
        self.cur  = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def close(self):
        self.cur.close()
        self.conn.close()

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_seeded_tournaments(self, search: str | None = None) -> list[dict[str, Any]]:
        """Tournaments whose config has all teams with non-empty player lists."""
        params = []
        where  = ""
        if search and search.strip():
            where = "AND t.tournament_name ILIKE %s"
            params.append(f"%{search.strip()}%")

        # A tournament is "seeded" when every team in the config has ≥1 player.
        # We check: config IS NOT NULL AND all teams have players (no empty arrays).
        self.cur.execute(f"""
            SELECT
                t.tournament_id,
                CASE t.tournament_name
                    WHEN 'World Cup'     THEN 'ICC Cricket World Cup'
                    WHEN 'ICC World Cup' THEN 'ICC Cricket World Cup'
                    ELSE t.tournament_name
                END                                                    AS name,
                t.season,
                jsonb_array_length(ts.config->'teams')                AS team_count,
                (ts.config->>'gender')                                 AS gender,
                (ts.config->>'format')                                 AS format,
                ts.overseas_limit,
                ts.home_country_name
            FROM history.tournaments t
            JOIN simulation.tournament_seeded ts ON ts.tournament_id = t.tournament_id
            WHERE ts.config IS NOT NULL
              AND jsonb_array_length(ts.config->'teams') > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(ts.config->'teams') team
                  WHERE jsonb_array_length(team->'players') = 0
              )
              {where}
            ORDER BY t.season DESC, name
        """, params or None)
        return [dict(r) for r in self.cur.fetchall()]

    def get_squads(self, tournament_id: int) -> dict[str, Any]:
        """Return all teams + players for a tournament from the config column."""
        self.cur.execute(
            "SELECT 1 FROM history.tournaments WHERE tournament_id = %s",
            (tournament_id,),
        )
        if not self.cur.fetchone():
            return {}

        self.cur.execute(
            "SELECT config FROM simulation.tournament_seeded WHERE tournament_id = %s",
            (tournament_id,),
        )
        row = self.cur.fetchone()
        if not row or not row["config"]:
            return {}

        config = row["config"]
        team_entries = config.get("teams", [])
        if not team_entries:
            return {}

        # Collect all player IDs to fetch metadata in one query
        all_player_ids: list[int] = []
        for team in team_entries:
            all_player_ids.extend(p for p in team.get("players", []) if isinstance(p, int))

        player_meta: dict[int, dict] = {}
        if all_player_ids:
            self.cur.execute("""
                SELECT p.player_id,
                       COALESCE(p.display_name, p.name) AS player_name,
                       p.player_role,
                       p.batting_style,
                       p.bowling_style,
                       p.cricinfo_id,
                       c.name AS country_name
                FROM history.players p
                LEFT JOIN history.countries c ON c.country_id = p.country_id
                WHERE p.player_id = ANY(%s)
            """, (all_player_ids,))
            for p in self.cur.fetchall():
                player_meta[p["player_id"]] = dict(p)

        teams_out = []
        for team in team_entries:
            players_out = []
            for pos, pid in enumerate(team.get("players", []), start=1):
                if not isinstance(pid, int):
                    continue
                meta = player_meta.get(pid, {})
                cricinfo_id = meta.get("cricinfo_id")
                players_out.append({
                    "player_id":        pid,
                    "player_name":      meta.get("player_name", f"Player {pid}"),
                    "player_role":      meta.get("player_role"),
                    "batting_style":    meta.get("batting_style"),
                    "bowling_style":    meta.get("bowling_style"),
                    "batting_position": pos,
                    "cricinfo_id":      cricinfo_id,
                    "country_name":     meta.get("country_name"),
                    "headshot_url": _headshot_url(cricinfo_id),
                })
            teams_out.append({
                "team_id":    team.get("team_id"),
                "team_name":  team.get("name", ""),
                "short_name": team.get("short_name"),
                "players":    players_out,
            })

        return {"tournament_id": tournament_id, "teams": teams_out}

    def get_underdog_team_seasons(self, tournament_name: str, max_win_pct: float = 0.33) -> list[dict[str, Any]]:
        """
        (team, season) combos where win% < max_win_pct for a seeded tournament.
        Uses history.tournament_teams rather than expanding config JSONB.
        """
        self.cur.execute("""
            WITH seeded AS (
                SELECT ts.tournament_id
                FROM simulation.tournament_seeded ts
                WHERE ts.config IS NOT NULL
                  AND jsonb_array_length(ts.config->'teams') > 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(ts.config->'teams') team
                      WHERE jsonb_array_length(team->'players') = 0
                  )
            )
            SELECT
                t.team_id,
                t.name                                             AS team_name,
                tn.tournament_id,
                tn.season,
                COUNT(m.match_id)                                  AS total_matches,
                COUNT(m.match_id) FILTER (WHERE m.winner_id = t.team_id) AS wins
            FROM history.tournaments tn
            JOIN seeded s  ON s.tournament_id = tn.tournament_id
            JOIN history.tournament_teams tt ON tt.tournament_id = tn.tournament_id
            JOIN history.teams t ON t.team_id = tt.team_id
            LEFT JOIN history.matches m ON m.tournament_id = tn.tournament_id
                AND (m.home_team_id = t.team_id OR m.away_team_id = t.team_id)
            WHERE tn.tournament_name = %s
            GROUP BY t.team_id, t.name, tn.tournament_id, tn.season
            HAVING COUNT(m.match_id) > 0
                AND (COUNT(m.match_id) FILTER (WHERE m.winner_id = t.team_id))::float
                    / COUNT(m.match_id) < %s
            ORDER BY
                (COUNT(m.match_id) FILTER (WHERE m.winner_id = t.team_id))::float / COUNT(m.match_id) ASC,
                tn.season DESC,
                t.name
        """, (tournament_name, max_win_pct))
        rows = self.cur.fetchall()
        return [
            {
                "team_id":       row["team_id"],
                "team_name":     row["team_name"],
                "tournament_id": row["tournament_id"],
                "season":        row["season"],
                "wins":          row["wins"],
                "total_matches": row["total_matches"],
                "win_pct":       round(row["wins"] / row["total_matches"], 4) if row["total_matches"] else 0.0,
            }
            for row in rows
        ]

    # ── Write ──────────────────────────────────────────────────────────────────

    def upsert_team_squad(
        self,
        tournament_id: int,
        team_id: int,
        players: list[dict],  # [{player_id, batting_position}]
    ) -> int:
        """Replace a team's squad within the config.  Returns player count written."""
        if len(players) != 11:
            raise ValueError(f"Squad must have exactly 11 players, got {len(players)}")

        self.cur.execute(
            "SELECT config FROM simulation.tournament_seeded WHERE tournament_id = %s",
            (tournament_id,),
        )
        row = self.cur.fetchone()
        if not row or not row["config"]:
            raise ValueError(
                f"No seeded config for tournament_id={tournament_id}. "
                "Run seed_sim_configs.py first."
            )

        config = row["config"]
        teams_list = config.get("teams", [])

        # Sort incoming players by batting_position, extract ordered player_id list
        ordered = sorted(players, key=lambda p: p["batting_position"])
        player_ids = [p["player_id"] for p in ordered]

        updated = False
        for i, team in enumerate(teams_list):
            if team.get("team_id") == team_id:
                teams_list[i] = {**team, "players": player_ids}
                updated = True
                break

        if not updated:
            raise ValueError(
                f"team_id={team_id} not found in config for tournament_id={tournament_id}"
            )

        config["teams"] = teams_list
        self.cur.execute(
            "UPDATE simulation.tournament_seeded SET config = %s::jsonb WHERE tournament_id = %s",
            (json.dumps(config), tournament_id),
        )
        self.conn.commit()
        return len(player_ids)

    def delete_tournament_squads_seeded(self, tournament_id: int) -> int:
        """Remove the seeded config for a tournament entirely."""
        self.cur.execute(
            "UPDATE simulation.tournament_seeded SET config = NULL WHERE tournament_id = %s",
            (tournament_id,),
        )
        count = self.cur.rowcount
        self.conn.commit()
        return count
