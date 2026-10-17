"""
Seeds - how a simulation is made exactly replayable.

Each simulation gets one seed (stored in simulation.simulations.seed). Every
match in it gets its own random generator derived from that seed and the
match's number, and every chance event in the match draws from it
(SimulationMatch.rng): the toss, each ball, the fielder on a dismissal.
Tournament-level chance (fixture order, venue picks) uses a generator seeded
directly from the same seed.

So the same seed + the same config replays the same result ball by ball, as
long as the code and the precomputed stats haven't changed - and match N of a
tournament can be replayed on its own.
"""
from __future__ import annotations

import random
import secrets

SEED_BITS = 63   # fits a Postgres BIGINT


def new_seed() -> int:
    return secrets.randbits(SEED_BITS)


def match_rng(seed: int, match_number: int) -> random.Random:
    """The generator for match `match_number` of the simulation with `seed`.
    String seeding is stable across Python processes and versions (sha512),
    unlike hash()-based seeding."""
    return random.Random(f"{seed}:{match_number}")
