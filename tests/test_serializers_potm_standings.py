"""
Tests for the read side of persisted POTM / final standings:
- get_scorecard includes a potm dict built from simulation.matches columns
  (player_of_match_id/potm_player_name/potm_team_name/potm_points), instead
  of the frontend recomputing it from scratch.
- get_tournament_result prefers simulation.tournaments.final_standings when
  present, and only falls back to the (deprecated) _build_points_table SQL
  recomputation for pre-migration sims that don't have it yet.

No live DB connection — cur is a MagicMock; internals that aren't the focus
of a given test (_fetch_innings_deliveries, _build_points_table) are
monkeypatched out rather than exercised, keeping each test to the one thing
it's checking.
"""
from unittest.mock import MagicMock

import simulator.serializers.match as match_mod


class TestGetScorecardPotm:
    def _match_row(self, **overrides):
        row = {
            'match_id': 1, 'match_label': 'Final', 'venue_id': 1,
            'match_format': 'T20', 'overs_per_innings': 20,
            'home_team': 'Alpha', 'away_team': 'Beta', 'winner': 'Alpha',
            'venue_name': 'Wankhede', 'venue_country': 'India',
            'result': 'win', 'win_type': 'runs', 'win_by': 10,
            'player_of_match_id': None, 'potm_player_name': None,
            'potm_team_name': None, 'potm_points': None,
            'is_super_over': False,
        }
        row.update(overrides)
        return row

    def test_includes_potm_when_set(self, monkeypatch):
        monkeypatch.setattr(match_mod, '_fetch_match_row', lambda cur, mid: self._match_row(
            player_of_match_id=7, potm_player_name='Virat Kohli',
            potm_team_name='RCB', potm_points=87.46,
        ))
        monkeypatch.setattr(match_mod, '_fetch_innings_deliveries', lambda cur, mid: {})

        data = match_mod.get_scorecard(MagicMock(), 1)

        assert data['potm'] == {
            'player_id': 7, 'name': 'Virat Kohli', 'team': 'RCB', 'points': 87.46,
        }

    def test_potm_none_when_unset(self, monkeypatch):
        monkeypatch.setattr(match_mod, '_fetch_match_row', lambda cur, mid: self._match_row())
        monkeypatch.setattr(match_mod, '_fetch_innings_deliveries', lambda cur, mid: {})

        data = match_mod.get_scorecard(MagicMock(), 1)

        assert data['potm'] is None

    def test_empty_dict_when_match_not_found(self, monkeypatch):
        monkeypatch.setattr(match_mod, '_fetch_match_row', lambda cur, mid: None)

        assert match_mod.get_scorecard(MagicMock(), 999) == {}


class TestGetTournamentResultStandingsSource:
    def _cur_returning(self, t_row, matches_rows, gs_row):
        cur = MagicMock()
        # get_tournament_result issues 3 SELECTs in order: tournaments, matches, game_sessions.
        cur.fetchone.side_effect = [t_row, gs_row]
        cur.fetchall.return_value = matches_rows
        return cur

    def test_uses_persisted_final_standings_when_present(self, monkeypatch):
        persisted = [{"team": "Alpha", "played": 1, "won": 1, "lost": 0,
                      "tied": 0, "no_result": 0, "points": 2, "nrr": 0.39}]
        cur = self._cur_returning(
            t_row={"tournament_name": "IPL", "season": "2025", "format": "T20",
                   "final_standings": persisted},
            matches_rows=[],
            gs_row=None,
        )
        called = {"build_points_table": False}
        def _fail_if_called(*a, **kw):
            called["build_points_table"] = True
            return []
        monkeypatch.setattr(match_mod, '_build_points_table', _fail_if_called)

        result = match_mod.get_tournament_result(cur, "sim-1")

        assert result["points_table"] == persisted
        assert called["build_points_table"] is False

    def test_falls_back_to_rebuild_when_final_standings_absent(self, monkeypatch):
        cur = self._cur_returning(
            t_row={"tournament_name": "IPL", "season": "2025", "format": "T20",
                   "final_standings": None},
            matches_rows=[],
            gs_row=None,
        )
        fallback_result = [{"team": "Alpha", "played": 0, "won": 0, "lost": 0,
                             "tied": 0, "no_result": 0, "points": 0, "nrr": 0.0}]
        monkeypatch.setattr(match_mod, '_build_points_table', lambda cur, sim_id, group_matches: fallback_result)

        result = match_mod.get_tournament_result(cur, "sim-1")

        assert result["points_table"] == fallback_result
