from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from simulator.entities.team import MatchTeam
from simulator.events import MatchEventBus
from simulator.presentation.colors import rgb, bold, dim
from simulator.presentation.formatters import format_innings_scorecard
from db.entities.venue import Venue
from db.entities.tournament import Tournament

if TYPE_CHECKING:
    from simulator.entities.inning import Inning
    from simulator.entities.inning_team import InningTeam
    from simulator.entities.inning_player import InningPlayer
    from simulator.entities.delivery import SimulationDelivery


class MatchStatus(Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


@dataclass
class MatchResult:
    """Set by the match engine at completion. Consumed by the tournament layer."""
    winner: Optional[str]       # winning team name, or None for tie/no result
    description: str            # e.g. "Mumbai Indians won by 2 wickets"
    is_tie: bool = False
    is_no_result: bool = False

    # Per-team summary for NRR and points-table calculations.
    # Keys are team names; values are (runs_scored, balls_faced).
    team_innings_summary: dict = field(default_factory=dict)


@dataclass
class SimulationMatch:
    id: Optional[int]
    home_team: MatchTeam
    away_team: MatchTeam
    venue: Optional[Venue] = None
    overs_per_innings: Optional[int] = 20
    innings_per_match: int = 2
    balls_per_over: int = 6

    innings: List["Inning"] = field(default_factory=list)

    current_inning: int = 1
    current_over: int = 0
    current_ball: int = 0

    current_batting_team: Optional["InningTeam"] = None
    current_bowling_team: Optional["InningTeam"] = None

    striker: Optional["InningPlayer"] = None
    non_striker: Optional["InningPlayer"] = None
    current_bowler: Optional["InningPlayer"] = None

    target_score: Optional[int] = None
    follow_on_enforced: bool = False
    is_super_over: bool = False
    is_free_hit: bool = False
    status: MatchStatus = MatchStatus.SCHEDULED
    result: Optional["MatchResult"] = None

    match_format: str = "T20"
    gender: str = "male"
    tournament: Optional[Tournament] = None

    event_bus: MatchEventBus = field(default_factory=MatchEventBus)

    @property
    def deliveries(self) -> List["SimulationDelivery"]:
        return [d for inning in self.innings for d in inning.deliveries]

    # ── Presentation ──────────────────────────────────────────────────────────

    def print_scorecard(self) -> None:
        """Print all innings scorecards with ANSI colours when team colors are set."""
        for inning in self.innings:
            if not inning.batting_team or not inning.bowling_team:
                continue
            print(format_innings_scorecard(inning))

    def print_result(self, label: str = "", venue: str = "") -> None:
        """Print the match result block (teams, winner, description)."""
        home = self.home_team
        away = self.away_team
        colored = home.primary_color is not None

        h_str = rgb(home.name, home.primary_color, bold=True) if colored else bold(home.name)
        a_str = rgb(away.name, away.primary_color, bold=True) if colored else bold(away.name)
        venue_str = f"  @ {dim(venue)}" if venue else ""

        print(f"\n  {bold(label) if label else ''}{venue_str}")
        print(f"  {h_str}  vs  {a_str}")
        if self.result and self.result.winner:
            winner_team = (home if home.name == self.result.winner else
                           away if away.name == self.result.winner else None)
            wcolor = winner_team.primary_color if winner_team else None
            winner_str = "Winner: " + self.result.winner
            colored_winner = rgb(winner_str, wcolor, bold=True) if wcolor else bold(winner_str)
            print(f"  → {colored_winner}  {self.result.description}")
        else:
            desc = self.result.description if self.result else "No result"
            print(f"  → {desc}")
