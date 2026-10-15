"""
Data refresh: rebuild the historical data on the build machine (the Mac -
prod has no history.deliveries and too little RAM to precompute) and merge it
into prod without touching prod's user data.

    # 1. on the droplet: export prod's admin edits, copy them down
    python -m db.replay_admin_edits --export ~/edits.jsonl
    # 2. on the Mac
    python -m db.refresh build --edits data/backups/prod_admin_edits.jsonl
    # 3. copy data/refresh/refresh_<ts>.dump up, then on the droplet
    python -m db.refresh apply refresh_<ts>.dump --dry-run     # gates + merge, rolled back
    python -m db.refresh apply refresh_<ts>.dump

build: backup -> admin edits -> download -> ingest -> venues -> enrichment ->
precompute -> export. It stops at each gate (G0-G4) with a report; --yes
answers "continue" to the confirmable ones.

apply: backup -> load staging schema -> gates (A1 schema, A2 unique
conflicts, A3 prod-side edits) -> venue dedup -> one transaction: upsert
reference tables by primary key (only rows that differ; nothing deleted),
replace precomputed tables (readers keep the old stats until commit) ->
VACUUM ANALYZE -> drop staging -> clear the API's stats cache (SIGUSR1).
simulation.* is never written except by the venue dedup (which re-points
prod's own matches off merged venues).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Iterable

import psycopg2

from db import database
from db.database import get_db_connection
from simulator.logger import get_logger

STAGE = "refresh_stage"
AUDIT_COLS = ("created_at", "updated_at", "updated_by")

# FK order: every table comes after the tables it references.
REFERENCE_TABLES: list[tuple[str, tuple[str, ...]]] = [
    ("countries", ("country_id",)),
    ("venues", ("venue_id",)),
    ("teams", ("team_id",)),
    ("tournaments", ("tournament_id",)),
    ("players", ("player_id",)),
    ("tournament_teams", ("tournament_id", "team_id")),
    ("matches", ("match_id",)),
    ("match_players", ("match_id", "player_id")),
]
PRECOMPUTED_TABLES = [
    "global_yearly_baseline", "player_outcome_stats", "player_context_stats",
    "batter_bowler_matchups", "bowler_order_stats", "player_scalar_stats",
    "aggregate_stats", "venue_stats", "country_stats", "tournament_outcome_stats",
]
SEQUENCES = {  # sequence -> (table, column); deliveries is deliberately absent (prod has none)
    "countries_country_id_seq": ("countries", "country_id"),
    "venues_id_seq": ("venues", "venue_id"),
    "teams_id_seq": ("teams", "team_id"),
    "tournaments_id_seq": ("tournaments", "tournament_id"),
    "players_id_seq": ("players", "player_id"),
    "matches_id_seq": ("matches", "match_id"),
}
REQUIRED_MIGRATIONS = ("034_audit_columns.sql", "035_fix_cricinfo_f6ba97c6.sql",
                       "036_tournament_seeded_overseas_columns.sql", "037_vocabulary_checks.sql")
PEOPLE_CSV_URL = "https://cricsheet.org/register/people.csv"
REPO_ROOT = Path(__file__).resolve().parent.parent
REFRESH_DIR = REPO_ROOT / "data" / "refresh"

log = get_logger()


class GateFailed(SystemExit):
    """A gate stopped the run - the report above it says why."""


# ── helpers ───────────────────────────────────────────────────────────────────

def _say(msg: str = "") -> None:
    print(msg, flush=True)


def _confirm(question: str, yes: bool) -> None:
    if yes:
        _say(f"{question} [--yes: continuing]")
        return
    answer = input(f"{question} [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        raise GateFailed("stopped at gate")


def _pg_cli_args() -> list[str]:
    """Connection args for pg_dump / pg_restore, matching get_db_connection()."""
    if database._DATABASE_URL:
        return ["-d", database._DATABASE_URL]
    return ["-h", database.DB_HOST, "-p", str(database.DB_PORT), "-U", database.DB_USER, "-d", database.DB_NAME]


def _pg_env() -> dict:
    env = dict(os.environ)
    if not database._DATABASE_URL and database.DB_PASS:
        env["PGPASSWORD"] = database.DB_PASS
    return env


def _run(cmd: list[str]) -> None:
    _say("  $ " + " ".join(c if not c.startswith("postgres") else "<DATABASE_URL>" for c in cmd))
    subprocess.run(cmd, check=True, env=_pg_env())


def _backup(dest_dir: Path, label: str, keep: int | None = None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"cricket_db_{label}_{datetime.now():%Y%m%d_%H%M%S}.dump"
    _run(["pg_dump", "-Fc", *_pg_cli_args(), "-f", str(path)])
    _say(f"  backup: {path} ({path.stat().st_size / 1e6:.0f} MB)")
    if keep:
        old = sorted(dest_dir.glob(f"cricket_db_{label}_*.dump"))[:-keep]
        for p in old:
            p.unlink()
            _say(f"  pruned old backup {p.name}")
    return path


def _columns(cur, schema: str, table: str) -> list[tuple[str, str]]:
    cur.execute(
        """SELECT column_name, data_type FROM information_schema.columns
           WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position""",
        (schema, table),
    )
    return [(c, t) for c, t in cur.fetchall() if c not in AUDIT_COLS]


def _counts(cur, schema: str) -> dict[str, int]:
    out = {}
    for t in [t for t, _ in REFERENCE_TABLES] + PRECOMPUTED_TABLES:
        cur.execute(f"SELECT count(*) FROM {schema}.{t}")
        out[t] = cur.fetchone()[0]
    return out


def upsert_sql(table: str, pk: Iterable[str], columns: list[str]) -> str:
    """INSERT … ON CONFLICT (pk) DO UPDATE, touching only rows whose values differ."""
    pk = list(pk)
    cols = ", ".join(columns)
    non_pk = [c for c in columns if c not in pk]
    head = f"INSERT INTO history.{table} ({cols}) SELECT {cols} FROM {STAGE}.{table} ON CONFLICT ({', '.join(pk)}) "
    if not non_pk:
        return head + "DO NOTHING"
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in non_pk)
    old = ", ".join(f"history.{table}.{c}" for c in non_pk)
    new = ", ".join(f"EXCLUDED.{c}" for c in non_pk)
    return head + f"DO UPDATE SET {sets} WHERE ({old}) IS DISTINCT FROM ({new})"


def _pk_match(alias_a: str, alias_b: str, pk: Iterable[str]) -> str:
    return " AND ".join(f"{alias_a}.{c} = {alias_b}.{c}" for c in pk)


def _unique_keys(cur, table: str) -> list[tuple[str, ...]]:
    """Non-primary unique indexes on plain columns (e.g. players.cricinfo_id, venues.name)."""
    cur.execute(
        """SELECT array_agg(a.attname ORDER BY k.ord)
           FROM pg_index i
           CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord)
           JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
           WHERE i.indrelid = %s::regclass AND i.indisunique AND NOT i.indisprimary AND i.indexprs IS NULL
           GROUP BY i.indexrelid""",
        (f"history.{table}",),
    )
    return [tuple(r[0]) for r in cur.fetchall()]


# ── build ─────────────────────────────────────────────────────────────────────

def _download_people_csv() -> None:
    dest_dir = REPO_ROOT / "data" / f"incoming_people_{datetime.now():%Y%m%d_%H%M%S}"
    dest_dir.mkdir(parents=True)
    fresh = dest_dir / "people.csv"
    urllib.request.urlretrieve(PEOPLE_CSV_URL, fresh)
    current = REPO_ROOT / "people.csv"
    with fresh.open(newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    if "identifier" not in header or "key_cricinfo" not in header:
        raise GateFailed(f"downloaded people.csv has an unexpected header: {header[:5]}")
    if current.exists():
        stamp = datetime.fromtimestamp(current.stat().st_mtime).strftime("%Y%m%d")
        shutil.copy2(current, REPO_ROOT / "data" / "backups" / f"people_{stamp}.csv")
    shutil.copy2(fresh, current)
    _say(f"  people.csv refreshed ({sum(1 for _ in fresh.open(encoding='utf-8')) - 1} people)")


def gate_new_venues(cur, venue_id_before: int, yes: bool) -> None:
    """G1: new venues next to same-city existing ones - likely Cricsheet name variants."""
    cur.execute(
        """SELECT n.venue_id, n.name, n.city,
                  (SELECT string_agg(e.venue_id || ' ' || e.name, ' | ' ORDER BY e.name)
                   FROM history.venues e WHERE e.city = n.city AND e.venue_id <= %s)
           FROM history.venues n WHERE n.venue_id > %s ORDER BY n.city, n.name""",
        (venue_id_before, venue_id_before),
    )
    rows = cur.fetchall()
    if not rows:
        _say("  G1: no new venues")
        return
    _say(f"  G1: {len(rows)} new venue(s). Ones with same-city existing venues may be duplicates -")
    _say("      confirm via ESPN venue ids, add aliases to db/venue_country_overrides.json, then rerun.")
    for vid, name, city, same_city in rows:
        _say(f"    {vid} {name!r} ({city}){'   same city: ' + same_city if same_city else ''}")
    _confirm("  Continue (no aliases needed / already added)?", yes)


def gate_cricinfo(cur) -> None:
    """G2: pass 1 would hit a cricinfo_id held by another player, or the register changed an existing mapping."""
    from db.enrich_players import _load_cricinfo_map
    cmap = _load_cricinfo_map()
    cur.execute("SELECT player_id, code, cricinfo_id, coalesce(display_name, name) FROM history.players WHERE code IS NOT NULL")
    players = cur.fetchall()
    owner = {cid: (pid, name) for pid, _, cid, name in players if cid is not None}
    problems = []
    for pid, code, cid, name in players:
        reg = cmap.get(code)
        if reg is None:
            continue
        if cid is None and reg in owner and owner[reg][0] != pid:
            problems.append(f"player {pid} {name!r} ({code}) -> {reg}, already held by player {owner[reg][0]} {owner[reg][1]!r}")
        elif cid is not None and cid != reg:
            problems.append(f"player {pid} {name!r} ({code}) has {cid}, register now says {reg}")
    if problems:
        _say("  G2: Cricinfo id problems - fix with a data migration (see 035_fix_cricinfo_f6ba97c6.sql), then rerun:")
        for p in problems:
            _say(f"    {p}")
        raise GateFailed("G2")
    _say("  G2: no Cricinfo id conflicts")


def gate_precompute_fresh(cur, started: datetime) -> None:
    """G3: every precomputed table was rewritten in this run (stale leftovers are only reported)."""
    bad = []
    for t in PRECOMPUTED_TABLES:
        cur.execute(f"SELECT count(*), count(*) FILTER (WHERE updated_at >= %s) FROM history.{t}", (started,))
        total, fresh = cur.fetchone()
        if fresh == 0:
            bad.append(t)
        elif fresh < total:
            _say(f"    {t}: {total - fresh} stale row(s) not rewritten (keys no longer produced; dropped on apply)")
    if bad:
        raise GateFailed(f"G3: precompute did not refresh {bad}")
    _say("  G3: every precomputed table refreshed")


def gate_counts(counts: dict[str, int], yes: bool) -> None:
    """G4: compare with the last successful build."""
    last = REFRESH_DIR / "last_report.json"
    if not last.exists():
        _say("  G4: no previous build report - skipping comparison")
        return
    prev = json.loads(last.read_text())["counts"]
    shrank = {t: (prev[t], n) for t, n in counts.items() if t in prev and n < prev[t]}
    _say("  G4: row counts vs last build: " + ", ".join(f"{t} {prev.get(t, 0)}->{n}" for t, n in counts.items()
                                                     if t in ("matches", "players", "venues", "tournaments")))
    expected_shrink = {"venues"} | set(PRECOMPUTED_TABLES)
    unexpected = {t: v for t, v in shrank.items() if t not in expected_shrink}
    if unexpected:
        _say(f"    unexpected shrink: {unexpected}")
        _confirm("  Continue anyway?", yes)


def export_stage(out_dir: Path) -> Path:
    """Copy history tables (minus deliveries and audit columns) into a staging schema and pg_dump it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = get_db_connection(autocommit=False)
    try:
        cur = conn.cursor()
        cur.execute(f"DROP SCHEMA IF EXISTS {STAGE} CASCADE")
        cur.execute(f"CREATE SCHEMA {STAGE}")
        for t in [t for t, _ in REFERENCE_TABLES] + PRECOMPUTED_TABLES:
            cols = ", ".join(c for c, _ in _columns(cur, "history", t))
            cur.execute(f"CREATE TABLE {STAGE}.{t} AS SELECT {cols} FROM history.{t}")
        cur.execute(f"CREATE TABLE {STAGE}._meta (key text PRIMARY KEY, value text)")
        cur.execute(f"INSERT INTO {STAGE}._meta VALUES ('built_at', %s), ('source_db', %s)",
                    (datetime.now().isoformat(timespec="seconds"), database.DB_NAME))
        conn.commit()
        path = out_dir / f"refresh_{datetime.now():%Y%m%d_%H%M%S}.dump"
        _run(["pg_dump", "-Fc", *_pg_cli_args(), "-n", STAGE, "-f", str(path)])
        cur.execute(f"DROP SCHEMA {STAGE} CASCADE")
        conn.commit()
    finally:
        conn.close()
    _say(f"  export: {path} ({path.stat().st_size / 1e6:.0f} MB)")
    return path


def build(edits: str | None, yes: bool, skip_download: bool, skip_enrich_api: bool) -> Path:
    started = datetime.now().astimezone()
    _say(f"== refresh build on {database.DB_NAME} ({started:%Y-%m-%d %H:%M})")

    _say("\n[1] backup local DB")
    _backup(REPO_ROOT / "data" / "backups", "before_refresh")

    _say("\n[2] prod admin edits")
    if edits:
        from db.replay_admin_edits import apply_edits
        applied, skipped, failed = apply_edits(edits)
        _say(f"  applied {applied}, already present {skipped}, failed {failed}")
        if failed:
            raise GateFailed("admin edits failed to apply - see errors.log")
    else:
        _confirm("  No --edits given: prod admin edits made since the last sync will be overwritten on apply. Continue?", yes)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT coalesce(max(venue_id), 0) FROM history.venues")
    venue_id_before = cur.fetchone()[0]

    _say("\n[3] download")
    if skip_download:
        _say("  skipped (--skip-download)")
    else:
        from setup_db import DatabaseSetupFacade
        facade = DatabaseSetupFacade()
        facade.download()
        facade.unzip()
        _download_people_csv()

    _say("\n[4] ingest")
    from db.ingest_data import ingest_data
    result = ingest_data()
    if result["failed"]:
        _say(f"  G0: {len(result['failed'])} match file(s) were skipped (details in errors.log):")
        for name, stage, err in result["failed"]:
            _say(f"    {name} [{stage}]: {err.splitlines()[0] if err else ''}")
        _confirm("  Continue without them (they'll be retried next run)?", yes)
    else:
        _say(f"  G0: all {result['ingested']} new matches ingested")

    _say("\n[5] venues")
    gate_new_venues(cur, venue_id_before, yes)
    from db.dedup_venues import run as dedup_run
    from db.populate_venue_countries import run as countries_run
    dedup_run(commit=True)
    countries_run(commit=True)
    cur.execute("SELECT venue_id, name, city FROM history.venues WHERE country_id IS NULL")
    missing = cur.fetchall()
    if missing:
        _say(f"  venues without a country (add to venue_country_overrides.json by_name_city): {missing}")
        raise GateFailed("venues without a country")

    _say("\n[6] enrichment")
    gate_cricinfo(cur)
    from db.enrich_players import pass1, pass2
    pass1(commit=True)
    if skip_enrich_api:
        _say("  pass 2 skipped (--skip-enrich-api)")
    else:
        pass2(commit=True)

    _say("\n[7] precompute")
    from db.precompute import populate_all
    populate_all(dry_run=True)
    populate_all()
    gate_precompute_fresh(cur, started)

    _say("\n[8] counts")
    counts = _counts(cur, "history")
    gate_counts(counts, yes)
    conn.close()

    _say("\n[9] export")
    path = export_stage(REFRESH_DIR)
    report = {"built_at": started.isoformat(timespec="seconds"), "export": path.name, "counts": counts,
              "ingest": {"ingested": result["ingested"], "failed": [f for f, _, _ in result["failed"]]}}
    (REFRESH_DIR / f"report_{path.stem}.json").write_text(json.dumps(report, indent=2))
    (REFRESH_DIR / "last_report.json").write_text(json.dumps(report, indent=2))
    _say(f"\n== build done: copy {path} to the droplet and run `python -m db.refresh apply {path.name}`")
    return path


# ── apply ─────────────────────────────────────────────────────────────────────

def gate_schema(cur) -> None:
    """A1: staging tables match prod's history columns; required migrations are applied."""
    problems = []
    for t in [t for t, _ in REFERENCE_TABLES] + PRECOMPUTED_TABLES:
        stage, prod = _columns(cur, STAGE, t), _columns(cur, "history", t)
        if not stage:
            problems.append(f"{t}: missing from the export")
        elif set(stage) != set(prod):
            problems.append(f"{t}: export {sorted(set(stage) - set(prod))} vs prod {sorted(set(prod) - set(stage))}")
    cur.execute("SELECT to_regclass('history.schema_migrations') IS NOT NULL")
    if cur.fetchone()[0]:
        cur.execute("SELECT filename FROM history.schema_migrations WHERE filename = ANY(%s)", (list(REQUIRED_MIGRATIONS),))
        applied = {r[0] for r in cur.fetchall()}
        problems += [f"migration not applied: {m}" for m in REQUIRED_MIGRATIONS if m not in applied]
    if problems:
        _say("  A1: schema mismatch - deploy the code and apply migrations first:")
        for p in problems:
            _say(f"    {p}")
        raise GateFailed("A1")
    _say("  A1: schema matches")


def gate_unique_conflicts(cur) -> None:
    """A2: a staged unique value (e.g. cricinfo_id, venue name) held on prod by a different row that
    the refresh doesn't move off it. Nullable single-column values that the refresh moves are
    cleared first in the merge, so swaps (like 035's Cricinfo fix) need no manual step."""
    problems = []
    for t, pk in REFERENCE_TABLES:
        for key in _unique_keys(cur, t):
            same_key = " AND ".join(f"h.{c} = s.{c}" for c in key)
            other_row = " OR ".join(f"h.{c} <> s.{c}" for c in pk)
            moved_off = " AND ".join(f"s2.{c} IS NOT DISTINCT FROM h.{c}" for c in key)
            cur.execute(
                f"""SELECT {', '.join('s.' + c for c in pk)}, {', '.join('h.' + c for c in pk)}, {', '.join('s.' + c for c in key)}
                    FROM {STAGE}.{t} s JOIN history.{t} h ON {same_key} AND ({other_row})
                    LEFT JOIN {STAGE}.{t} s2 ON {_pk_match('s2', 'h', pk)}
                    WHERE s2.{pk[0]} IS NULL OR ({moved_off})"""
            )
            for row in cur.fetchall():
                problems.append(f"{t}.{'/'.join(key)}={row[-len(key):]}: staged row {row[:len(pk)]} vs prod row {row[len(pk):2 * len(pk)]}")
    if problems:
        _say("  A2: unique-key conflicts (prod rows hold values the export assigns elsewhere):")
        for p in problems:
            _say(f"    {p}")
        raise GateFailed("A2")
    _say("  A2: no unique-key conflicts")


def gate_prod_edits(cur, yes: bool) -> None:
    """A3: prod rows the merge would change that were last written by something other than a
    migration or a previous refresh - i.e. edited on prod and not pulled into the build."""
    found = []
    for t, pk in REFERENCE_TABLES:
        cols = [c for c, _ in _columns(cur, STAGE, t) if c not in pk]
        if not cols:
            continue
        cur.execute(
            f"""SELECT {', '.join('h.' + c for c in pk)}, h.updated_by, h.updated_at
                FROM history.{t} h JOIN {STAGE}.{t} s ON {_pk_match('h', 's', pk)}
                WHERE ({', '.join('h.' + c for c in cols)}) IS DISTINCT FROM ({', '.join('s.' + c for c in cols)})
                  AND h.updated_by NOT LIKE 'migration:%%' AND h.updated_by NOT LIKE 'script:refresh%%'"""
        )
        found += [(t, r) for r in cur.fetchall()]
    if not found:
        _say("  A3: no prod-side edits would be overwritten")
        return
    _say(f"  A3: {len(found)} prod row(s) edited on prod would be overwritten by the export:")
    for t, r in found[:30]:
        _say(f"    {t} {r[:-2]} last written by {r[-2]} at {r[-1]:%Y-%m-%d %H:%M}")
    _confirm("  Overwrite them (normally: re-sync admin edits into the build first)?", yes)


def _merge(cur) -> dict[str, int]:
    changed = {}
    for t, pk in REFERENCE_TABLES:
        for key in _unique_keys(cur, t):
            if len(key) != 1:
                continue
            col = key[0]
            cur.execute("""SELECT is_nullable FROM information_schema.columns
                           WHERE table_schema = 'history' AND table_name = %s AND column_name = %s""", (t, col))
            if cur.fetchone()[0] == "YES":
                cur.execute(f"""UPDATE history.{t} h SET {col} = NULL FROM {STAGE}.{t} s
                                WHERE {_pk_match('h', 's', pk)} AND h.{col} IS NOT NULL
                                  AND s.{col} IS DISTINCT FROM h.{col}""")
        cols = [c for c, _ in _columns(cur, STAGE, t)]
        cur.execute(upsert_sql(t, pk, cols))
        changed[t] = cur.rowcount
    for t in PRECOMPUTED_TABLES:
        cols = ", ".join(c for c, _ in _columns(cur, STAGE, t))
        cur.execute(f"DELETE FROM history.{t}")
        cur.execute(f"INSERT INTO history.{t} ({cols}) SELECT {cols} FROM {STAGE}.{t}")
        changed[t] = cur.rowcount
    for seq, (t, col) in SEQUENCES.items():
        cur.execute(f"SELECT setval('history.{seq}', GREATEST((SELECT max({col}) FROM history.{t}), 1))")
    return changed


def apply(dump: str, yes: bool, dry_run: bool, backup_dir: Path, keep: int,
          clear_cache: bool, service: str) -> None:
    _say(f"== refresh apply {dump} on {database.DB_NAME}{' (DRY RUN)' if dry_run else ''}")
    if not dry_run:
        _say("\n[1] backup prod")
        _backup(backup_dir, "prod", keep=keep)

    _say("\n[2] load staging schema")
    conn = get_db_connection()
    conn.cursor().execute(f"DROP SCHEMA IF EXISTS {STAGE} CASCADE")
    conn.close()
    _run(["pg_restore", "--no-owner", *_pg_cli_args(), dump])

    conn = get_db_connection(autocommit=False)
    try:
        cur = conn.cursor()
        _say("\n[3] gates")
        gate_schema(cur)
        gate_unique_conflicts(cur)
        gate_prod_edits(cur, yes)
        conn.commit()

        if not dry_run:
            _say("\n[4] venue dedup (re-points prod's own simulations off merged venues)")
            from db.dedup_venues import run as dedup_run
            dedup_run(commit=True)

        _say("\n[5] merge" + (" - rolled back (dry run)" if dry_run else ""))
        t0 = time.perf_counter()
        changed = _merge(cur)
        for t, n in changed.items():
            _say(f"  {t}: {n} row(s) {'inserted/updated' if t not in PRECOMPUTED_TABLES else 'loaded'}")
        stage_counts, prod_counts = _counts(cur, STAGE), _counts(cur, "history")
        mismatch = {t: (stage_counts[t], prod_counts[t]) for t in stage_counts if stage_counts[t] != prod_counts[t]}
        if mismatch:
            _say(f"  note: tables with rows that exist only on prod (kept): {mismatch}")
        if dry_run:
            conn.rollback()
            _say(f"  rolled back after {time.perf_counter() - t0:.1f}s")
        else:
            conn.commit()
            _say(f"  committed in {time.perf_counter() - t0:.1f}s")
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

    conn = get_db_connection()
    cur = conn.cursor()
    if not dry_run:
        _say("\n[6] vacuum")
        for t in [t for t, _ in REFERENCE_TABLES] + PRECOMPUTED_TABLES:
            cur.execute(f"VACUUM ANALYZE history.{t}")
    cur.execute(f"DROP SCHEMA IF EXISTS {STAGE} CASCADE")
    conn.close()

    if not dry_run and clear_cache:
        _say("\n[7] clear the API stats cache")
        try:
            subprocess.run(["sudo", "systemctl", "kill", "-s", "USR1", service], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            log.exception("refresh apply: cache clear failed")
            _say(f"  could not signal {service} ({e}) - run: sudo systemctl kill -s USR1 {service}")
    _say(f"\n== apply {'dry run ' if dry_run else ''}done")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="refresh the local DB and export it (Mac)")
    b.add_argument("--edits", help="prod admin edits exported with replay_admin_edits --export")
    b.add_argument("--yes", action="store_true", help="answer 'continue' at confirmable gates")
    b.add_argument("--skip-download", action="store_true")
    b.add_argument("--skip-enrich-api", action="store_true", help="skip enrichment pass 2 (ESPN)")
    a = sub.add_parser("apply", help="merge an export into this DB (droplet)")
    a.add_argument("dump")
    a.add_argument("--dry-run", action="store_true", help="gates + merge, then roll back; no backup, no cache clear")
    a.add_argument("--yes", action="store_true")
    a.add_argument("--backup-dir", default=str(Path.home() / "backups"))
    a.add_argument("--keep", type=int, default=5, help="prod backups to keep (default 5)")
    a.add_argument("--no-cache-clear", action="store_true")
    a.add_argument("--service", default="cricsim-api")
    args = p.parse_args()
    try:
        if args.cmd == "build":
            build(args.edits, args.yes, args.skip_download, args.skip_enrich_api)
        else:
            apply(args.dump, args.yes, args.dry_run, Path(args.backup_dir), args.keep,
                  not args.no_cache_clear, args.service)
    except GateFailed as e:
        _say(f"\nSTOPPED: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
