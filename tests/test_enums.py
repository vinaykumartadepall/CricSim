"""
enums/domain.py - the single definition of the shared vocabularies - and every
consumer that has to agree with it: the format alias maps, db/schema.sql and
migration 037 CHECK constraints, the generated frontend types, the API request
models, and the raw-vs-unified format fixes (A8/A9) that came with it.
"""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.routes.simulations as sim_routes
import db.precompute as precompute
import db.stats_repository as stats_repository
from api.main import app
from enums import ts_export
from enums.domain import (
    RAW_VALUES_BY_FORMAT, Gender, GameMode, MatchFormat, MatchLevel, MatchResult,
    RawMatchFormat, SimStatus, SimulationType,
)
from parser.cricsheet_parser import CricsheetParser
from simulator.entities.rules import MatchRules

REPO = Path(__file__).resolve().parent.parent
SCHEMA = (REPO / "db" / "schema.sql").read_text()
MIGRATION_037 = (REPO / "db" / "migrations" / "037_vocabulary_checks.sql").read_text()


class TestMatchFormat:
    @pytest.mark.parametrize("raw, unified", [
        ("Test", "Test"), ("MDM", "Test"), ("ODI", "ODI"), ("ODM", "ODI"),
        ("T20", "T20"), ("IT20", "T20"), (" IT20 ", "T20"),
    ])
    def test_from_raw(self, raw, unified):
        assert MatchFormat.from_raw(raw) == unified

    def test_every_raw_format_maps_somewhere(self):
        assert {MatchFormat.from_raw(r) for r in RawMatchFormat} == set(MatchFormat)

    @pytest.mark.parametrize("bad", ["t20", "ONE DAY", "", None])
    def test_from_raw_rejects_unknown(self, bad):
        with pytest.raises(ValueError):
            MatchFormat.from_raw(bad)

    def test_raw_values_are_the_sql_filter_direction(self):
        assert RAW_VALUES_BY_FORMAT == {
            "T20": ["T20", "IT20"], "ODI": ["ODI", "ODM"], "Test": ["Test", "MDM"],
        }

    def test_precompute_and_stats_repository_use_the_one_mapping(self):
        assert precompute._FORMAT_ALIASES is RAW_VALUES_BY_FORMAT
        assert stats_repository._FORMAT_ALIASES is RAW_VALUES_BY_FORMAT
        assert precompute._FORMATS == ["T20", "ODI", "Test"]

    def test_unified_format_keeps_its_lenient_contract(self):
        assert MatchRules.get_unified_format("MDM") == "Test"
        assert MatchRules.get_unified_format("weird") == "weird"
        assert MatchRules.get_unified_format("") == "UNKNOWN"

    def test_members_behave_as_plain_strings(self):
        assert MatchFormat.TEST == "Test"
        assert f"{MatchFormat.TEST}" == "Test"
        assert json.dumps({"f": MatchFormat.ODI}) == '{"f": "ODI"}'


class TestGeneratedTypescript:
    def test_frontend_enums_file_is_up_to_date(self):
        assert ts_export.TS_PATH.read_text(encoding="utf-8") == ts_export.render(), \
            "run: python -m enums.ts_export"

    def test_render_shape(self):
        out = ts_export.render()
        assert "export const MATCH_FORMATS = ['T20', 'ODI', 'Test'] as const" in out
        assert "export type SimStatus = (typeof SIM_STATUSES)[number]" in out
        assert "export const MATCH_RESULTS = ['win', 'tie', 'no result'] as const" in out


def _check_values(sql: str, table: str, column: str) -> list:
    """Values of `column IN (...)` inside table's CREATE TABLE in schema.sql."""
    m = re.search(rf"CREATE TABLE IF NOT EXISTS {re.escape(table)} \((.*?)\n\);", sql, re.S)
    assert m, table
    c = re.search(rf"\b{column}\b[^\n]*?(?:\n\s+)?CHECK \([^)]*?\b{column} IN \(([^)]*)\)", m.group(1))
    assert c, f"no CHECK on {table}.{column} in schema.sql"
    return [v.strip().strip("'") for v in c.group(1).split(",")]


def _migration_values(table: str, column: str) -> list:
    name = f"{table.split('.')[1]}_{column}_check"
    m = re.search(rf"ADD\s+CONSTRAINT {name}\s+CHECK \([^)]*?\b{column} IN \(([^)]*)\)",
                  MIGRATION_037[MIGRATION_037.index(f"ALTER TABLE {table}\n"):])
    assert m, name
    return [v.strip().strip("'") for v in m.group(1).split(",")]


CHECKED_COLUMNS = [
    ("simulation.simulations", "simulation_type", SimulationType),
    ("simulation.simulations", "status", SimStatus),
    ("simulation.simulations", "mode", GameMode),
    ("simulation.game_sessions", "mode", GameMode),
    ("simulation.tournaments", "format", MatchFormat),
    ("simulation.tournaments", "gender", Gender),
    ("simulation.matches", "match_format", MatchFormat),
    ("simulation.matches", "result", MatchResult),
    ("simulation.matches", "gender", Gender),
    ("history.matches", "match_format", RawMatchFormat),
    ("history.matches", "match_type", MatchLevel),
    ("history.matches", "gender", Gender),
]


class TestDatabaseChecksMatchEnums:
    @pytest.mark.parametrize("table, column, enum", CHECKED_COLUMNS)
    def test_schema_sql(self, table, column, enum):
        assert _check_values(SCHEMA, table, column) == enum.values()

    @pytest.mark.parametrize("table, column, enum", CHECKED_COLUMNS)
    def test_migration_037(self, table, column, enum):
        assert _migration_values(table, column) == enum.values()

    def test_existing_precomputed_and_rooms_checks_use_the_format_enum(self):
        lists = re.findall(r"CHECK \(match_format IN \(([^)]*)\)\)", SCHEMA)
        assert lists
        for vals in lists:
            assert [v.strip().strip("'") for v in vals.split(",")] == MatchFormat.values()


class TestFreshSchemaEnforcesChecks:
    """DB tier: a database built from schema.sql rejects values outside the enums."""

    def test_rejects_unknown_values_accepts_valid_ones(self, make_db):
        import psycopg2
        db = make_db()
        conn = db.connect("test:checks")
        cur = conn.cursor()
        insert = ("INSERT INTO simulation.simulations (sim_id, simulation_type, status, mode, config) "
                  "VALUES (%s, %s, %s, %s, '{}')")
        from uuid import uuid4
        cur.execute(insert, (str(uuid4()), "match", "pending", None))
        cur.execute(insert, (str(uuid4()), SimulationType.TOURNAMENT, SimStatus.COMPLETED, GameMode.CUSTOM))
        for bad in [(str(uuid4()), "matchh", "pending", None), (str(uuid4()), "match", "done", None),
                    (str(uuid4()), "match", "pending", "Fun")]:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(insert, bad)
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO history.matches (match_format) VALUES ('ONE DAY')")
        conn.close()


class TestMigration037OnExistingDb:
    """DB tier: 037 applies cleanly to a database without the CHECKs, fixes MDM rows, and re-runs."""

    def _strip_checks(self, cur):
        for table, column, _ in CHECKED_COLUMNS:
            cur.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table.split('.')[1]}_{column}_check")

    def test_applies_fixes_mdm_and_is_rerunnable(self, make_db):
        db = make_db()
        conn = db.connect("test:037")
        cur = conn.cursor()
        self._strip_checks(cur)
        cur.execute("INSERT INTO history.matches (match_format, innings_per_match, overs_per_innings) "
                    "VALUES ('MDM', 2, 20), ('T20', 2, 20) RETURNING match_id")
        mdm_id, t20_id = (r[0] for r in cur.fetchall())
        body = MIGRATION_037.replace("BEGIN;", "").replace("COMMIT;", "")
        cur.execute(body)
        cur.execute(body)          # idempotent
        cur.execute("SELECT match_id, innings_per_match, overs_per_innings FROM history.matches ORDER BY match_id")
        assert cur.fetchall() == [(mdm_id, 4, None), (t20_id, 2, 20)]
        cur.execute("SELECT count(*) FROM pg_constraint WHERE conname LIKE '%%_check' "
                    "AND conname = ANY(%s)", ([f"{t.split('.')[1]}_{c}_check" for t, c, _ in CHECKED_COLUMNS],))
        assert cur.fetchone()[0] == len(CHECKED_COLUMNS)
        conn.close()


class TestRawFormatFixes:
    def _parse_as(self, tmp_path, match_type):
        src = json.loads((REPO / "tests" / "fixtures" / "cricsheet" / "1534186.json").read_text())
        src["info"]["match_type"] = match_type
        f = tmp_path / "m.json"
        f.write_text(json.dumps(src))
        return CricsheetParser.parse(str(f)).match

    def test_parser_stores_multi_day_as_four_innings(self, tmp_path):
        m = self._parse_as(tmp_path, "MDM")
        assert (m.innings_per_match, m.overs_per_innings) == (4, None)

    def test_parser_keeps_limited_overs_shape(self, tmp_path):
        m = self._parse_as(tmp_path, "ODM")
        assert m.innings_per_match == 2


class _FakeSimRepo:
    def __init__(self, sim, matches):
        self._sim, self._matches = sim, matches
        self.dict_cursor = None

    def get_simulation(self, sim_id):
        return self._sim

    def get_matches_for_sim(self, sim_id):
        return self._matches

    def close(self):
        pass


class _NoDbRepo:
    """Stands in for SimulationRepository in request-validation tests: a request
    that wrongly passes validation fails the test here instead of creating a
    real simulation row and job (which an early version of these tests did)."""
    def __init__(self):
        raise AssertionError("request passed validation and reached the database")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def no_db(monkeypatch):
    monkeypatch.setattr(sim_routes, "SimulationRepository", _NoDbRepo)
    monkeypatch.setattr(sim_routes.job_queue, "submit",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("job submitted")))
    import api.routes.sim_history as hist_routes
    monkeypatch.setattr(hist_routes, "SimulationRepository", _NoDbRepo)


class TestApiBoundary:
    def test_result_reports_match_format_of_a_match_sim(self, client, monkeypatch):   # A8
        match_row = {"home_team": "A", "away_team": "B", "winner": "A", "win_type": "runs",
                     "win_by": 12, "result": "win"}
        monkeypatch.setattr(sim_routes, "SimulationRepository", lambda: _FakeSimRepo(
            {"status": "completed", "simulation_type": "match", "config": {"match_format": "ODI"}},
            [match_row]))
        monkeypatch.setattr(sim_routes, "_fetch_venue", lambda cur, sim_id: None)
        resp = client.get("/cricsimapi/simulations/s1/result")
        assert resp.status_code == 200
        assert resp.json()["format"] == "ODI"

    @pytest.mark.parametrize("field, value", [("match_format", "odi"), ("match_format", "T-20")])
    def test_match_request_rejects_unknown_format(self, client, no_db, field, value):
        body = {"simulation_type": "match", field: value,
                "team_a": {"name": "A", "players": [1]}, "team_b": {"name": "B", "players": [2]}}
        assert TestClient(app, raise_server_exceptions=False).post(
            "/cricsimapi/simulations/createsim", json=body).status_code == 422

    @pytest.mark.parametrize("field, value", [("format", "t20"), ("gender", "Female")])
    def test_tournament_request_rejects_unknown_values(self, client, no_db, field, value):
        body = {"simulation_type": "tournament", "tournament_name": "X", field: value,
                "teams": [{"name": "A", "players": [1]}]}
        assert TestClient(app, raise_server_exceptions=False).post(
            "/cricsimapi/simulations/createsim", json=body).status_code == 422

    def test_sim_history_rejects_unknown_mode(self, client, no_db, as_identity):
        resp = client.get("/cricsimapi/sim-history/best", params={"tournament_id": 1, "mode": "xyz"},
                          headers=as_identity("c"))
        assert resp.status_code == 422
