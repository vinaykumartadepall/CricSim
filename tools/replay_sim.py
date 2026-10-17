"""
Replay a stored simulation from its seed and check it reproduces exactly.

    python -m tools.replay_sim <sim_id>

Re-runs the simulation in memory - nothing is written - with the config and
seed stored in simulation.simulations, then compares every ball with the
deliveries saved for it: innings, over, ball, batter, bowler, runs, extras,
dismissal/extra type and fielder. Exit code 0 when identical.

A replay matches only while the code and precomputed stats are the same as
when the simulation ran, and when the admin's default strategies haven't
changed (configs without explicit strategies use the current defaults - the
strategies used are printed). Simulations from before migration 039 have no
seed and can't be replayed.
"""
from __future__ import annotations

import argparse
import sys
from collections import OrderedDict

from api.worker import _build_tournament_config
from db.simulation_repository import SimulationRepository
from db.stats_repository import StatsRepository
from simulator.match_runner import MatchRunner
from simulator.tournament.engine import TournamentEngine

Ball = tuple   # (inning, over, ball, batter_id, bowler_id, runs_batter, runs_extras, outcome_kind, fielder_id)


def _ball(inning_number, d) -> Ball:
    return (inning_number, d.over_number, d.ball_number,
            d.batter.id if d.batter else None, d.bowler.id if d.bowler else None,
            d.runs_batter, d.runs_extras, d.wicket_kind or d.extras_type,
            d.outcome_player.id if d.outcome_player else None)


def stored_balls(repo: SimulationRepository, sim_id: str) -> "OrderedDict[str, list[Ball]]":
    repo.cur.execute(
        """
        SELECT m.match_label, d.inning_number, d.over_number, d.ball_number, d.batter_id, d.bowler_id,
               d.runs_batter, d.runs_extras, d.outcome_kind, d.outcome_player_id
        FROM simulation.deliveries d
        JOIN simulation.matches m ON m.match_id = d.match_id
        WHERE m.sim_id = %s
        ORDER BY m.match_id, d.delivery_id
        """,
        (sim_id,),
    )
    out: "OrderedDict[str, list[Ball]]" = OrderedDict()
    for label, *ball in repo.cur.fetchall():
        out.setdefault(label, []).append(tuple(ball))
    return out


def replayed_balls(sim: dict) -> tuple["OrderedDict[str, list[Ball]]", str]:
    config, seed = sim["config"], sim["seed"]
    out: "OrderedDict[str, list[Ball]]" = OrderedDict()
    if sim["simulation_type"] == "match":
        runner = MatchRunner(config, repo=StatsRepository(), silent=True, seed=seed)
        match = runner.run()
        out["Match 1"] = [_ball(i.inning_number, d) for i in match.innings for d in i.deliveries]
        return out, f"{runner._outcome_strat.__class__.__name__} / {runner._bowling_strat.__class__.__name__}"

    tc = _build_tournament_config(config)

    class _Capturing(TournamentEngine):
        def _on_fixture_complete(self, match, fixture, stage, potm=None):
            label = getattr(fixture, "match_label", "") or f"Match {self._match_counter}"
            out[label] = [_ball(i.inning_number, d) for i in match.innings for d in i.deliveries]

    _Capturing(tc, repo=StatsRepository(), seed=seed, silent=True).run()
    return out, f"{tc.outcome_strategy} / {tc.bowling_strategy}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("sim_id")
    args = ap.parse_args(argv)

    repo = SimulationRepository()
    try:
        sim = repo.get_simulation(args.sim_id)
        if not sim:
            print(f"No simulation {args.sim_id}")
            return 2
        if sim["seed"] is None:
            print("This simulation ran before seeds were stored (migration 039) - it can't be replayed.")
            return 2
        stored = stored_balls(repo, args.sim_id)
    finally:
        repo.close()

    replayed, strategies = replayed_balls(sim)
    print(f"{sim['simulation_type']} {args.sim_id}  seed={sim['seed']}  strategies: {strategies}")

    identical, problems = 0, []
    for label in OrderedDict.fromkeys(list(stored) + list(replayed)):
        a, b = stored.get(label), replayed.get(label)
        if a == b:
            identical += 1
            continue
        if a is None or b is None:
            problems.append(f"  {label}: {'only in replay' if a is None else 'missing from replay'}")
            continue
        first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        problems.append(f"  {label}: differs at ball {first + 1} (stored {len(a)} balls, replayed {len(b)})"
                        f"\n      stored:   {a[first] if first < len(a) else '-'}"
                        f"\n      replayed: {b[first] if first < len(b) else '-'}")

    total = len(OrderedDict.fromkeys(list(stored) + list(replayed)))
    print(f"{identical}/{total} matches identical ball by ball "
          f"({sum(len(v) for v in stored.values())} stored balls)")
    if problems:
        print("Differences:\n" + "\n".join(problems[:10]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
