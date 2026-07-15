"""
Single source for rendering a dismissal (kind, bowler, fielder) as text.

Three display surfaces need this - API scorecards ("c&b Bumrah"), ball-by-ball
commentary prose ("caught and bowled Bumrah"), and CLI scorecards - and each
previously had its own switch-on-kind block. That duplication is exactly how
the literal "Caught and Bowled" outcome kind got fixed in one place and kept
rendering wrong in another. The kind-classification lives here once; the two
functions only differ in output style.

Outcome kinds are sampled from historical data, so casing and phrasing vary:
"caught" (with the bowler as catcher), "Caught and Bowled", "c and b" all mean
the same dismissal and every branch below must treat them identically.
"""

from __future__ import annotations

from typing import Optional


def scorecard_dismissal(okind: Optional[str], bowler: Optional[str], fielder: Optional[str]) -> str:
    """Abbreviated scorecard style: 'c Jadeja b Bumrah', 'c&b Bumrah', 'lbw b Bumrah'."""
    if not okind:
        return "out"
    kind = okind.lower()
    if kind == "bowled":
        return f"b {bowler}" if bowler else "bowled"
    if kind == "caught":
        if fielder and fielder != bowler:
            return f"c {fielder} b {bowler}"
        return f"c&b {bowler}" if bowler else "caught"
    if kind in ("caught and bowled", "c and b"):
        return f"c&b {bowler}" if bowler else "caught and bowled"
    if kind == "lbw":
        return f"lbw b {bowler}" if bowler else "lbw"
    if kind in ("run out", "runout", "run_out"):
        return f"run out ({fielder})" if fielder else "run out"
    if kind == "stumped":
        return f"st {fielder} b {bowler}" if fielder else f"st b {bowler}"
    return okind


def commentary_dismissal(okind: Optional[str], bowler: Optional[str], outcome_player: Optional[str]) -> str:
    """Prose commentary style: 'caught by Jadeja, bowled Bumrah', 'caught and bowled Bumrah'."""
    kind = (okind or "out").lower()
    if kind == "caught":
        if outcome_player and outcome_player != bowler:
            return f"caught by {outcome_player}, bowled {bowler}"
        return f"caught and bowled {bowler}"
    if kind in ("caught and bowled", "c and b"):
        return f"caught and bowled {bowler}"
    if kind == "bowled":
        return f"bowled by {bowler}"
    if kind == "lbw":
        return f"lbw, bowled {bowler}"
    if kind == "stumped":
        return f"stumped by {outcome_player or bowler}, bowled {bowler}"
    if kind in ("run out", "runout", "run_out"):
        return f"run out by {outcome_player or 'fielder'}"
    return f"{okind or 'out'} by {outcome_player or bowler}"
