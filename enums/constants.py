from enum import Enum


class ExtraType(str, Enum):
    WIDE = "Wide"
    NOBALL = "Noball"
    LEGBYES = "Legbyes"
    BYES = "Byes"


class DismissalType(str, Enum):
    BOWLED = "bowled"
    CAUGHT = "caught"
    LBW = "lbw"
    RUN_OUT = "run out"
    STUMPED = "stumped"
    RETIRED_HURT = "retired hurt"
    OBSTRUCTING_FIELD = "obstructing the field"
    HANDLED_BALL = "handled the ball"
    HIT_BALL_TWICE = "hit the ball twice"
    TIMED_OUT = "timed out"
    CAUGHT_AND_BOWLED = "caught and bowled"
    C_AND_B = "c and b"


class OutcomeType(str, Enum):
    DOT = "Dot"
    RUNS = "Runs"
    WICKET = "Wicket"
    EXTRAS = "Extras"
