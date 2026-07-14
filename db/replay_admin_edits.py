"""
Export / replay the admin edit log (simulation.admin_edits) between databases.

Typical flow - edits made on prod via the admin UI, synced to local:

    # on the droplet
    python db/replay_admin_edits.py --export edits.jsonl
    # locally, after scp'ing the file down
    python db/replay_admin_edits.py --apply edits.jsonl

--apply is idempotent: rows whose edit_id already exists in the target are
skipped, and applied rows are copied into the target's log verbatim (same
edit_id/edited_at), so repeated applies are no-ops and both DBs end up with
identical logs. It also re-applies hand edits after seed_sim_configs.py has
overwritten the seeded configs.

Replays go through the same repository methods the admin API uses (with
record=False, since the original edit row is copied instead) - one write path.
Uses the DB that DATABASE_URL / DB_* env vars point at.
"""

from __future__ import annotations

import argparse
import json
import sys

from db.admin_edits import record_edit
from db.database import get_db_connection
from db.player_repository import PlayerRepository
from db.squad_repository import SquadRepository
from simulator.logger import configure_logger, get_logger


def export_edits(path: str) -> int:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT edit_id, edited_at, entity_type, entity_id, payload "
                "FROM simulation.admin_edits ORDER BY edited_at, edit_id"
            )
            rows = cur.fetchall()
        finally:
            cur.close()
    finally:
        conn.close()

    with open(path, "w", encoding="utf-8") as f:
        for edit_id, edited_at, entity_type, entity_id, payload in rows:
            f.write(json.dumps({
                "edit_id":     str(edit_id),
                "edited_at":   edited_at.isoformat(),
                "entity_type": entity_type,
                "entity_id":   entity_id,
                "payload":     payload,
            }) + "\n")
    return len(rows)


def _apply_one(edit: dict) -> None:
    """Dispatch one edit through the same repo methods the admin API uses."""
    etype   = edit["entity_type"]
    payload = edit["payload"]

    if etype == "player":
        repo = PlayerRepository()
        try:
            repo.update_player(payload["player_id"], payload["fields"], record=False)
        finally:
            repo.close()
        return

    repo = SquadRepository()
    try:
        if etype == "tournament_meta":
            repo.update_tournament_meta(payload["tournament_id"], payload["fields"], record=False)
        elif etype == "team_meta":
            repo.update_team_meta(payload["tournament_id"], payload["team_id"],
                                  payload["fields"], record=False)
        elif etype == "tournament_venues":
            repo.update_venues(payload["tournament_id"], payload["venues"], record=False)
        elif etype == "tournament_schedule":
            repo.update_schedule(payload["tournament_id"], payload.get("schedule"),
                                 payload.get("playoffs"), record=False)
        elif etype == "team_squad":
            repo.upsert_team_squad(payload["tournament_id"], payload["team_id"],
                                   payload["players"], record=False)
        else:
            raise ValueError(f"Unknown entity_type: {etype}")
    finally:
        repo.close()


def apply_edits(path: str) -> tuple[int, int, int]:
    """Returns (applied, skipped, failed)."""
    log = get_logger()
    with open(path, encoding="utf-8") as f:
        edits = [json.loads(line) for line in f if line.strip()]

    applied = skipped = failed = 0
    for edit in edits:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM simulation.admin_edits WHERE edit_id = %s",
                        (edit["edit_id"],))
            exists = cur.fetchone() is not None
            cur.close()
        finally:
            conn.close()
        if exists:
            skipped += 1
            continue

        try:
            _apply_one(edit)
        except Exception:
            log.exception("Failed to apply edit %s (%s %s)",
                          edit["edit_id"], edit["entity_type"], edit["entity_id"])
            failed += 1
            continue

        # Copy the original row so both DBs carry the same log (and a second
        # --apply of this file skips it).
        conn = get_db_connection(autocommit=False)
        try:
            cur = conn.cursor()
            record_edit(cur, edit["entity_type"], edit["entity_id"], edit["payload"],
                        edit_id=edit["edit_id"], edited_at=edit["edited_at"])
            conn.commit()
            cur.close()
        finally:
            conn.close()
        applied += 1

    return applied, skipped, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", metavar="FILE", help="write the edit log to FILE (jsonl)")
    group.add_argument("--apply", metavar="FILE", help="replay edits from FILE onto this DB")
    args = parser.parse_args()

    configure_logger()
    if args.export:
        count = export_edits(args.export)
        print(f"Exported {count} edits to {args.export}")
        return 0

    applied, skipped, failed = apply_edits(args.apply)
    print(f"Applied {applied}, skipped {skipped} already-present, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
