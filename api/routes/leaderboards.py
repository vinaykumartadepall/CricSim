from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, Query

from api.models.responses import (
    BattingAggregateRow,
    BestFiguresRow,
    BowlingAggregateRow,
    HighestScoreRow,
    LeaderboardsDashboard,
    MVPRow,
    PaginatedLeaderboard,
)
from db.leaderboard_repository import LeaderboardRepository, _BATTING_SORT, _BOWLING_SORT
from db.simulation_repository import SimulationRepository

_BATTING_LB_TYPES = set(_BATTING_SORT)
_BOWLING_LB_TYPES = set(_BOWLING_SORT)

router = APIRouter(prefix="/cricsimapi/simulations", tags=["leaderboards"])

_ALL_LEADERBOARDS = list(_BATTING_SORT) + ['highest-score'] + list(_BOWLING_SORT) + ['best-bowling-figures', 'mvp']


# ── GET /{sim_id}/leaderboards  (dashboard - tournament only) ─────────────────

@router.get("/{sim_id}/leaderboards", response_model=LeaderboardsDashboard)
def leaderboards_dashboard(sim_id: str):
    repo = SimulationRepository()
    try:
        sim = _require_completed(repo, sim_id)
        if sim['simulation_type'] != 'tournament':
            raise HTTPException(status_code=400, detail="Leaderboard dashboard is only available for tournament simulations")

        tournament_id = repo.get_tournament_id_for_sim(sim_id)
        if tournament_id is None:
            raise HTTPException(status_code=404, detail="Tournament data not found for this simulation")

        def _load(lb_type: str) -> list:
            cached = repo.get_leaderboard_cache(tournament_id, lb_type)
            if cached is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Leaderboard cache not found - re-run the tournament simulation to generate it",
                )
            return cached

        data = {lb_type: _load(lb_type) for lb_type in _ALL_LEADERBOARDS}
    finally:
        repo.close()

    return LeaderboardsDashboard(
        sim_id=sim_id,
        most_runs=[BattingAggregateRow(**r) for r in data['most-runs']],
        highest_score=[HighestScoreRow(**r) for r in data['highest-score']],
        best_batting_average=[BattingAggregateRow(**r) for r in data['best-batting-average']],
        best_strike_rate=[BattingAggregateRow(**r) for r in data['best-strike-rate']],
        most_sixes=[BattingAggregateRow(**r) for r in data['most-sixes']],
        most_fours=[BattingAggregateRow(**r) for r in data['most-fours']],
        most_wickets=[BowlingAggregateRow(**r) for r in data['most-wickets']],
        best_bowling_average=[BowlingAggregateRow(**r) for r in data['best-bowling-average']],
        best_economy=[BowlingAggregateRow(**r) for r in data['best-economy']],
        best_bowling_figures=[BestFiguresRow(**r) for r in data['best-bowling-figures']],
        most_dots=[BowlingAggregateRow(**r) for r in data['most-dots']],
        mvp=[MVPRow(**r) for r in data['mvp']],
    )


# ── GET /{sim_id}/leaderboards/{leaderboard_type}  (paginated) ────────────────

@router.get("/{sim_id}/leaderboards/{leaderboard_type}")
def leaderboard(
    sim_id: str,
    leaderboard_type: str,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    if leaderboard_type not in _ALL_LEADERBOARDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown leaderboard '{leaderboard_type}'. Valid types: {_ALL_LEADERBOARDS}",
        )

    repo = SimulationRepository()
    try:
        _require_completed(repo, sim_id)
        lb = LeaderboardRepository(repo.dict_cursor)

        if leaderboard_type in _BATTING_LB_TYPES:
            entries, total = lb.batting_aggregate(sim_id, leaderboard_type, limit, offset)
            typed = [BattingAggregateRow(**r) for r in entries]
        elif leaderboard_type == 'highest-score':
            entries, total = lb.highest_score(sim_id, limit, offset)
            typed = [HighestScoreRow(**r) for r in entries]
        elif leaderboard_type in _BOWLING_LB_TYPES:
            entries, total = lb.bowling_aggregate(sim_id, leaderboard_type, limit, offset)
            typed = [BowlingAggregateRow(**r) for r in entries]
        elif leaderboard_type == 'best-bowling-figures':
            entries, total = lb.best_bowling_figures(sim_id, limit, offset)
            typed = [BestFiguresRow(**r) for r in entries]
        else:  # mvp
            entries, total = lb.mvp(sim_id, limit, offset)
            typed = [MVPRow(**r) for r in entries]
    finally:
        repo.close()

    return PaginatedLeaderboard(
        leaderboard=leaderboard_type,
        sim_id=sim_id,
        total=total,
        limit=limit,
        offset=offset,
        entries=typed,
    )


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
