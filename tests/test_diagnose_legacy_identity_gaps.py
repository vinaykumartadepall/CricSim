"""
db/diagnose_legacy_identity_gaps.py - read-only reporting for the old
link_anonymous bug's blast radius (see module docstring for why this can
only report scale, not attribute ids to accounts). No live DB - a fake
cursor returns canned rows per query.
"""
from unittest.mock import MagicMock

from db.diagnose_legacy_identity_gaps import (
    _known_ids,
    _orphaned_participant_ids,
    _orphaned_game_session_ids,
    _orphaned_room_host_ids,
    _orphaned_room_member_ids,
)


def _cursor(rows):
    cur = MagicMock()
    cur.fetchall.return_value = rows
    return cur


class TestKnownIds:
    def test_includes_both_id_and_linked_auth_id(self):
        cur = _cursor([("A1", "G1"), ("A2", None)])
        assert _known_ids(cur) == {"A1", "G1", "A2"}

    def test_empty_table(self):
        assert _known_ids(_cursor([])) == set()


class TestOrphanedLookups:
    def test_participant_ids_excludes_known(self):
        cur = _cursor([("A1",), ("StaleAnon1",)])
        assert _orphaned_participant_ids(cur, known={"A1"}) == {"StaleAnon1"}

    def test_game_session_ids_excludes_known(self):
        cur = _cursor([("A1",), ("StaleAnon2",)])
        assert _orphaned_game_session_ids(cur, known={"A1"}) == {"StaleAnon2"}

    def test_room_host_ids_excludes_known(self):
        cur = _cursor([("A1",), ("StaleHost",)])
        assert _orphaned_room_host_ids(cur, known={"A1"}) == {"StaleHost"}

    def test_room_member_ids_excludes_known(self):
        cur = _cursor([("A1",), ("StaleMember",)])
        assert _orphaned_room_member_ids(cur, known={"A1"}) == {"StaleMember"}

    def test_all_known_yields_no_orphans(self):
        cur = _cursor([("A1",), ("A2",)])
        assert _orphaned_participant_ids(cur, known={"A1", "A2"}) == set()
