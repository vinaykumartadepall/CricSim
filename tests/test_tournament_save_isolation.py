"""
One tournament match failing to save must not lose the others
(api/worker.py::_PersistingTournamentEngine._on_fixture_complete).

Matches are committed in batches of 20. Previously a failed save rolled back
the whole open batch - up to 19 earlier matches - and the job still finished
as 'completed' with them missing. Now each save runs in its own savepoint.

DB tier: real SimulationRepository against a throwaway database. The middle
match's players don't exist in history.players, so the database itself
rejects that save (foreign key) - the same kind of failure as a real one.
"""
from types import SimpleNamespace

import pytest

import api.worker as worker
from db.simulation_repository import SimulationRepository
from tests.test_seeding import _offline_repo, _STATS_REPO_USERS   # offline engine helpers
from simulator.engines.engine_factory import EngineFactory
from simulator.entities.match import SimulationMatch
from simulator.entities.player import Player
from simulator.entities.team import MatchTeam
from simulator.predictors.factory import FORMAT_SETTINGS, BowlingStrategyFactory, OutcomeStrategyFactory
from simulator.seeding import match_rng
from unittest.mock import patch


@pytest.fixture
def offline():
    patchers = [patch(t, side_effect=_offline_repo) for t in _STATS_REPO_USERS]
    for p in patchers:
        p.start()
    yield
    for p in patchers:
        p.stop()


def _played_match(n, home, away, base):
    def team(tid, name, b):
        return MatchTeam(id=tid, name=name, players=[Player(id=b + i, name=f"P{b + i}") for i in range(11)])
    m = SimulationMatch(id=n, home_team=team(1, home, base), away_team=team(2, away, base + 100),
                        match_format="T20", balls_per_over=6, rng=match_rng(9, n), **FORMAT_SETTINGS["T20"])
    EngineFactory.create(m, OutcomeStrategyFactory.for_name("enhanced", "T20"),
                         BowlingStrategyFactory.for_name("historical", "T20")).simulate()
    return m


def test_a_failed_match_save_keeps_the_others(make_db, app_db, offline):
    db = make_db()
    app_db(db)
    conn = db.connect("test:seed")
    with conn.cursor() as cur:   # players for the matches that should save; 900..1110 deliberately absent
        cur.execute("INSERT INTO history.players (player_id, name, gender) "
                    "SELECT g, 'P' || g, 'male' FROM generate_series(100, 310) g")
    conn.close()

    repo = SimulationRepository()
    try:
        sim_id = repo.create_simulation("tournament", {"x": 1}, client_id=None)
        tid = repo.save_tournament(sim_id=sim_id, tournament_name="Cup", season="", format="T20", gender="male")
        teams = {name: repo.save_team(MatchTeam(id=0, name=name, players=[])) for name in ("A", "B")}
        repo.commit()

        engine = worker._PersistingTournamentEngine.__new__(worker._PersistingTournamentEngine)
        engine._sim_repo, engine._sim_id, engine._tournament_id = repo, sim_id, tid
        engine._team_id_map, engine._pending_commits, engine.unsaved_matches = teams, 0, []
        engine._match_counter = 0

        for n, base in ((1, 100), (2, 900), (3, 100)):
            engine._match_counter = n
            fixture = SimpleNamespace(home="A", away="B", match_label=f"Match {n}")
            engine._on_fixture_complete(_played_match(n, "A", "B", base), fixture, "group")
        repo.commit()   # what run_tournament_job's final flush does

        repo.cur.execute("SELECT match_label FROM simulation.matches WHERE sim_id = %s ORDER BY match_id", (sim_id,))
        assert [r[0] for r in repo.cur.fetchall()] == ["Match 1", "Match 3"]
        repo.cur.execute("SELECT count(*) FROM simulation.deliveries d JOIN simulation.matches m USING (match_id) "
                         "WHERE m.sim_id = %s", (sim_id,))
        assert repo.cur.fetchone()[0] > 100            # both saved matches kept every ball
        assert engine.unsaved_matches == ["Match 2"]
    finally:
        repo.close()


def test_the_job_fails_instead_of_completing_with_missing_matches(monkeypatch):
    """run_tournament_job raises on unsaved matches, so the existing error
    handler marks the simulation failed (with the match names)."""
    import inspect
    src = inspect.getsource(worker.run_tournament_job)
    assert "engine.unsaved_matches" in src and "could not be saved" in src
