"""
StatsRepository._run_query must reconnect the shared singleton connection
when it dies mid-process (psycopg2.InterfaceError/OperationalError), instead
of silently returning [] forever afterwards.

Bug (seen in production logs): once the one process-level connection dropped
(observed cause: "SSL connection has been closed unexpectedly" after a long
idle gap - likely a Postgres restart or network-level idle disconnect, not
anything on the app side - RSS/available-RAM stayed flat through the whole
gap), every subsequent query in that uvicorn process's lifetime failed with
"connection already closed" and _run_query swallowed it, returning [].
Callers can't distinguish that from "no data" - resolve_player_by_id
(simulator/predictors/factory.py) treats an empty result as "player not in
DB" and silently substitutes a nameless placeholder player, so every
simulation kept "succeeding" while quietly producing garbage. This affects
match and tournament jobs identically - both go through the same
StatsRepository() singleton with no caching on that particular lookup - so a
single dropped connection breaks every simulation process-wide, not just one
job type.
"""
import psycopg2
import pytest

import db.stats_repository as sr_mod
from db.stats_repository import StatsRepository


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def mogrify(self, query, params):
        return b"<query>"

    def execute(self, query, params):
        pass

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    """closed=True means .cursor() raises, mirroring a dropped psycopg2 connection."""

    def __init__(self, closed=False, rows=None):
        self.closed = closed
        self._rows = rows or []

    def cursor(self):
        if self.closed:
            raise psycopg2.InterfaceError("connection already closed")
        return _FakeCursor(self._rows)


class TestRunQueryReconnect:
    def setup_method(self):
        self._orig_conn = sr_mod.StatsRepository._conn
        self._orig_has_db = sr_mod.HAS_DB
        sr_mod.HAS_DB = True
        self.repo = StatsRepository.__new__(StatsRepository)

    def teardown_method(self):
        sr_mod.StatsRepository._conn = self._orig_conn
        sr_mod.HAS_DB = self._orig_has_db

    def test_reconnects_and_retries_after_dead_connection(self, monkeypatch):
        dead = _FakeConn(closed=True)
        revived = _FakeConn(closed=False, rows=[(1, "ok")])
        monkeypatch.setattr(sr_mod, "get_db_connection", lambda autocommit=True: revived)

        self.repo.conn = dead
        result = self.repo._run_query("SELECT 1", ())

        assert result == [(1, "ok")]
        # The class-level singleton and this instance's own handle both healed.
        assert sr_mod.StatsRepository._conn is revived
        assert self.repo.conn is revived

    def test_gives_up_gracefully_if_reconnect_also_dead(self, monkeypatch):
        monkeypatch.setattr(
            sr_mod, "get_db_connection", lambda autocommit=True: _FakeConn(closed=True)
        )
        self.repo.conn = _FakeConn(closed=True)

        result = self.repo._run_query("SELECT 1", ())

        assert result == []

    def test_gives_up_gracefully_if_reconnect_raises(self, monkeypatch):
        def _boom(autocommit=True):
            raise psycopg2.OperationalError("could not connect to server")

        monkeypatch.setattr(sr_mod, "get_db_connection", _boom)
        self.repo.conn = _FakeConn(closed=True)

        result = self.repo._run_query("SELECT 1", ())

        assert result == []

    def test_unrelated_db_error_returns_empty_without_reconnect_attempt(self, monkeypatch):
        class _RaisesValueError(_FakeConn):
            def cursor(self):
                raise ValueError("not a connection problem")

        called = []
        monkeypatch.setattr(
            sr_mod, "get_db_connection",
            lambda autocommit=True: called.append(1) or _FakeConn(),
        )
        self.repo.conn = _RaisesValueError()

        result = self.repo._run_query("SELECT 1", ())

        assert result == []
        assert called == []  # never attempted a reconnect for a non-connection error

    def test_healthy_connection_never_triggers_reconnect(self, monkeypatch):
        healthy = _FakeConn(closed=False, rows=[(42,)])
        monkeypatch.setattr(
            sr_mod, "get_db_connection",
            lambda autocommit=True: pytest.fail("should not reconnect a healthy connection"),
        )
        self.repo.conn = healthy

        result = self.repo._run_query("SELECT 1", ())

        assert result == [(42,)]
