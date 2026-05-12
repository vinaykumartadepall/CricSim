from dataclasses import dataclass
from typing import Optional, Any

@dataclass(frozen=True)
class BallOutcome:
    runs_batter: int = 0
    runs_extras: int = 0
    is_wicket: bool = False
    wicket_kind: Optional[str] = None
    extras_type: Optional[str] = None
    outcome_player: Optional[Any] = None
