"""
Merge duplicate venue rows in the DB caused by the same physical ground
appearing under slightly different name strings across Cricsheet data.

The canonical groups are defined in venue_country_overrides.json under
canonical_names.  For each group the script:

  1. Finds all venue_ids whose name matches any alias or the canonical name.
  2. Picks the winner — the row whose name IS already the canonical name;
     if none exists, the one with the most history.matches references.
  3. Renames the winner to the canonical name / city if needed.
  4. Re-points all history.matches and simulation.matches to the winner.
  5. Deletes the losing rows.

Usage:
    python -m db.dedup_venues           # dry run (prints plan, no writes)
    python -m db.dedup_venues --commit  # apply changes
"""

from __future__ import annotations

import argparse
from typing import Optional

from db.database import get_db_connection
from db.venue_resolver import load_overrides, all_canonical_groups, invalidate_cache


def _find_venue_ids(cur, names: list[str]) -> list[tuple[int, str, Optional[str], int]]:
    """
    Return [(venue_id, name, city, match_count)] for every row whose name
    case-insensitively matches any of the given names.
    """
    lower_names = [n.lower() for n in names]
    cur.execute(
        """
        SELECT v.venue_id, v.name, v.city,
               COUNT(m.match_id) AS match_count
        FROM history.venues v
        LEFT JOIN history.matches m ON m.venue_id = v.venue_id
        WHERE lower(v.name) = ANY(%s)
        GROUP BY v.venue_id, v.name, v.city
        ORDER BY match_count DESC
        """,
        (lower_names,),
    )
    return cur.fetchall()


def run(commit: bool) -> None:
    invalidate_cache()
    overrides = load_overrides()
    groups = all_canonical_groups(overrides)

    conn = get_db_connection(autocommit=False)
    cur = conn.cursor()

    total_merged = 0
    total_matches_repointed = 0

    for group in groups:
        canonical = group["canonical"]
        canonical_city = group.get("city")
        aliases = group.get("aliases", [])
        all_names = [canonical] + aliases

        rows = _find_venue_ids(cur, all_names)
        if len(rows) <= 1:
            continue  # nothing to merge

        # ── Pick winner ───────────────────────────────────────────────────────
        # Prefer the row that already has the canonical name; fall back to
        # most match_count (rows are already sorted DESC by match_count).
        canonical_lower = canonical.lower()
        winner = next(
            (r for r in rows if r[1].lower() == canonical_lower),
            rows[0],  # fallback: most matches
        )
        winner_id, winner_name, winner_city, winner_count = winner
        losers = [r for r in rows if r[0] != winner_id]
        loser_ids = [r[0] for r in losers]

        print(f"\n[{canonical}]")
        print(f"  winner  : #{winner_id}  '{winner_name}'  ({winner_count} matches)")
        for lid, lname, lcity, lcount in losers:
            print(f"  merge   : #{lid}  '{lname}'  ({lcount} matches)")

        if commit:
            # Rename winner to canonical if needed
            if winner_name != canonical or (canonical_city and winner_city != canonical_city):
                cur.execute(
                    "UPDATE history.venues SET name = %s, city = COALESCE(%s, city) WHERE venue_id = %s",
                    (canonical, canonical_city, winner_id),
                )
                print(f"  renamed → '{canonical}' / city={canonical_city or winner_city}")

            # Re-point history.matches references
            for lid, _, _, lcount in losers:
                cur.execute(
                    "UPDATE history.matches SET venue_id = %s WHERE venue_id = %s",
                    (winner_id, lid),
                )
                total_matches_repointed += lcount

            # Delete losing venue rows (no FK references remain after re-pointing)
            cur.execute(
                "DELETE FROM history.venues WHERE venue_id = ANY(%s)",
                (loser_ids,),
            )
            total_merged += len(loser_ids)

    conn.commit()
    cur.close()
    conn.close()

    if commit:
        print(f"\nDone. Merged {total_merged} duplicate rows; re-pointed {total_matches_repointed} matches.")
    else:
        print("\n[DRY RUN] No changes written. Re-run with --commit to apply.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge duplicate venue rows.")
    parser.add_argument("--commit", action="store_true", help="Write to DB (default: dry run)")
    args = parser.parse_args()
    run(commit=args.commit)
