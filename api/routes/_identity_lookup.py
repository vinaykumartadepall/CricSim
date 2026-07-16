"""Shared batched username lookup for cross-user list/leaderboard routes."""
from db.identity_repository import IdentityRepository
from simulator.logger import get_logger


def display_names_for(client_ids: set) -> dict:
    """identity_links can't be joined into the main list query (raw
    client_ids there may be un-resolved historical ids), so fetch usernames
    in one batched lookup instead. Best effort: the caller's list must still
    render (ids only) if this lookup fails."""
    if not client_ids:
        return {}
    try:
        repo = IdentityRepository()
        try:
            return repo.get_usernames(list(client_ids))
        finally:
            repo.close()
    except Exception:
        get_logger().exception("Identity username lookup failed")
        return {}
