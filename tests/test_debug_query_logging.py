"""
Tests for SQL query logging (DEBUG level — see db/database.py's
make_query_logging_cursor docstring for why not INFO/TRACE):
  - db.database.make_query_logging_cursor — the reusable cursor-wrapping factory
  - StatsRepository._run_query logs the rendered SQL before executing
  - SimulationRepository wires both its cursors through the logging factory

sim_id/match_id context is injected into every log line automatically by
simulator.logger's existing ContextFilter (set via log_context() in
api/worker.py) — nothing here needs to pass sim_id explicitly, which is
exactly the point of building on that existing mechanism.

No live DB connection required anywhere in this file.
"""
from unittest.mock import MagicMock, patch

import db.database as db_mod
from db.database import make_query_logging_cursor
from db.stats_repository import StatsRepository


class _FakeBaseCursor:
    """Stand-in for a psycopg2 cursor — just enough surface for the wrapper."""

    def __init__(self):
        self.executed = []

    def mogrify(self, query, vars=None):
        rendered = query if vars is None else f"{query} % {vars}"
        return rendered.encode('utf-8')

    def execute(self, query, vars=None):
        self.executed.append((query, vars))
        return "executed"


class TestMakeQueryLoggingCursor:

    def test_execute_logs_rendered_sql_at_debug_level(self):
        LoggingCursor = make_query_logging_cursor(_FakeBaseCursor)
        cur = LoggingCursor()
        with patch.object(db_mod, 'get_logger') as mock_get_logger, \
             patch.object(db_mod, 'is_level_active', return_value=True):
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            cur.execute("SELECT 1 WHERE id = %s", (42,))
            mock_logger.debug.assert_called_once()
            fmt, rendered = mock_logger.debug.call_args[0]
            assert fmt == "SQL: %s"
            assert "42" in rendered

    def test_execute_still_calls_through_to_base_class(self):
        LoggingCursor = make_query_logging_cursor(_FakeBaseCursor)
        cur = LoggingCursor()
        with patch.object(db_mod, 'get_logger', return_value=MagicMock()), \
             patch.object(db_mod, 'is_level_active', return_value=True):
            result = cur.execute("SELECT 1", None)
        assert result == "executed"
        assert cur.executed == [("SELECT 1", None)]

    def test_falls_back_to_raw_query_if_mogrify_fails(self):
        class _BrokenMogrify(_FakeBaseCursor):
            def mogrify(self, query, vars=None):
                raise RuntimeError("boom")

        LoggingCursor = make_query_logging_cursor(_BrokenMogrify)
        cur = LoggingCursor()
        with patch.object(db_mod, 'get_logger') as mock_get_logger, \
             patch.object(db_mod, 'is_level_active', return_value=True):
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            cur.execute("SELECT 1", None)
            mock_logger.debug.assert_called_once_with("SQL: %s", "SELECT 1")

    def test_no_log_call_when_no_handler_would_show_it(self):
        LoggingCursor = make_query_logging_cursor(_FakeBaseCursor)
        cur = LoggingCursor()
        with patch.object(db_mod, 'get_logger') as mock_get_logger, \
             patch.object(db_mod, 'is_level_active', return_value=False):
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            result = cur.execute("SELECT 1", None)
        mock_logger.debug.assert_not_called()
        assert result == "executed"

    def test_insert_statements_are_never_logged(self):
        """Bulk INSERTs (e.g. save_deliveries) render every row's literal
        values via mogrify — one such statement measured at 2000+ log lines
        by itself in production. Must be skipped regardless of log level."""
        LoggingCursor = make_query_logging_cursor(_FakeBaseCursor)
        cur = LoggingCursor()
        with patch.object(db_mod, 'get_logger') as mock_get_logger, \
             patch.object(db_mod, 'is_level_active', return_value=True):
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            result = cur.execute(
                "INSERT INTO simulation.deliveries (a, b) VALUES (%s, %s)", (1, 2)
            )
        mock_logger.debug.assert_not_called()
        assert result == "executed"
        assert cur.executed == [("INSERT INTO simulation.deliveries (a, b) VALUES (%s, %s)", (1, 2))]

    def test_insert_check_is_case_insensitive_and_ignores_leading_whitespace(self):
        LoggingCursor = make_query_logging_cursor(_FakeBaseCursor)
        cur = LoggingCursor()
        with patch.object(db_mod, 'get_logger') as mock_get_logger, \
             patch.object(db_mod, 'is_level_active', return_value=True):
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            cur.execute("  \n  insert into x values (%s)", (1,))
        mock_logger.debug.assert_not_called()

    def test_insert_statements_as_bytes_are_never_logged(self):
        """Regression guard: psycopg2.extras.execute_batch (used by
        save_deliveries) mogrifies rows itself and calls execute() with the
        already-rendered batch as BYTES, not str, with vars=None. This is the
        actual path that leaked a 2000+ line log entry into production —
        str(some_bytes) gives "b'...'" and silently never matched "INSERT"."""
        LoggingCursor = make_query_logging_cursor(_FakeBaseCursor)
        cur = LoggingCursor()
        with patch.object(db_mod, 'get_logger') as mock_get_logger, \
             patch.object(db_mod, 'is_level_active', return_value=True):
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            cur.execute(b"INSERT INTO simulation.deliveries (a) VALUES (1);INSERT INTO simulation.deliveries (a) VALUES (2)")
        mock_logger.debug.assert_not_called()

    def test_select_and_update_still_logged(self):
        LoggingCursor = make_query_logging_cursor(_FakeBaseCursor)
        cur = LoggingCursor()
        with patch.object(db_mod, 'get_logger') as mock_get_logger, \
             patch.object(db_mod, 'is_level_active', return_value=True):
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            cur.execute("UPDATE simulation.simulations SET status = %s", ('completed',))
        mock_logger.debug.assert_called_once()


class TestStatsRepositoryRunQueryLogsDebug:

    def test_logs_rendered_sql_before_executing(self):
        mock_cursor = MagicMock()
        mock_cursor.mogrify.return_value = b"SELECT * FROM x WHERE id = 42"
        mock_cursor.fetchall.return_value = [(1,)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        repo = StatsRepository.__new__(StatsRepository)
        repo.conn = mock_conn

        with patch('db.stats_repository.get_logger') as mock_get_logger, \
             patch('db.stats_repository.is_level_active', return_value=True):
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            result = repo._run_query("SELECT * FROM x WHERE id = %s", (42,))

        mock_logger.debug.assert_called_once_with("SQL: %s", "SELECT * FROM x WHERE id = 42")
        assert result == [(1,)]

    def test_no_query_logged_when_no_connection(self):
        repo = StatsRepository.__new__(StatsRepository)
        repo.conn = None
        with patch('db.stats_repository.get_logger') as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            result = repo._run_query("SELECT 1")
        mock_logger.debug.assert_not_called()
        assert result == []

    def test_no_log_call_when_debug_not_active(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1,)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        repo = StatsRepository.__new__(StatsRepository)
        repo.conn = mock_conn

        with patch('db.stats_repository.get_logger') as mock_get_logger, \
             patch('db.stats_repository.is_level_active', return_value=False):
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            result = repo._run_query("SELECT 1")

        mock_logger.debug.assert_not_called()
        mock_cursor.mogrify.assert_not_called()
        assert result == [(1,)]


class TestSimulationRepositoryUsesLoggingCursors:

    def test_cursors_created_with_logging_factory(self):
        from db.simulation_repository import _LoggingCursor, _LoggingDictCursor
        import db.simulation_repository as sim_repo_mod

        mock_conn = MagicMock()
        with patch.object(sim_repo_mod, 'get_db_connection', return_value=mock_conn):
            sim_repo_mod.SimulationRepository()

        factories_used = [
            call.kwargs.get('cursor_factory') for call in mock_conn.cursor.call_args_list
        ]
        assert _LoggingCursor in factories_used
        assert _LoggingDictCursor in factories_used
