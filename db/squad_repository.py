"""
Read/write repository for simulation.tournament_seeded.

Uses the single `config` JSONB column (TournamentConfig-compatible format).
Used by both the LOV endpoint (read) and the admin squad editor (read+write).
"""

from __future__ import annotations

import json
from typing import Any

import psycopg2.extras

from db.admin_edits import record_edit
from db.database import get_db_connection
from simulator.tournament.config import parse_tournament_config

_VALID_FORMATS = {"T20", "ODI", "Test"}
_VALID_SCHEDULE_TYPES = {"round_robin", "double_round_robin", "two_group_hybrid"}
_VALID_PLAYOFF_FORMATS = {"none", "ipl", "semis_final"}

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

    def get_tournament_detail(self, tournament_id: int) -> dict[str, Any]:
        """get_squads plus everything the admin editor needs: tournament meta,
        venues, schedule/playoffs, and per-team colors/home_venue."""
        base = self.get_squads(tournament_id)
        if not base:
            return {}

        config = self._load_config(tournament_id)
        team_extra = {t.get("team_id"): t for t in config.get("teams", [])}
        for team in base["teams"]:
            extra = team_extra.get(team["team_id"], {})
            team["primary_color"]   = extra.get("primary_color")
            team["secondary_color"] = extra.get("secondary_color")
            team["home_venue"]      = extra.get("home_venue")

        base["tournament_name"] = config.get("tournament_name")
        base["format"]          = config.get("format")
        base["gender"]          = config.get("gender")
        base["season"]          = config.get("season")
        base["venues"]          = config.get("venues", [])
        base["schedule"]        = config.get("schedule", {})
        base["playoffs"]        = config.get("playoffs", {})
        return base

    # ── Write ──────────────────────────────────────────────────────────────────

    def _load_config(self, tournament_id: int) -> dict:
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
        return row["config"]

    @staticmethod
    def _validate_config(config: dict) -> None:
        """Reject any document the tournament engine couldn't run. One parser
        for files, worker input and admin saves - parse_tournament_config."""
        try:
            parse_tournament_config(config)
        except Exception as e:
            raise ValueError(f"Config no longer parses: {e}") from e

        if config.get("format") not in _VALID_FORMATS:
            raise ValueError(f"format must be one of {sorted(_VALID_FORMATS)}")

        venue_names = {v.get("name") for v in config.get("venues", [])}
        seen_names: set = set()
        for team in config.get("teams", []):
            name = (team.get("name") or "").strip()
            if not name:
                raise ValueError("Every team needs a non-empty name")
            if name in seen_names:
                raise ValueError(f"Duplicate team name: {name}")
            seen_names.add(name)
            if team.get("team_id") is None:
                raise ValueError(f"Team '{name}' has no team_id")
            players = team.get("players", [])
            if players and (len(players) != 11 or not all(isinstance(p, int) for p in players)):
                raise ValueError(f"Team '{name}' must have exactly 11 player ids")
            hv = team.get("home_venue")
            if hv and hv not in venue_names:
                raise ValueError(f"Team '{name}' home venue '{hv}' is not in the venues list")

        sched = config.get("schedule", {})
        if isinstance(sched, dict) and sched.get("type") not in _VALID_SCHEDULE_TYPES:
            raise ValueError(f"schedule.type must be one of {sorted(_VALID_SCHEDULE_TYPES)}")
        if config.get("playoffs", {}).get("format", "none") not in _VALID_PLAYOFF_FORMATS:
            raise ValueError(f"playoffs.format must be one of {sorted(_VALID_PLAYOFF_FORMATS)}")

    def _save_config(self, tournament_id: int, config: dict,
                     entity_type: str, entity_id: str, payload: dict,
                     record: bool = True) -> None:
        """Validate, persist and (unless replaying) log one config mutation -
        the single write path for every admin edit."""
        self._validate_config(config)
        self.cur.execute(
            "UPDATE simulation.tournament_seeded SET config = %s::jsonb WHERE tournament_id = %s",
            (json.dumps(config), tournament_id),
        )
        if record:
            record_edit(self.cur, entity_type, entity_id, payload)
        self.conn.commit()

    def update_tournament_meta(self, tournament_id: int, fields: dict,
                               record: bool = True) -> dict:
        """Edit tournament_name / format / gender. A tournament_name change is
        also propagated to history.tournaments for this season, so wizard
        grouping, admin pages and future re-seeds stay consistent."""
        allowed = {k: v for k, v in fields.items()
                   if k in ("tournament_name", "format", "gender") and v is not None}
        if not allowed:
            raise ValueError("No editable fields provided")

        config = self._load_config(tournament_id)
        config.update(allowed)

        if "tournament_name" in allowed:
            self.cur.execute(
                "UPDATE history.tournaments SET tournament_name = %s WHERE tournament_id = %s",
                (allowed["tournament_name"], tournament_id),
            )

        self._save_config(
            tournament_id, config,
            "tournament_meta", str(tournament_id),
            {"tournament_id": tournament_id, "fields": allowed},
            record=record,
        )
        return allowed

    def update_team_meta(self, tournament_id: int, team_id: int, fields: dict,
                         record: bool = True) -> dict:
        """Edit one team's name / short_name / colors / home_venue in the config."""
        allowed = {k: v for k, v in fields.items()
                   if k in ("name", "short_name", "primary_color", "secondary_color", "home_venue")}
        allowed = {k: v for k, v in allowed.items() if v is not None or k == "home_venue"}
        if not allowed:
            raise ValueError("No editable fields provided")

        config = self._load_config(tournament_id)
        for i, team in enumerate(config.get("teams", [])):
            if team.get("team_id") == team_id:
                config["teams"][i] = {**team, **allowed}
                break
        else:
            raise ValueError(f"team_id={team_id} not found in config for tournament_id={tournament_id}")

        self._save_config(
            tournament_id, config,
            "team_meta", f"{tournament_id}/{team_id}",
            {"tournament_id": tournament_id, "team_id": team_id, "fields": allowed},
            record=record,
        )
        return allowed

    def update_venues(self, tournament_id: int, venues: list[dict],
                      record: bool = True) -> int:
        """Replace the venue list. Entries may carry previous_name to signal a
        rename, which is cascaded into team home_venues; a home_venue pointing
        at a removed venue is cleared rather than left dangling."""
        clean = []
        renames: dict[str, str] = {}
        for v in venues:
            name = (v.get("name") or "").strip()
            if not name:
                raise ValueError("Every venue needs a non-empty name")
            clean.append({"name": name, "city": (v.get("city") or "").strip()})
            prev = (v.get("previous_name") or "").strip()
            if prev and prev != name:
                renames[prev] = name

        config = self._load_config(tournament_id)
        config["venues"] = clean
        new_names = {v["name"] for v in clean}
        for team in config.get("teams", []):
            hv = team.get("home_venue")
            if hv in renames:
                team["home_venue"] = renames[hv]
            elif hv and hv not in new_names:
                team["home_venue"] = None

        self._save_config(
            tournament_id, config,
            "tournament_venues", str(tournament_id),
            {"tournament_id": tournament_id, "venues": venues},
            record=record,
        )
        return len(clean)

    def update_schedule(self, tournament_id: int, schedule: dict | None,
                        playoffs: dict | None, record: bool = True) -> None:
        """Replace the schedule and/or playoffs sections."""
        if schedule is None and playoffs is None:
            raise ValueError("Provide schedule and/or playoffs")

        config = self._load_config(tournament_id)
        if schedule is not None:
            config["schedule"] = schedule
        if playoffs is not None:
            config["playoffs"] = playoffs

        self._save_config(
            tournament_id, config,
            "tournament_schedule", str(tournament_id),
            {"tournament_id": tournament_id, "schedule": schedule, "playoffs": playoffs},
            record=record,
        )

    def upsert_team_squad(
        self,
        tournament_id: int,
        team_id: int,
        players: list[dict],  # [{player_id, batting_position}]
        record: bool = True,
    ) -> int:
        """Replace a team's squad within the config.  Returns player count written."""
        if len(players) != 11:
            raise ValueError(f"Squad must have exactly 11 players, got {len(players)}")

        config = self._load_config(tournament_id)
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
        self._save_config(
            tournament_id, config,
            "team_squad", f"{tournament_id}/{team_id}",
            {"tournament_id": tournament_id, "team_id": team_id, "players": players},
            record=record,
        )
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
