from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class TeamConfig(BaseModel):
    name: str
    players: List[int]
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None


class MatchSimRequest(BaseModel):
    simulation_type: Literal["match"]
    match_format: str = "T20"
    venue: Optional[str] = None
    bowling_strategy: str = "historical"
    ball_outcome_strategy: str = "enhanced"
    era_normalize_contexts: Optional[List[str]] = None
    team_a: TeamConfig
    team_b: TeamConfig
    client_id: Optional[str] = None


class TournamentVenueConfig(BaseModel):
    name: str
    city: str = ""


class TournamentTeamConfig(BaseModel):
    name: str
    short_name: Optional[str] = None
    players: List[int]  # history.players IDs — no name strings in the API path
    home_venue: Optional[str] = None
    primary_color: str = "#1E88E5"
    secondary_color: str = "#FFFFFF"


class ScheduleConfig(BaseModel):
    type: str = "round_robin"          # round_robin | double_round_robin | two_group_hybrid
    matches_per_pair: int = 1
    neutral_venues: bool = True
    groups: Optional[List[List[str]]] = None
    within_matches_per_pair: int = 1
    cross_matches_per_pair: int = 2


class FixtureConfig(BaseModel):
    home: str
    away: str
    venue: Optional[str] = None


class PlayoffConfig(BaseModel):
    format: str = "none"
    top_n: int = 4


class TournamentSimRequest(BaseModel):
    simulation_type: Literal["tournament"]
    tournament_name: str
    format: str = "T20"
    gender: str = "male"
    season: str = "2025"
    outcome_strategy: str = "enhanced"
    bowling_strategy: str = "historical"
    era_normalize_contexts: Optional[List[str]] = None
    venues: List[TournamentVenueConfig] = Field(default_factory=list)
    teams: List[TournamentTeamConfig]
    schedule: Union[ScheduleConfig, List[FixtureConfig]] = Field(default_factory=ScheduleConfig)
    playoffs: PlayoffConfig = Field(default_factory=PlayoffConfig)
    client_id: Optional[str] = None
    mode: Optional[Literal["fun", "challenge"]] = None


CreateSimRequest = Union[MatchSimRequest, TournamentSimRequest]
