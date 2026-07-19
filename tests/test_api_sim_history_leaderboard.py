"""
/cricsimapi/sim-history/{leaderboard,my-ranks,leaderboards-enabled} routes
(api/routes/sim_history.py). No live DB - SimulationRepository and the
shared username lookup are monkeypatched with fakes.
"""
import api.routes.sim_history as sim_history_mod
from fastapi.testclient import TestClient

from api.main import app
from simulator.admin_settings import get_admin_settings

client = TestClient(app)


class _FakeRepo:
    def __init__(self, rows, you=None):
        self._rows = rows
        self._you = you

    def get_challenge_leaderboard(self, client_id, tournament_id, team_name, mode, limit=10, offset=0):
        assert tournament_id == 3039
        assert team_name == "Mumbai Indians"
        assert mode == "challenge"
        return {"you": self._you, "entries": self._rows, "total_entrants": len(self._rows)}

    def get_my_challenge_ranks(self, client_id, tournament_id, mode):
        assert tournament_id == 3039
        assert mode == "challenge"
        return self._rows

    def close(self):
        pass


def _leaderboard_rows():
    return [
        {"client_id": "a", "best_placement": "Winner", "swap_count": 0,
         "win_pct": 1.0, "sim_id": "s1", "is_you": True, "rank": 1},
        {"client_id": "b", "best_placement": "Runner-up", "swap_count": 2,
         "win_pct": 0.5, "sim_id": "s2", "is_you": False, "rank": 2},
    ]


class TestChallengeLeaderboardRoute:

    def setup_method(self):
        self._original = get_admin_settings().leaderboards_enabled
        get_admin_settings().leaderboards_enabled = True

    def teardown_method(self):
        get_admin_settings().leaderboards_enabled = self._original

    def test_happy_path_shape(self, monkeypatch):
        monkeypatch.setattr(sim_history_mod, "SimulationRepository", lambda: _FakeRepo(_leaderboard_rows()))
        monkeypatch.setattr(sim_history_mod, "_display_names_for", lambda ids: {"a": "Alice"})

        resp = client.get("/cricsimapi/sim-history/leaderboard", params={
            "client_id": "a", "tournament_id": 3039, "team_name": "Mumbai Indians", "mode": "challenge",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_entrants"] == 2
        first, second = body["entries"]
        assert first["username"] == "Alice"
        assert first["is_you"] is True
        assert first["win_pct"] == 1.0
        assert second["username"] == "Anonymous Player"  # no identity_links row
        assert second["is_you"] is False

    def test_invalid_mode_is_422(self):
        resp = client.get("/cricsimapi/sim-history/leaderboard", params={
            "client_id": "a", "tournament_id": 3039, "team_name": "Mumbai Indians", "mode": "multiplayer",
        })
        assert resp.status_code == 422

    def test_missing_mode_is_422(self):
        resp = client.get("/cricsimapi/sim-history/leaderboard", params={
            "client_id": "a", "tournament_id": 3039, "team_name": "Mumbai Indians",
        })
        assert resp.status_code == 422

    def test_disabled_is_503(self):
        get_admin_settings().leaderboards_enabled = False
        resp = client.get("/cricsimapi/sim-history/leaderboard", params={
            "client_id": "a", "tournament_id": 3039, "team_name": "Mumbai Indians", "mode": "challenge",
        })
        assert resp.status_code == 503

    def test_you_included_even_when_outside_the_page(self, monkeypatch):
        you = {"client_id": "a", "best_placement": "Group stage", "swap_count": 2,
               "win_pct": 0.36, "sim_id": "s99", "is_you": True, "rank": 47}
        monkeypatch.setattr(sim_history_mod, "SimulationRepository", lambda: _FakeRepo(_leaderboard_rows(), you=you))
        monkeypatch.setattr(sim_history_mod, "_display_names_for", lambda ids: {"a": "Alice"})

        resp = client.get("/cricsimapi/sim-history/leaderboard", params={
            "client_id": "a", "tournament_id": 3039, "team_name": "Mumbai Indians", "mode": "challenge",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["you"]["rank"] == 47
        assert body["you"]["username"] == "Alice"

    def test_you_is_null_when_caller_has_no_attempt(self, monkeypatch):
        monkeypatch.setattr(sim_history_mod, "SimulationRepository", lambda: _FakeRepo(_leaderboard_rows()))
        monkeypatch.setattr(sim_history_mod, "_display_names_for", lambda ids: {})

        resp = client.get("/cricsimapi/sim-history/leaderboard", params={
            "client_id": "a", "tournament_id": 3039, "team_name": "Mumbai Indians", "mode": "challenge",
        })
        assert resp.json()["you"] is None

    def test_offset_at_cap_is_422(self):
        resp = client.get("/cricsimapi/sim-history/leaderboard", params={
            "client_id": "a", "tournament_id": 3039, "team_name": "Mumbai Indians", "mode": "challenge",
            "offset": 100,
        })
        assert resp.status_code == 422

    def test_limit_above_cap_is_422(self):
        resp = client.get("/cricsimapi/sim-history/leaderboard", params={
            "client_id": "a", "tournament_id": 3039, "team_name": "Mumbai Indians", "mode": "challenge",
            "limit": 101,
        })
        assert resp.status_code == 422

    def test_limit_clamped_to_remaining_room_under_cap(self, monkeypatch):
        seen = {}

        class _CapturingRepo(_FakeRepo):
            def get_challenge_leaderboard(self, client_id, tournament_id, team_name, mode, limit=10, offset=0):
                seen["limit"], seen["offset"] = limit, offset
                return super().get_challenge_leaderboard(client_id, tournament_id, team_name, mode, limit, offset)

        monkeypatch.setattr(sim_history_mod, "SimulationRepository", lambda: _CapturingRepo(_leaderboard_rows()))
        monkeypatch.setattr(sim_history_mod, "_display_names_for", lambda ids: {})

        resp = client.get("/cricsimapi/sim-history/leaderboard", params={
            "client_id": "a", "tournament_id": 3039, "team_name": "Mumbai Indians", "mode": "challenge",
            "limit": 50, "offset": 90,
        })
        assert resp.status_code == 200
        assert seen == {"limit": 10, "offset": 90}  # 90 + 50 would exceed 100 -> clamped to 10


class TestMyChallengeRanksRoute:

    def setup_method(self):
        self._original = get_admin_settings().leaderboards_enabled
        get_admin_settings().leaderboards_enabled = True

    def teardown_method(self):
        get_admin_settings().leaderboards_enabled = self._original

    def test_happy_path_shape(self, monkeypatch):
        rows = [{"team_name": "CSK", "rank": 2, "total_entrants": 5,
                  "best_placement": "Runner-up", "swap_count": 1, "win_pct": 0.6}]
        monkeypatch.setattr(sim_history_mod, "SimulationRepository", lambda: _FakeRepo(rows))

        resp = client.get("/cricsimapi/sim-history/my-ranks", params={
            "client_id": "a", "tournament_id": 3039, "mode": "challenge",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body == [{"team_name": "CSK", "rank": 2, "total_entrants": 5,
                          "best_placement": "Runner-up", "swap_count": 1, "win_pct": 0.6}]

    def test_invalid_mode_is_422(self):
        resp = client.get("/cricsimapi/sim-history/my-ranks", params={
            "client_id": "a", "tournament_id": 3039, "mode": "fun-mode-typo",
        })
        assert resp.status_code == 422

    def test_disabled_is_503(self):
        get_admin_settings().leaderboards_enabled = False
        resp = client.get("/cricsimapi/sim-history/my-ranks", params={
            "client_id": "a", "tournament_id": 3039, "mode": "challenge",
        })
        assert resp.status_code == 503


class TestLeaderboardsEnabledRoute:
    """Public (unauthenticated) read of the admin kill switch - regular users
    aren't admins and can't hit /admin/leaderboards-enabled, but the frontend
    still needs to know whether to show the button/rank hints at all."""

    def setup_method(self):
        self._original = get_admin_settings().leaderboards_enabled

    def teardown_method(self):
        get_admin_settings().leaderboards_enabled = self._original

    def test_reflects_enabled(self):
        get_admin_settings().leaderboards_enabled = True
        resp = client.get("/cricsimapi/sim-history/leaderboards-enabled")
        assert resp.status_code == 200
        assert resp.json() == {"enabled": True}

    def test_reflects_disabled(self):
        get_admin_settings().leaderboards_enabled = False
        resp = client.get("/cricsimapi/sim-history/leaderboards-enabled")
        assert resp.status_code == 200
        assert resp.json() == {"enabled": False}

    def test_no_auth_required(self):
        # No Authorization header, no dependency override - must not 401/403.
        resp = client.get("/cricsimapi/sim-history/leaderboards-enabled")
        assert resp.status_code == 200
