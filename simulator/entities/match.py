from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from simulator.entities.team import MatchTeam
from simulator.events import MatchEventBus
from db.entities.venue import Venue
from db.entities.tournament import Tournament

if TYPE_CHECKING:
    from simulator.entities.inning import Inning
    from simulator.entities.inning_team import InningTeam
    from simulator.entities.inning_player import InningPlayer
    from simulator.entities.delivery import SimulationDelivery


class MatchStatus(Enum):
    SCHEDULED   = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED   = "COMPLETED"
    ABANDONED   = "ABANDONED"


@dataclass
class MatchResult:
    """Set by the match engine at completion. Consumed by the tournament layer."""
    winner: Optional[str]       # winning team name, or None for tie / no result
    description: str            # e.g. "Mumbai Indians won by 2 wickets"
    is_tie: bool = False
    is_no_result: bool = False

    # Per-team (runs_scored, balls_faced) used for NRR and points-table calculations.
    team_innings_summary: dict = field(default_factory=dict)

    # Set only by TournamentEngine's playoff tiebreak chain, when a knockout
    # fixture's genuine outcome was a tie/draw (is_tie/is_no_result above stay
    # true - the match itself really was drawn) but a winner still had to be
    # picked to progress the bracket. None for a normal decisive/tie/draw
    # result. Values: "super_over_tied_rank", "first_innings_lead", "group_stage_rank".
    tiebreak_reason: Optional[str] = None
    tiebreak_margin: Optional[int] = None  # numeric margin backing the reason, if any


@dataclass
class SimulationMatch:
    """
    Central state container for a match simulation.

    Fields are grouped by concern:

    ① Static match identity - set once at construction, never mutated.
    ② Accumulated innings data - grows as innings complete.
    ③ Live inning cursor - current position within the active inning.
    ④ Active delivery context - changes on every ball.
    ⑤ Terminal match state - written by the engine at match completion.

    Presentation is handled externally by
    ``simulator.presentation.formatters.print_match_scorecard`` and
    ``print_match_result``; this class intentionally contains no I/O.
    """

    # ── ① Static match identity ────────────────────────────────────────────────
    id: Optional[int]
    home_team: MatchTeam
    away_team: MatchTeam
    venue: Optional[Venue] = None
    overs_per_innings: Optional[int] = 20
    innings_per_match: int = 2
    balls_per_over: int = 6
    match_format: str = "T20"
    gender: str = "male"
    tournament: Optional[Tournament] = None
    era_normalize_contexts: List[str] = field(default_factory=list)

    # ── ② Accumulated innings data ─────────────────────────────────────────────
    innings: List["Inning"] = field(default_factory=list)

    # ── ③ Live inning cursor ───────────────────────────────────────────────────
    current_inning: int = 1
    current_over: int = 0
    current_ball: int = 0
    current_batting_team: Optional["InningTeam"] = None
    current_bowling_team: Optional["InningTeam"] = None

    # ── ④ Active delivery context ──────────────────────────────────────────────
    striker: Optional["InningPlayer"] = None
    non_striker: Optional["InningPlayer"] = None
    current_bowler: Optional["InningPlayer"] = None
    is_free_hit:   bool = False
    is_super_over: bool = False

    # ── ⑤ Terminal match state ─────────────────────────────────────────────────
    target_score: Optional[int] = None
    follow_on_enforced: bool = False
    status: MatchStatus = MatchStatus.SCHEDULED
    result: Optional["MatchResult"] = None

    # ── ⑥ Infrastructure ───────────────────────────────────────────────────────
    # NOTE: the bus is re-wired per inning by BaseEngine._create_inning().
    # It is match-scoped by storage but inning-scoped by usage - a known smell
    # scheduled for extraction to a proper inning-scoped bus in a future pass.
    event_bus: MatchEventBus = field(default_factory=MatchEventBus)

    @property
    def deliveries(self) -> List["SimulationDelivery"]:
        return [d for inning in self.innings for d in inning.deliveries]
