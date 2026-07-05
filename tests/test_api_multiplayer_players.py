"""
Tests for GET /multiplayer/players and GET /multiplayer/player-filters
(api/routes/multiplayer.py) — the player search filters (role, country,
batting/bowling style) that replaced the old keeper_only-only toggle.

No live DB connection required — get_db_connection is monkeypatched with a
fake connection/cursor that records executed SQL/params and returns canned
rows.
"""
from fastapi.testclient import TestClient

import api.routes.multiplayer as mp_routes
from api.main import app


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.last_query = None
        self.last_params = None

    def execute(self, query, params=None):
        self.last_query = query
        self.last_params = params

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


class TestSearchPlayers:

    def test_applies_role_country_and_style_filters(self, monkeypatch):
        cur = _FakeCursor(rows=[])
        monkeypatch.setattr(mp_routes, "get_db_connection", lambda *a, **kw: _FakeConn(cur))

        resp = TestClient(app).get(
            "/cricsimapi/multiplayer/players",
            params=[
                ("q", "sharma"),
                ("role", "Keeper"), ("role", "All-rounder"),
                ("country_id", 7), ("country_id", 9),
                ("batting_style", "Right-hand bat"),
                ("bowling_style", "Legbreak"),
            ],
        )

        assert resp.status_code == 200
        query, params = cur.last_query, cur.last_params
        assert "p.player_role = ANY(%s)" in query
        assert "p.country_id = ANY(%s)" in query
        assert "p.batting_style = ANY(%s)" in query
        assert "p.bowling_style = ANY(%s)" in query
        assert params[:4] == (["Keeper", "All-rounder"], [7, 9], ["Right-hand bat"], ["Legbreak"])
        assert params[-3:] == ("%sharma%", "%sharma%", 30)

    def test_no_filters_omits_filter_clauses(self, monkeypatch):
        cur = _FakeCursor(rows=[])
        monkeypatch.setattr(mp_routes, "get_db_connection", lambda *a, **kw: _FakeConn(cur))

        resp = TestClient(app).get("/cricsimapi/multiplayer/players", params={"q": "kohli"})

        assert resp.status_code == 200
        assert "p.player_role = ANY(%s)" not in cur.last_query
        assert "p.country_id = ANY(%s)" not in cur.last_query
        assert "p.batting_style = ANY(%s)" not in cur.last_query
        assert "p.bowling_style = ANY(%s)" not in cur.last_query
        assert cur.last_params == ("%kohli%", "%kohli%", 30)

    def test_response_includes_country(self, monkeypatch):
        rows = [(1, "V Kohli", "Batter", "Right-hand bat", None, 253802, False, "India")]
        cur = _FakeCursor(rows=rows)
        monkeypatch.setattr(mp_routes, "get_db_connection", lambda *a, **kw: _FakeConn(cur))

        resp = TestClient(app).get("/cricsimapi/multiplayer/players", params={"q": "kohli"})

        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["country"] == "India"
        assert body[0]["name"] == "V Kohli"


class TestPlayerFilterOptions:

    def test_returns_all_four_option_lists(self, monkeypatch):
        class _SequencedCursor(_FakeCursor):
            def __init__(self):
                super().__init__(rows=[])
                self._responses = [
                    [("Batter",), ("Bowler",)],
                    [(1, "India"), (2, "Australia")],
                    [("Right-hand bat",), ("Left-hand bat",)],
                    [("Legbreak",), ("Right-arm fast",)],
                ]
                self._call = 0

            def execute(self, query, params=None):
                self.last_query = query

            def fetchall(self):
                result = self._responses[self._call]
                self._call += 1
                return result

        cur = _SequencedCursor()
        monkeypatch.setattr(mp_routes, "get_db_connection", lambda *a, **kw: _FakeConn(cur))

        resp = TestClient(app).get("/cricsimapi/multiplayer/player-filters")

        assert resp.status_code == 200
        body = resp.json()
        assert body["roles"] == ["Batter", "Bowler"]
        assert body["countries"] == [
            {"country_id": 1, "name": "India"},
            {"country_id": 2, "name": "Australia"},
        ]
        assert body["batting_styles"] == ["Right-hand bat", "Left-hand bat"]
        assert body["bowling_styles"] == ["Legbreak", "Right-arm fast"]
