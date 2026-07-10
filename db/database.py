import logging
import os
import psycopg2
from psycopg2 import sql

from simulator.logger import get_logger, is_level_active


def _is_insert_query(query) -> bool:
    # psycopg2.extras.execute_batch (used by save_deliveries etc.) mogrifies each
    # row itself and passes the already-rendered, semicolon-joined batch to
    # execute() as bytes, not str - str(some_bytes) gives "b'...'" in Python 3,
    # which would never match "INSERT" and silently defeated this check.
    if isinstance(query, (bytes, bytearray)):
        try:
            query = query.decode('utf-8', 'replace')
        except Exception:
            return False
    return str(query).lstrip().upper().startswith("INSERT")


def make_query_logging_cursor(base_cursor_cls):
    """
    Wrap a psycopg2 cursor class so every .execute() call logs the fully
    rendered SQL (query text with parameters substituted in) at DEBUG level.

    DEBUG, not TRACE - TRACE is dominated by extremely high-volume per-ball/
    per-over strategy dumps (see simulator/logger.py's level table), which
    would drown out query visibility entirely if SQL logging shared that
    level. DEBUG is opt-in (not enabled by default like INFO) but doesn't
    carry that TRACE-level noise, so flipping to DEBUG gives clean query
    visibility on demand without it cluttering the default log output.

    INSERTs are skipped entirely - bulk inserts (e.g. save_deliveries, writing
    every ball of a match in one statement) render via mogrify() with every
    row's literal values embedded, producing a single log line thousands of
    lines long. Confirmed in practice: one such INSERT consumed most of a
    12MB capture and only explained 549 of its ~258k lines. Everything else
    (SELECT, UPDATE, ...) still logs normally.

    The active sim_id/match_id (set via simulator.logger.log_context, e.g. in
    api/worker.py's run_match_job/run_tournament_job) is injected into the log
    line automatically by the existing ContextFilter - callers never need to
    pass it explicitly.
    """
    class _QueryLoggingCursor(base_cursor_cls):
        def execute(self, query, vars=None):
            if is_level_active(logging.DEBUG) and not _is_insert_query(query):
                try:
                    rendered = self.mogrify(query, vars).decode('utf-8', 'replace')
                except Exception:
                    rendered = query
                get_logger().debug("SQL: %s", rendered)
            return super().execute(query, vars)
    return _QueryLoggingCursor

# DATABASE_URL takes precedence (standard format used by all hosting platforms).
# Falls back to individual DB_* vars for local dev without a URL.
_DATABASE_URL = os.environ.get('DATABASE_URL')

# Supabase DB - stores only the profiles table.
# Falls back to main connection if not set (e.g. local dev).
_SUPABASE_DATABASE_URL = os.environ.get('SUPABASE_DATABASE_URL')

DB_NAME = os.environ.get('DB_NAME', 'cricket_db')
DB_USER = os.environ.get('DB_USER', 'vnaykumart')
DB_PASS = os.environ.get('DB_PASS', '')
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_PORT = os.environ.get('DB_PORT', '5432')

def get_supabase_connection(autocommit=True):
    """Connection to Supabase DB (profiles table only). Falls back to main DB if SUPABASE_DATABASE_URL is not set."""
    url = _SUPABASE_DATABASE_URL or _DATABASE_URL
    if url:
        conn = psycopg2.connect(url)
    else:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            host=DB_HOST,
            port=DB_PORT,
        )
    if autocommit:
        conn.autocommit = True
    return conn


def get_db_connection(autocommit=True):
    if _DATABASE_URL:
        conn = psycopg2.connect(_DATABASE_URL)
    else:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            host=DB_HOST,
            port=DB_PORT,
        )
    if autocommit:
        conn.autocommit = True
    return conn

def create_database():
    try:
        conn = psycopg2.connect(
            dbname='postgres',
            user=DB_USER,
            password=DB_PASS,
            host=DB_HOST,
            port=DB_PORT
        )
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (DB_NAME,))
        exists = cur.fetchone()

        if not exists:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(DB_NAME))
            )
            print(f"Database {DB_NAME} created successfully.")
        else:
            print(f"Database {DB_NAME} already exists.")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error creating database: {e}")

def initialize_schema():
    """Apply schema DDL then seed reference data. Idempotent."""
    conn = get_db_connection()
    cur = conn.cursor()

    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    with open(schema_path, 'r') as f:
        cur.execute(f.read())
    conn.commit()
    print("Schema initialized.")

    seed_path = os.path.join(os.path.dirname(__file__), 'seed_data.sql')
    with open(seed_path, 'r') as f:
        cur.execute(f.read())
    conn.commit()
    print("Seed data applied.")

    cur.close()
    conn.close()

if __name__ == "__main__":
    create_database()
    initialize_schema()
