from __future__ import annotations

from typing import Annotated, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from api.models.requests import (
    CreateSimRequest,
    FixtureConfig,
    MatchSimRequest,
    PlayoffConfig,
    ScheduleConfig,
    TournamentSimRequest,
    TournamentTeamConfig,
    TournamentVenueConfig,
)  # Some imports kept for /createsim endpoint
from api.models.responses import (
    CommentaryResponse,
    MatchResultResponse,
    PointsTableRow,
    ScorecardResponse,
    SimCreatedResponse,
    SimSummaryItem,
    TournamentMatchItem,
    TournamentMatchResultResponse,
    TournamentResultResponse,
)
from api.worker import run_match_job, run_tournament_job
from db.database import get_db_connection
from db.simulation_repository import SimulationRepository, _parse_win
from simulator.serializers.match import get_commentary, get_match_result, get_scorecard, get_tournament_result

import psycopg2.extras

router = APIRouter(prefix="/cricsimapi/simulations", tags=["simulations"])


# ── POST /createsim ────────────────────────────────────────────────────────────

@router.post("/createsim", response_model=SimCreatedResponse, status_code=202)
def create_simulation(
    request: Annotated[Union[MatchSimRequest, TournamentSimRequest], Field(discriminator="simulation_type")],
    background_tasks: BackgroundTasks,
):
    repo = SimulationRepository()
    try:
        config_dict = request.model_dump()
        sim_id      = repo.create_simulation(
            request.simulation_type,
            config_dict,
            client_id=request.client_id,
            mode=getattr(request, "mode", None),
        )
        repo.commit()
    finally:
        repo.close()

    if request.simulation_type == "match":
        background_tasks.add_task(run_match_job, sim_id, config_dict)
    else:
        background_tasks.add_task(run_tournament_job, sim_id, config_dict)

    return SimCreatedResponse(sim_id=sim_id)


# ── POST /tournament  (UI shorthand — builds config from tournament_id) ───────

class TournamentFromIdRequest(BaseModel):
    tournament_id: int
    team_id:       Optional[int]  = None
    mode:          Optional[str]  = None
    client_id:     Optional[str]  = None
    swaps:         List[dict]     = Field(default_factory=list)
    batting_order: List[int]      = Field(default_factory=list)


@router.post("/tournament", response_model=SimCreatedResponse, status_code=202)
def create_tournament_from_id(body: TournamentFromIdRequest, background_tasks: BackgroundTasks):
    """Start a tournament simulation using a pre-seeded tournament_id."""
    conn = get_db_connection(autocommit=False)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # 1. Load the full seeded config (TournamentConfig-compatible document)
        cur.execute(
            """
            SELECT ts.config
            FROM history.tournaments t
            JOIN simulation.tournament_seeded ts ON ts.tournament_id = t.tournament_id
            WHERE t.tournament_id = %s
            """,
            (body.tournament_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tournament not found or not seeded")
        config: dict = row["config"]
        if not config:
            raise HTTPException(
                status_code=422,
                detail="No seeded config for this tournament. Run seed_sim_configs.py first.",
            )

        teams: list[dict] = config.get("teams", [])
        if not teams:
            raise HTTPException(status_code=422, detail="Tournament config has no teams")
        if len(teams) < 4:
            raise HTTPException(status_code=422, detail=f"A tournament requires at least 4 teams ({len(teams)} found)")

        for team in teams:
            if not team.get("players"):
                raise HTTPException(
                    status_code=422,
                    detail=f"Team '{team.get('name')}' has no seeded squad. Run precompute --seed-squads first.",
                )

    finally:
        cur.close()
        conn.close()

    # 2. Apply swaps + optional batting order reorder
    user_team_name: str | None = None
    if body.team_id:
        swap_map = {s["player_out_id"]: s["player_in_id"] for s in body.swaps}
        updated_teams = []
        for team in teams:
            if team.get("team_id") == body.team_id:
                user_team_name = team["name"]
                base_order = body.batting_order if body.batting_order else team["players"]
                updated_teams.append({**team, "players": [swap_map.get(pid, pid) for pid in base_order]})
            else:
                # Bidirectional trade: if a player was traded out of this team, put original back
                reverse: dict[int, int] = {}
                for s in body.swaps:
                    if s.get("from_team_id") == team.get("team_id"):
                        reverse[s["player_in_id"]] = s["player_out_id"]
                if reverse:
                    updated_teams.append({**team, "players": [reverse.get(pid, pid) for pid in team["players"]]})
                else:
                    updated_teams.append(team)
        config = {**config, "teams": updated_teams}

    # 3. Rate-limit: max 2 concurrent running simulations per client
    if body.client_id:
        conn2 = get_db_connection()
        cur2  = conn2.cursor()
        cur2.execute(
            "SELECT COUNT(*) FROM simulation.simulations WHERE client_id = %s AND status IN ('pending','running')",
            (body.client_id,),
        )
        active = cur2.fetchone()[0]
        cur2.close(); conn2.close()
        if active >= 2:
            raise HTTPException(status_code=429, detail="Too many active simulations. Wait for your current simulation to finish.")

    # 4. Create simulation record + game session, then dispatch worker
    config_dict = config  # already in TournamentConfig-compatible format

    repo = SimulationRepository()
    try:
        sim_id = repo.create_simulation(
            "tournament",
            config_dict,
            client_id=body.client_id,
            mode=body.mode,
        )
        repo.save_game_session(
            sim_id=sim_id,
            client_id=body.client_id,
            mode=body.mode,
            source_tournament_id=body.tournament_id,
            user_team_id=None,  # back-filled by worker after simulation.teams rows are inserted
            swaps=body.swaps or [],
        )
        repo.commit()
    finally:
        repo.close()

    background_tasks.add_task(
        run_tournament_job, sim_id, config_dict,
        user_team_name=user_team_name,
        client_id=body.client_id,
    )
    return SimCreatedResponse(sim_id=sim_id)



# ── GET /total ─────────────────────────────────────────────────────────────────

@router.get("/total")
def get_total_simulations():
    repo = SimulationRepository()
    try:
        count = repo.get_total_simulation_count()
    finally:
        repo.close()
    return {"total": count}


# ── GET  (no trailing slash — avoids 307 CORS redirect) ──────────────────────

@router.get("", response_model=List[SimSummaryItem])
def list_simulations(limit: int = 5, offset: int = 0, client_id: Optional[str] = None):
    repo = SimulationRepository()
    try:
        rows = repo.list_simulations(limit=limit, offset=offset, client_id=client_id)
    finally:
        repo.close()
    return [SimSummaryItem(**r) for r in rows]


# ── GET /{sim_id}/status ───────────────────────────────────────────────────────

@router.get("/{sim_id}/status")
def get_status(sim_id: str):
    repo = SimulationRepository()
    try:
        sim = repo.get_simulation(sim_id)
        if not sim:
            raise HTTPException(status_code=404, detail="Simulation not found")
    finally:
        repo.close()
    return {"sim_id": sim_id, "status": sim["status"], "error": sim.get("error_message")}


# ── GET /{sim_id}/session ─────────────────────────────────────────────────────

@router.get("/{sim_id}/session")
def get_session(sim_id: str):
    """Return game session metadata (mode, source_tournament_id, user_team_id)."""
    repo = SimulationRepository()
    try:
        sim = repo.get_simulation(sim_id)
        if not sim:
            raise HTTPException(status_code=404, detail="Simulation not found")
        session = repo.get_game_session(sim_id)
    finally:
        repo.close()
    return session or {}


# ── GET /{sim_id}/result ───────────────────────────────────────────────────────

@router.get("/{sim_id}/result")
def get_result(sim_id: str, client_id: Optional[str] = None):
    repo = SimulationRepository()
    try:
        sim = repo.get_simulation(sim_id)
        if not sim:
            raise HTTPException(status_code=404, detail="Simulation not found")

        if sim['status'] != 'completed':
            return {"sim_id": sim_id, "status": sim['status']}

        if sim['simulation_type'] == 'match':
            matches = repo.get_matches_for_sim(sim_id)
            if not matches:
                raise HTTPException(status_code=404, detail="No match data found")
            m = matches[0]
            return MatchResultResponse(
                sim_id             = sim_id,
                status             = sim['status'],
                home_team          = m['home_team'],
                away_team          = m['away_team'],
                venue              = _fetch_venue(repo.dict_cursor, sim_id),
                format             = sim['config'].get('format', 'T20'),
                winner             = m['winner'],
                result_description = _build_desc(m),
                win_type           = m['win_type'],
                win_by             = m['win_by'],
            )

        # Tournament
        t_data = get_tournament_result(repo.dict_cursor, sim_id, client_id=client_id)
        return TournamentResultResponse(
            sim_id               = sim_id,
            status               = sim['status'],
            tournament_name      = t_data['tournament_name'],
            season               = t_data['season'],
            format               = t_data['format'],
            winner               = t_data['winner'],
            runner_up            = t_data['runner_up'],
            total_matches        = t_data['total_matches'],
            points_table         = [PointsTableRow(**r) for r in t_data['points_table']],
            user_team_name       = t_data.get('user_team_name'),
            user_team_placement  = t_data.get('user_team_placement'),
            mode                 = t_data.get('mode'),
            source_tournament_id = t_data.get('source_tournament_id'),
            user_team_id         = t_data.get('user_team_id'),
        )
    finally:
        repo.close()


# ── GET /{sim_id}/awards  (tournament only) ────────────────────────────────────

@router.get("/{sim_id}/awards")
def get_awards(sim_id: str):
    repo = SimulationRepository()
    try:
        sim = _require_completed(repo, sim_id)
        _require_type(sim, 'tournament', '/awards')
        awards = repo.get_player_awards(sim_id)
    finally:
        repo.close()
    return {"sim_id": sim_id, "awards": awards}


# ── GET /{sim_id}/lineups  (tournament only) ──────────────────────────────────

@router.get("/{sim_id}/lineups")
def get_lineups(sim_id: str):
    """Per-team player list with batting/bowling/MVP stats for the tournament."""
    repo = SimulationRepository()
    try:
        sim = _require_completed(repo, sim_id)
        _require_type(sim, 'tournament', '/lineups')

        # Batting aggregates
        repo.dict_cursor.execute(
            """
            WITH inning_bat AS (
                SELECT d.batter_id,
                       d.batting_team_id,
                       d.match_id,
                       SUM(d.runs_batter)                                         AS runs,
                       COUNT(*) FILTER (
                           WHERE d.outcome_kind IS DISTINCT FROM 'Wide'
                             AND d.outcome_kind IS DISTINCT FROM 'Noball'
                       )                                                           AS balls,
                       MAX(CASE WHEN d.outcome_type = 'Wicket' THEN 0 ELSE 1 END) AS not_out
                FROM simulation.deliveries d
                JOIN simulation.matches m ON m.match_id = d.match_id
                WHERE m.sim_id = %(sim_id)s AND m.is_super_over = FALSE
                GROUP BY d.batter_id, d.batting_team_id, d.match_id
            )
            SELECT ib.batter_id                                             AS player_id,
                   COALESCE(hp.display_name, hp.name)                      AS player_name,
                   hp.player_role,
                   st.name                                                  AS team_name,
                   COUNT(DISTINCT ib.match_id)                             AS matches,
                   SUM(ib.runs)                                             AS runs,
                   SUM(ib.balls)                                            AS balls
            FROM inning_bat ib
            JOIN history.players hp ON hp.player_id = ib.batter_id
            JOIN simulation.teams  st ON st.team_id  = ib.batting_team_id
            GROUP BY ib.batter_id, hp.display_name, hp.name, hp.player_role, st.name
            """,
            {"sim_id": sim_id},
        )
        bat_rows = {(r["player_id"], r["team_name"]): r for r in repo.dict_cursor.fetchall()}

        # Bowling aggregates
        repo.dict_cursor.execute(
            """
            SELECT d.bowler_id                                              AS player_id,
                   st.name                                                  AS team_name,
                   SUM(CASE
                       WHEN d.outcome_type = 'Wicket'
                        AND (d.outcome_kind IS NULL OR d.outcome_kind != 'run out')
                       THEN 1 ELSE 0 END)                                   AS wickets
            FROM simulation.deliveries d
            JOIN simulation.matches m ON m.match_id = d.match_id
            JOIN simulation.teams  st ON st.team_id  = d.bowling_team_id
            WHERE m.sim_id = %(sim_id)s AND m.is_super_over = FALSE
              AND d.bowler_id IS NOT NULL
            GROUP BY d.bowler_id, st.name
            """,
            {"sim_id": sim_id},
        )
        bowl_rows = {(r["player_id"], r["team_name"]): r for r in repo.dict_cursor.fetchall()}

        # MVP points
        mvp_by_key: dict = {}
        for a in repo.get_player_awards(sim_id):
            key = (a["player_id"], a["team_name"])
            mvp_by_key[key] = a

        # Batting order from sim config (list of player IDs in declared order per team)
        config_teams = sim.get("config", {}).get("teams", [])
        batting_order: dict = {}  # team_name -> [player_id, ...]
        for t in config_teams:
            batting_order[t["name"]] = [int(pid) for pid in t.get("players", [])]

        # Collect all player+team combos
        all_keys = set(bat_rows) | set(bowl_rows) | set(mvp_by_key)

        # Group by team
        team_players: dict = {}
        for pid, tname in all_keys:
            bat = bat_rows.get((pid, tname), {})
            bowl = bowl_rows.get((pid, tname), {})
            mvp = mvp_by_key.get((pid, tname), {})

            entry = {
                "player_id":   pid,
                "player_name": bat.get("player_name") or mvp.get("player_name", ""),
                "player_role": bat.get("player_role"),
                "runs":        int(bat.get("runs", 0) or 0),
                "balls":       int(bat.get("balls", 0) or 0),
                "wickets":     int(bowl.get("wickets", 0) or 0),
                "mvp_points":  round(float(mvp.get("total_pts", 0) or 0), 1),
                "batting_pts": round(float(mvp.get("batting_pts", 0) or 0), 1),
                "bowling_pts": round(float(mvp.get("bowling_pts", 0) or 0), 1),
                "fielding_pts":round(float(mvp.get("fielding_pts", 0) or 0), 1),
            }
            team_players.setdefault(tname, []).append(entry)

        # Sort by batting lineup order from config; unknown players go to end
        for tname, players in team_players.items():
            order = batting_order.get(tname, [])
            order_idx = {pid: i for i, pid in enumerate(order)}
            players.sort(key=lambda p: order_idx.get(p["player_id"], 999))

        teams_out = [
            {"team_name": tname, "players": players}
            for tname, players in sorted(team_players.items())
        ]
    finally:
        repo.close()

    return {"sim_id": sim_id, "teams": teams_out}


# ── GET /{sim_id}/scorecard  (match only) ─────────────────────────────────────

@router.get("/{sim_id}/scorecard", response_model=ScorecardResponse)
def match_scorecard(sim_id: str):
    repo = SimulationRepository()
    try:
        sim = _require_completed(repo, sim_id)
        _require_type(sim, 'match', '/scorecard')
        matches = repo.get_matches_for_sim(sim_id)
        if not matches:
            raise HTTPException(status_code=404, detail="No match data")
        match_id = matches[0]['match_id']
        data = get_scorecard(repo.dict_cursor, match_id)
    finally:
        repo.close()
    return ScorecardResponse(**data)


# ── GET /{sim_id}/commentary  (match only) ────────────────────────────────────

@router.get("/{sim_id}/commentary", response_model=CommentaryResponse)
def match_commentary(sim_id: str):
    repo = SimulationRepository()
    try:
        sim = _require_completed(repo, sim_id)
        _require_type(sim, 'match', '/commentary')
        matches = repo.get_matches_for_sim(sim_id)
        if not matches:
            raise HTTPException(status_code=404, detail="No match data")
        match_id = matches[0]['match_id']
        data = get_commentary(repo.dict_cursor, match_id)
    finally:
        repo.close()
    return CommentaryResponse(**data)


# ── GET /{sim_id}/matches  (tournament only) ──────────────────────────────────

@router.get("/{sim_id}/matches", response_model=List[TournamentMatchItem])
def tournament_matches(sim_id: str):
    repo = SimulationRepository()
    try:
        sim = _require_completed(repo, sim_id)
        _require_type(sim, 'tournament', '/matches')
        rows = repo.get_matches_for_sim(sim_id)
    finally:
        repo.close()
    for r in rows:
        r['result'] = _build_desc(r)
    return [TournamentMatchItem(**r) for r in rows]


# ── GET /{sim_id}/matches/{match_id}/result  (tournament) ────────────────────

@router.get("/{sim_id}/matches/{match_id}/result", response_model=TournamentMatchResultResponse)
def tournament_match_result(sim_id: str, match_id: int):
    repo = SimulationRepository()
    try:
        sim = _require_completed(repo, sim_id)
        _require_type(sim, 'tournament', '/matches/{id}/result')
        _verify_match_belongs(repo, sim_id, match_id)
        data = get_match_result(repo.dict_cursor, match_id)
        if not data:
            raise HTTPException(status_code=404, detail="Match not found")
    finally:
        repo.close()
    return TournamentMatchResultResponse(**data)


# ── GET /{sim_id}/matches/{match_id}/scorecard  (tournament) ──────────────────

@router.get("/{sim_id}/matches/{match_id}/scorecard", response_model=ScorecardResponse)
def tournament_match_scorecard(sim_id: str, match_id: int):
    repo = SimulationRepository()
    try:
        sim = _require_completed(repo, sim_id)
        _require_type(sim, 'tournament', '/matches/{id}/scorecard')
        _verify_match_belongs(repo, sim_id, match_id)
        data = get_scorecard(repo.dict_cursor, match_id)
    finally:
        repo.close()
    return ScorecardResponse(**data)


# ── GET /{sim_id}/matches/{match_id}/commentary  (tournament) ─────────────────

@router.get("/{sim_id}/matches/{match_id}/commentary", response_model=CommentaryResponse)
def tournament_match_commentary(sim_id: str, match_id: int):
    repo = SimulationRepository()
    try:
        sim = _require_completed(repo, sim_id)
        _require_type(sim, 'tournament', '/matches/{id}/commentary')
        _verify_match_belongs(repo, sim_id, match_id)
        data = get_commentary(repo.dict_cursor, match_id)
    finally:
        repo.close()
    return CommentaryResponse(**data)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _require_completed(repo: SimulationRepository, sim_id: str) -> dict:
    sim = repo.get_simulation(sim_id)
    if not sim:
        raise HTTPException(status_code=404, detail="Simulation not found")
    if sim['status'] != 'completed':
        raise HTTPException(
            status_code=409,
            detail=f"Simulation is '{sim['status']}', not completed yet",
        )
    return sim


def _require_type(sim: dict, expected: str, endpoint: str):
    if sim['simulation_type'] != expected:
        raise HTTPException(
            status_code=400,
            detail=f"{endpoint} is only available for {expected} simulations",
        )


def _verify_match_belongs(repo: SimulationRepository, sim_id: str, match_id: int):
    repo.cur.execute(
        "SELECT 1 FROM simulation.matches WHERE match_id = %s AND sim_id = %s",
        (match_id, sim_id),
    )
    if not repo.cur.fetchone():
        raise HTTPException(status_code=404, detail="Match not found in this simulation")


def _fetch_venue(cur, sim_id: str):
    cur.execute(
        """
        SELECT v.name FROM history.venues v
        JOIN simulation.matches m ON m.venue_id = v.venue_id
        WHERE m.sim_id = %s LIMIT 1
        """,
        (sim_id,),
    )
    row = cur.fetchone()
    return row['name'] if row else None


def _build_desc(m: dict):
    if m['result'] == 'no result':
        if m.get('match_format') in ('Test', 'MDM'):
            return "Match drawn"
        return "No result"
    if m['result'] == 'tie':
        return "Match tied"
    if m.get('is_super_over') and m['winner']:
        return f"Match tied · {m['winner']} won Super Over"
    if m['winner'] and m['win_type'] and m['win_by'] is not None:
        if m['win_type'] == 'innings':
            n = m['win_by']
            return f"{m['winner']} won by an innings and {n} run{'s' if n != 1 else ''}"
        unit = 'run' if m['win_type'] == 'runs' else 'wicket'
        plural = 's' if m['win_by'] != 1 else ''
        return f"{m['winner']} won by {m['win_by']} {unit}{plural}"
    return None
