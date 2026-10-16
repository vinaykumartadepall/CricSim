"""
Shared fixtures for the DB tier: throwaway PostgreSQL databases built from
db/schema.sql on the local server. Tests that use them are skipped (not
failed) when no local Postgres is reachable or databases can't be created,
so the rest of the suite still runs without a database.
"""
import uuid
from pathlib import Path

import psycopg2
import pytest

import db.database as database

SCHEMA_SQL = (Path(__file__).resolve().parent.parent / "db" / "schema.sql").read_text()


class ThrowawayDB:
    """A database created from schema.sql; dropped by the fixture that made it."""

    def __init__(self, admin, name: str):
        self._admin = admin
        self.name = name

    def connect(self, actor: str = "test:default", autocommit: bool = True):
        with database.db_actor(actor):
            conn = database._connect(dbname=self.name, user=database.DB_USER, password=database.DB_PASS,
                                     host=database.DB_HOST, port=database.DB_PORT)
        conn.autocommit = autocommit
        return conn

    def drop(self):
        with self._admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def _pg_admin():
    try:
        admin = psycopg2.connect(dbname="postgres", user=database.DB_USER, password=database.DB_PASS,
                                 host=database.DB_HOST, port=database.DB_PORT, connect_timeout=3)
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres: {e}")
    admin.autocommit = True
    yield admin
    admin.close()


@pytest.fixture(scope="session")
def make_db(_pg_admin):
    """Factory: make_db() -> ThrowawayDB built from schema.sql. All dropped at teardown."""
    made = []

    def _make() -> ThrowawayDB:
        name = f"cricsim_test_{uuid.uuid4().hex[:10]}"
        try:
            with _pg_admin.cursor() as cur:
                cur.execute(f'CREATE DATABASE "{name}"')
        except psycopg2.Error as e:
            pytest.skip(f"cannot create a test database: {e}")
        db = ThrowawayDB(_pg_admin, name)
        made.append(db)
        conn = db.connect("test:schema")
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.close()
        return db

    yield _make
    for db in made:
        db.drop()


@pytest.fixture
def app_db(monkeypatch):
    """Point the app's get_db_connection() at a ThrowawayDB for the test."""
    def _use(db: ThrowawayDB):
        monkeypatch.setattr(database, "_DATABASE_URL", None)
        monkeypatch.setattr(database, "DB_NAME", db.name)
    return _use


@pytest.fixture
def as_identity():
    """Route tests that aren't about authentication: stand in for a verified
    identity without real credentials. Returns a helper that builds the request
    headers - e.g. client.get(url, headers=as_identity("a")). No header means
    no credentials (401 on endpoints that require an identity). The real check
    (api/identity_auth.py) is tested in tests/test_identity_auth.py."""
    from typing import Optional

    from fastapi import Header

    from api.identity_auth import Identity, _request_identity
    from api.main import app

    def _test_identity(x_test_identity: Optional[str] = Header(None)) -> Optional[Identity]:
        return Identity(x_test_identity, f"client:{x_test_identity}") if x_test_identity else None

    app.dependency_overrides[_request_identity] = _test_identity
    yield lambda ident: {"X-Test-Identity": ident}
    app.dependency_overrides.pop(_request_identity, None)
