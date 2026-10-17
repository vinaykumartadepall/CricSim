"""
Per-simulation seeds (simulator/seeding.py, migration 039): the same seed
must replay the same match / tournament ball by ball, and nothing on the
simulation path may draw from the global `random` (that's what made runs
unrepeatable before - two concurrent simulations interleaved their draws).

Offline: StatsRepository is replaced with a connection-less instance (every
lookup returns empty, so the strategies run on their baseline fallbacks) -
which still exercises every chance event: toss, each ball, fielders, fixture
order and venue picks.
"""
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from db.stats_repository import StatsRepository
from simulator.engines.engine_factory import EngineFactory
from simulator.entities.match import SimulationMatch
from simulator.entities.player import Player
from simulator.entities.team import MatchTeam
from simulator.predictors.factory import FORMAT_SETTINGS, BowlingStrategyFactory, OutcomeStrategyFactory
from simulator.seeding import match_rng, new_seed
from simulator.tournament.config import parse_tournament_config
from simulator.tournament.engine import TournamentEngine

REPO = Path(__file__).resolve().parent.parent
_STATS_REPO_USERS = [
    "simulator.predictors.ball_outcome_prediction.enhanced_historical_stats.strategy.StatsRepository",
    "simulator.predictors.ball_outcome_prediction.historical_stats.strategy.StatsRepository",
    "simulator.predictors.bowling.historical.base.StatsRepository",
]


def _offline_repo():
    repo = StatsRepository.__new__(StatsRepository)
    repo.conn = None
    return repo


@pytest.fixture
def offline():
    patchers = [patch(target, side_effect=_offline_repo) for target in _STATS_REPO_USERS]
    for p in patchers:
        p.start()
    yield _offline_repo()
    for p in patchers:
        p.stop()


def _team(team_id, base):
    return MatchTeam(id=team_id, name=f"Team{team_id}",
                     players=[Player(id=base + i, name=f"P{base + i}") for i in range(11)])


def _play_match(rng, fmt="T20"):
    match = SimulationMatch(id=1, home_team=_team(1, 100), away_team=_team(2, 200), match_format=fmt,
                            balls_per_over=6, rng=rng, **FORMAT_SETTINGS[fmt])
    EngineFactory.create(match, OutcomeStrategyFactory.for_name("enhanced", fmt),
                         BowlingStrategyFactory.for_name("historical", fmt)).simulate()
    return [(d.inning_number, d.over_number, d.ball_number, d.batter.id, d.bowler.id,
             d.runs_batter, d.runs_extras, d.wicket_kind, d.extras_type,
             d.outcome_player.id if d.outcome_player else None)
            for inning in match.innings for d in inning.deliveries]


class TestMatchReplay:
    def test_same_seed_same_match_ball_by_ball(self, offline):
        assert _play_match(match_rng(42, 1)) == _play_match(match_rng(42, 1))

    def test_different_seed_different_match(self, offline):
        assert _play_match(match_rng(42, 1)) != _play_match(match_rng(43, 1))

    def test_each_match_number_gets_its_own_stream(self, offline):
        assert _play_match(match_rng(42, 1)) != _play_match(match_rng(42, 2))

    def test_global_random_state_has_no_effect(self, offline):
        import random
        random.seed(1)
        first = _play_match(match_rng(7, 1))
        random.seed(999)
        assert _play_match(match_rng(7, 1)) == first


def _tournament_config():
    teams = [{"name": f"T{t}", "players": [t * 100 + i for i in range(11)]} for t in range(1, 5)]
    return parse_tournament_config({
        "tournament_name": "Seed Cup", "format": "T20", "gender": "male",
        "outcome_strategy": "enhanced", "bowling_strategy": "historical",
        "teams": teams, "venues": [{"name": "Ground A"}, {"name": "Ground B"}, {"name": "Ground C"}],
        "schedule": {"type": "round_robin", "matches_per_pair": 1},
        "playoffs": {"format": "semis_final", "top_n": 4},
    })


def _play_tournament(seed):
    captured = []

    class _Capturing(TournamentEngine):
        def _on_fixture_complete(self, match, fixture, stage, potm=None):
            captured.append((fixture.home, fixture.away, getattr(fixture, "match_label", ""),
                             [(d.runs_batter, d.runs_extras, d.wicket_kind, d.extras_type)
                              for inning in match.innings for d in inning.deliveries]))

    engine = _Capturing(_tournament_config(), repo=_offline_repo(), seed=seed, silent=True)
    engine.run()
    return engine, captured


class TestTournamentReplay:
    def test_same_seed_same_tournament(self, offline):
        _, a = _play_tournament(seed=123)
        _, b = _play_tournament(seed=123)
        assert len(a) == 6 + 3          # round robin of 4, then semis + final
        assert a == b

    def test_different_seed_different_tournament(self, offline):
        assert _play_tournament(seed=123)[1] != _play_tournament(seed=124)[1]

    def test_unseeded_engine_picks_and_exposes_a_seed_that_replays(self, offline):
        engine, first = _play_tournament(seed=None)
        assert isinstance(engine.seed, int)
        assert _play_tournament(seed=engine.seed)[1] == first


class TestSeeds:
    def test_new_seed_fits_bigint(self):
        assert all(0 <= new_seed() < 2 ** 63 for _ in range(100))

    def test_match_rng_is_stable_across_processes(self):
        # str seeding is sha512-based - unlike hash(), it doesn't change per process
        assert match_rng(5, 3).random() == match_rng(5, 3).random()
        assert round(match_rng(5, 3).random(), 12) == 0.229568146235   # computed in a separate process


class TestNoGlobalRandomOnTheSimulationPath:
    """The guarantee that makes seeds work: chance only comes from match.rng
    or the tournament's seeded generator."""
    GLOBAL_CALL = re.compile(r"\brandom\.(choice|choices|random|shuffle|uniform|randint|randrange|sample|gauss|seed)\(")
    ALLOWED = {"simulator/predictors/ball_outcome_prediction/historical_stats/optimize_weights.py"}  # offline tool

    def test_no_global_random_calls(self):
        offenders = []
        for path in sorted((REPO / "simulator").rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            if rel in self.ALLOWED:
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if self.GLOBAL_CALL.search(line) and not line.lstrip().startswith("#"):
                    offenders.append(f"{rel}:{n}: {line.strip()}")
        assert not offenders, "use match.rng (or the engine's seeded generator):\n" + "\n".join(offenders)


class TestEnsureSeed:
    """DB tier: the seed is stored once and never replaced."""

    def test_assigned_once_then_reused(self, make_db, app_db):
        from db.simulation_repository import SimulationRepository
        db = make_db()
        app_db(db)
        repo = SimulationRepository()
        try:
            sim_id = repo.create_simulation("match", {"x": 1}, client_id=None)
            repo.commit()
            first = repo.ensure_seed(sim_id)
            repo.commit()
            assert isinstance(first, int)
            assert repo.ensure_seed(sim_id) == first     # restarted job reuses it
            assert repo.get_simulation(sim_id)["seed"] == first
        finally:
            repo.close()
