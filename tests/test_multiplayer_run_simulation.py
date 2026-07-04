"""
Tests for api.routes.multiplayer._run_simulation's on_sim_created callback.

The callback lets the websocket layer tell clients the sim_id as soon as the
simulation.simulations row exists, instead of waiting for the full run (which
can take 10-30s) to finish — this is what lets the multiplayer draft hand off
to the shared SimulatingPage instead of showing its own bare spinner.

No live DB connection required — SimulationRepository, run_match_job,
run_tournament_job, and _save_multiplayer_game_sessions are all monkeypatched
(the first three are imported locally inside _run_simulation, so patching the
modules they're imported from is picked up at call time).
"""
import db.simulation_repository as sim_repo_mod
import api.worker as worker_mod
import api.routes.multiplayer as mp_routes
from api.multiplayer.manager import Member, RoomState


class _FakeCursor:
    def execute(self, *a, **kw):
        pass

    def fetchone(self):
        return (99,)


class _FakeRepo:
    def __init__(self, sim_id="sim-123"):
        self.sim_id = sim_id
        self.cur = _FakeCursor()
        self.committed = False

    def create_simulation(self, *a, **kw):
        return self.sim_id

    def commit(self):
        self.committed = True

    def close(self):
        pass


def _make_room(mode: str, n_members: int) -> RoomState:
    room = RoomState(
        room_id="room-1", host_id="p0", mode=mode,
        tournament_name="Test Cup", player_count=n_members, match_format="T20",
    )
    for i in range(n_members):
        room.members[f"p{i}"] = Member(client_id=f"p{i}", display_name=f"Player {i}", draft_order=i)
    return room


class TestRunSimulationCallsOnSimCreatedEarly:

    def test_1v1_calls_on_sim_created_before_run_match_job(self, monkeypatch):
        monkeypatch.setattr(sim_repo_mod, "SimulationRepository", lambda: _FakeRepo())
        monkeypatch.setattr(mp_routes, "_save_multiplayer_game_sessions", lambda *a, **kw: None)
        calls = []
        monkeypatch.setattr(worker_mod, "run_match_job", lambda *a, **kw: calls.append("run_match_job"))

        room = _make_room("1v1", 2)
        seen_sim_ids = []
        sim_id, match_id = mp_routes._run_simulation(room, on_sim_created=seen_sim_ids.append)

        assert seen_sim_ids == ["sim-123"]  # called, and before run_match_job
        assert calls == ["run_match_job"]
        assert sim_id == "sim-123"
        assert match_id == 99

    def test_tournament_calls_on_sim_created_before_run_tournament_job(self, monkeypatch):
        monkeypatch.setattr(sim_repo_mod, "SimulationRepository", lambda: _FakeRepo())
        monkeypatch.setattr(mp_routes, "_save_multiplayer_game_sessions", lambda *a, **kw: None)
        calls = []
        monkeypatch.setattr(worker_mod, "run_tournament_job", lambda *a, **kw: calls.append("run_tournament_job"))

        room = _make_room("tournament", 4)
        seen_sim_ids = []
        sim_id, match_id = mp_routes._run_simulation(room, on_sim_created=seen_sim_ids.append)

        assert seen_sim_ids == ["sim-123"]
        assert calls == ["run_tournament_job"]
        assert sim_id == "sim-123"
        assert match_id is None
