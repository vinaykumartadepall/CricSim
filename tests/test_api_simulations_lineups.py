"""
GET /simulations/{sim_id}/lineups (api/routes/simulations.py) - headshot_url
wiring specifically. This endpoint previously joined history.players for
name/role only, never cricinfo_id, so squad-preview cards (ResultsPage's
TeamPreviewPanel, the leaderboard's squad popup) always fell back to
initials-only avatars even for real, photographed players.

No live DB - SimulationRepository is monkeypatched with a fake in the
module's own namespace, matching tests/test_api_simulations_status.py.
"""
import pytest
from fastapi.testclient import TestClient

import api.routes.simulations as sim_routes
from api.main import app


class _FakeDictCursor:
    """Returns queued fetchall() results in the order queries are executed
    (batting aggregate, then bowling aggregate, then the cricinfo_id lookup)."""

    def __init__(self, results):
        self._results = list(results)
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchall(self):
        return self._results.pop(0)


class _FakeSimulationRepository:
    def __init__(self, sim_row, dict_cursor, awards=None):
        self._sim_row = sim_row
        self.dict_cursor = dict_cursor
        self._awards = awards or []

    def get_simulation(self, sim_id):
        return self._sim_row

    def get_player_awards(self, sim_id):
        return self._awards

    def close(self):
        pass


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _sim_row():
    return {
        "status": "completed", "simulation_type": "tournament",
        "config": {"teams": [{"name": "Mumbai Indians", "players": ["1"]}]},
    }


class TestLineupsHeadshotUrl:
    def test_headshot_url_derived_from_cricinfo_id(self, client, monkeypatch):
        batting_rows = [{
            "player_id": 1, "player_name": "Rohit Sharma", "player_role": "Batter",
            "team_name": "Mumbai Indians", "matches": 1, "runs": 50, "balls": 30,
        }]
        cur = _FakeDictCursor([batting_rows, [], [{"player_id": 1, "cricinfo_id": 34102}]])
        monkeypatch.setattr(sim_routes, "SimulationRepository", lambda: _FakeSimulationRepository(_sim_row(), cur))

        resp = client.get("/cricsimapi/simulations/sim-1/lineups")

        assert resp.status_code == 200
        players = resp.json()["teams"][0]["players"]
        assert players[0]["headshot_url"] == "https://a.espncdn.com/i/headshots/cricket/players/full/34102.png"

    def test_headshot_url_none_when_player_has_no_cricinfo_id(self, client, monkeypatch):
        batting_rows = [{
            "player_id": 1, "player_name": "Rohit Sharma", "player_role": "Batter",
            "team_name": "Mumbai Indians", "matches": 1, "runs": 50, "balls": 30,
        }]
        cur = _FakeDictCursor([batting_rows, [], [{"player_id": 1, "cricinfo_id": None}]])
        monkeypatch.setattr(sim_routes, "SimulationRepository", lambda: _FakeSimulationRepository(_sim_row(), cur))

        resp = client.get("/cricsimapi/simulations/sim-1/lineups")

        assert resp.json()["teams"][0]["players"][0]["headshot_url"] is None

    def test_bowler_with_no_batting_row_still_gets_a_headshot(self, client, monkeypatch):
        """cricinfo_id is looked up for every player_id seen anywhere (batting,
        bowling, or awards), not just those with a batting row - a pure bowler
        who never batted must not silently lose their photo."""
        bowling_rows = [{"player_id": 7, "team_name": "Mumbai Indians", "wickets": 3}]
        cur = _FakeDictCursor([[], bowling_rows, [{"player_id": 7, "cricinfo_id": 8917}]])
        sim_row = {
            "status": "completed", "simulation_type": "tournament",
            "config": {"teams": [{"name": "Mumbai Indians", "players": ["7"]}]},
        }
        monkeypatch.setattr(sim_routes, "SimulationRepository", lambda: _FakeSimulationRepository(sim_row, cur))

        resp = client.get("/cricsimapi/simulations/sim-1/lineups")

        players = resp.json()["teams"][0]["players"]
        assert players[0]["headshot_url"] == "https://a.espncdn.com/i/headshots/cricket/players/full/8917.png"
