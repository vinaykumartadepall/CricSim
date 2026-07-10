"""
Tests for api.main._resume_or_fail_interrupted_sims() - the startup sweep
that handles sims left mid-flight by a previous process lifetime (crash or
restart), since this deploys as a single uvicorn process with no external
job broker (see api/job_queue.py).

No live DB connection required - get_db_connection is monkeypatched with a
fake connection/cursor (same pattern as tests/test_api_multiplayer_players.py),
and job_queue.submit is monkeypatched to record calls instead of actually
running anything.
"""
import api.main as main_mod


class _FakeCursor:
    def __init__(self, pending_rows):
        self._pending_rows = pending_rows
        self.executed = []
        self.rowcount = 0

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if query.strip().startswith("UPDATE"):
            self.rowcount = 3  # pretend 3 rows were stuck 'running'

    def fetchall(self):
        return self._pending_rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


class TestResumeOrFailInterruptedSims:

    def test_marks_running_sims_failed(self, monkeypatch):
        cur = _FakeCursor(pending_rows=[])
        monkeypatch.setattr(main_mod, "get_db_connection", lambda *a, **kw: _FakeConn(cur))
        submitted = []
        monkeypatch.setattr(main_mod.job_queue, "submit", lambda *a, **kw: submitted.append((a, kw)))

        main_mod._resume_or_fail_interrupted_sims()

        update_query = cur.executed[0][0]
        assert "UPDATE" in update_query
        assert "status = 'failed'" in update_query
        assert "WHERE status = 'running'" in update_query

    def test_resubmits_pending_match_sim(self, monkeypatch):
        cur = _FakeCursor(pending_rows=[
            ("sim-1", "match", {"foo": "bar"}, "client-a"),
        ])
        monkeypatch.setattr(main_mod, "get_db_connection", lambda *a, **kw: _FakeConn(cur))
        submitted = []
        monkeypatch.setattr(main_mod.job_queue, "submit", lambda *a, **kw: submitted.append((a, kw)))

        main_mod._resume_or_fail_interrupted_sims()

        assert len(submitted) == 1
        args, kwargs = submitted[0]
        assert args[0] == "sim-1"                       # job_id
        assert args[1] is main_mod.run_match_job         # fn
        assert args[2:] == ("sim-1", {"foo": "bar"})     # sim_id, config
        assert kwargs == {}

    def test_resubmits_pending_tournament_sim_with_client_id(self, monkeypatch):
        cur = _FakeCursor(pending_rows=[
            ("sim-2", "tournament", {"teams": []}, "client-b"),
        ])
        monkeypatch.setattr(main_mod, "get_db_connection", lambda *a, **kw: _FakeConn(cur))
        submitted = []
        monkeypatch.setattr(main_mod.job_queue, "submit", lambda *a, **kw: submitted.append((a, kw)))

        main_mod._resume_or_fail_interrupted_sims()

        assert len(submitted) == 1
        args, kwargs = submitted[0]
        assert args[0] == "sim-2"
        assert args[1] is main_mod.run_tournament_job
        assert args[2:] == ("sim-2", {"teams": []})
        assert kwargs == {"client_id": "client-b"}

    def test_no_pending_sims_submits_nothing(self, monkeypatch):
        cur = _FakeCursor(pending_rows=[])
        monkeypatch.setattr(main_mod, "get_db_connection", lambda *a, **kw: _FakeConn(cur))
        submitted = []
        monkeypatch.setattr(main_mod.job_queue, "submit", lambda *a, **kw: submitted.append((a, kw)))

        main_mod._resume_or_fail_interrupted_sims()

        assert submitted == []
