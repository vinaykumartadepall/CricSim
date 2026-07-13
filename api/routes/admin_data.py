"""
Read-only admin data views - cross-user queries with no client_id filter.

Every route here is mounted in api/main.py with the require_admin_user guard
(verified Supabase JWT in ADMIN_USER_IDS), which is what makes the unfiltered
queries acceptable. Keep this router strictly read-only: mutations belong on
the regular admin router, and per-user views belong on the public routes.
"""
from fastapi import APIRouter, Query

from api.models.responses import AdminSimListResponse
from db.profile_repository import ProfileRepository
from db.simulation_repository import SimulationRepository
from simulator.logger import get_logger

router = APIRouter(prefix="/admin/data", tags=["admin-data"])


def _display_names_for(client_ids: set) -> dict:
    """Profiles live in the separate Supabase DB, so names can't be joined in
    the main list query - fetch them in one batched lookup instead. Best
    effort: the list must still render (ids only) if Supabase is unreachable."""
    if not client_ids:
        return {}
    try:
        repo = ProfileRepository()
        try:
            return repo.get_display_names(list(client_ids))
        finally:
            repo.close()
    except Exception:
        get_logger().exception("Admin data: profile display-name lookup failed")
        return {}


@router.get("/simulations", response_model=AdminSimListResponse)
def list_all_simulations(limit: int = Query(50, le=200), offset: int = Query(0, ge=0)):
    """Every user's simulations, newest first, failed ones included."""
    repo = SimulationRepository()
    try:
        rows = repo.list_simulations(limit=limit, offset=offset, client_id=None, admin_view=True)
    finally:
        repo.close()

    total = rows[0]["total_count"] if rows else 0
    names = _display_names_for({r["client_id"] for r in rows if r.get("client_id")})
    for r in rows:
        r.pop("total_count", None)
        r["display_name"] = names.get(r.get("client_id"))
    return {"simulations": rows, "total": total}
