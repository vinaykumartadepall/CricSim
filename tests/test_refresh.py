"""
db/refresh.py: build exports the refreshed history tables, apply merges them
into prod. The DB-tier rehearsal uses two throwaway databases built from
schema.sql - "local" (refreshed data) and "prod" (older data plus user
simulations) - and a real pg_dump/pg_restore round trip. Skipped when no
local Postgres is available.
"""
import re
from pathlib import Path

import pytest

import db.refresh as refresh

SCHEMA_SQL = (Path(__file__).resolve().parent.parent / "db" / "schema.sql").read_text()


# ── DB-free ───────────────────────────────────────────────────────────────────

class TestUpsertSql:
    def test_updates_only_rows_that_differ(self):
        sql = refresh.upsert_sql("players", ("player_id",), ["player_id", "name", "cricinfo_id"])
        assert sql.startswith("INSERT INTO history.players (player_id, name, cricinfo_id) "
                              "SELECT player_id, name, cricinfo_id FROM refresh_stage.players "
                              "ON CONFLICT (player_id) DO UPDATE SET name = EXCLUDED.name, cricinfo_id = EXCLUDED.cricinfo_id")
        assert sql.endswith("WHERE (history.players.name, history.players.cricinfo_id) "
                            "IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.cricinfo_id)")

    def test_key_only_table_does_nothing_on_conflict(self):
        assert refresh.upsert_sql("tournament_teams", ("tournament_id", "team_id"),
                                  ["tournament_id", "team_id"]).endswith("DO NOTHING")


class TestTableLists:
    def test_reference_tables_are_in_foreign_key_order(self):
        order = [t for t, _ in refresh.REFERENCE_TABLES]
        for t in order:
            body = re.search(rf"CREATE TABLE IF NOT EXISTS history\.{t} \((.*?)\n\);", SCHEMA_SQL, re.S).group(1)
            for ref in set(re.findall(r"REFERENCES history\.(\w+)", body)) - {t}:
                assert ref in order and order.index(ref) < order.index(t), f"{t} must come after {ref}"

    def test_never_exports_deliveries_or_simulation_tables(self):
        names = [t for t, _ in refresh.REFERENCE_TABLES] + refresh.PRECOMPUTED_TABLES
        assert "deliveries" not in names
        assert all(re.search(rf"CREATE TABLE IF NOT EXISTS history\.{t} ", SCHEMA_SQL) for t in names)


# ── DB tier: build export -> apply ────────────────────────────────────────────

def _exec(db, sql, params=(), actor="migration:seed"):
    conn = db.connect(actor)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall() if cur.description else None
    conn.close()
    return rows


def _seed_base(db):
    _exec(db, """
        INSERT INTO history.countries (country_id, name) VALUES (1, 'India'), (2, 'Australia');
        INSERT INTO history.venues (venue_id, name, city, country_id) VALUES (5000, 'Ground A', 'City A', 1), (5001, 'Ground B', 'City B', 2);
        INSERT INTO history.teams (team_id, name) VALUES (10000, 'Team X'), (10001, 'Team Y');
        INSERT INTO history.tournaments (tournament_id, tournament_name, season) VALUES (1000, 'League', '2025');
        INSERT INTO history.players (player_id, code, name, cricinfo_id) VALUES
            (100000, 'c1', 'P One', 11), (100001, 'c2', 'P Two', 22), (100002, 'c3', 'P Three', NULL);
        INSERT INTO history.tournament_teams VALUES (1000, 10000), (1000, 10001);
        INSERT INTO history.matches (match_id, original_match_id, venue_id, tournament_id, home_team_id, away_team_id, gender, match_format, date)
            VALUES (1000000, 'm1.json', 5000, 1000, 10000, 10001, 'male', 'T20', '2025-05-01');
        INSERT INTO history.match_players (match_id, team_id, player_id) VALUES (1000000, 10000, 100000), (1000000, 10001, 100001);
        INSERT INTO history.player_outcome_stats (player_id, match_format, stat_type, probs_raw)
            VALUES (100000, 'T20', 'batting', '{}'), (100001, 'T20', 'batting', '{}');
        INSERT INTO history.venue_stats (venue_id, match_format, gender, probs) VALUES (5000, 'T20', 'male', '{}');
    """)


def _refresh_local(db):
    _exec(db, """
        INSERT INTO history.players (player_id, code, name, cricinfo_id) VALUES (100003, 'c4', 'P Four', 33);
        UPDATE history.players SET display_name = 'Player Two' WHERE player_id = 100001;
        -- a register correction moving a Cricinfo id between players (the 035 case)
        UPDATE history.players SET cricinfo_id = 44 WHERE player_id = 100000;
        UPDATE history.players SET cricinfo_id = 11 WHERE player_id = 100002;
        INSERT INTO history.matches (match_id, original_match_id, venue_id, tournament_id, home_team_id, away_team_id, gender, match_format, date)
            VALUES (1000001, 'm2.json', 5001, 1000, 10001, 10000, 'male', 'T20', '2026-09-01');
        INSERT INTO history.match_players (match_id, team_id, player_id) VALUES (1000001, 10001, 100003);
        UPDATE history.player_outcome_stats SET probs_raw = '{"x": 1}' WHERE player_id = 100000;
        INSERT INTO history.player_outcome_stats (player_id, match_format, stat_type, probs_raw) VALUES (100003, 'T20', 'batting', '{}');
        INSERT INTO history.venue_stats (venue_id, match_format, gender, probs) VALUES (5001, 'T20', 'male', '{}');
    """)


def _prod_user_data(db):
    sim = _exec(db, "INSERT INTO simulation.simulations (simulation_type, config) VALUES ('match', '{}') RETURNING sim_id",
                actor="api")[0][0]
    _exec(db, "INSERT INTO simulation.matches (sim_id, venue_id, match_label) VALUES (%s, 5000, 'Match 1')", (sim,), actor="api")
    # stale precomputed row the refreshed data no longer produces
    _exec(db, "INSERT INTO history.player_outcome_stats (player_id, match_format, stat_type, probs_raw) VALUES (100001, 'T20', 'bowling', '{}')")
    return sim


@pytest.fixture
def local_and_prod(make_db, app_db, tmp_path):
    local, prod = make_db(), make_db()
    for db in (local, prod):
        _seed_base(db)
    _refresh_local(local)
    sim = _prod_user_data(prod)
    app_db(local)
    dump = refresh.export_stage(tmp_path / "export")
    app_db(prod)
    return local, prod, dump, sim


def _apply(dump, tmp_path, yes=True, dry_run=False):
    refresh.apply(str(dump), yes=yes, dry_run=dry_run, backup_dir=tmp_path / "backups", keep=2,
                  clear_cache=False, service="none")


class TestRefreshRoundTrip:
    def test_merges_new_and_changed_rows(self, local_and_prod, tmp_path):
        _, prod, dump, _ = local_and_prod
        _apply(dump, tmp_path)
        assert _exec(prod, "SELECT player_id, display_name, cricinfo_id FROM history.players ORDER BY 1") == [
            (100000, None, 44), (100001, "Player Two", 22), (100002, None, 11), (100003, None, 33)]
        assert _exec(prod, "SELECT original_match_id FROM history.matches ORDER BY 1") == [("m1.json",), ("m2.json",)]

    def test_replaces_precomputed_tables_and_drops_stale_rows(self, local_and_prod, tmp_path):
        _, prod, dump, _ = local_and_prod
        _apply(dump, tmp_path)
        assert _exec(prod, "SELECT player_id, stat_type, probs_raw FROM history.player_outcome_stats ORDER BY 1, 2") == [
            (100000, "batting", {"x": 1}), (100001, "batting", {}), (100003, "batting", {})]
        assert _exec(prod, "SELECT venue_id FROM history.venue_stats ORDER BY 1") == [(5000,), (5001,)]

    def test_leaves_user_simulations_untouched(self, local_and_prod, tmp_path):
        _, prod, dump, sim = local_and_prod
        before = _exec(prod, "SELECT * FROM simulation.matches")
        _apply(dump, tmp_path)
        assert _exec(prod, "SELECT * FROM simulation.matches") == before
        assert _exec(prod, "SELECT count(*) FROM simulation.simulations WHERE sim_id = %s", (sim,)) == [(1,)]

    def test_unchanged_rows_are_not_rewritten(self, local_and_prod, tmp_path):
        _, prod, dump, _ = local_and_prod
        _apply(dump, tmp_path)
        assert _exec(prod, "SELECT updated_by FROM history.teams") == [("migration:seed",), ("migration:seed",)]
        assert _exec(prod, "SELECT updated_by FROM history.players WHERE player_id = 100001")[0][0] != "migration:seed"

    def test_advances_sequences_past_imported_ids(self, local_and_prod, tmp_path):
        _, prod, dump, _ = local_and_prod
        _apply(dump, tmp_path)
        assert _exec(prod, "SELECT nextval('history.players_id_seq')")[0][0] > 100003

    def test_backs_up_and_removes_the_staging_schema(self, local_and_prod, tmp_path):
        _, prod, dump, _ = local_and_prod
        _apply(dump, tmp_path)
        assert len(list((tmp_path / "backups").glob("cricket_db_prod_*.dump"))) == 1
        assert _exec(prod, "SELECT to_regnamespace('refresh_stage')") == [(None,)]

    def test_dry_run_changes_nothing(self, local_and_prod, tmp_path):
        _, prod, dump, _ = local_and_prod
        before = _exec(prod, "SELECT player_id, display_name, cricinfo_id FROM history.players ORDER BY 1")
        _apply(dump, tmp_path, dry_run=True)
        assert _exec(prod, "SELECT player_id, display_name, cricinfo_id FROM history.players ORDER BY 1") == before
        assert not (tmp_path / "backups").exists()


class TestApplyGates:
    def test_a2_stops_on_unique_value_held_by_a_prod_only_row(self, local_and_prod, tmp_path):
        _, prod, dump, _ = local_and_prod
        _exec(prod, "INSERT INTO history.players (player_id, code, name, cricinfo_id) VALUES (100009, 'c9', 'Prod Only', 44)")
        with pytest.raises(refresh.GateFailed, match="A2"):
            _apply(dump, tmp_path)
        assert _exec(prod, "SELECT cricinfo_id FROM history.players WHERE player_id = 100000") == [(11,)]

    def test_a3_flags_prod_side_edits_and_stops_without_confirmation(self, local_and_prod, tmp_path, monkeypatch):
        _, prod, dump, _ = local_and_prod
        _exec(prod, "UPDATE history.players SET name = 'Edited On Prod' WHERE player_id = 100002", actor="user:admin-1")
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")
        with pytest.raises(refresh.GateFailed):
            _apply(dump, tmp_path, yes=False)
        assert _exec(prod, "SELECT name FROM history.players WHERE player_id = 100002") == [("Edited On Prod",)]

    def test_a1_stops_on_schema_mismatch(self, local_and_prod, tmp_path):
        _, prod, dump, _ = local_and_prod
        _exec(prod, "ALTER TABLE history.players ADD COLUMN surprise int")
        with pytest.raises(refresh.GateFailed, match="A1"):
            _apply(dump, tmp_path)
