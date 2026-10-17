"""
Leftover multiplayer rooms (api/routes/multiplayer.py::_reap_orphaned_room_rows).

Live rooms exist only in memory, so every restart left their simulation.rooms
rows behind, and the in-memory reaper never saw them again (15 such rooms on
prod on 2026-10-17). DB tier, against a throwaway database built from
schema.sql.
"""
import pytest

import api.routes.multiplayer as mp


@pytest.fixture
def db(make_db, app_db):
    d = make_db()
    app_db(d)
    return d


def _room(conn, room_id, status, idle_s, member_idle_s=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO simulation.rooms (room_id, host_id, status, tournament_name, updated_at) "
            "VALUES (%s, 'host', %s, 'Cup', now() - make_interval(secs => %s))",
            (room_id, status, idle_s),
        )
        if member_idle_s is not None:
            cur.execute(
                "INSERT INTO simulation.room_members (room_id, client_id, display_name, updated_at) "
                "VALUES (%s, 'm1', 'M', now() - make_interval(secs => %s))",
                (room_id, member_idle_s),
            )


def _remaining(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT room_id FROM simulation.rooms ORDER BY 1")
        return [r[0] for r in cur.fetchall()]


def test_reaps_only_leftovers_idle_past_their_limit(db):
    idle, day = mp.ROOM_IDLE_TIMEOUT_S, mp.ORPHANED_ACTIVE_ROOM_TTL_S
    conn = db.connect("test:rooms")
    _room(conn, "WAITOLD", "waiting", idle + 60)                 # reaped
    _room(conn, "WAITNEW", "waiting", idle - 60)                 # kept: within the idle timeout
    _room(conn, "DRAFTOLD", "drafting", day + 60)                # reaped
    _room(conn, "DRAFTNEW", "drafting", day - 3600)              # kept: players may still reconnect
    _room(conn, "SIMOLD", "simulating", day + 60)                # reaped (sim died with the restart)
    _room(conn, "DRAFTPICK", "drafting", day + 60, member_idle_s=120)   # kept: a recent pick counts
    _room(conn, "LIVE", "waiting", idle + 3600)                  # kept: loaded in memory
    _room(conn, "DONE", "completed", day * 30)                   # kept: completed rooms aren't touched

    reaped = mp._reap_orphaned_room_rows(["LIVE"])

    assert sorted(r for r, _ in reaped) == ["DRAFTOLD", "SIMOLD", "WAITOLD"]
    assert _remaining(conn) == ["DONE", "DRAFTNEW", "DRAFTPICK", "LIVE", "WAITNEW"]
    conn.close()


def test_members_are_removed_with_their_room(db):
    conn = db.connect("test:rooms")
    _room(conn, "OLD", "drafting", mp.ORPHANED_ACTIVE_ROOM_TTL_S + 60,
          member_idle_s=mp.ORPHANED_ACTIVE_ROOM_TTL_S + 60)
    mp._reap_orphaned_room_rows([])
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM simulation.room_members")
        assert cur.fetchone()[0] == 0
    conn.close()
