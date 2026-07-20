"""
Deterministic ORDER BY tiebreakers for every paginated leaderboard query
(db/leaderboard_repository.py).

Bug (reproduced against real prod-scale data before this fix): every
leaderboard's ORDER BY sorted only by the display stat (wickets, runs,
average, total points, ...) with no tiebreaker. Ties on that stat are common
(e.g. dozens of bowlers sharing figures like 3/24 in a single tournament), and
Postgres does not guarantee a stable row order among ties across separate
query executions. The frontend's "Load More" pagination (ResultsPage.tsx)
issues a new query per page (growing offset) - so a tied row could land in
two different pages' windows, appearing twice on screen (or another row
being skipped). Confirmed empirically: running best_bowling_figures paginated
over five real completed tournament sims showed the exact same
(bowler_id, match_id) pair surfacing on two different pages.

Fix: append a tiebreaker that is unique per row to every affected ORDER BY -
the row's own id columns for the per-innings-performance queries
(best_bowling_figures, highest_score), the aggregate's player id for the
one-row-per-player queries (batting_aggregate, bowling_aggregate), and the
table's own primary key for mvp.

These tests assert the SQL text (no live DB - a fake cursor records the
executed query, matching this project's established pattern, e.g.
tests/test_api_multiplayer_players.py).
"""
import re

from db.leaderboard_repository import LeaderboardRepository


class _FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.last_query = None

    def execute(self, query, params=None):
        self.last_query = query

    def fetchall(self):
        return self._rows


def _order_by_clause(sql: str) -> str:
    """Extract the query's own ORDER BY (immediately before its LIMIT) -
    several queries here have earlier, unrelated ORDER BYs inside CTEs
    (e.g. best_bowling's DISTINCT ON ordering), so take the last one, which
    is always the outer query's pagination order."""
    matches = re.findall(r"ORDER BY(.+?)LIMIT", sql, re.DOTALL)
    assert matches, f"no ORDER BY/LIMIT found in query:\n{sql}"
    return " ".join(matches[-1].split())


class TestBestBowlingFiguresTiebreaker:
    def test_order_by_includes_full_row_identity(self):
        cur = _FakeCursor()
        LeaderboardRepository(cur).best_bowling_figures("sim-1", limit=20, offset=0)
        order_by = _order_by_clause(cur.last_query)
        assert "ib.wickets DESC" in order_by
        assert "ib.runs ASC" in order_by
        assert "ib.bowler_id" in order_by
        assert "ib.match_id" in order_by
        assert "ib.inning_number" in order_by

    def test_reuses_shared_inning_bowling_cte_not_a_duplicate(self):
        """best_bowling_figures previously had its own hand-rolled copy of
        _INNING_BOWLING_CTE (missing inning_number) instead of sharing it with
        bowling_aggregate - exactly the kind of duplication that let this bug
        go unnoticed in one of the two copies."""
        cur = _FakeCursor()
        LeaderboardRepository(cur).best_bowling_figures("sim-1", limit=20, offset=0)
        assert "inning_bowling AS" in cur.last_query
        assert cur.last_query.count("inning_bowling AS") == 1


class TestHighestScoreTiebreaker:
    def test_order_by_includes_full_row_identity(self):
        cur = _FakeCursor()
        LeaderboardRepository(cur).highest_score("sim-1", limit=20, offset=0)
        order_by = _order_by_clause(cur.last_query)
        assert "ib.inning_runs DESC" in order_by
        assert "ib.balls ASC" in order_by
        assert "ib.batter_id" in order_by
        assert "ib.match_id" in order_by
        assert "ib.inning_number" in order_by


class TestBattingAggregateTiebreaker:
    def test_order_by_includes_batter_id_for_every_sort_column(self):
        cur = _FakeCursor()
        repo = LeaderboardRepository(cur)
        for leaderboard in ("most-runs", "best-batting-average", "best-strike-rate", "most-sixes", "most-fours"):
            repo.batting_aggregate("sim-1", leaderboard, limit=20, offset=0)
            order_by = _order_by_clause(cur.last_query)
            assert order_by.endswith("batter_id"), f"{leaderboard}: {order_by}"


class TestBowlingAggregateTiebreaker:
    def test_order_by_includes_bowler_id_for_every_sort_column(self):
        cur = _FakeCursor()
        repo = LeaderboardRepository(cur)
        for leaderboard in ("most-wickets", "best-bowling-average", "best-economy", "most-dots"):
            repo.bowling_aggregate("sim-1", leaderboard, limit=20, offset=0)
            order_by = _order_by_clause(cur.last_query)
            assert order_by.endswith("bowler_id"), f"{leaderboard}: {order_by}"


class TestMvpTiebreaker:
    def test_order_by_includes_award_id(self):
        cur = _FakeCursor()
        LeaderboardRepository(cur).mvp("sim-1", limit=20, offset=0)
        order_by = _order_by_clause(cur.last_query)
        assert "DESC" in order_by
        assert order_by.endswith("pa.award_id")


class TestMvpCricinfoId:
    """mvp() selects cricinfo_id raw (not a derived headshot_url) - this is
    what api/worker.py persists into simulation.leaderboard_cache, and we
    want that to store the small stable id rather than a URL string baked to
    today's CDN path. api/routes/leaderboards.py converts to headshot_url via
    db.headshots.with_headshot_url right before building the API response,
    not here - see tests/test_db_headshots.py for that conversion."""

    def test_selects_cricinfo_id(self):
        cur = _FakeCursor()
        LeaderboardRepository(cur).mvp("sim-1", limit=20, offset=0)
        assert "hp.cricinfo_id" in cur.last_query

    def test_row_passes_cricinfo_id_through_raw(self):
        cur = _FakeCursor(rows=[{
            "player": "Virat Kohli", "team": "Royal Challengers Bangalore",
            "batting_pts": 100.0, "bowling_pts": 0.0, "fielding_pts": 5.0, "total": 105.0,
            "cricinfo_id": 253802, "total_count": 1,
        }])
        entries, _ = LeaderboardRepository(cur).mvp("sim-1", limit=20, offset=0)
        assert entries[0]["cricinfo_id"] == 253802
        assert "headshot_url" not in entries[0]
