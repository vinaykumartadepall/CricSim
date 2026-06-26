"""
Enrich history.players with ESPN/cricinfo data.

Two-pass operation:
  Pass 1  (fast, no network)  — maps people.csv identifier → cricinfo_id
  Pass 2  (~1 hour, network)  — fetches displayName / batting_style /
                                bowling_style / player_role / country_id
                                from ESPN athlete API per cricinfo_id

Usage:
    python -m db.enrich_players               # both passes, dry run
    python -m db.enrich_players --commit      # both passes, write to DB
    python -m db.enrich_players --pass1-only --commit
    python -m db.enrich_players --pass2-only --commit
    python -m db.enrich_players --pass2-only --commit --workers 10
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from db.database import get_db_connection

# ── ESPN API ──────────────────────────────────────────────────────────────────

_ESPN_URL = "http://core.espnuk.org/v2/sports/cricket/athletes/{cid}"
_TIMEOUT  = 10  # seconds per request

POSITION_TO_ROLE: dict[str, str] = {
    "TBT": "Batter",
    "MOB": "Batter",
    "LB":  "Batter",
    "OBT": "Batter",   # Opening batter
    "MBT": "Batter",   # Middle-order batter
    "BT":  "Batter",   # Generic batter
    "WBT": "Keeper",
    "WK":  "Keeper",
    "AR":  "All-rounder",
    "BTA": "All-rounder",
    "BAR": "All-rounder",
    "BL":  "Bowler",
    # UKN (Unknown) intentionally omitted — maps to None
}

# ── people.csv ────────────────────────────────────────────────────────────────

PEOPLE_CSV = Path(__file__).parent.parent / "people.csv"


def _load_cricinfo_map() -> dict[str, int]:
    """Return {cricsheet_hex_id: cricinfo_int_id} from people.csv."""
    mapping: dict[str, int] = {}
    with PEOPLE_CSV.open(newline="") as fh:
        for row in csv.DictReader(fh):
            raw = row.get("key_cricinfo", "").strip()
            if raw:
                try:
                    mapping[row["identifier"]] = int(raw)
                except ValueError:
                    pass
    return mapping


# ── ESPN fetch helpers ────────────────────────────────────────────────────────

def _fetch_athlete(cricinfo_id: int, max_retries: int = 4) -> Optional[dict]:
    """Fetch raw ESPN athlete JSON with exponential backoff on timeout/error."""
    url = _ESPN_URL.format(cid=cricinfo_id)
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # Player not in ESPN — don't retry
            wait = 2 ** attempt
            print(f"\n    [retry {attempt+1}/{max_retries} in {wait}s] {cricinfo_id}: HTTP {e.code}")
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            wait = 2 ** attempt
            print(f"\n    [retry {attempt+1}/{max_retries} in {wait}s] {cricinfo_id}: {e}")
            time.sleep(wait)
        except json.JSONDecodeError:
            return None  # Malformed response — don't retry
    return None


def _parse_athlete(data: dict, espn_to_country_id: dict[int, int]) -> dict:
    """Extract the fields we care about from an ESPN athlete response."""
    result: dict = {}

    result["display_name"] = data.get("displayName") or None

    # style is a list: [{"type": "batting", "description": "..."}, {"type": "bowling", ...}]
    styles: dict[str, str] = {}
    for entry in data.get("style") or []:
        if isinstance(entry, dict) and entry.get("type"):
            styles[entry["type"]] = entry.get("description") or ""
    result["batting_style"] = styles.get("batting") or None
    result["bowling_style"] = styles.get("bowling") or None

    position = data.get("position") or {}
    pos_id   = position.get("id") or ""
    result["player_role"] = POSITION_TO_ROLE.get(pos_id)

    # country is a plain integer ESPN team ID
    espn_country_id: Optional[int] = None
    raw_country = data.get("country")
    if raw_country is not None:
        try:
            espn_country_id = int(raw_country)
        except (TypeError, ValueError):
            pass

    result["country_id"]       = espn_to_country_id.get(espn_country_id) if espn_country_id else None
    result["espn_country_int"] = espn_country_id
    return result


# ── Pass 1 ────────────────────────────────────────────────────────────────────

def pass1(commit: bool) -> None:
    """Map players.code → cricinfo_id via people.csv (no network)."""
    print("\n=== Pass 1: assign cricinfo_id from people.csv ===")

    cricinfo_map = _load_cricinfo_map()
    print(f"  people.csv: {len(cricinfo_map):,} identifier→cricinfo_id entries")

    conn = get_db_connection(autocommit=False)
    cur  = conn.cursor()

    cur.execute(
        "SELECT player_id, code FROM history.players WHERE cricinfo_id IS NULL AND code IS NOT NULL"
    )
    rows = cur.fetchall()
    print(f"  Players without cricinfo_id: {len(rows):,}")

    updates: list[tuple[int, int]] = []
    for player_id, code in rows:
        cid = cricinfo_map.get(code)
        if cid:
            updates.append((cid, player_id))

    matched_pct = len(updates) * 100 / max(len(rows), 1)
    print(f"  Matched: {len(updates):,}  ({matched_pct:.1f}%)")
    print(f"  Unmatched: {len(rows) - len(updates):,}")

    if not commit:
        print("  [dry-run] no changes written.")
        cur.close(); conn.close()
        return

    if updates:
        print(f"  Writing {len(updates):,} cricinfo_id updates …")
        cur.executemany(
            "UPDATE history.players SET cricinfo_id = %s WHERE player_id = %s",
            updates,
        )
        conn.commit()
        print("  Done.")
    else:
        print("  Nothing to update.")

    cur.close()
    conn.close()


# ── Pass 2 ────────────────────────────────────────────────────────────────────

def _fetch_worker(cricinfo_id: int) -> tuple[int, Optional[dict]]:
    return cricinfo_id, _fetch_athlete(cricinfo_id)


def pass2(commit: bool, max_workers: int = 5, chunk_size: int = 50, pause: float = 0.5,
          re_enrich_missing: bool = False) -> None:
    """Fetch ESPN data for players that have cricinfo_id but missing display_name.

    With re_enrich_missing=True, also re-fetches players that have display_name
    but are still missing player_role or country_id.
    """
    print("\n=== Pass 2: fetch ESPN athlete data ===")

    conn = get_db_connection(autocommit=False)
    cur  = conn.cursor()

    # Build ESPN numeric ID → our country_id lookup
    cur.execute("SELECT espn_id, country_id FROM history.countries WHERE espn_id IS NOT NULL")
    espn_to_country_id: dict[int, int] = {row[0]: row[1] for row in cur.fetchall()}
    print(f"  ESPN→country_id map: {len(espn_to_country_id)} entries")

    if re_enrich_missing:
        cur.execute(
            "SELECT player_id, cricinfo_id FROM history.players "
            "WHERE cricinfo_id IS NOT NULL "
            "  AND display_name IS NOT NULL "
            "  AND (player_role IS NULL OR country_id IS NULL)"
        )
    else:
        cur.execute(
            "SELECT player_id, cricinfo_id FROM history.players "
            "WHERE cricinfo_id IS NOT NULL AND display_name IS NULL"
        )
    rows = cur.fetchall()
    print(f"  Players to enrich: {len(rows):,}")

    if not rows:
        print("  Nothing to do.")
        cur.close(); conn.close()
        return

    # Process in chunks to respect rate limits
    total       = len(rows)
    batch: list[tuple] = []   # (player_id, display_name, batting_style, bowling_style, player_role, country_id)
    fetched     = 0
    failed      = 0
    BATCH_FLUSH = 200

    def _flush(force: bool = False) -> None:
        if not batch or (not force and len(batch) < BATCH_FLUSH):
            return
        if commit:
            cur.executemany(
                """
                UPDATE history.players
                SET    display_name     = %s,
                       batting_style    = %s,
                       bowling_style    = %s,
                       player_role      = COALESCE(%s, player_role),
                       country_id       = COALESCE(%s, country_id),
                       espn_country_int = COALESCE(%s, espn_country_int)
                WHERE  player_id        = %s
                """,
                batch,
            )
            conn.commit()
        batch.clear()

    for chunk_start in range(0, total, chunk_size):
        chunk = rows[chunk_start : chunk_start + chunk_size]
        chunk_end = min(chunk_start + chunk_size, total)
        print(f"  [{chunk_end:>5}/{total}]  fetching …", end="", flush=True)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_fetch_worker, cid): pid for pid, cid in chunk}
            id_to_pid = {cid: pid for pid, cid in chunk}

            for future in as_completed(futures):
                cricinfo_id, data = future.result()
                pid = id_to_pid[cricinfo_id]
                if data:
                    parsed = _parse_athlete(data, espn_to_country_id)
                    batch.append((
                        parsed["display_name"],
                        parsed["batting_style"],
                        parsed["bowling_style"],
                        parsed["player_role"],
                        parsed["country_id"],
                        parsed["espn_country_int"],
                        pid,
                    ))
                    fetched += 1
                else:
                    failed += 1

        _flush()
        print(f"  ok  (fetched={fetched}, failed={failed})")
        if chunk_end < total:
            time.sleep(pause)

    _flush(force=True)

    if not commit:
        print(f"\n  [dry-run] would have updated {fetched} players.")
    else:
        print(f"\n  Done.  Updated: {fetched}  Failed/skipped: {failed}")

    cur.close()
    conn.close()


# ── Country remap (no API) ────────────────────────────────────────────────────

def remap_countries(commit: bool) -> None:
    """Update country_id from cached espn_country_int — no API calls needed."""
    print("\n=== Remap countries from cached espn_country_int ===")
    conn = get_db_connection(autocommit=False)
    cur  = conn.cursor()

    cur.execute("""
        UPDATE history.players p
        SET    country_id = c.country_id
        FROM   history.countries c
        WHERE  c.espn_id      = p.espn_country_int
          AND  p.country_id   IS NULL
          AND  p.espn_country_int IS NOT NULL
    """)
    updated = cur.rowcount
    print(f"  Updated: {updated} players")

    # Report still-unresolved ESPN country integers
    cur.execute("""
        SELECT p.espn_country_int, COUNT(*) AS cnt
        FROM   history.players p
        WHERE  p.country_id       IS NULL
          AND  p.espn_country_int IS NOT NULL
        GROUP  BY p.espn_country_int
        ORDER  BY cnt DESC
        LIMIT  20
    """)
    rows = cur.fetchall()
    if rows:
        print(f"  Still unresolved ESPN country IDs (add to history.countries to fix):")
        for espn_int, cnt in rows:
            print(f"    espn_id={espn_int}: {cnt} players")

    if not commit:
        print("  [dry-run] no changes written.")
        conn.rollback()
    else:
        conn.commit()
        print("  Done.")

    cur.close()
    conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich history.players from ESPN")
    parser.add_argument("--commit",      action="store_true", help="Write to DB (default: dry run)")
    parser.add_argument("--pass1-only",        action="store_true", help="Only run Pass 1 (people.csv → cricinfo_id)")
    parser.add_argument("--pass2-only",        action="store_true", help="Only run Pass 2 (ESPN API fetch)")
    parser.add_argument("--re-enrich-missing", action="store_true", help="Re-fetch players with missing role or country_id")
    parser.add_argument("--remap-countries",   action="store_true", help="Update country_id from cached espn_country_int — no API calls")
    parser.add_argument("--workers",           type=int, default=5,  help="ThreadPoolExecutor workers for Pass 2 (default 5)")
    args = parser.parse_args()

    if args.remap_countries:
        remap_countries(commit=args.commit)
        return

    if args.pass1_only and args.pass2_only:
        parser.error("--pass1-only and --pass2-only are mutually exclusive")

    if not args.pass2_only:
        pass1(commit=args.commit)

    if not args.pass1_only:
        pass2(commit=args.commit, max_workers=args.workers, re_enrich_missing=args.re_enrich_missing)


if __name__ == "__main__":
    main()
