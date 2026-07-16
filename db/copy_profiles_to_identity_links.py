"""
One-time copy: simulation.profiles (Supabase DB) -> simulation.identity_links
(main DB, migration 031).

simulation.profiles only ever held signed-in users, one row per Supabase auth
user id, with no separate anonymous identity concept. Every row is copied
self-referentially - id = linked_auth_id = user_id - since for these existing
accounts the auth id IS already the canonical identity (any anonymous history
they had before signing in was migrated to their auth id by the old, buggy
link_anonymous mechanism; see db/simulation_repository.py history).

Case-insensitive username collisions (not expected to exist, but not
guaranteed) are resolved by appending _2, _3, ... to every row after the
first, ordered by created_at so the earliest account keeps its name
unsuffixed. Rows already present in identity_links (id already copied by a
previous run) are skipped, so this script is safe to re-run.

Usage:
    python -m db.copy_profiles_to_identity_links           # dry run (prints plan)
    python -m db.copy_profiles_to_identity_links --commit  # apply
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from db.database import get_db_connection, get_supabase_connection


def _fetch_profiles(cur) -> list[dict]:
    cur.execute(
        "SELECT user_id, display_name, created_at FROM simulation.profiles ORDER BY created_at ASC"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _existing_identity_ids(cur) -> set:
    cur.execute("SELECT id FROM simulation.identity_links")
    return {row[0] for row in cur.fetchall()}


def _existing_usernames_lower(cur) -> set:
    cur.execute("SELECT lower(username) FROM simulation.identity_links")
    return {row[0] for row in cur.fetchall()}


def _dedupe_usernames(profiles: list[dict], taken_lower: set) -> list[dict]:
    """Assigns each profile a `final_username`, suffixing _2, _3, ... for every
    name (case-insensitive) that collides with an earlier profile in this same
    batch or with a username identity_links already has."""
    seen_counts: dict = defaultdict(int)
    out = []
    for p in profiles:
        base = p["display_name"]
        key = base.lower()
        candidate = base
        while candidate.lower() in taken_lower:
            seen_counts[key] += 1
            candidate = f"{base}_{seen_counts[key] + 1}"
        taken_lower.add(candidate.lower())
        out.append({**p, "final_username": candidate})
    return out


def run(commit: bool) -> None:
    supa_conn = get_supabase_connection(autocommit=True)
    try:
        supa_cur = supa_conn.cursor()
        profiles = _fetch_profiles(supa_cur)
    finally:
        supa_conn.close()

    if not profiles:
        print("No rows in simulation.profiles - nothing to copy.")
        return

    conn = get_db_connection(autocommit=False)
    try:
        cur = conn.cursor()
        already_copied = _existing_identity_ids(cur)
        taken_lower = _existing_usernames_lower(cur)

        pending = [p for p in profiles if p["user_id"] not in already_copied]
        skipped = len(profiles) - len(pending)

        pending = _dedupe_usernames(pending, taken_lower)
        renamed = [p for p in pending if p["final_username"] != p["display_name"]]

        print(f"simulation.profiles rows: {len(profiles)}")
        print(f"already in identity_links (skipped): {skipped}")
        print(f"to copy: {len(pending)}")
        if renamed:
            print("username collisions resolved by suffixing:")
            for p in renamed:
                print(f"  {p['user_id']}: {p['display_name']!r} -> {p['final_username']!r}")

        if not commit:
            print("\nDry run - no changes written. Re-run with --commit to apply.")
            return

        for p in pending:
            cur.execute(
                """
                INSERT INTO simulation.identity_links (id, username, is_anonymous, linked_auth_id)
                VALUES (%s, %s, FALSE, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (p["user_id"], p["final_username"], p["user_id"]),
            )
        conn.commit()
        print(f"\nCopied {len(pending)} row(s) into simulation.identity_links.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true", help="Apply changes (default: dry run)")
    args = parser.parse_args()
    run(commit=args.commit)
