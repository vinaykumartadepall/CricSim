"""
api/worker.py::_build_tournament_config - the parser feeding every tournament
simulation. It delegates to the shared parse_tournament_config (the same
function that loads config files and validates admin edits) plus three
worker-only behaviors these tests pin down:

1. absent/empty outcome/bowling strategies fall back to the admin-configured
   defaults (not the parser's static literals),
2. explicit strategies are respected untouched,
3. era_normalize_contexts defaults to a fresh COPY of ERA_NORMALIZE_ALL, so
   later mutation can't poison the module-level constant.
"""

import pytest

from api.worker import _build_tournament_config
from simulator.admin_settings import get_admin_settings
from simulator.tournament.config import ERA_NORMALIZE_ALL, Fixture, ScheduleConfig


def _seeded_style_config() -> dict:
    """Mirrors what simulation.tournament_seeded.config actually contains,
    including the extra team keys (team_id) the parser must tolerate."""
    return {
        "tournament_name": "Indian Premier League",
        "format": "T20",
        "gender": "male",
        "season": "2024",
        "venues": [{"name": "Wankhede Stadium", "city": "Mumbai"},
                   {"name": "MA Chidambaram Stadium, Chepauk", "city": "Chennai"}],
        "teams": [
            {"team_id": 1, "name": "Mumbai Indians", "short_name": "MI",
             "primary_color": "#004B8D", "secondary_color": "#D4AF37",
             "home_venue": "Wankhede Stadium", "players": list(range(101, 112))},
            {"team_id": 2, "name": "Chennai Super Kings",
             "home_venue": None, "players": list(range(201, 212))},
        ],
        "schedule": {"type": "two_group_hybrid", "neutral_venues": False,
                     "within_matches_per_pair": 1, "cross_matches_per_pair": 2,
                     "groups": [["Mumbai Indians"], ["Chennai Super Kings"]]},
        "playoffs": {"format": "ipl", "top_n": 4},
    }


class TestBuildTournamentConfig:
    def test_seeded_config_round_trips(self):
        cfg = _build_tournament_config(_seeded_style_config())
        assert cfg.tournament_name == "Indian Premier League"
        assert cfg.format == "T20"
        assert [v.name for v in cfg.venues] == ["Wankhede Stadium", "MA Chidambaram Stadium, Chepauk"]
        assert cfg.venues[0].city == "Mumbai"
        assert cfg.teams[0].name == "Mumbai Indians"
        assert cfg.teams[0].short_name == "MI"
        assert cfg.teams[0].home_venue == "Wankhede Stadium"
        assert cfg.teams[0].players == list(range(101, 112))
        # short_name auto-derives, colors default, when absent
        assert cfg.teams[1].short_name == "CHE"
        assert cfg.teams[1].primary_color == "#1E88E5"
        assert isinstance(cfg.schedule, ScheduleConfig)
        assert cfg.schedule.type == "two_group_hybrid"
        assert cfg.schedule.neutral_venues is False
        assert cfg.schedule.groups == [["Mumbai Indians"], ["Chennai Super Kings"]]
        assert cfg.playoffs.format == "ipl"
        assert cfg.playoffs.top_n == 4

    def test_explicit_fixture_list_schedule(self):
        raw = _seeded_style_config()
        raw["schedule"] = [
            {"home": "Mumbai Indians", "away": "Chennai Super Kings", "venue": "Wankhede Stadium"},
            {"home": "Chennai Super Kings", "away": "Mumbai Indians"},
        ]
        cfg = _build_tournament_config(raw)
        assert isinstance(cfg.schedule, list)
        assert all(isinstance(f, Fixture) for f in cfg.schedule)
        assert cfg.schedule[0].venue == "Wankhede Stadium"
        assert cfg.schedule[0].match_number == 1
        assert cfg.schedule[1].venue is None
        assert cfg.schedule[1].match_number == 2

    def test_missing_strategies_fall_back_to_admin_defaults(self):
        cfg = _build_tournament_config(_seeded_style_config())
        settings = get_admin_settings()
        assert cfg.outcome_strategy == settings.default_outcome_strategy
        assert cfg.bowling_strategy == settings.default_bowling_strategy

    def test_empty_string_strategy_also_falls_back(self):
        raw = _seeded_style_config()
        raw["outcome_strategy"] = ""
        raw["bowling_strategy"] = ""
        cfg = _build_tournament_config(raw)
        settings = get_admin_settings()
        assert cfg.outcome_strategy == settings.default_outcome_strategy
        assert cfg.bowling_strategy == settings.default_bowling_strategy

    def test_explicit_strategies_respected(self):
        raw = _seeded_style_config()
        raw["outcome_strategy"] = "historical"
        raw["bowling_strategy"] = "smart"
        cfg = _build_tournament_config(raw)
        assert cfg.outcome_strategy == "historical"
        assert cfg.bowling_strategy == "smart"

    @pytest.mark.parametrize("present", [False, True])
    def test_era_contexts_default_is_a_fresh_copy(self, present):
        raw = _seeded_style_config()
        if present:
            raw["era_normalize_contexts"] = None  # explicit null, same as absent
        cfg = _build_tournament_config(raw)
        assert cfg.era_normalize_contexts == list(ERA_NORMALIZE_ALL)
        cfg.era_normalize_contexts.append("poisoned")
        assert "poisoned" not in ERA_NORMALIZE_ALL

    def test_explicit_era_contexts_respected(self):
        raw = _seeded_style_config()
        raw["era_normalize_contexts"] = ["venue"]
        cfg = _build_tournament_config(raw)
        assert cfg.era_normalize_contexts == ["venue"]

    def test_defaults_for_minimal_config(self):
        cfg = _build_tournament_config({"teams": [{"name": "A", "players": [1]},
                                                  {"name": "B", "players": [2]}]})
        assert cfg.tournament_name == "Cricket Tournament"
        assert cfg.format == "T20"
        assert cfg.season == "2025"
        assert isinstance(cfg.schedule, ScheduleConfig)
        assert cfg.schedule.type == "round_robin"
        assert cfg.playoffs.format == "none"
