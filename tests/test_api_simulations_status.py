"""
Tests for GET /simulations/{sim_id}/status (api/routes/simulations.py).

No live DB connection required - SimulationRepository is monkeypatched with a
fake in the module's own namespace (it's imported by name there), and
get_tournament_progress is monkeypatched the same way to control the
in-process progress store without touching api.worker's real dict.
"""
import pytest
from fastapi.testclient import TestClient

import api.routes.simulations as sim_routes
from api.main import app


class _FakeSimulationRepository:
    def __init__(self, sim_row, matches=None):
        self._sim_row = sim_row
        self._matches = matches or []

    def get_simulation(self, sim_id: str):
        return self._sim_row

    def get_matches_for_sim(self, sim_id: str):
        return self._matches

    def close(self):
        pass


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


class TestStatusRoute:

    def test_includes_progress_fields_when_tournament_is_tracked(self, client, monkeypatch):
        monkeypatch.setattr(
            sim_routes, "SimulationRepository",
            lambda: _FakeSimulationRepository({"status": "running", "error_message": None}),
        )
        monkeypatch.setattr(sim_routes, "get_tournament_progress", lambda sim_id: {
            "completed": 4, "total": 10, "teams": 8, "total_deliveries": 4800,
            "results": [{"label": "Match 1", "text": "India vs Australia - India won by 5 wickets"}],
        })

        resp = client.get("/cricsimapi/simulations/some-sim/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["matches_completed"] == 4
        assert body["matches_total"] == 10
        assert body["teams"] == 8
        assert body["total_deliveries"] == 4800
        assert body["results"] == [{"label": "Match 1", "text": "India vs Australia - India won by 5 wickets"}]

    def test_omits_progress_fields_for_single_match_or_untracked_job(self, client, monkeypatch):
        monkeypatch.setattr(
            sim_routes, "SimulationRepository",
            lambda: _FakeSimulationRepository({"status": "running", "error_message": None}),
        )
        monkeypatch.setattr(sim_routes, "get_tournament_progress", lambda sim_id: None)

        resp = client.get("/cricsimapi/simulations/some-sim/status")

        assert resp.status_code == 200
        body = resp.json()
        assert "matches_completed" not in body
        assert "matches_total" not in body
        assert "teams" not in body
        assert "total_deliveries" not in body
        assert "results" not in body

    def test_404_for_unknown_sim(self, client, monkeypatch):
        monkeypatch.setattr(sim_routes, "SimulationRepository", lambda: _FakeSimulationRepository(None))

        resp = client.get("/cricsimapi/simulations/does-not-exist/status")

        assert resp.status_code == 404

    def test_includes_match_id_for_completed_match_sim(self, client, monkeypatch):
        monkeypatch.setattr(
            sim_routes, "SimulationRepository",
            lambda: _FakeSimulationRepository(
                {"status": "completed", "error_message": None, "simulation_type": "match"},
                matches=[{"match_id": 42}],
            ),
        )
        monkeypatch.setattr(sim_routes, "get_tournament_progress", lambda sim_id: None)

        resp = client.get("/cricsimapi/simulations/some-sim/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["simulation_type"] == "match"
        assert body["match_id"] == 42

    def test_omits_match_id_while_match_sim_still_running(self, client, monkeypatch):
        monkeypatch.setattr(
            sim_routes, "SimulationRepository",
            lambda: _FakeSimulationRepository(
                {"status": "running", "error_message": None, "simulation_type": "match"},
                matches=[{"match_id": 42}],
            ),
        )
        monkeypatch.setattr(sim_routes, "get_tournament_progress", lambda sim_id: None)

        resp = client.get("/cricsimapi/simulations/some-sim/status")

        assert resp.status_code == 200
        body = resp.json()
        assert "match_id" not in body

    def test_omits_match_id_for_completed_tournament_sim(self, client, monkeypatch):
        monkeypatch.setattr(
            sim_routes, "SimulationRepository",
            lambda: _FakeSimulationRepository(
                {"status": "completed", "error_message": None, "simulation_type": "tournament"},
            ),
        )
        monkeypatch.setattr(sim_routes, "get_tournament_progress", lambda sim_id: None)

        resp = client.get("/cricsimapi/simulations/some-sim/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["simulation_type"] == "tournament"
        assert "match_id" not in body

    def test_includes_queue_position_while_pending(self, client, monkeypatch):
        monkeypatch.setattr(
            sim_routes, "SimulationRepository",
            lambda: _FakeSimulationRepository(
                {"status": "pending", "error_message": None, "simulation_type": "tournament"},
            ),
        )
        monkeypatch.setattr(sim_routes, "get_tournament_progress", lambda sim_id: None)
        monkeypatch.setattr(sim_routes.job_queue, "position", lambda job_id: 2)

        resp = client.get("/cricsimapi/simulations/some-sim/status")

        assert resp.status_code == 200
        assert resp.json()["queue_position"] == 2

    def test_omits_queue_position_once_running(self, client, monkeypatch):
        monkeypatch.setattr(
            sim_routes, "SimulationRepository",
            lambda: _FakeSimulationRepository(
                {"status": "running", "error_message": None, "simulation_type": "tournament"},
            ),
        )
        monkeypatch.setattr(sim_routes, "get_tournament_progress", lambda sim_id: None)
        monkeypatch.setattr(sim_routes.job_queue, "position", lambda job_id: 0)

        resp = client.get("/cricsimapi/simulations/some-sim/status")

        assert resp.status_code == 200
        assert "queue_position" not in resp.json()
