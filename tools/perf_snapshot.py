"""
Database performance snapshot: run a fixed set of benchmarks against the DB
that DB_NAME / DATABASE_URL points at, save the results as JSON, and compare
two snapshots. Built for before/after checks around schema changes.

    DB_NAME=cricsim_perf_before python -m tools.perf_snapshot --save before
    DB_NAME=cricsim_perf_after  python -m tools.perf_snapshot --save after --compare before

Results go to data/perf/<name>.json (data/ is gitignored).

Micro-benchmarks run inside transactions that are rolled back (nothing kept).
The end-to-end benchmarks run real simulations, which ARE persisted - so they
refuse to run against cricket_db unless --allow-main-db is passed; point the
tool at a throwaway copy instead.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import psycopg2.extensions
import psycopg2.extras

from db.database import DB_NAME, _DATABASE_URL, get_db_connection

# jsonb columns come back as dicts; re-inserting them needs the Json adapter.
psycopg2.extensions.register_adapter(dict, psycopg2.extras.Json)
from db.simulation_repository import SimulationRepository
from simulator.serializers.match import get_tournament_result

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "perf"
AUDIT_COLS = {"created_at", "updated_at", "updated_by"}
SIZE_TABLES = [
    "history.deliveries", "simulation.deliveries", "history.player_outcome_stats",
    "history.batter_bowler_matchups", "history.player_context_stats", "history.match_players",
    "simulation.match_players", "simulation.matches", "simulation.simulations",
]


def _insertable_columns(cur, table: str, skip: set[str]) -> list[str]:
    schema, name = table.split(".")
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (schema, name),
    )
    return [c for (c,) in cur.fetchall() if c not in skip and c not in AUDIT_COLS]


def _timed_rolled_back(fn, runs: int) -> dict:
    """Run fn(cur) in a fresh transaction `runs` times, rolling back each time."""
    times = []
    for _ in range(runs):
        conn = get_db_connection(autocommit=False)
        cur = conn.cursor()
        try:
            t0 = time.perf_counter()
            fn(cur)
            times.append(time.perf_counter() - t0)
        finally:
            conn.rollback()
            cur.close()
            conn.close()
    return {"median_s": statistics.median(times), "runs_s": times}


def bench_insert(table: str, pk: str, n: int, page_size: int, runs: int) -> dict:
    conn = get_db_connection()
    cur = conn.cursor()
    cols = _insertable_columns(cur, table, {pk})
    cur.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {pk} DESC LIMIT %s", (n,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
    res = _timed_rolled_back(lambda c: psycopg2.extras.execute_batch(c, sql, rows, page_size=page_size), runs)
    res["rows"] = len(rows)
    res["rows_per_s"] = len(rows) / res["median_s"]
    return res


def bench_upsert_player_outcome_stats(n: int, runs: int) -> dict:
    conn = get_db_connection()
    cur = conn.cursor()
    cols = _insertable_columns(cur, "history.player_outcome_stats", set())
    cur.execute(f"SELECT {', '.join(cols)} FROM history.player_outcome_stats LIMIT %s", (n,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in ("player_id", "match_format", "stat_type"))
    sql = (f"INSERT INTO history.player_outcome_stats ({', '.join(cols)}) "
           f"VALUES ({', '.join(['%s'] * len(cols))}) "
           f"ON CONFLICT (player_id, match_format, stat_type) DO UPDATE SET {updates}")
    res = _timed_rolled_back(lambda c: psycopg2.extras.execute_batch(c, sql, rows, page_size=500), runs)
    res["rows"] = len(rows)
    res["rows_per_s"] = len(rows) / res["median_s"]
    return res


def _seeded_config(tournament_id: int) -> dict:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT config FROM simulation.tournament_seeded WHERE tournament_id = %s", (tournament_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row or not row[0]:
        sys.exit(f"tournament_seeded {tournament_id} has no config")
    return row[0]


def _create_sim(sim_type: str, config: dict) -> str:
    repo = SimulationRepository()
    try:
        sim_id = repo.create_simulation(sim_type, config, client_id="perf-bench")
        repo.commit()
        return sim_id
    finally:
        repo.close()


def bench_e2e_tournament(tournament_id: int, runs: int) -> dict:
    from api.worker import run_tournament_job
    config = _seeded_config(tournament_id)
    times, sim_ids = [], []
    for _ in range(runs):
        sim_id = _create_sim("tournament", config)
        t0 = time.perf_counter()
        run_tournament_job(sim_id, config)
        times.append(time.perf_counter() - t0)
        sim_ids.append(sim_id)
    _assert_completed(sim_ids)
    return {"cold_s": times[0], "warm_median_s": statistics.median(times[1:] or times),
            "runs_s": times, "sim_ids": sim_ids, "tournament_id": tournament_id}


def bench_e2e_match(tournament_id: int, runs: int) -> dict:
    from api.worker import run_match_job
    seeded = _seeded_config(tournament_id)
    a, b = seeded["teams"][0], seeded["teams"][1]
    venue = (seeded.get("venues") or [{}])[0].get("name")
    config = {"simulation_type": "match", "match_format": seeded.get("format", "T20"), "venue": venue,
              "team_a": {"name": a["name"], "players": a["players"]},
              "team_b": {"name": b["name"], "players": b["players"]}}
    times, sim_ids = [], []
    for _ in range(runs):
        sim_id = _create_sim("match", config)
        t0 = time.perf_counter()
        run_match_job(sim_id, config)
        times.append(time.perf_counter() - t0)
        sim_ids.append(sim_id)
    _assert_completed(sim_ids)
    return {"median_s": statistics.median(times), "runs_s": times, "sim_ids": sim_ids}


def _assert_completed(sim_ids: list[str]) -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT sim_id::text, status, error_message FROM simulation.simulations WHERE sim_id::text = ANY(%s)", (sim_ids,))
    bad = [r for r in cur.fetchall() if r[1] != "completed"]
    cur.close()
    conn.close()
    if bad:
        sys.exit(f"benchmark simulations did not complete: {bad}")


def bench_reads(tournament_sim_id: str | None, runs: int) -> dict:
    out = {}
    times = []
    for _ in range(runs):
        repo = SimulationRepository()
        try:
            t0 = time.perf_counter()
            repo.list_simulations(limit=50, offset=0, client_id=None, admin_view=True)
            times.append(time.perf_counter() - t0)
        finally:
            repo.close()
    out["list_simulations_admin_median_s"] = statistics.median(times)
    if tournament_sim_id:
        times = []
        for _ in range(runs):
            repo = SimulationRepository()
            try:
                t0 = time.perf_counter()
                get_tournament_result(repo.dict_cursor, tournament_sim_id)
                times.append(time.perf_counter() - t0)
            finally:
                repo.close()
        out["tournament_result_median_s"] = statistics.median(times)
    return out


def table_sizes() -> dict:
    conn = get_db_connection()
    cur = conn.cursor()
    sizes = {}
    for t in SIZE_TABLES:
        cur.execute("SELECT pg_total_relation_size(%s::regclass)", (t,))
        sizes[t] = cur.fetchone()[0]
    cur.close()
    conn.close()
    return sizes


def _db_label() -> str:
    return "DATABASE_URL" if _DATABASE_URL else DB_NAME


def compare(before: dict, after: dict) -> None:
    def row(label, b, a, unit="s", higher_is_better=False):
        if b is None or a is None:
            return
        delta = (a - b) / b * 100 if b else 0.0
        worse = delta < 0 if higher_is_better else delta > 0
        flag = "  <-- worse" if worse and abs(delta) >= 5 else ""
        print(f"  {label:48s} {b:>14.4f} {a:>14.4f} {delta:>+8.1f}%{flag}  ({unit})")

    print(f"\n{'':50s} {'before':>14s} {'after':>14s} {'change':>9s}")
    for key in ("insert_sim_deliveries", "insert_hist_deliveries", "upsert_player_outcome_stats"):
        b, a = before["benchmarks"].get(key), after["benchmarks"].get(key)
        if b and a:
            row(f"{key} rows/s", b["rows_per_s"], a["rows_per_s"], "rows/s", higher_is_better=True)
    for key, field in (("e2e_tournament", "cold_s"), ("e2e_tournament", "warm_median_s"), ("e2e_match", "median_s")):
        b, a = before["benchmarks"].get(key), after["benchmarks"].get(key)
        if b and a:
            row(f"{key} {field}", b[field], a[field])
    for field in ("list_simulations_admin_median_s", "tournament_result_median_s"):
        row(f"reads {field}", before["benchmarks"]["reads"].get(field), after["benchmarks"]["reads"].get(field))
    for t, b in before["sizes"].items():
        a = after["sizes"].get(t)
        row(f"size {t} MB", b / 1e6, a / 1e6 if a else None, "MB")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--save", required=True, help="snapshot name (data/perf/<name>.json)")
    p.add_argument("--compare", help="earlier snapshot name to compare against")
    p.add_argument("--runs", type=int, default=5, help="runs per micro-benchmark (default 5)")
    p.add_argument("--e2e-runs", type=int, default=3, help="runs per end-to-end benchmark (default 3)")
    p.add_argument("--tournament-id", type=int, default=3039, help="seeded tournament for e2e (default 3039, IPL 2026)")
    p.add_argument("--skip-e2e", action="store_true")
    p.add_argument("--allow-main-db", action="store_true", help="allow persisting e2e sims into cricket_db")
    args = p.parse_args()

    if not args.skip_e2e and DB_NAME == "cricket_db" and not _DATABASE_URL and not args.allow_main_db:
        sys.exit("refusing to persist benchmark simulations into cricket_db - set DB_NAME to a throwaway copy, "
                 "or pass --skip-e2e / --allow-main-db")

    print(f"perf snapshot '{args.save}' on {_db_label()}")
    benchmarks = {}
    benchmarks["insert_sim_deliveries"] = bench_insert("simulation.deliveries", "delivery_id", 50_000, 500, args.runs)
    print("  insert_sim_deliveries done")
    benchmarks["insert_hist_deliveries"] = bench_insert("history.deliveries", "delivery_id", 10_000, 100, args.runs)
    print("  insert_hist_deliveries done")
    benchmarks["upsert_player_outcome_stats"] = bench_upsert_player_outcome_stats(20_000, args.runs)
    print("  upsert_player_outcome_stats done")
    sim_for_reads = None
    if not args.skip_e2e:
        benchmarks["e2e_tournament"] = bench_e2e_tournament(args.tournament_id, args.e2e_runs)
        sim_for_reads = benchmarks["e2e_tournament"]["sim_ids"][-1]
        print("  e2e_tournament done")
        benchmarks["e2e_match"] = bench_e2e_match(args.tournament_id, args.e2e_runs)
        print("  e2e_match done")
    benchmarks["reads"] = bench_reads(sim_for_reads, args.runs)

    snapshot = {"name": args.save, "db": _db_label(), "taken_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "benchmarks": benchmarks, "sizes": table_sizes()}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{args.save}.json"
    out.write_text(json.dumps(snapshot, indent=2, default=str))
    print(f"saved {out}")

    if args.compare:
        before = json.loads((OUT_DIR / f"{args.compare}.json").read_text())
        compare(before, snapshot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
