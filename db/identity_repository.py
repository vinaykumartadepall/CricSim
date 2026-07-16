"""
Single source of identity for both anonymous and authenticated users -
simulation.identity_links (migration 031). Replaces simulation.profiles
(Supabase-hosted) and the earlier idea of a separate anon_profiles table.

Every person has exactly one canonical `id`: their original anonymous
client_id if they ever played anonymously first, or their Supabase auth user
id if they signed in with no prior anonymous history. resolve_client_id() is
the one function every simulation.* consumer calls before touching data, so
no table - existing or future - ever needs its own per-table migration logic
when someone signs in; only one row in this table changes.

Linking (link_account) happens exactly once per Google account, at its first
ever sign-in. Every sign-in after that is a no-op lookup - it deliberately
never merges in whatever anonymous activity happened between a sign-out and
a later sign-in to an already-linked account. That is a product decision,
not an oversight: see the conversation this was designed in.
"""

from __future__ import annotations

import psycopg2.errors
import psycopg2.extras

from db.database import get_db_connection


class UsernameTakenError(Exception):
    """Raised when a username is already claimed by a different identity."""

    def __init__(self, username: str):
        self.username = username
        super().__init__(f"Username already taken: {username}")


class IdentityRepository:
    def __init__(self):
        self._conn = get_db_connection(autocommit=False)
        self._cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._cur.close()
        self._conn.close()

    # ── Resolution ───────────────────────────────────────────────────────────

    def resolve_client_id(self, raw_id: str | None) -> str | None:
        """
        The one function every simulation.* consumer calls before using a
        client_id from a request. Returns the canonical id raw_id currently
        resolves to - or raw_id itself if there's no link row yet (a plain
        anonymous session that hasn't synced, or an id nothing has ever
        linked), which degrades safely rather than erroring.
        """
        if raw_id is None:
            return None
        self._cur.execute(
            "SELECT id FROM simulation.identity_links WHERE id = %s OR linked_auth_id = %s",
            (raw_id, raw_id),
        )
        row = self._cur.fetchone()
        return row["id"] if row else raw_id

    # ── Anonymous identity ───────────────────────────────────────────────────

    def sync_anonymous(self, anon_id: str, username: str) -> None:
        """
        Passive sync: called on every app load for an anonymous session, and
        on explicit rename. Upserts the CURRENT localStorage name for this
        anon id - the only way an anonymous identity's data ever reaches the
        server at all. Existing anonymous identities self-heal the first
        time they reopen the app after this shipped; no backfill needed.
        A username collision here (astronomically unlikely for an
        auto-generated name) is swallowed rather than raised - a passive
        background sync should never surface a hard error to the user for
        this; their existing username is simply left as-is.
        """
        try:
            self._cur.execute(
                """
                INSERT INTO simulation.identity_links (id, username, is_anonymous)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (id) DO UPDATE
                    SET username = EXCLUDED.username, updated_at = now()
                """,
                (anon_id, username),
            )
            self.commit()
        except psycopg2.errors.UniqueViolation:
            self.rollback()

    # ── Sign-in / linking ────────────────────────────────────────────────────

    def link_account(self, auth_id: str, current_client_id: str, fallback_username: str) -> str:
        """
        Called once per sign-in. If auth_id has never been linked before,
        this is genuinely the first time this Google account has signed in:
        link whichever identity current_client_id resolves to (creating a
        row for it if none exists yet - e.g. anon sync never ran) to this
        auth_id, and return the canonical id. If auth_id is ALREADY linked
        (a returning sign-in), this is a no-op that just returns the
        existing canonical id.
        """
        self._cur.execute(
            "SELECT id FROM simulation.identity_links WHERE linked_auth_id = %s",
            (auth_id,),
        )
        existing = self._cur.fetchone()
        if existing:
            return existing["id"]

        canonical_id = self.resolve_client_id(current_client_id) or current_client_id
        self._cur.execute(
            "SELECT id FROM simulation.identity_links WHERE id = %s",
            (canonical_id,),
        )
        has_row = self._cur.fetchone() is not None

        try:
            if has_row:
                self._cur.execute(
                    """
                    UPDATE simulation.identity_links
                    SET linked_auth_id = %s, is_anonymous = FALSE, updated_at = now()
                    WHERE id = %s
                    """,
                    (auth_id, canonical_id),
                )
            else:
                # No row yet (e.g. passive sync hasn't run) - create one,
                # self-referential to the current session's own id.
                self._cur.execute(
                    """
                    INSERT INTO simulation.identity_links (id, username, is_anonymous, linked_auth_id)
                    VALUES (%s, %s, FALSE, %s)
                    """,
                    (canonical_id, fallback_username, auth_id),
                )
            self.commit()
        except psycopg2.errors.UniqueViolation:
            self.rollback()
            # Either a concurrent sign-in for the same account just won the
            # race (linked_auth_id collision - re-check and use its result),
            # or the fallback username collided (a real conflict to surface).
            self._cur.execute(
                "SELECT id FROM simulation.identity_links WHERE linked_auth_id = %s",
                (auth_id,),
            )
            row = self._cur.fetchone()
            if row:
                return row["id"]
            raise UsernameTakenError(fallback_username)

        return canonical_id

    # ── Username ─────────────────────────────────────────────────────────────

    def get_username(self, canonical_id: str) -> str | None:
        self._cur.execute(
            "SELECT username FROM simulation.identity_links WHERE id = %s",
            (canonical_id,),
        )
        row = self._cur.fetchone()
        return row["username"] if row else None

    def get_usernames(self, canonical_ids: list) -> dict:
        """Batched lookup for admin/list views: {id: username}. ids that have
        no row (never synced) are simply omitted from the result."""
        if not canonical_ids:
            return {}
        self._cur.execute(
            "SELECT id, username FROM simulation.identity_links WHERE id = ANY(%s)",
            (list(canonical_ids),),
        )
        return {r["id"]: r["username"] for r in self._cur.fetchall()}

    def set_username(self, canonical_id: str, username: str) -> None:
        try:
            self._cur.execute(
                "UPDATE simulation.identity_links SET username = %s, updated_at = now() WHERE id = %s",
                (username, canonical_id),
            )
            self.commit()
        except psycopg2.errors.UniqueViolation:
            self.rollback()
            raise UsernameTakenError(username)
