"""
Write-side repository for persisting simulation results to the simulation schema.

Usage pattern (match):
    repo = SimulationRepository()
    sim_id = repo.create_simulation('match', config_dict)
    repo.update_status(sim_id, 'running')
    try:
        # ... run simulation ...
        team_a_id = repo.save_team(match.home_team)
        team_b_id = repo.save_team(match.away_team)
        match_id  = repo.save_match(sim_id, 1, sim_match, team_a_id, team_b_id, venue_id)
        for inning in sim_match.innings:
            repo.save_match_players(match_id, inning)
            repo.save_deliveries(match_id, inning)
        repo.update_status(sim_id, 'completed')
        repo.commit()
    except Exception as e:
        repo.rollback()
        repo.update_status(sim_id, 'failed', error=str(e))
        repo.commit()
    finally:
        repo.close()
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

import psycopg2.extras

from db.database import get_db_connection
from simulator.entities.match import SimulationMatch
from simulator.entities.team import MatchTeam
from simulator.entities.inning import Inning
from simulator.logger import get_logger

# ── Shared placement SQL fragments ────────────────────────────────────────────
# Used by list_simulations and get_sim_history_best to avoid duplication.

_FINAL_LATERAL = """
    LEFT JOIN LATERAL (
        SELECT match_id, winner_id, home_team_id, away_team_id
        FROM simulation.matches m2
        WHERE m2.sim_id = s.sim_id
          AND m2.match_label ILIKE '%%final%%'
          AND m2.result NOT IN ('no result', 'tie')
        ORDER BY m2.match_id DESC
        LIMIT 1
    ) mf ON true
"""

_PLAYOFF_LATERAL = """
    LEFT JOIN LATERAL (
        SELECT match_id
        FROM simulation.matches m3
        WHERE m3.sim_id = s.sim_id
          AND m3.match_label NOT ILIKE '%%group%%'
          AND m3.match_label NOT ILIKE 'match %%'
          AND (m3.home_team_id = gs.user_team_id OR m3.away_team_id = gs.user_team_id)
          AND mf.match_id IS NOT NULL
        LIMIT 1
    ) mpo ON true
"""

_MATCH_LATERAL = """
    LEFT JOIN LATERAL (
        SELECT match_id, winner_id, home_team_id, away_team_id
        FROM simulation.matches m4
        WHERE m4.sim_id = s.sim_id
          AND s.simulation_type = 'match'
        LIMIT 1
    ) mm ON true
"""

_PLACEMENT_CASE = """
    CASE
        -- 1v1 / single match sims
        WHEN s.simulation_type = 'match'
         AND mm.winner_id = gs.user_team_id                         THEN 'Winner'
        WHEN s.simulation_type = 'match'
         AND mm.match_id IS NOT NULL
         AND (mm.home_team_id = gs.user_team_id
              OR mm.away_team_id = gs.user_team_id)
         AND mm.winner_id != gs.user_team_id                        THEN 'Loser'
        -- Tournament sims
        WHEN mf.winner_id = gs.user_team_id                        THEN 'Winner'
        WHEN mf.match_id  IS NOT NULL
         AND (mf.home_team_id = gs.user_team_id
              OR mf.away_team_id = gs.user_team_id)
         AND mf.winner_id != gs.user_team_id                       THEN 'Runner-up'
        WHEN mpo.match_id IS NOT NULL                               THEN 'Playoffs'
        WHEN gs.user_team_id IS NOT NULL                            THEN 'Group stage'
        ELSE NULL
    END
"""

_PLACEMENT_RANK = """
    CASE
        WHEN s.simulation_type = 'match'
         AND mm.winner_id = gs.user_team_id                         THEN 1
        WHEN s.simulation_type = 'match'
         AND mm.match_id IS NOT NULL
         AND mm.winner_id != gs.user_team_id                        THEN 2
        WHEN mf.winner_id = gs.user_team_id                        THEN 1
        WHEN mf.match_id  IS NOT NULL
         AND (mf.home_team_id = gs.user_team_id
              OR mf.away_team_id = gs.user_team_id)
         AND mf.winner_id != gs.user_team_id                       THEN 2
        WHEN mpo.match_id IS NOT NULL                               THEN 3
        ELSE 4
    END
"""


class SimulationRepository:
    def __init__(self):
        self.conn = get_db_connection(autocommit=False)
        self.cur  = self.conn.cursor()
        self._dict_cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    @property
    def dict_cursor(self):
        """Cursor that returns rows as dicts keyed by column name."""
        return self._dict_cur

    # ── Transaction control ────────────────────────────────────────────────────

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.cur.close()
        self._dict_cur.close()
        self.conn.close()

    # ── simulation.simulations ─────────────────────────────────────────────────

    def create_simulation(
        self,
        sim_type: str,
        config_dict: dict,
        client_id: Optional[str] = None,
        mode: Optional[str] = None,
        participant_ids: Optional[list] = None,
    ) -> str:
        """Insert a new simulation job row and return its UUID."""
        self.cur.execute(
            """
            INSERT INTO simulation.simulations
                (simulation_type, status, config, client_id, mode, participant_ids)
            VALUES (%s, 'pending', %s, %s, %s, %s)
            RETURNING sim_id
            """,
            (sim_type, json.dumps(config_dict), client_id, mode, participant_ids or []),
        )
        return str(self.cur.fetchone()[0])

    def update_status(
        self,
        sim_id: str,
        status: str,
        error: Optional[str] = None,
    ):
        """Update job status (pending → running → completed | failed)."""
        if status == 'running':
            self.cur.execute(
                """
                UPDATE simulation.simulations
                SET status = %s, started_at = now()
                WHERE sim_id = %s
                """,
                (status, sim_id),
            )
        elif status in ('completed', 'failed'):
            self.cur.execute(
                """
                UPDATE simulation.simulations
                SET status = %s, completed_at = now(), error_message = %s
                WHERE sim_id = %s
                """,
                (status, error, sim_id),
            )
        else:
            self.cur.execute(
                "UPDATE simulation.simulations SET status = %s WHERE sim_id = %s",
                (status, sim_id),
            )
    # ── simulation.teams ───────────────────────────────────────────────────────

    def save_team(self, team: MatchTeam) -> int:
        """Insert a simulation team row and return its ID."""
        self.cur.execute(
            """
            INSERT INTO simulation.teams (name, primary_color, secondary_color)
            VALUES (%s, %s, %s)
            RETURNING team_id
            """,
            (team.name, team.primary_color, team.secondary_color),
        )
        return self.cur.fetchone()[0]

    # ── simulation.tournaments ─────────────────────────────────────────────────

    def save_tournament(
        self,
        sim_id: str,
        tournament_name: str,
        season: str,
        format: str,
        gender: str,
    ) -> int:
        """Insert a simulation tournament row and return its ID."""
        self.cur.execute(
            """
            INSERT INTO simulation.tournaments (sim_id, tournament_name, season, format, gender)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING tournament_id
            """,
            (sim_id, tournament_name, season, format, gender),
        )
        return self.cur.fetchone()[0]

    def save_tournament_teams(self, tournament_id: int, team_ids: List[int]):
        """Populate simulation.tournament_teams junction table."""
        rows = [(tournament_id, tid) for tid in team_ids]
        psycopg2.extras.execute_batch(
            self.cur,
            """
            INSERT INTO simulation.tournament_teams (tournament_id, team_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )

    # ── simulation.matches ─────────────────────────────────────────────────────

    def save_match(
        self,
        sim_id: str,
        match_label: str,
        sim_match: SimulationMatch,
        home_team_id: int,
        away_team_id: int,
        venue_id: Optional[int],
        tournament_id: Optional[int] = None,
    ) -> int:
        """
        Insert a simulation.matches row from a completed SimulationMatch.

        match_label: 'Match 1', 'Semi-final 1', 'Final', etc.
        Returns the new match_id.
        winner_id references simulation.teams — pass sim team IDs, not history IDs.
        """
        result      = sim_match.result
        winner_name = result.winner if result else None

        # Map winning team name → simulation team_id
        winner_id: Optional[int] = None
        if winner_name:
            if sim_match.home_team.name == winner_name:
                winner_id = home_team_id
            elif sim_match.away_team.name == winner_name:
                winner_id = away_team_id

        # win_type / win_by from result description (e.g. "won by 34 runs", "won by 2 wickets")
        win_type, win_by = _parse_win(result.description if result else "")

        # result / result_type
        if result is None:
            db_result, result_type = None, None
        elif result.is_no_result:
            db_result, result_type = 'no result', None
        elif result.is_tie:
            db_result, result_type = 'tie', None
        else:
            db_result, result_type = 'win', 'normal'

        self.cur.execute(
            """
            INSERT INTO simulation.matches (
                sim_id, match_label, name,
                venue_id, tournament_id,
                home_team_id, away_team_id,
                gender, match_format,
                balls_per_over, overs_per_innings,
                result, result_type,
                winner_id, win_type, win_by,
                is_super_over
            )
            VALUES (
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s
            )
            RETURNING match_id
            """,
            (
                sim_id, match_label,
                f"{sim_match.home_team.name} vs {sim_match.away_team.name}",
                venue_id, tournament_id,
                home_team_id, away_team_id,
                sim_match.gender, sim_match.match_format,
                sim_match.balls_per_over, sim_match.overs_per_innings,
                db_result, result_type,
                winner_id, win_type, win_by,
                sim_match.is_super_over,
            ),
        )
        return self.cur.fetchone()[0]

    # ── simulation.match_players ───────────────────────────────────────────────

    def save_match_players(
        self,
        match_id: int,
        team_id: int,
        player_ids: List[int],
    ):
        """
        Record which players participated in a match on a given team.
        player_ids must be history.players IDs.
        """
        rows = [(match_id, team_id, pid) for pid in player_ids]
        psycopg2.extras.execute_batch(
            self.cur,
            """
            INSERT INTO simulation.match_players (match_id, team_id, player_id)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )

    def save_match_players_from_inning(
        self,
        match_id: int,
        inning: Inning,
        team_id: int,
    ):
        """Convenience: derive player IDs from an Inning's inning_players list."""
        player_ids = [ip.id for ip in inning.batting_team.inning_players]
        self.save_match_players(match_id, team_id, player_ids)

    # ── simulation.deliveries ──────────────────────────────────────────────────

    def save_deliveries(self, match_id: int, inning: Inning, team_id_map: Dict[str, int]):
        """
        Bulk-insert all deliveries from one Inning.

        team_id_map: { team_name: simulation_team_id } for batting and bowling teams.
        Player IDs are history.players IDs (from InningPlayer.id → Player.id).
        """
        rows = []
        for d in inning.deliveries:
            batting_tid  = team_id_map.get(inning.batting_team.name)
            bowling_tid  = team_id_map.get(inning.bowling_team.name)
            batter_id      = d.batter.id       if d.batter       else None
            bowler_id      = d.bowler.id       if d.bowler       else None
            non_striker_id = d.non_striker.id  if d.non_striker  else None

            outcome_type = _delivery_outcome_type(d)
            outcome_kind = d.wicket_kind or d.extras_type  # both are plain strings
            outcome_player_id = d.outcome_player.id if d.outcome_player else None

            rows.append((
                match_id,
                inning.inning_number,
                d.over_number,
                d.ball_number,
                batter_id,
                bowler_id,
                non_striker_id,
                batting_tid,
                bowling_tid,
                d.runs_batter,
                d.runs_extras,
                outcome_type,
                outcome_kind,
                outcome_player_id,
                d.is_free_hit,
            ))

        psycopg2.extras.execute_batch(
            self.cur,
            """
            INSERT INTO simulation.deliveries (
                match_id, inning_number, over_number, ball_number,
                batter_id, bowler_id, non_striker_id,
                batting_team_id, bowling_team_id,
                runs_batter, runs_extras,
                outcome_type, outcome_kind, outcome_player_id,
                is_free_hit
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s
            )
            """,
            rows,
            page_size=500,
        )

    def save_all_deliveries(self, match_id: int, sim_match: SimulationMatch, team_id_map: Dict[str, int]):
        """Save deliveries for all innings of a match."""
        for inning in sim_match.innings:
            self.save_deliveries(match_id, inning, team_id_map)

    # ── simulation.player_awards ───────────────────────────────────────────────

    def save_player_awards(self, sim_id: str, awards: list) -> None:
        """Persist tournament MVP point totals for every player."""
        rows = [
            (sim_id, p.player_id, p.player_name, p.team,
             round(p.batting_pts, 2), round(p.bowling_pts, 2), round(p.fielding_pts, 2))
            for p in awards
        ]
        psycopg2.extras.execute_batch(
            self.cur,
            """
            INSERT INTO simulation.player_awards
                (sim_id, player_id, player_name, team_name, batting_pts, bowling_pts, fielding_pts)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )

    def get_player_awards(self, sim_id: str) -> list:
        self._dict_cur.execute(
            """
            SELECT player_id, player_name, team_name,
                   batting_pts, bowling_pts, fielding_pts,
                   (batting_pts + bowling_pts + fielding_pts) AS total_pts
            FROM simulation.player_awards
            WHERE sim_id = %s
            ORDER BY total_pts DESC
            """,
            (sim_id,),
        )
        return [dict(r) for r in self._dict_cur.fetchall()]

    # ── simulation.leaderboard_cache ──────────────────────────────────────────

    def save_leaderboard_cache(self, tournament_id: int, leaderboard_type: str, entries: list) -> None:
        self.cur.execute(
            """
            INSERT INTO simulation.leaderboard_cache (tournament_id, leaderboard_type, entries)
            VALUES (%s, %s, %s)
            ON CONFLICT (tournament_id, leaderboard_type) DO UPDATE
                SET entries = EXCLUDED.entries, computed_at = now()
            """,
            (tournament_id, leaderboard_type, json.dumps(entries)),
        )

    def get_leaderboard_cache(self, tournament_id: int, leaderboard_type: str) -> Optional[list]:
        self._dict_cur.execute(
            """
            SELECT entries FROM simulation.leaderboard_cache
            WHERE tournament_id = %s AND leaderboard_type = %s
            """,
            (tournament_id, leaderboard_type),
        )
        row = self._dict_cur.fetchone()
        return row['entries'] if row else None

    def get_tournament_id_for_sim(self, sim_id: str) -> Optional[int]:
        self.cur.execute(
            "SELECT tournament_id FROM simulation.tournaments WHERE sim_id = %s LIMIT 1",
            (sim_id,),
        )
        row = self.cur.fetchone()
        return row[0] if row else None

    # ── Read helpers ───────────────────────────────────────────────────────────

    def get_simulation(self, sim_id: str) -> Optional[dict]:
        self._dict_cur.execute(
            "SELECT sim_id, simulation_type, status, config, error_message, created_at, started_at, completed_at "
            "FROM simulation.simulations WHERE sim_id = %s",
            (sim_id,),
        )
        row = self._dict_cur.fetchone()
        return dict(row) if row else None

    def list_simulations(self, limit: int = 50, offset: int = 0, client_id: str | None = None) -> List[dict]:
        """Return enriched simulation summaries for the home page cards."""
        self._dict_cur.execute(
            f"""
            SELECT
                s.sim_id,
                s.simulation_type,
                s.status,
                s.created_at,
                s.completed_at,
                s.mode,
                COALESCE(
                    t.tournament_name,
                    CASE WHEN s.simulation_type = 'match' THEN
                        (s.config->'team_a'->>'name') || ' vs ' || (s.config->'team_b'->>'name')
                    END
                )                                          AS tournament_name,
                t.season,
                ut.name                                    AS user_team_name,
                JSONB_ARRAY_LENGTH(gs.swaps)               AS swap_count,
                wt.name                                    AS winner_name,
                {_PLACEMENT_CASE}                          AS user_team_placement,
                CASE WHEN s.simulation_type = 'match' THEN (
                    SELECT m.match_id FROM simulation.matches m WHERE m.sim_id = s.sim_id LIMIT 1
                ) END                                      AS match_id,
                COALESCE(t.format, s.config->>'match_format') AS match_format
            FROM simulation.simulations s
            LEFT JOIN simulation.tournaments t   ON t.sim_id   = s.sim_id
            LEFT JOIN simulation.game_sessions gs ON gs.sim_id  = s.sim_id
                                                 AND gs.client_id = %s
            LEFT JOIN simulation.teams        ut  ON ut.team_id = gs.user_team_id
            {_FINAL_LATERAL}
            LEFT JOIN simulation.teams wt ON wt.team_id = mf.winner_id
            {_PLAYOFF_LATERAL}
            {_MATCH_LATERAL}
            WHERE (%s IS NULL OR s.client_id = %s OR %s = ANY(s.participant_ids))
              AND s.status != 'failed'
            ORDER BY s.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (client_id, client_id, client_id, client_id, limit, offset),
        )
        return [dict(r) for r in self._dict_cur.fetchall()]

    def get_total_simulation_count(self) -> int:
        self.cur.execute(
            "SELECT COUNT(*) FROM simulation.simulations WHERE status = 'completed'"
        )
        return self.cur.fetchone()[0]

    def save_game_session(
        self,
        sim_id: str,
        client_id: str,
        mode: str | None,
        source_tournament_id: int | None,
        user_team_id: int | None,
        swaps: list,
    ) -> None:
        """Persist game session metadata (UI context) for one participant of a simulation."""
        self.cur.execute(
            """
            INSERT INTO simulation.game_sessions
                (sim_id, client_id, mode, source_tournament_id, user_team_id, swaps)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (sim_id, client_id) DO UPDATE
                SET mode = EXCLUDED.mode,
                    source_tournament_id = EXCLUDED.source_tournament_id,
                    user_team_id = EXCLUDED.user_team_id,
                    swaps = EXCLUDED.swaps
            """,
            (sim_id, client_id, mode, source_tournament_id, user_team_id, json.dumps(swaps)),
        )

    def get_game_session(self, sim_id: str, client_id: str | None = None) -> dict | None:
        """Return game session metadata for one participant of a simulation.

        client_id: if provided, returns that participant's row; otherwise returns
                   the first row (backward-compat for single-player callers that
                   don't pass client_id, where there is exactly one row per sim).
        Returns None if no matching row exists.
        """
        try:
            if client_id is not None:
                self._dict_cur.execute(
                    """
                    SELECT gs.mode,
                           gs.source_tournament_id,
                           gs.user_team_id,
                           t.name AS user_team_name
                    FROM simulation.game_sessions gs
                    LEFT JOIN simulation.teams t ON t.team_id = gs.user_team_id
                    WHERE gs.sim_id = %s AND gs.client_id = %s
                    """,
                    (sim_id, client_id),
                )
            else:
                self._dict_cur.execute(
                    """
                    SELECT gs.mode,
                           gs.source_tournament_id,
                           gs.user_team_id,
                           t.name AS user_team_name
                    FROM simulation.game_sessions gs
                    LEFT JOIN simulation.teams t ON t.team_id = gs.user_team_id
                    WHERE gs.sim_id = %s
                    LIMIT 1
                    """,
                    (sim_id,),
                )
            row = self._dict_cur.fetchone()
            return dict(row) if row else None
        except Exception:
            get_logger().exception("Failed to fetch game session %s", sim_id)
            self.conn.rollback()
            return None

    def get_matches_for_sim(self, sim_id: str) -> List[dict]:
        self._dict_cur.execute(
            """
            SELECT m.match_id, m.match_label, m.name,
                   m.match_format,
                   ht.name AS home_team, at.name AS away_team,
                   wt.name AS winner,
                   v.name  AS venue,
                   c.name  AS venue_country,
                   m.win_type, m.win_by, m.result,
                   (m.is_super_over OR EXISTS (
                       SELECT 1 FROM simulation.deliveries dso
                       WHERE dso.match_id = m.match_id AND dso.inning_number = 3
                         AND m.match_format NOT IN ('Test', 'MDM')
                   )) AS is_super_over,
                   home_s.runs  AS home_score,
                   home_s.wkts  AS home_wickets,
                   CASE WHEN home_s.lb IS NOT NULL
                        THEN (home_s.lb / 6)::text || '.' || (home_s.lb %% 6)::text
                        ELSE NULL END AS home_overs,
                   home_s.innings_json  AS home_innings,
                   away_s.runs  AS away_score,
                   away_s.wkts  AS away_wickets,
                   CASE WHEN away_s.lb IS NOT NULL
                        THEN (away_s.lb / 6)::text || '.' || (away_s.lb %% 6)::text
                        ELSE NULL END AS away_overs,
                   away_s.innings_json  AS away_innings
            FROM simulation.matches m
            JOIN simulation.teams ht ON ht.team_id = m.home_team_id
            JOIN simulation.teams at ON at.team_id = m.away_team_id
            LEFT JOIN simulation.teams wt ON wt.team_id = m.winner_id
            LEFT JOIN history.venues   v  ON v.venue_id  = m.venue_id
            LEFT JOIN history.countries c ON c.country_id = v.country_id
            LEFT JOIN LATERAL (
                SELECT SUM(COALESCE(d.runs_batter, 0) + COALESCE(d.runs_extras, 0)) AS runs,
                       SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END) AS wkts,
                       SUM(CASE WHEN d.outcome_kind IS NULL OR d.outcome_kind NOT IN ('Wide', 'wide', 'Noball', 'noball') THEN 1 ELSE 0 END) AS lb,
                       (SELECT COALESCE(JSONB_AGG(
                           JSONB_BUILD_OBJECT('runs', sub.r, 'wkts', sub.w) ORDER BY sub.inn
                       ), '[]'::jsonb)
                        FROM (
                            SELECT di.inning_number AS inn,
                                   SUM(COALESCE(di.runs_batter,0)+COALESCE(di.runs_extras,0)) AS r,
                                   SUM(CASE WHEN di.outcome_type='Wicket' THEN 1 ELSE 0 END) AS w
                            FROM simulation.deliveries di
                            WHERE di.match_id = m.match_id AND di.batting_team_id = m.home_team_id
                            GROUP BY di.inning_number
                        ) sub
                       ) AS innings_json
                FROM simulation.deliveries d
                WHERE d.match_id = m.match_id AND d.batting_team_id = m.home_team_id
                  AND (m.match_format IN ('Test', 'MDM') OR d.inning_number <= 2)
            ) home_s ON true
            LEFT JOIN LATERAL (
                SELECT SUM(COALESCE(d.runs_batter, 0) + COALESCE(d.runs_extras, 0)) AS runs,
                       SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END) AS wkts,
                       SUM(CASE WHEN d.outcome_kind IS NULL OR d.outcome_kind NOT IN ('Wide', 'wide', 'Noball', 'noball') THEN 1 ELSE 0 END) AS lb,
                       (SELECT COALESCE(JSONB_AGG(
                           JSONB_BUILD_OBJECT('runs', sub.r, 'wkts', sub.w) ORDER BY sub.inn
                       ), '[]'::jsonb)
                        FROM (
                            SELECT di.inning_number AS inn,
                                   SUM(COALESCE(di.runs_batter,0)+COALESCE(di.runs_extras,0)) AS r,
                                   SUM(CASE WHEN di.outcome_type='Wicket' THEN 1 ELSE 0 END) AS w
                            FROM simulation.deliveries di
                            WHERE di.match_id = m.match_id AND di.batting_team_id = m.away_team_id
                            GROUP BY di.inning_number
                        ) sub
                       ) AS innings_json
                FROM simulation.deliveries d
                WHERE d.match_id = m.match_id AND d.batting_team_id = m.away_team_id
                  AND (m.match_format IN ('Test', 'MDM') OR d.inning_number <= 2)
            ) away_s ON true
            WHERE m.sim_id = %s
            ORDER BY m.match_id
            """,
            (sim_id,),
        )
        return [dict(r) for r in self._dict_cur.fetchall()]

    # ── Sim history (fun-mode challenge tracking) ──────────────────────────────

    def get_sim_history_counts(
        self,
        client_id: str,
        tournament_ids: list[int] | None = None,
        mode: str | None = None,
    ) -> list[dict]:
        """
        Without tournament_ids  → per tournament-name counts (Step 1).
        With    tournament_ids  → per tournament-id counts   (Step 2).
        mode='challenge': totals only count underdog (win_pct < 0.33) team×season combos.
        """
        if tournament_ids is None:
            if mode == 'challenge':
                self._dict_cur.execute(
                    """
                    WITH seeded AS (
                        SELECT ts.tournament_id
                        FROM simulation.tournament_seeded ts
                        WHERE ts.config IS NOT NULL
                          AND jsonb_array_length(ts.config->'teams') > 0
                          AND NOT EXISTS (
                              SELECT 1 FROM jsonb_array_elements(ts.config->'teams') tm
                              WHERE jsonb_array_length(tm->'players') = 0
                          )
                    ),
                    underdog_combos AS (
                        SELECT tn.tournament_name AS name,
                               tn.tournament_id,
                               t.team_id
                        FROM seeded s
                        JOIN history.tournaments tn ON tn.tournament_id = s.tournament_id
                        JOIN history.tournament_teams tt ON tt.tournament_id = tn.tournament_id
                        JOIN history.teams t ON t.team_id = tt.team_id
                        LEFT JOIN history.matches m ON m.tournament_id = tn.tournament_id
                            AND (m.home_team_id = t.team_id OR m.away_team_id = t.team_id)
                        GROUP BY tn.tournament_name, tn.tournament_id, t.team_id
                        HAVING COUNT(m.match_id) > 0
                           AND (COUNT(m.match_id) FILTER (WHERE m.winner_id = t.team_id))::float
                                / COUNT(m.match_id) < 0.33
                    ),
                    totals AS (
                        SELECT name,
                               COUNT(*)                            AS total,
                               ARRAY_AGG(DISTINCT tournament_id)   AS tournament_ids
                        FROM underdog_combos
                        GROUP BY name
                    ),
                    done AS (
                        SELECT tn.tournament_name AS name,
                               COUNT(DISTINCT (gs.source_tournament_id, st.name)) AS completed
                        FROM simulation.game_sessions gs
                        JOIN simulation.simulations sim ON sim.sim_id = gs.sim_id
                        JOIN simulation.teams st ON st.team_id = gs.user_team_id
                        JOIN history.tournaments tn ON tn.tournament_id = gs.source_tournament_id
                        WHERE sim.client_id = %s
                          AND sim.status = 'completed'
                          AND gs.user_team_id IS NOT NULL
                          AND gs.source_tournament_id IS NOT NULL
                          AND gs.mode = 'challenge'
                        GROUP BY tn.tournament_name
                    )
                    SELECT t.name,
                           t.tournament_ids,
                           t.total,
                           COALESCE(d.completed, 0) AS completed
                    FROM totals t
                    LEFT JOIN done d ON d.name = t.name
                    ORDER BY t.name
                    """,
                    (client_id,),
                )
            else:
                self._dict_cur.execute(
                    """
                    WITH seeded AS (
                        SELECT ts.tournament_id,
                               tn.tournament_name AS name
                        FROM simulation.tournament_seeded ts
                        JOIN history.tournaments tn ON tn.tournament_id = ts.tournament_id
                        WHERE ts.config IS NOT NULL
                          AND jsonb_array_length(ts.config->'teams') > 0
                    ),
                    totals AS (
                        SELECT s.name,
                               COUNT(*)                           AS total,
                               ARRAY_AGG(DISTINCT s.tournament_id) AS tournament_ids
                        FROM seeded s
                        JOIN history.tournament_teams tt ON tt.tournament_id = s.tournament_id
                        GROUP BY s.name
                    ),
                    done AS (
                        SELECT tn.tournament_name AS name,
                               COUNT(DISTINCT (gs.source_tournament_id, st.name)) AS completed
                        FROM simulation.game_sessions gs
                        JOIN simulation.simulations sim ON sim.sim_id = gs.sim_id
                        JOIN simulation.teams st ON st.team_id = gs.user_team_id
                        JOIN history.tournaments tn ON tn.tournament_id = gs.source_tournament_id
                        WHERE sim.client_id = %s
                          AND sim.status = 'completed'
                          AND gs.user_team_id IS NOT NULL
                          AND gs.source_tournament_id IS NOT NULL
                          AND (%s IS NULL OR gs.mode = %s)
                        GROUP BY tn.tournament_name
                    )
                    SELECT t.name,
                           t.tournament_ids,
                           t.total,
                           COALESCE(d.completed, 0) AS completed
                    FROM totals t
                    LEFT JOIN done d ON d.name = t.name
                    ORDER BY t.name
                    """,
                    (client_id, mode, mode),
                )
        else:
            if mode == 'challenge':
                self._dict_cur.execute(
                    """
                    WITH underdog_combos AS (
                        SELECT tn.tournament_id,
                               t.team_id
                        FROM simulation.tournament_seeded ts
                        JOIN history.tournaments tn ON tn.tournament_id = ts.tournament_id
                        JOIN history.tournament_teams tt ON tt.tournament_id = tn.tournament_id
                        JOIN history.teams t ON t.team_id = tt.team_id
                        LEFT JOIN history.matches m ON m.tournament_id = tn.tournament_id
                            AND (m.home_team_id = t.team_id OR m.away_team_id = t.team_id)
                        WHERE ts.tournament_id = ANY(%s)
                          AND ts.config IS NOT NULL
                        GROUP BY tn.tournament_id, t.team_id
                        HAVING COUNT(m.match_id) > 0
                           AND (COUNT(m.match_id) FILTER (WHERE m.winner_id = t.team_id))::float
                                / COUNT(m.match_id) < 0.33
                    ),
                    totals AS (
                        SELECT tournament_id,
                               COUNT(*) AS total
                        FROM underdog_combos
                        GROUP BY tournament_id
                    ),
                    done AS (
                        SELECT gs.source_tournament_id AS tournament_id,
                               COUNT(DISTINCT st.name) AS completed
                        FROM simulation.game_sessions gs
                        JOIN simulation.simulations sim ON sim.sim_id = gs.sim_id
                        JOIN simulation.teams st ON st.team_id = gs.user_team_id
                        WHERE sim.client_id = %s
                          AND sim.status = 'completed'
                          AND gs.source_tournament_id = ANY(%s)
                          AND gs.user_team_id IS NOT NULL
                          AND gs.mode = 'challenge'
                        GROUP BY gs.source_tournament_id
                    )
                    SELECT t.tournament_id,
                           t.total,
                           COALESCE(d.completed, 0) AS completed
                    FROM totals t
                    LEFT JOIN done d ON d.tournament_id = t.tournament_id
                    """,
                    (tournament_ids, client_id, tournament_ids),
                )
            else:
                self._dict_cur.execute(
                    """
                    WITH totals AS (
                        SELECT ts.tournament_id,
                               COUNT(DISTINCT tt.team_id) AS total
                        FROM simulation.tournament_seeded ts
                        JOIN history.tournament_teams tt ON tt.tournament_id = ts.tournament_id
                        WHERE ts.tournament_id = ANY(%s)
                          AND ts.config IS NOT NULL
                        GROUP BY ts.tournament_id
                    ),
                    done AS (
                        SELECT gs.source_tournament_id AS tournament_id,
                               COUNT(DISTINCT st.name) AS completed
                        FROM simulation.game_sessions gs
                        JOIN simulation.simulations sim ON sim.sim_id = gs.sim_id
                        JOIN simulation.teams st ON st.team_id = gs.user_team_id
                        WHERE sim.client_id = %s
                          AND sim.status = 'completed'
                          AND gs.source_tournament_id = ANY(%s)
                          AND gs.user_team_id IS NOT NULL
                          AND (%s IS NULL OR gs.mode = %s)
                        GROUP BY gs.source_tournament_id
                    )
                    SELECT t.tournament_id,
                           t.total,
                           COALESCE(d.completed, 0) AS completed
                    FROM totals t
                    LEFT JOIN done d ON d.tournament_id = t.tournament_id
                    """,
                    (tournament_ids, client_id, tournament_ids, mode, mode),
                )
        return [dict(r) for r in self._dict_cur.fetchall()]

    def get_sim_history_best(
        self,
        client_id: str,
        tournament_id: int,
        mode: str | None = None,
    ) -> list[dict]:
        """Best placement per team for a specific tournament+season.
        Keyed by team name (not team_id) because game_sessions stores simulation.teams IDs
        which differ from history.teams IDs returned by the squads endpoint.
        mode: when provided, only considers simulations with that mode.
        """
        self._dict_cur.execute(
            f"""
            WITH ranked AS (
                SELECT
                    st.name                              AS team_name,
                    COALESCE(JSONB_ARRAY_LENGTH(gs.swaps), 0) AS swap_count,
                    s.sim_id,
                    {_PLACEMENT_CASE}                    AS best_placement,
                    {_PLACEMENT_RANK}                    AS placement_rank
                FROM simulation.game_sessions gs
                JOIN simulation.simulations s  ON s.sim_id    = gs.sim_id
                JOIN simulation.teams       st ON st.team_id  = gs.user_team_id
                {_FINAL_LATERAL}
                {_PLAYOFF_LATERAL}
                {_MATCH_LATERAL}
                WHERE s.client_id = %s
                  AND s.status = 'completed'
                  AND gs.source_tournament_id = %s
                  AND gs.user_team_id IS NOT NULL
                  AND (%s IS NULL OR gs.mode = %s)
            )
            SELECT DISTINCT ON (team_name)
                team_name, best_placement, swap_count, sim_id
            FROM ranked
            ORDER BY team_name, placement_rank ASC, swap_count ASC
            """,
            (client_id, tournament_id, mode, mode),
        )
        return [dict(r) for r in self._dict_cur.fetchall()]


    # ── User profiles ──────────────────────────────────────────────────────────

    def get_profile(self, user_id: str) -> dict | None:
        """Returns {user_id, display_name} or None if not found."""
        self._dict_cur.execute(
            "SELECT user_id, display_name FROM simulation.profiles WHERE user_id = %s",
            (user_id,),
        )
        row = self._dict_cur.fetchone()
        return dict(row) if row else None

    def upsert_profile(self, user_id: str, display_name: str, anonymous_id: str | None = None) -> dict:
        """Creates or updates a user profile. Returns {user_id, display_name}."""
        self._dict_cur.execute(
            """
            INSERT INTO simulation.profiles (user_id, display_name, anonymous_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
                SET display_name = EXCLUDED.display_name,
                    updated_at   = now()
            RETURNING user_id, display_name
            """,
            (user_id, display_name, anonymous_id),
        )
        return dict(self._dict_cur.fetchone())

    def link_anonymous(self, user_id: str, anonymous_id: str) -> int:
        """Migrates all simulations from anonymous_id → user_id. Returns row count updated."""
        self.cur.execute(
            """
            UPDATE simulation.simulations
            SET client_id = %s
            WHERE client_id = %s AND client_id != %s
            """,
            (user_id, anonymous_id, user_id),
        )
        return self.cur.rowcount


# ── Private helpers ────────────────────────────────────────────────────────────

def _delivery_outcome_type(d) -> str:
    if d.is_wicket:
        return 'Wicket'
    if d.extras_type is not None:
        return 'Extras'
    if d.runs_batter == 0:
        return 'Dot'
    return 'Runs'


def _parse_win(description: str):
    """
    Extract (win_type, win_by) from a result description string.
    e.g. "India won by 34 runs"              → ('runs', 34)
         "England won by 2 wickets"           → ('wickets', 2)
         "Australia won by an innings and 45" → ('innings', 45)
    Returns (None, None) if unparseable.
    """
    import re
    m_inn = re.search(r'by an innings and (\d+)', description, re.IGNORECASE)
    if m_inn:
        return 'innings', int(m_inn.group(1))
    m = re.search(r'by (\d+) (run|wicket)', description, re.IGNORECASE)
    if not m:
        return None, None
    win_by   = int(m.group(1))
    win_type = 'runs' if 'run' in m.group(2).lower() else 'wickets'
    return win_type, win_by
