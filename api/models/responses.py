from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SimCreatedResponse(BaseModel):
    sim_id: str
    status: str = "pending"


class SimSummaryItem(BaseModel):
    sim_id: str
    simulation_type: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    mode: Optional[str] = None
    tournament_name: Optional[str] = None
    season: Optional[str] = None
    user_team_name: Optional[str] = None
    swap_count: Optional[int] = None
    winner_name: Optional[str] = None
    user_team_placement: Optional[str] = None
    match_id: Optional[int] = None


# ── /result ────────────────────────────────────────────────────────────────────

class MatchResultResponse(BaseModel):
    sim_id: str
    simulation_type: str = "match"
    status: str
    home_team: str
    away_team: str
    venue: Optional[str]
    format: str
    winner: Optional[str]
    result_description: Optional[str]
    win_type: Optional[str]
    win_by: Optional[int]


class PointsTableRow(BaseModel):
    team: str
    played: int
    won: int
    lost: int
    tied: int
    no_result: int
    points: int
    nrr: float


class TournamentResultResponse(BaseModel):
    sim_id: str
    simulation_type: str = "tournament"
    status: str
    tournament_name: Optional[str]
    season: Optional[str]
    format: Optional[str]
    winner: Optional[str]
    runner_up: Optional[str]
    total_matches: int
    points_table: List[PointsTableRow]
    user_team_name: Optional[str] = None
    user_team_placement: Optional[str] = None
    mode: Optional[str] = None
    source_tournament_id: Optional[int] = None
    user_team_id: Optional[int] = None


# ── /scorecard ─────────────────────────────────────────────────────────────────

class BatterRow(BaseModel):
    name: str
    runs: int
    balls: int
    fours: int
    sixes: int
    strike_rate: float
    dismissal: Optional[str]       # e.g. "c Salt b Bumrah", "not out", "did not bat"
    headshot_url: Optional[str] = None


class BowlerRow(BaseModel):
    name: str
    overs: str                     # e.g. "4.0"
    runs: int
    wickets: int
    economy: float
    dot_balls: int


class InningScorecard(BaseModel):
    inning_number: int
    batting_team: str
    bowling_team: str
    total_runs: int
    total_wickets: int
    overs: str
    extras: int
    extras_wides: int = 0
    extras_nb: int = 0
    extras_lb: int = 0
    extras_byes: int = 0
    batters: List[BatterRow]
    bowlers: List[BowlerRow]


class ScorecardResponse(BaseModel):
    match_id: int
    match_label: str
    home_team: str
    away_team: str
    venue: Optional[str]
    venue_country: Optional[str] = None
    result_description: Optional[str]
    innings: List[InningScorecard]


# ── /commentary ────────────────────────────────────────────────────────────────

class DeliveryCommentary(BaseModel):
    inning_number: int
    over_ball: str                 # e.g. "3.4"
    bowler: str
    batter: str
    non_striker: str = "Unknown"
    runs_batter: int
    runs_extras: int
    outcome_type: str
    outcome_kind: Optional[str]
    is_wicket: bool
    is_free_hit: bool
    commentary_text: str


class CommentaryResponse(BaseModel):
    match_id: int
    match_label: str
    match_format: Optional[str] = None
    overs_per_innings: Optional[int] = None
    deliveries: List[DeliveryCommentary]


# ── Tournament match result ────────────────────────────────────────────────────

class TournamentMatchResultResponse(BaseModel):
    match_id: int
    match_label: str
    home_team: str
    away_team: str
    venue: Optional[str]
    format: Optional[str]
    winner: Optional[str]
    result_description: Optional[str]
    win_type: Optional[str]
    win_by: Optional[int]
    is_super_over: bool


# ── Tournament match list ──────────────────────────────────────────────────────

class TournamentMatchItem(BaseModel):
    match_id: int
    match_label: str
    home_team: str
    away_team: str
    winner: Optional[str]
    result: Optional[str]
    win_type: Optional[str]
    win_by: Optional[int]
    is_super_over: bool
    venue: Optional[str] = None
    venue_country: Optional[str] = None
    home_score: Optional[int] = None
    home_wickets: Optional[int] = None
    home_overs: Optional[str] = None
    away_score: Optional[int] = None
    away_wickets: Optional[int] = None
    away_overs: Optional[str] = None


# ── Leaderboards ───────────────────────────────────────────────────────────────

class BattingAggregateRow(BaseModel):
    rank: int
    player: str
    team: str
    matches: int
    innings: int
    runs: int
    average: Optional[float]
    strike_rate: Optional[float]
    highest_score: int
    fifties: int
    hundreds: int
    fours: int
    sixes: int
    not_outs: int


class HighestScoreRow(BaseModel):
    rank: int
    player: str
    team: str
    runs: int
    balls: int
    strike_rate: Optional[float]
    fours: int
    sixes: int
    not_out: bool
    opponent: str
    venue: Optional[str]


class BowlingAggregateRow(BaseModel):
    rank: int
    player: str
    team: str
    matches: int
    innings: int
    overs: str
    runs: int
    wickets: int
    economy: Optional[float]
    average: Optional[float]
    strike_rate: Optional[float]
    dots: int
    best_bowling: str
    four_wicket_hauls: int
    five_wicket_hauls: int


class BestFiguresRow(BaseModel):
    rank: int
    player: str
    team: str
    wickets: int
    runs: int
    economy: Optional[float]
    best_figures: str
    opponent: str
    venue: Optional[str]


class MVPRow(BaseModel):
    rank: int
    player: str
    team: str
    batting_pts: float
    bowling_pts: float
    fielding_pts: float
    total: float


class PaginatedLeaderboard(BaseModel):
    leaderboard: str
    sim_id: str
    total: int
    limit: int
    offset: int
    entries: List[Any]


class LeaderboardsDashboard(BaseModel):
    sim_id: str
    most_runs: List[BattingAggregateRow]
    highest_score: List[HighestScoreRow]
    best_batting_average: List[BattingAggregateRow]
    best_strike_rate: List[BattingAggregateRow]
    most_sixes: List[BattingAggregateRow]
    most_fours: List[BattingAggregateRow]
    most_wickets: List[BowlingAggregateRow]
    best_bowling_average: List[BowlingAggregateRow]
    best_economy: List[BowlingAggregateRow]
    best_bowling_figures: List[BestFiguresRow]
    most_dots: List[BowlingAggregateRow]
    mvp: List[MVPRow]
