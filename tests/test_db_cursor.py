"""
db_cursor context manager (db/database.py): the connection and cursor must be
closed on every path - clean exit, exception, and early return - because
get_db_connection opens a brand-new psycopg2 connection per call (no pool),
and a leaked connection counts against Postgres max_connections until GC.
"""

from unittest.mock import MagicMock, patch

import pytest

import db.database as db_mod
from db.database import db_cursor


def _mock_conn():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


class TestDbCursor:
    def test_closes_cursor_and_connection_on_success(self):
        conn, cur = _mock_conn()
        with patch.object(db_mod, "get_db_connection", return_value=conn):
            with db_cursor() as c:
                assert c is cur
        cur.close.assert_called_once()
        conn.close.assert_called_once()

    def test_closes_cursor_and_connection_when_body_raises(self):
        conn, cur = _mock_conn()
        with patch.object(db_mod, "get_db_connection", return_value=conn):
            with pytest.raises(RuntimeError):
                with db_cursor():
                    raise RuntimeError("query failed")
        cur.close.assert_called_once()
        conn.close.assert_called_once()

    def test_closes_connection_when_cursor_creation_raises(self):
        conn = MagicMock()
        conn.cursor.side_effect = RuntimeError("cannot create cursor")
        with patch.object(db_mod, "get_db_connection", return_value=conn):
            with pytest.raises(RuntimeError):
                with db_cursor():
                    pass  # pragma: no cover - never reached
        conn.close.assert_called_once()

    def test_autocommit_true_never_commits_or_rolls_back(self):
        conn, _ = _mock_conn()
        with patch.object(db_mod, "get_db_connection", return_value=conn):
            with db_cursor():
                pass
        conn.commit.assert_not_called()
        conn.rollback.assert_not_called()

    def test_non_autocommit_commits_on_clean_exit(self):
        conn, _ = _mock_conn()
        with patch.object(db_mod, "get_db_connection", return_value=conn) as gdc:
            with db_cursor(autocommit=False):
                pass
        gdc.assert_called_once_with(autocommit=False)
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_non_autocommit_rolls_back_on_exception(self):
        conn, _ = _mock_conn()
        with patch.object(db_mod, "get_db_connection", return_value=conn):
            with pytest.raises(ValueError):
                with db_cursor(autocommit=False):
                    raise ValueError("bad data")
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_closes_on_early_return(self):
        conn, cur = _mock_conn()

        def helper():
            with patch.object(db_mod, "get_db_connection", return_value=conn):
                with db_cursor() as c:
                    return c.fetchone()

        helper()
        cur.close.assert_called_once()
        conn.close.assert_called_once()
