from __future__ import annotations

import psycopg2
import psycopg2.extras

from db.database import get_supabase_connection


class ProfileRepository:
    """Thin repository for the profiles table, which lives in Supabase DB."""

    def __init__(self):
        self._conn = get_supabase_connection(autocommit=False)
        self._cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def get(self, user_id: str) -> dict | None:
        self._cur.execute(
            "SELECT user_id, display_name FROM simulation.profiles WHERE user_id = %s",
            (user_id,),
        )
        row = self._cur.fetchone()
        return dict(row) if row else None

    def upsert(self, user_id: str, display_name: str, anonymous_id: str | None = None) -> dict:
        self._cur.execute(
            """
            INSERT INTO simulation.profiles (user_id, display_name, anonymous_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
                SET display_name = EXCLUDED.display_name,
                    updated_at   = now()
            RETURNING user_id, display_name
            """,
            (user_id, display_name, anonymous_id),
        )
        return dict(self._cur.fetchone())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._cur.close()
        self._conn.close()
