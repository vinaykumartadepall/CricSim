"""
Read-only repository for List-of-Values (LOV) data used by the UI.

All queries are delegated to SquadRepository which reads from
simulation.tournament_seeded.config — no runtime deliveries scans.
"""

from __future__ import annotations

from typing import Any

from db.squad_repository import SquadRepository


class LovRepository:
    def __init__(self):
        self._squads = SquadRepository()

    def close(self):
        self._squads.close()

    # ── Tournaments ────────────────────────────────────────────────────────────

    def get_tournaments(self, search: str | None = None) -> list[dict[str, Any]]:
        """Return only seeded tournaments (have squads), optionally filtered by name."""
        return self._squads.get_seeded_tournaments(search=search)

    # ── Squads ─────────────────────────────────────────────────────────────────

    def get_tournament_squads(self, tournament_id: int) -> dict[str, Any]:
        return self._squads.get_squads(tournament_id)

    def get_underdog_team_seasons(self, tournament_name: str) -> list[dict]:
        return self._squads.get_underdog_team_seasons(tournament_name)
