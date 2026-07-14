"""
Admin edit log: every admin-UI mutation is recorded in simulation.admin_edits
so hand edits can be (a) audited, (b) replayed onto another database
(prod <-> local sync), and (c) re-applied after seed_sim_configs.py overwrites
the seeded configs.

record_edit() is called by the repositories inside the same transaction as the
mutation itself. Replay/export logic lives in db/replay_admin_edits.py.
"""

from __future__ import annotations

import json


def record_edit(cur, entity_type: str, entity_id: str, payload: dict,
                edit_id: str | None = None, edited_at=None) -> None:
    """Append one edit row using the caller's cursor (same transaction as the
    mutation). edit_id/edited_at are only passed by the replay CLI, which
    copies rows verbatim; ON CONFLICT makes re-applying the same file a no-op."""
    cur.execute(
        """
        INSERT INTO simulation.admin_edits (edit_id, edited_at, entity_type, entity_id, payload)
        VALUES (COALESCE(%s::uuid, gen_random_uuid()), COALESCE(%s, now()), %s, %s, %s::jsonb)
        ON CONFLICT (edit_id) DO NOTHING
        """,
        (edit_id, edited_at, entity_type, entity_id, json.dumps(payload)),
    )
