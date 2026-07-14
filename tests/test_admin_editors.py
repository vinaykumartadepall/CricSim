"""
Admin editor write paths, DB-free:

- SquadRepository config-section updates (tournament meta / team meta / venues /
  schedule / squad): validation via parse_tournament_config, edit-log recording,
  and rejection of documents the engine couldn't run.
- PlayerRepository.update_player field validation.
- replay_admin_edits._apply_one dispatch (each entity_type reaches the right
  repo method with record=False).
"""

from unittest.mock import MagicMock

import pytest

import db.replay_admin_edits as replay_mod
from db.player_repository import PlayerRepository
from db.squad_repository import SquadRepository


# ── Fakes ──────────────────────────────────────────────────────────────────────

class _FakeCursor:
    """Answers 'SELECT config ...' with the canned config; records all queries."""

    def __init__(self, config=None, fetchone_results=None):
        self._config = config
        self._queue = list(fetchone_results or [])
        self.executed = []          # [(query, params)]
        self.rowcount = 1

    def execute(self, query, params=None):
        self.executed.append((query, params))
        self._last_query = query

    def fetchone(self):
        if "SELECT config" in self._last_query:
            return {"config": self._config}
        if self._queue:
            return self._queue.pop(0)
        return {"?": 1}

    def queries(self, fragment):
        return [q for q, _ in self.executed if fragment in q]


def _squad_repo(config):
    repo = SquadRepository.__new__(SquadRepository)
    repo.cur = _FakeCursor(config)
    repo.conn = MagicMock()
    return repo


def _config():
    return {
        "tournament_name": "IPL", "format": "T20", "gender": "male", "season": "2024",
        "venues": [{"name": "Wankhede Stadium", "city": "Mumbai"},
                   {"name": "Chepauk", "city": "Chennai"}],
        "teams": [
            {"team_id": 1, "name": "Mumbai Indians", "short_name": "MI",
             "primary_color": "#004B8D", "secondary_color": "#D4AF37",
             "home_venue": "Wankhede Stadium", "players": list(range(101, 112))},
            {"team_id": 2, "name": "Chennai Super Kings", "short_name": "CSK",
             "primary_color": "#F9CD05", "secondary_color": "#0047AB",
             "home_venue": "Chepauk", "players": list(range(201, 212))},
        ],
        "schedule": {"type": "double_round_robin", "neutral_venues": False},
        "playoffs": {"format": "ipl", "top_n": 4},
    }


# ── Tournament / team meta ─────────────────────────────────────────────────────

class TestTournamentMeta:
    def test_rename_updates_config_history_and_records_edit(self):
        repo = _squad_repo(_config())
        repo.update_tournament_meta(7, {"tournament_name": "Indian Premier League"})

        assert repo.cur.queries("UPDATE history.tournaments")
        saves = repo.cur.queries("UPDATE simulation.tournament_seeded")
        assert saves and "Indian Premier League" in repo.cur.executed[-2][1][0]
        assert repo.cur.queries("INSERT INTO simulation.admin_edits")
        repo.conn.commit.assert_called_once()

    def test_invalid_format_rejected_before_any_write(self):
        repo = _squad_repo(_config())
        with pytest.raises(ValueError, match="format"):
            repo.update_tournament_meta(7, {"format": "T10"})
        assert not repo.cur.queries("UPDATE simulation.tournament_seeded")

    def test_no_editable_fields_rejected(self):
        repo = _squad_repo(_config())
        with pytest.raises(ValueError, match="No editable fields"):
            repo.update_tournament_meta(7, {"season": "2030"})


class TestTeamMeta:
    def test_short_name_and_colors_updated(self):
        repo = _squad_repo(_config())
        updated = repo.update_team_meta(7, 1, {"short_name": "MUM", "primary_color": "#111111"})
        assert updated == {"short_name": "MUM", "primary_color": "#111111"}
        assert repo.cur.queries("INSERT INTO simulation.admin_edits")

    def test_home_venue_must_exist_in_venues(self):
        repo = _squad_repo(_config())
        with pytest.raises(ValueError, match="home venue"):
            repo.update_team_meta(7, 1, {"home_venue": "Eden Gardens"})

    def test_clearing_home_venue_is_allowed(self):
        repo = _squad_repo(_config())
        assert repo.update_team_meta(7, 1, {"home_venue": None}) == {"home_venue": None}

    def test_duplicate_team_name_rejected(self):
        repo = _squad_repo(_config())
        with pytest.raises(ValueError, match="Duplicate team name"):
            repo.update_team_meta(7, 1, {"name": "Chennai Super Kings"})

    def test_unknown_team_rejected(self):
        repo = _squad_repo(_config())
        with pytest.raises(ValueError, match="team_id=99"):
            repo.update_team_meta(7, 99, {"short_name": "XX"})


class TestVenues:
    def test_rename_cascades_into_home_venues(self):
        repo = _squad_repo(_config())
        repo.update_venues(7, [
            {"name": "Wankhede", "city": "Mumbai", "previous_name": "Wankhede Stadium"},
            {"name": "Chepauk", "city": "Chennai"},
        ])
        import json
        saved = json.loads(repo.cur.executed[-2][1][0])
        assert saved["teams"][0]["home_venue"] == "Wankhede"

    def test_removed_venue_clears_dangling_home_venue(self):
        repo = _squad_repo(_config())
        repo.update_venues(7, [{"name": "Chepauk", "city": "Chennai"}])
        import json
        saved = json.loads(repo.cur.executed[-2][1][0])
        assert saved["teams"][0]["home_venue"] is None
        assert saved["teams"][1]["home_venue"] == "Chepauk"

    def test_empty_venue_name_rejected(self):
        repo = _squad_repo(_config())
        with pytest.raises(ValueError, match="non-empty name"):
            repo.update_venues(7, [{"name": "  "}])


class TestSchedule:
    def test_unknown_schedule_type_rejected(self):
        repo = _squad_repo(_config())
        with pytest.raises(ValueError, match="schedule.type"):
            repo.update_schedule(7, {"type": "best_of_three"}, None)

    def test_valid_schedule_and_playoffs_saved(self):
        repo = _squad_repo(_config())
        repo.update_schedule(7, {"type": "round_robin", "neutral_venues": True},
                             {"format": "semis_final", "top_n": 4})
        assert repo.cur.queries("UPDATE simulation.tournament_seeded")


class TestSquadWrites:
    def test_squad_write_records_edit(self):
        repo = _squad_repo(_config())
        players = [{"player_id": 300 + i, "batting_position": i} for i in range(1, 12)]
        assert repo.upsert_team_squad(7, 1, players) == 11
        assert repo.cur.queries("INSERT INTO simulation.admin_edits")

    def test_replay_mode_skips_edit_recording(self):
        repo = _squad_repo(_config())
        players = [{"player_id": 300 + i, "batting_position": i} for i in range(1, 12)]
        repo.upsert_team_squad(7, 1, players, record=False)
        assert not repo.cur.queries("INSERT INTO simulation.admin_edits")


# ── Player editor ──────────────────────────────────────────────────────────────

def _player_repo(fetchone_results=None):
    repo = PlayerRepository.__new__(PlayerRepository)
    repo.cur = _FakeCursor(fetchone_results=fetchone_results)
    repo.conn = MagicMock()
    return repo


class TestPlayerUpdate:
    def test_valid_update_writes_and_records(self):
        repo = _player_repo()
        updated = repo.update_player(42, {"player_role": "Keeper", "display_name": "MS Dhoni"})
        assert updated == {"player_role": "Keeper", "display_name": "MS Dhoni"}
        assert repo.cur.queries("UPDATE history.players")
        assert repo.cur.queries("INSERT INTO simulation.admin_edits")
        repo.conn.commit.assert_called_once()

    def test_invalid_role_rejected(self):
        repo = _player_repo()
        with pytest.raises(ValueError, match="player_role"):
            repo.update_player(42, {"player_role": "Wicketkeeper"})

    def test_empty_name_rejected(self):
        repo = _player_repo()
        with pytest.raises(ValueError, match="name cannot be empty"):
            repo.update_player(42, {"name": "   "})

    def test_non_editable_fields_ignored(self):
        repo = _player_repo()
        with pytest.raises(ValueError, match="No editable fields"):
            repo.update_player(42, {"code": "XYZ", "espn_country_int": 5})

    def test_unknown_country_rejected(self):
        repo = _player_repo(fetchone_results=[None])
        with pytest.raises(ValueError, match="Unknown country_id"):
            repo.update_player(42, {"country_id": 9999})


# ── Replay dispatch ────────────────────────────────────────────────────────────

class TestReplayDispatch:
    def _spy_repos(self, monkeypatch):
        squad = MagicMock()
        player = MagicMock()
        monkeypatch.setattr(replay_mod, "SquadRepository", lambda: squad)
        monkeypatch.setattr(replay_mod, "PlayerRepository", lambda: player)
        return squad, player

    def test_each_entity_type_reaches_the_right_method(self, monkeypatch):
        squad, player = self._spy_repos(monkeypatch)

        replay_mod._apply_one({"entity_type": "tournament_meta",
                               "payload": {"tournament_id": 7, "fields": {"format": "ODI"}}})
        squad.update_tournament_meta.assert_called_once_with(7, {"format": "ODI"}, record=False)

        replay_mod._apply_one({"entity_type": "team_meta",
                               "payload": {"tournament_id": 7, "team_id": 1, "fields": {"short_name": "MUM"}}})
        squad.update_team_meta.assert_called_once_with(7, 1, {"short_name": "MUM"}, record=False)

        replay_mod._apply_one({"entity_type": "team_squad",
                               "payload": {"tournament_id": 7, "team_id": 1, "players": []}})
        squad.upsert_team_squad.assert_called_once_with(7, 1, [], record=False)

        replay_mod._apply_one({"entity_type": "player",
                               "payload": {"player_id": 42, "fields": {"player_role": "Batter"}}})
        player.update_player.assert_called_once_with(42, {"player_role": "Batter"}, record=False)

    def test_unknown_entity_type_raises(self, monkeypatch):
        self._spy_repos(monkeypatch)
        with pytest.raises(ValueError, match="Unknown entity_type"):
            replay_mod._apply_one({"entity_type": "mystery", "payload": {}})

    def test_repos_closed_even_on_failure(self, monkeypatch):
        squad, _ = self._spy_repos(monkeypatch)
        squad.update_tournament_meta.side_effect = ValueError("boom")
        with pytest.raises(ValueError):
            replay_mod._apply_one({"entity_type": "tournament_meta",
                                   "payload": {"tournament_id": 7, "fields": {}}})
        squad.close.assert_called_once()
