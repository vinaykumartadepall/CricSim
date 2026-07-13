"""
Read-only admin data views - cross-user queries with no client_id filter.

Every route here is mounted in api/main.py with the require_admin_user guard
(verified Supabase JWT in ADMIN_USER_IDS), which is what makes the unfiltered
queries acceptable. Keep this router strictly read-only: mutations belong on
the regular admin router, and per-user views belong on the public routes.
"""
from fastapi import APIRouter, Query

from api.models.responses import AdminSimListResponse
from db.simulation_repository import SimulationRepository

router = APIRouter(prefix="/admin/data", tags=["admin-data"])


@router.get("/simulations", response_model=AdminSimListResponse)
def list_all_simulations(limit: int = Query(50, le=200), offset: int = Query(0, ge=0)):
    """Every user's simulations, newest first, failed ones included."""
    repo = SimulationRepository()
    try:
        rows = repo.list_simulations(limit=limit, offset=offset, client_id=None, admin_view=True)
    finally:
        repo.close()

    total = rows[0]["total_count"] if rows else 0
    for r in rows:
        r.pop("total_count", None)
    return {"simulations": rows, "total": total}
