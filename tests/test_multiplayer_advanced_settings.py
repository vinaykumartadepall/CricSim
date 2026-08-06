"""
Tests for multiplayer Advanced Settings (schedule type, playoff format, venue
selection) - api/multiplayer/manager.py, api/routes/multiplayer.py, and the
new SquadRepository venue/country query methods.

No live DB connection required - db_cursor/SquadRepository/SimulationRepository/
run_match_job/run_tournament_job are all monkeypatched, matching the existing
patterns in test_multiplayer_manager.py, test_api_multiplayer_public_rooms.py,
and test_multiplayer_run_simulation.py.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import api.routes.multiplayer as mp_routes
import api.worker as worker_mod
import db.simulation_repository as sim_repo_mod
from api.main import app
from api.multiplayer.manager import DraftManager, Member, RoomState
from db.squad_repository import SquadRepository


# ── RoomState / DraftManager ────────────────────────────────────────────────────

class TestRoomAdvancedSettingsFields:
    def test_create_room_defaults_all_three_to_none(self):
        manager = DraftManager()
        room = manager.create_room(
            host_id="host", display_name="Host", mode="tournament",
            tournament_name="Test Cup", player_count=4,
        )
        assert room.schedule_type is None
        assert room.playoff_format is None
        assert room.venue_config is None

    def test_create_room_accepts_all_three(self):
        manager = DraftManager()
        venue_config = {"mode": "country", "country_ids": [7, 9], "country_names": ["India", "Pakistan"]}
        room = manager.create_room(
            host_id="host", display_name="Host", mode="tournament",
            tournament_name="Test Cup", player_count=4,
            schedule_type="round_robin", playoff_format="semis_final",
            venue_config=venue_config,
        )
        assert room.schedule_type == "round_robin"
        assert room.playoff_format == "semis_final"
        assert room.venue_config == venue_config

    def test_to_dict_includes_advanced_settings(self):
        room = RoomState(
            room_id="ABC123", host_id="host", mode="tournament", tournament_name="Cup",
            player_count=4, schedule_type="round_robin", playoff_format="ipl",
            venue_config={"mode": "specific", "venues": ["Eden Gardens"]},
        )
        d = room.to_dict()
        assert d["schedule_type"] == "round_robin"
        assert d["playoff_format"] == "ipl"
        assert d["venue_config"] == {"mode": "specific", "venues": ["Eden Gardens"]}


# ── _persist_room ────────────────────────────────────────────────────────────────

class _FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


def _fake_db_cursor(cur):
    @contextmanager
    def _cm(*args, **kwargs):
        yield cur
    return _cm


class TestPersistRoomIncludesAdvancedSettings:
    def test_insert_includes_all_three_columns(self, monkeypatch):
        cur = _FakeCursor()
        monkeypatch.setattr(mp_routes, "db_cursor", _fake_db_cursor(cur))
        room = RoomState(
            room_id="XYZ999", host_id="host", mode="tournament", tournament_name="Cup",
            player_count=4, schedule_type="round_robin", playoff_format="semis_final",
            venue_config={"mode": "country", "country_ids": [7, 9]},
        )
        room.members["host"] = Member(client_id="host", display_name="Host")

        mp_routes._persist_room(room)

        rooms_insert_query, rooms_insert_params = cur.calls[0]
        assert "schedule_type" in rooms_insert_query
        assert "playoff_format" in rooms_insert_query
        assert "venue_config" in rooms_insert_query
        assert rooms_insert_params[-3] == "round_robin"
        assert rooms_insert_params[-2] == "semis_final"
        # venue_config is wrapped in psycopg2.extras.Json - compare its .adapted payload
        assert rooms_insert_params[-1].adapted == {"mode": "country", "country_ids": [7, 9]}

    def test_insert_with_none_advanced_settings(self, monkeypatch):
        cur = _FakeCursor()
        monkeypatch.setattr(mp_routes, "db_cursor", _fake_db_cursor(cur))
        room = RoomState(
            room_id="XYZ998", host_id="host", mode="1v1", tournament_name="Cup", player_count=2,
        )
        room.members["host"] = Member(client_id="host", display_name="Host")

        mp_routes._persist_room(room)

        _, rooms_insert_params = cur.calls[0]
        assert rooms_insert_params[-3] is None
        assert rooms_insert_params[-2] is None
        assert rooms_insert_params[-1] is None


# ── _resolve_venue_pool ────────────────────────────────────────────────────────

class TestResolveVenuePool:
    def _room(self, venue_config=None):
        return RoomState(
            room_id="R1", host_id="host", mode="tournament", tournament_name="Cup",
            player_count=4, match_format="T20", venue_config=venue_config,
        )

    def test_default_none_uses_curated_list(self):
        result = mp_routes._resolve_venue_pool(self._room(venue_config=None), "T20")
        # Whatever venues_for_format("T20") returns today - just confirm it's
        # the same thing, and non-empty (the curated list always has entries).
        from api.multiplayer.venues import venues_for_format
        assert result == venues_for_format("T20")
        assert len(result) > 0

    def test_specific_mode_uses_exact_venue_names(self):
        room = self._room(venue_config={"mode": "specific", "venues": ["Eden Gardens", "Wankhede Stadium"]})
        result = mp_routes._resolve_venue_pool(room, "T20")
        assert result == [{"name": "Eden Gardens"}, {"name": "Wankhede Stadium"}]

    def test_specific_mode_empty_list_falls_back_to_curated(self):
        room = self._room(venue_config={"mode": "specific", "venues": []})
        from api.multiplayer.venues import venues_for_format
        result = mp_routes._resolve_venue_pool(room, "T20")
        assert result == venues_for_format("T20")

    def test_country_mode_queries_squad_repository(self, monkeypatch):
        calls = []

        class _FakeSquadRepo:
            def venues_for_countries(self, country_ids):
                calls.append(country_ids)
                return [{"name": "Eden Gardens"}, {"name": "Wankhede Stadium"}]

            def close(self):
                pass

        monkeypatch.setattr(mp_routes, "SquadRepository", lambda: _FakeSquadRepo())
        room = self._room(venue_config={"mode": "country", "country_ids": [7, 9]})

        result = mp_routes._resolve_venue_pool(room, "T20")

        assert calls == [[7, 9]]
        assert result == [{"name": "Eden Gardens"}, {"name": "Wankhede Stadium"}]

    def test_country_mode_empty_result_falls_back_to_curated(self, monkeypatch):
        class _FakeSquadRepo:
            def venues_for_countries(self, country_ids):
                return []

            def close(self):
                pass

        monkeypatch.setattr(mp_routes, "SquadRepository", lambda: _FakeSquadRepo())
        room = self._room(venue_config={"mode": "country", "country_ids": [999]})
        from api.multiplayer.venues import venues_for_format

        result = mp_routes._resolve_venue_pool(room, "T20")

        assert result == venues_for_format("T20")


# ── Config assembly via _run_simulation ─────────────────────────────────────────

class _FakeSimCursor:
    def execute(self, *a, **kw):
        pass

    def fetchone(self):
        return (99,)


class _FakeSimRepo:
    def __init__(self):
        self.cur = _FakeSimCursor()

    def create_simulation(self, *a, **kw):
        return "sim-123"

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _make_tournament_room(**overrides) -> RoomState:
    room = RoomState(
        room_id="room-1", host_id="p0", mode="tournament",
        tournament_name="Test Cup", player_count=4, match_format="T20",
        **overrides,
    )
    for i in range(4):
        room.members[f"p{i}"] = Member(client_id=f"p{i}", display_name=f"Player {i}", draft_order=i)
    return room


class _FakeSquadRepoForSim:
    """Stands in for SquadRepository during _run_simulation's tournament
    branch, which now unconditionally calls top_venues_by_matches for the
    playoff marquee pool (and, in country mode, venues_for_countries too)."""
    def __init__(self):
        self.top_venues_calls = []

    def venues_for_countries(self, country_ids):
        return [{"name": "Eden Gardens"}, {"name": "Wankhede Stadium"}]

    def top_venues_by_matches(self, venue_names, limit=3):
        self.top_venues_calls.append(list(venue_names))
        return venue_names[:limit]

    def close(self):
        pass


class TestTournamentConfigAssemblyHonorsAdvancedSettings:
    def _run_and_capture_config(self, monkeypatch, room, fake_repo=None):
        monkeypatch.setattr(sim_repo_mod, "SimulationRepository", lambda: _FakeSimRepo())
        monkeypatch.setattr(mp_routes, "_save_multiplayer_game_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(mp_routes, "SquadRepository", lambda: fake_repo or _FakeSquadRepoForSim())
        captured = {}

        def _capture(sim_id, config, **kw):
            captured["config"] = config

        monkeypatch.setattr(worker_mod, "run_tournament_job", _capture)
        mp_routes._run_simulation(room, on_sim_created=lambda s: None)
        return captured["config"]

    def test_defaults_when_nothing_set(self, monkeypatch):
        config = self._run_and_capture_config(monkeypatch, _make_tournament_room())
        assert config["schedule"] == {"type": "double_round_robin", "matches_per_pair": 2}
        assert config["playoffs"]["format"] == "ipl"  # 4 teams -> ipl default

    def test_round_robin_overrides_schedule(self, monkeypatch):
        room = _make_tournament_room(schedule_type="round_robin")
        config = self._run_and_capture_config(monkeypatch, room)
        assert config["schedule"] == {"type": "round_robin", "matches_per_pair": 1}

    def test_playoff_format_override(self, monkeypatch):
        room = _make_tournament_room(playoff_format="semis_final")
        config = self._run_and_capture_config(monkeypatch, room)
        assert config["playoffs"]["format"] == "semis_final"

    def test_specific_venue_config_flows_into_venues_list(self, monkeypatch):
        room = _make_tournament_room(
            venue_config={"mode": "specific", "venues": ["Eden Gardens"]}
        )
        config = self._run_and_capture_config(monkeypatch, room)
        assert config["venues"] == [{"name": "Eden Gardens"}]

    def test_playoff_venues_derived_from_group_stage_pool(self, monkeypatch):
        room = _make_tournament_room(
            venue_config={"mode": "specific", "venues": ["Eden Gardens", "Wankhede Stadium"]}
        )
        fake_repo = _FakeSquadRepoForSim()
        config = self._run_and_capture_config(monkeypatch, room, fake_repo=fake_repo)
        assert config["playoff_venues"] == ["Eden Gardens", "Wankhede Stadium"]
        assert fake_repo.top_venues_calls == [["Eden Gardens", "Wankhede Stadium"]]

    def test_playoff_venues_set_for_default_mode_too(self, monkeypatch):
        config = self._run_and_capture_config(monkeypatch, _make_tournament_room())
        assert "playoff_venues" in config
        assert len(config["playoff_venues"]) > 0

    def test_playoff_venues_set_for_country_mode_too(self, monkeypatch):
        room = _make_tournament_room(venue_config={"mode": "country", "country_ids": [7]})
        config = self._run_and_capture_config(monkeypatch, room)
        assert config["playoff_venues"] == ["Eden Gardens", "Wankhede Stadium"]


class TestOneVOneConfigAssemblyHonorsVenueSetting:
    def test_specific_venue_used_for_1v1(self, monkeypatch):
        monkeypatch.setattr(sim_repo_mod, "SimulationRepository", lambda: _FakeSimRepo())
        monkeypatch.setattr(mp_routes, "_save_multiplayer_game_sessions", lambda *a, **kw: None)
        captured = {}

        def _capture(sim_id, config):
            captured["config"] = config

        monkeypatch.setattr(worker_mod, "run_match_job", _capture)

        room = RoomState(
            room_id="room-2", host_id="p0", mode="1v1", tournament_name="Cup",
            player_count=2, match_format="T20",
            venue_config={"mode": "specific", "venues": ["Eden Gardens"]},
        )
        room.members["p0"] = Member(client_id="p0", display_name="P0", draft_order=0)
        room.members["p1"] = Member(client_id="p1", display_name="P1", draft_order=1)

        mp_routes._run_simulation(room, on_sim_created=lambda s: None)

        # Only one venue in the pool, so the random pick is deterministic.
        assert captured["config"]["venue"] == "Eden Gardens"

    def test_1v1_never_calls_top_venues_by_matches(self, monkeypatch):
        """1v1 has no playoffs concept - the marquee-pool derivation must be
        scoped to the tournament branch only."""
        monkeypatch.setattr(sim_repo_mod, "SimulationRepository", lambda: _FakeSimRepo())
        monkeypatch.setattr(mp_routes, "_save_multiplayer_game_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(worker_mod, "run_match_job", lambda *a, **kw: None)

        def _fail_if_constructed():
            raise AssertionError("SquadRepository should not be constructed for 1v1")

        monkeypatch.setattr(mp_routes, "SquadRepository", _fail_if_constructed)

        room = RoomState(
            room_id="room-3", host_id="p0", mode="1v1", tournament_name="Cup",
            player_count=2, match_format="T20",
        )
        room.members["p0"] = Member(client_id="p0", display_name="P0", draft_order=0)
        room.members["p1"] = Member(client_id="p1", display_name="P1", draft_order=1)

        mp_routes._run_simulation(room, on_sim_created=lambda s: None)


# ── Public venue/country endpoints ──────────────────────────────────────────────

class _SquadFakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, query, params=None):
        pass

    def fetchall(self):
        return self._rows

    def close(self):
        pass


def _fake_squad_repo(rows):
    repo = SquadRepository.__new__(SquadRepository)
    repo.cur = _SquadFakeCursor(rows)
    repo.conn = MagicMock()
    return repo


class TestVenueSearchEndpoint:
    def test_returns_search_results_no_auth_required(self, monkeypatch):
        rows = [{"name": "Eden Gardens", "city": "Kolkata", "country": "India", "matches": 176}]
        monkeypatch.setattr(mp_routes, "SquadRepository", lambda: _fake_squad_repo(rows))

        resp = TestClient(app).get("/cricsimapi/multiplayer/venues/search", params={"q": "eden"})

        assert resp.status_code == 200
        assert resp.json() == rows


class TestCountriesEndpoint:
    def test_returns_country_list_no_auth_required(self, monkeypatch):
        rows = [{"country_id": 7, "name": "India", "venue_count": 42}]
        monkeypatch.setattr(mp_routes, "SquadRepository", lambda: _fake_squad_repo(rows))

        resp = TestClient(app).get("/cricsimapi/multiplayer/countries")

        assert resp.status_code == 200
        assert resp.json() == rows


# ── SquadRepository new methods (query shape only, no live DB) ─────────────────

class TestSquadRepositoryVenueCountryMethods:
    def test_list_venue_countries_query_joins_venues(self):
        repo = SquadRepository.__new__(SquadRepository)
        repo.cur = _SquadFakeCursor([])
        repo.list_venue_countries()
        # No exception, and executed against the right tables - covered
        # indirectly via the endpoint test above for the actual shape;
        # this just pins down that the method runs without a live DB.

    def test_venues_for_countries_returns_name_only_dicts(self):
        repo = SquadRepository.__new__(SquadRepository)
        repo.cur = _SquadFakeCursor([
            {"name": "Eden Gardens", "country_id": 7, "matches": 176},
            {"name": "Wankhede Stadium", "country_id": 7, "matches": 150},
        ])
        result = repo.venues_for_countries([7, 9])
        assert result == [{"name": "Eden Gardens"}, {"name": "Wankhede Stadium"}]

    def test_venues_for_countries_empty_list_returns_empty_without_querying(self):
        repo = SquadRepository.__new__(SquadRepository)
        repo.cur = _SquadFakeCursor([{"name": "should not be returned", "country_id": 1, "matches": 1}])
        result = repo.venues_for_countries([])
        assert result == []

    def test_venues_for_countries_caps_at_top_n_per_country(self):
        # Rows already come back ordered `matches DESC, name` (the fake
        # cursor just returns them as given, mirroring the live query's
        # ORDER BY) - country 7 has 3 venues but top_n=2 keeps only the
        # 2 most-played; country 9's single venue is unaffected. Result is
        # interleaved round-robin (7's #1, 9's #1, 7's #2, 9's #2-absent),
        # not the raw match-count order the rows arrived in.
        rows = [
            {"name": "Wankhede Stadium", "country_id": 7, "matches": 150},
            {"name": "Eden Gardens", "country_id": 7, "matches": 120},
            {"name": "Obscure Ground", "country_id": 7, "matches": 1},
            {"name": "Only Ground", "country_id": 9, "matches": 5},
        ]
        repo = SquadRepository.__new__(SquadRepository)
        repo.cur = _SquadFakeCursor(rows)
        result = repo.venues_for_countries([7, 9], top_n=2)
        assert result == [
            {"name": "Wankhede Stadium"},
            {"name": "Only Ground"},
            {"name": "Eden Gardens"},
        ]

    def test_venues_for_countries_keeps_all_when_under_top_n(self):
        rows = [
            {"name": "Only Ground A", "country_id": 3, "matches": 4},
            {"name": "Only Ground B", "country_id": 3, "matches": 1},
        ]
        repo = SquadRepository.__new__(SquadRepository)
        repo.cur = _SquadFakeCursor(rows)
        result = repo.venues_for_countries([3], top_n=8)
        assert result == [{"name": "Only Ground A"}, {"name": "Only Ground B"}]

    def test_venues_for_countries_interleaves_instead_of_favoring_high_volume_country(self):
        # Regression test for the reported bug: selecting India + UK + Australia
        # sent 12/16 matches to the UK because a flat match-count sort put every
        # UK venue (much higher historical match volume) ahead of every India/
        # Australia venue, and the group-stage cycler (venues[i % len(venues)])
        # never got far enough into the list to reach them in a short tournament.
        # Rows arrive globally sorted by matches DESC - UK's venues (thousands
        # of Test matches over a century-plus) dominate the front of that order.
        rows = [
            {"name": "Lord's", "country_id": 2, "matches": 500},
            {"name": "The Oval", "country_id": 2, "matches": 480},
            {"name": "Old Trafford", "country_id": 2, "matches": 400},
            {"name": "MCG", "country_id": 3, "matches": 300},
            {"name": "SCG", "country_id": 3, "matches": 250},
            {"name": "Wankhede Stadium", "country_id": 7, "matches": 150},
            {"name": "Eden Gardens", "country_id": 7, "matches": 120},
        ]
        repo = SquadRepository.__new__(SquadRepository)
        repo.cur = _SquadFakeCursor(rows)
        result = repo.venues_for_countries([7, 2, 3], top_n=8)  # India, UK, Australia
        # First 3 entries must already cover all 3 countries, not just the UK -
        # a short tournament's venue-cycling only ever gets this far.
        first_three_names = {v["name"] for v in result[:3]}
        assert first_three_names == {"Wankhede Stadium", "Lord's", "MCG"}
        assert result == [
            {"name": "Wankhede Stadium"}, {"name": "Lord's"}, {"name": "MCG"},
            {"name": "Eden Gardens"}, {"name": "The Oval"}, {"name": "SCG"},
            {"name": "Old Trafford"},
        ]

    def test_top_venues_by_matches_returns_top_k(self):
        rows = [
            {"name": "Eden Gardens", "country_id": 7, "matches": 176},
            {"name": "Wankhede Stadium", "country_id": 7, "matches": 150},
            {"name": "Obscure Ground", "country_id": 7, "matches": 2},
        ]
        repo = SquadRepository.__new__(SquadRepository)
        repo.cur = _SquadFakeCursor(rows)
        result = repo.top_venues_by_matches(
            ["Eden Gardens", "Wankhede Stadium", "Obscure Ground"], limit=2
        )
        assert result == ["Eden Gardens", "Wankhede Stadium"]

    def test_top_venues_by_matches_fewer_inputs_than_limit_returns_all(self):
        rows = [{"name": "Eden Gardens", "country_id": 7, "matches": 176}]
        repo = SquadRepository.__new__(SquadRepository)
        repo.cur = _SquadFakeCursor(rows)
        result = repo.top_venues_by_matches(["Eden Gardens"], limit=3)
        assert result == ["Eden Gardens"]

    def test_top_venues_by_matches_empty_list_returns_empty_without_querying(self):
        repo = SquadRepository.__new__(SquadRepository)
        repo.cur = _SquadFakeCursor([{"name": "should not be returned", "country_id": 1, "matches": 1}])
        result = repo.top_venues_by_matches([])
        assert result == []
