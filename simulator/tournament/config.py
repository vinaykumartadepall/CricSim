"""
Tournament configuration dataclasses and JSON loader.

A tournament config is a JSON file with the following structure:

{
  "tournament_name": "IPL 2025",
  "format": "T20",
  "gender": "male",
  "season": "2025",
  "outcome_strategy": "enhanced",   // or "historical"
  "bowling_strategy": "historical", // or "smart"

  "venues": [
    {"name": "Wankhede Stadium", "city": "Mumbai"}
  ],

  "teams": [
    {
      "name": "Mumbai Indians",
      "short_name": "MI",
      "home_venue": "Wankhede Stadium",  // optional
      "primary_color": "#004C97",
      "secondary_color": "#D1AB3E",
      "players": ["RG Sharma", "Ishan Kishan", ...]
    }
  ],

  // Option A: auto-generated schedule
  "schedule": {
    "type": "round_robin",      // round_robin | double_round_robin
    "matches_per_pair": 1,      // 1 for round_robin, 2 for double
    "neutral_venues": true      // if false, home team plays at home_venue
  },

  // Option B: explicit fixture list
  "schedule": [
    {
      "home": "Mumbai Indians",
      "away": "Chennai Super Kings",
      "venue": "Wankhede Stadium"   // optional, overrides home_venue
    }
  ],

  // Playoff format
  "playoffs": {
    "format": "ipl",    // none | two_teams | semis_final | ipl | quarters_semis_final
    "top_n": 4          // how many teams qualify from group stage
  }
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy import ERA_NORMALIZE_ALL


@dataclass
class VenueConfig:
    name: str
    city: str = ""


@dataclass
class TeamConfig:
    name: str
    short_name: str
    players: List[Union[int, str]]  # int = history.players ID (API path); str = name (JSON/CLI path)
    home_venue: Optional[str] = None
    primary_color: str = "#1E88E5"
    secondary_color: str = "#FFFFFF"


@dataclass
class ScheduleConfig:
    type: str = "round_robin"          # round_robin | double_round_robin | two_group_hybrid
    matches_per_pair: int = 1          # used for round_robin / double_round_robin
    neutral_venues: bool = True
    # two_group_hybrid only - teams divided into two named groups
    groups: Optional[List[List[str]]] = None  # [[group_a_names...], [group_b_names...]]
    within_matches_per_pair: int = 1           # how many times same-group pairs play
    cross_matches_per_pair: int = 2            # how many times cross-group pairs play


@dataclass
class Fixture:
    """A single scheduled match."""
    home: str
    away: str
    venue: Optional[str] = None
    match_number: int = 0
    match_label: str = ""     # e.g. "Semi-final 1", "Final"


@dataclass
class PlayoffConfig:
    format: str = "none"    # none | two_teams | semis_final | ipl | quarters_semis_final
    top_n: int = 4


@dataclass
class TournamentConfig:
    tournament_name: str
    format: str                        # T20 | ODI | Test
    gender: str
    season: str
    venues: List[VenueConfig]
    teams: List[TeamConfig]
    schedule: Union[ScheduleConfig, List[Fixture]]  # auto or explicit
    playoffs: PlayoffConfig
    outcome_strategy: str = "enhanced"
    bowling_strategy: str = "historical"
    era_normalize_contexts: List[str] = field(default_factory=lambda: list(ERA_NORMALIZE_ALL))

    @property
    def team_by_name(self) -> Dict[str, TeamConfig]:
        return {t.name: t for t in self.teams}

    @property
    def venue_names(self) -> List[str]:
        return [v.name for v in self.venues]


def load_tournament_config(path: str) -> TournamentConfig:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return parse_tournament_config(raw)


def parse_tournament_config(raw: dict) -> TournamentConfig:
    """Parse a raw config document (file contents or the tournament_seeded.config
    JSONB) into a TournamentConfig. Raises KeyError/TypeError/ValueError on
    malformed documents - the admin editor uses this as its save-time validator."""
    venues = [VenueConfig(name=v["name"], city=v.get("city", "")) for v in raw.get("venues", [])]

    teams = []
    for t in raw.get("teams", []):
        teams.append(TeamConfig(
            name=t["name"],
            short_name=t.get("short_name", t["name"][:3].upper()),
            players=t.get("players", []),
            home_venue=t.get("home_venue"),
            primary_color=t.get("primary_color", "#1E88E5"),
            secondary_color=t.get("secondary_color", "#FFFFFF"),
        ))

    raw_sched = raw.get("schedule", {"type": "round_robin"})
    if isinstance(raw_sched, list):
        schedule: Union[ScheduleConfig, List[Fixture]] = [
            Fixture(
                home=f["home"],
                away=f["away"],
                venue=f.get("venue"),
                match_number=i + 1,
            )
            for i, f in enumerate(raw_sched)
        ]
    else:
        schedule = ScheduleConfig(
            type=raw_sched.get("type", "round_robin"),
            matches_per_pair=raw_sched.get("matches_per_pair", 1),
            neutral_venues=raw_sched.get("neutral_venues", True),
            groups=raw_sched.get("groups"),
            within_matches_per_pair=raw_sched.get("within_matches_per_pair", 1),
            cross_matches_per_pair=raw_sched.get("cross_matches_per_pair", 2),
        )

    raw_po = raw.get("playoffs", {"format": "none"})
    playoffs = PlayoffConfig(
        format=raw_po.get("format", "none"),
        top_n=raw_po.get("top_n", 4),
    )

    return TournamentConfig(
        tournament_name=raw.get("tournament_name", "Cricket Tournament"),
        format=raw.get("format", "T20"),
        gender=raw.get("gender", "male"),
        season=raw.get("season", "2025"),
        venues=venues,
        teams=teams,
        schedule=schedule,
        playoffs=playoffs,
        outcome_strategy=raw.get("outcome_strategy", "enhanced"),
        bowling_strategy=raw.get("bowling_strategy", "historical"),
        era_normalize_contexts=raw.get("era_normalize_contexts", ERA_NORMALIZE_ALL),
    )
