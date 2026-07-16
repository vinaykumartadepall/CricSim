"""
Read-only diagnostic for the OLD link_anonymous bug (superseded by
simulation.identity_links + IdentityRepository.link_account - see
db/identity_repository.py). That bug only ever ran
`UPDATE simulation.simulations SET client_id = auth_id WHERE client_id = anon_id`,
so a signed-in user's OWN single-player simulations.client_id was fixed, but
their old anonymous id was never propagated into:
    simulation.simulations.participant_ids (multiplayer participant list)
    simulation.game_sessions.client_id     (per-participant UI/team context)
    simulation.rooms.host_id               (draft room creator)
    simulation.room_members.client_id      (draft room roster)

IMPORTANT - this cannot identify *which* account a stale id later became:
multiplayer simulations are created with client_id=None (see
api/routes/multiplayer.py), and simulation.profiles.anonymous_id was never
actually populated (confirmed via git history), so there is no stored record
anywhere linking an old anonymous client_id to the auth id it may have later
signed in as. This script only reports SCALE (how many ids/rows look
unresolved) - it does not attempt to guess pairings or write anything.

Most "orphaned" ids this reports are NOT broken accounts - they're simply
anonymous sessions that haven't loaded the app since simulation.identity_links
shipped (sync_anonymous hasn't run for them yet), which is expected and
harmless. If a specific user reports symptoms (e.g. shown as a spectator in
a past multiplayer game after signing in), the practical path is manual:
look up their known anonymous display name in the relevant room_members rows
that DID happen for their sim/room to identify the room in question.

Usage:
    python -m db.diagnose_legacy_identity_gaps
"""
from __future__ import annotations

from db.database import get_db_connection


def _known_ids(cur) -> set:
    cur.execute("SELECT id, linked_auth_id FROM simulation.identity_links")
    known = set()
    for row_id, linked_auth_id in cur.fetchall():
        known.add(row_id)
        if linked_auth_id:
            known.add(linked_auth_id)
    return known


def _orphaned_participant_ids(cur, known: set) -> set:
    cur.execute(
        "SELECT DISTINCT unnest(participant_ids) FROM simulation.simulations "
        "WHERE participant_ids <> '{}'"
    )
    return {row[0] for row in cur.fetchall()} - known


def _orphaned_game_session_ids(cur, known: set) -> set:
    cur.execute("SELECT DISTINCT client_id FROM simulation.game_sessions")
    return {row[0] for row in cur.fetchall()} - known


def _orphaned_room_host_ids(cur, known: set) -> set:
    cur.execute("SELECT DISTINCT host_id FROM simulation.rooms")
    return {row[0] for row in cur.fetchall()} - known


def _orphaned_room_member_ids(cur, known: set) -> set:
    cur.execute("SELECT DISTINCT client_id FROM simulation.room_members")
    return {row[0] for row in cur.fetchall()} - known


def run() -> None:
    conn = get_db_connection(autocommit=True)
    try:
        cur = conn.cursor()
        known = _known_ids(cur)

        orphaned = {
            "simulations.participant_ids": _orphaned_participant_ids(cur, known),
            "game_sessions.client_id": _orphaned_game_session_ids(cur, known),
            "rooms.host_id": _orphaned_room_host_ids(cur, known),
            "room_members.client_id": _orphaned_room_member_ids(cur, known),
        }
    finally:
        conn.close()

    print(f"identity_links rows: {len(known)} known id(s) (self + linked auth ids)\n")
    print("Orphaned ids per table (present in the table, absent from identity_links -")
    print("mostly not-yet-synced anonymous sessions, see module docstring):\n")
    total = 0
    for table, ids in orphaned.items():
        print(f"  {table}: {len(ids)} orphaned id(s)")
        total += len(ids)
    print(f"\nTotal orphaned id references: {total}")
    print(
        "\nNo pairing between an orphaned id and a signed-in account can be "
        "inferred from stored data - see module docstring. This report is "
        "for gauging scale only; no changes were made."
    )


if __name__ == "__main__":
    run()
