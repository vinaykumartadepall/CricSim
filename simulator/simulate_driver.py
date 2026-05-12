import argparse
import json
import logging
import os
import time

from simulator.logger import configure_logger
from simulator.entities.player import Player
from simulator.entities.team import MatchTeam
from simulator.entities.match import SimulationMatch
from simulator.engines.engine_factory import EngineFactory
from simulator.strategies.ball_outcome_prediction.historical_stats.strategy import (
    T20HistoricalStatsStrategy,
    ODIHistoricalStatsStrategy,
    TestHistoricalStatsStrategy,
)
from simulator.strategies.ball_outcome_prediction.historical_stats.enhanced_strategy import (
    T20EnhancedHistoricalStatsStrategy,
    ODIEnhancedHistoricalStatsStrategy,
    TestEnhancedHistoricalStatsStrategy,
)
from simulator.strategies.bowling.smart import SmartBowlingStrategy
from simulator.strategies.bowling.historical import create_historical_bowling_strategy
from db.stats_repository import StatsRepository
from db.entities.venue import Venue

_BOWLING_STRATEGY_FACTORIES = {
    "smart":      lambda fmt: SmartBowlingStrategy(),
    "historical": create_historical_bowling_strategy,
}

# Maps (strategy_type, format) → concrete class.
# Adding a new strategy type means adding one row per format here.
_OUTCOME_STRATEGIES: dict[str, dict[str, type]] = {
    "historical": {
        "T20":  T20HistoricalStatsStrategy,
        "ODI":  ODIHistoricalStatsStrategy,
        "Test": TestHistoricalStatsStrategy,
    },
    "enhanced": {
        "T20":  T20EnhancedHistoricalStatsStrategy,
        "ODI":  ODIEnhancedHistoricalStatsStrategy,
        "Test": TestEnhancedHistoricalStatsStrategy,
    },
}

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "simulation.log")

log = configure_logger(log_file=LOG_FILE, level=logging.DEBUG)
log.info("=" * 80)
log.info("  CRICKET SIMULATOR — DETAILED PROBABILITY LOG")
log.info("=" * 80)

_DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "match_config.json")

_FORMAT_SETTINGS = {
    "T20":  {"overs_per_innings": 20,   "innings_per_match": 2},
    "ODI":  {"overs_per_innings": 50,   "innings_per_match": 2},
    "Test": {"overs_per_innings": None, "innings_per_match": 4},
}


def _load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _resolve_player(repo: StatsRepository, name: str) -> Player:
    res = repo.get_player_by_name(name)
    if res:
        return Player(id=res[0], name=res[1])
    log.warning("Player '%s' not found in DB — using hash-based fallback ID", name)
    return Player(id=abs(hash(name)) % 10000, name=name)


def _resolve_venue(repo: StatsRepository, name: str | None) -> Venue | None:
    if not name:
        return None
    res = repo.get_venue_by_name(name)
    if res:
        venue_id, venue_name, country = res
        return Venue.builder().with_id(venue_id).with_name(venue_name).with_country(country).build()
    log.warning("Venue '%s' not found in DB — proceeding without venue context", name)
    return None


def main():
    parser = argparse.ArgumentParser(description="Cricket match simulator")
    parser.add_argument(
        "--config",
        default=_DEFAULT_CONFIG,
        help="Path to match config JSON (default: match_config.json at project root)",
    )
    args = parser.parse_args()

    t_start = time.perf_counter()

    config = _load_config(args.config)
    log.console("[Startup] Config loaded from %s", args.config)

    fmt = config.get("format", "T20")
    if fmt not in _FORMAT_SETTINGS:
        raise ValueError(f"Unknown format '{fmt}'. Must be one of: {list(_FORMAT_SETTINGS)}")
    fmt_settings = dict(_FORMAT_SETTINGS[fmt])

    t = time.perf_counter()
    repo = StatsRepository()
    log.console("[Startup] StatsRepository ready                    %.2fs", time.perf_counter() - t)

    team_a_cfg = config["team_a"]
    team_b_cfg = config["team_b"]

    t = time.perf_counter()
    team_a = MatchTeam(
        id=1,
        name=team_a_cfg["name"],
        players=[_resolve_player(repo, name) for name in team_a_cfg["players"]],
    )
    team_b = MatchTeam(
        id=2,
        name=team_b_cfg["name"],
        players=[_resolve_player(repo, name) for name in team_b_cfg["players"]],
    )
    log.console("[Startup] Players resolved (%s, %s)                %.2fs",
               team_a.name, team_b.name, time.perf_counter() - t)

    t = time.perf_counter()
    venue = _resolve_venue(repo, config.get("venue"))
    log.console("[Startup] Venue resolved (%s)                      %.2fs",
               venue.name if venue else "none", time.perf_counter() - t)

    outcome_strategy_name = config.get("ball_outcome_strategy", "historical")
    outcome_strategy_map  = _OUTCOME_STRATEGIES.get(outcome_strategy_name)
    if outcome_strategy_map is None:
        raise ValueError(
            f"Unknown ball_outcome_strategy '{outcome_strategy_name}'. "
            f"Must be one of: {list(_OUTCOME_STRATEGIES)}"
        )
    outcome_strategy_cls = outcome_strategy_map[fmt]

    bowling_strategy_name    = config.get("bowling_strategy", "smart")
    bowling_strategy_factory = _BOWLING_STRATEGY_FACTORIES.get(bowling_strategy_name)
    if bowling_strategy_factory is None:
        raise ValueError(
            f"Unknown bowling_strategy '{bowling_strategy_name}'. "
            f"Must be one of: {list(_BOWLING_STRATEGY_FACTORIES)}"
        )

    log.console("[Startup] Strategies: outcome=%s  bowling=%s  format=%s",
               outcome_strategy_name, bowling_strategy_name, fmt)

    match = SimulationMatch(
        id=config.get("match_id", 1),
        home_team=team_a,
        away_team=team_b,
        venue=venue,
        match_format=fmt,
        balls_per_over=6,
        **fmt_settings,
    )

    engine = EngineFactory.create(
        match=match,
        ball_outcome_strategy=outcome_strategy_cls(),
        bowling_strategy=bowling_strategy_factory(fmt),
    )

    log.console("[Startup] Setup complete — starting simulation     %.2fs total",
               time.perf_counter() - t_start)

    engine.simulate()


if __name__ == "__main__":
    main()
