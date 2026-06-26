# Cricket Simulator

A ball-by-ball cricket match and tournament simulator backed by historical Cricsheet data stored in PostgreSQL. Supports T20, ODI, and Test formats with realistic outcome distributions derived from player career stats, venue context, phase-aware adjustments, and era normalisation.

---

## Features

- **Ball-by-ball simulation** — each delivery is sampled from blended historical distributions (batter, bowler, matchup, venue, phase, milestone)
- **Three match formats** — T20, ODI, Test (including follow-on, draw detection, four innings)
- **Super over** — triggered automatically on ties in limited-overs matches
- **Tournament engine** — round-robin or double round-robin group stage + pluggable playoff brackets (IPL, semis-final, quarters-semis-final)
- **Live points table** — with NRR tracking
- **Leaderboards** — batting (runs, average, strike rate, sixes, fours) and bowling (wickets, economy, average)
- **Player-of-the-Match / Player-of-the-Tournament** — fantasy-points scoring
- **Pluggable strategy architecture** — swap outcome prediction or bowling selection independently; extend via abstract factory

---

## Architecture

```
cricket-simulator/
├── simulator/
│   ├── engines/          # BaseEngine, LimitedOversEngine, TestEngine, SuperOverEngine
│   ├── entities/         # SimulationMatch, InningTeam, InningPlayer, MatchRules …
│   ├── strategies/
│   │   ├── factory.py    # StrategyFactory (abstract) + concrete factories + resolver helpers
│   │   ├── ball_outcome_prediction/
│   │   │   ├── historical_stats/       # v1 RMS blending
│   │   │   └── enhanced_historical_stats/  # v2: phase, milestone, reliability, category
│   │   └── bowling/
│   │       ├── historical/   # data-driven bowler selection (F1–F6 scoring)
│   │       └── smart/        # heuristic phase-aware selection
│   ├── tournament/
│   │   ├── engine.py      # TournamentEngine
│   │   ├── config.py      # TournamentConfig dataclasses + JSON loader
│   │   ├── scheduler.py   # generate_fixtures / generate_playoffs
│   │   ├── points_table.py
│   │   ├── leaderboards.py
│   │   ├── awards.py
│   │   └── presenter.py
│   ├── events.py          # MatchEventBus, MatchObserver
│   └── simulate_driver.py # Single-match CLI entry point
├── api/
│   ├── main.py              # FastAPI app; warms caches at startup
│   ├── worker.py            # Background job runners (match + tournament)
│   └── routes/
│       ├── simulations.py   # POST /simulations, GET /simulations/{id}
│       ├── leaderboards.py  # GET /simulations/{id}/leaderboards/*
│       └── admin.py         # GET/PUT /admin/log-level
├── db/
│   ├── stats_repository.py  # All simulation queries; singleton connection; _PRECOMPUTED_CACHE
│   ├── repository.py        # Ingestion CRUD
│   └── schema.sql
├── tests/                   # pytest unit tests (no DB required)
├── tools/                   # Developer utilities (plotting, validation)
├── run_tournament.py        # Tournament CLI entry point
└── setup_db.py              # One-shot DB setup + data ingestion
```

### Strategy Factory

The abstract factory (`simulator/strategies/factory.py`) is the single source of truth for strategy wiring. To add a new strategy family:

```python
from simulator.strategies.factory import StrategyFactory
from simulator.strategies.ball_outcome_prediction.strategy_interface import BallOutcomeStrategy
from simulator.strategies.bowling.strategy_interface import BowlingStrategy

class MyStrategyFactory(StrategyFactory):
    def __init__(self, fmt: str): self._fmt = fmt
    def create_outcome_strategy(self) -> BallOutcomeStrategy: return MyOutcomeStrategy(self._fmt)
    def create_bowling_strategy(self) -> BowlingStrategy:     return MyBowlingStrategy(self._fmt)

StrategyFactory.register("my_outcome", "my_bowling", MyStrategyFactory)
```

Config files then reference it by name: `"outcome_strategy": "my_outcome"`.

---

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ running locally
- `PGDATABASE` / `PGUSER` / `PGPASSWORD` / `PGHOST` env vars set (or defaults from `db/database.py`)

### Install dependencies

```bash
pip install -r requirements.txt          # runtime only
pip install -r requirements-dev.txt      # + pytest + plotting tools
```

### Initialise the database and ingest data

```bash
python setup_db.py
```

This runs all steps in sequence: schema creation, Cricsheet archive download, JSON ingestion, venue deduplication, geocoding, and precomputed baseline tables. Steps are idempotent and can be re-run safely.

Individual steps:

```bash
python setup_db.py --skip-download       # skip re-downloading the archive
python setup_db.py --only-precompute     # only refresh baseline tables
```

---

## Running a match

```bash
python -m simulator.simulate_driver --config match_config.json
```

`match_config.json` shape:

```json
{
  "format": "T20",
  "ball_outcome_strategy": "enhanced",
  "bowling_strategy": "historical",
  "venue": "Wankhede Stadium",
  "team_a": { "name": "Mumbai Indians",      "players": ["RG Sharma", "..."] },
  "team_b": { "name": "Chennai Super Kings", "players": ["MS Dhoni",  "..."] }
}
```

**Strategy options**

| Key                      | Values                       |
|--------------------------|------------------------------|
| `ball_outcome_strategy`  | `enhanced` *(default)*, `historical` |
| `bowling_strategy`       | `historical` *(default)*, `smart`    |

---

## Running a tournament

```bash
python run_tournament.py --config tournament_config.json
python run_tournament.py --config ipl_config.json --seed 42
python run_tournament.py --config ipl_config.json --seed 42 --silent
```

`tournament_config.json` shape:

```json
{
  "tournament_name": "IPL 2025",
  "format": "T20",
  "gender": "male",
  "season": "2025",
  "outcome_strategy": "enhanced",
  "bowling_strategy": "historical",
  "venues": [{ "name": "Wankhede Stadium" }],
  "teams": [
    {
      "name": "Mumbai Indians",
      "short_name": "MI",
      "primary_color": "#004C97",
      "secondary_color": "#D1AB3E",
      "players": ["RG Sharma", "Ishan Kishan", "..."]
    }
  ],
  "schedule": { "type": "round_robin", "neutral_venues": true },
  "playoffs": { "format": "ipl", "top_n": 4 }
}
```

**Playoff formats**: `none`, `two_teams`, `semis_final`, `ipl`, `quarters_semis_final`

**Schedule types**: `round_robin`, `double_round_robin`; or provide an explicit list of `{ "home", "away", "venue" }` objects.

---

## Running via API

```bash
uvicorn api.main:app --reload --port 8000
```

On startup the server warms all `StatsRepository` caches (~11s first boot, zero-cost thereafter). Interactive docs at `http://localhost:8000/docs`.

**Key endpoints**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/simulations` | Submit a match or tournament simulation job |
| `GET`  | `/simulations/{id}` | Poll job status + results |
| `GET`  | `/simulations/{id}/leaderboards/{type}` | Batting/bowling aggregates |
| `GET`  | `/admin/log-level` | Current simulation.log level |
| `PUT`  | `/admin/log-level` | Switch level at runtime (`DEBUG`/`INFO`/`WARNING`/`ERROR`) |

---

## Logging

Log files are written to `logs/` (created automatically):

| File | Level | Capacity |
|------|-------|---------|
| `logs/simulation.log` | INFO (configurable) | 20 MB × 10 files = 200 MB |
| `logs/errors.log` | WARNING and above | 5 MB × 5 files = 25 MB |

Every line includes `[sim_id/m{match_id}]` context — concurrent simulations are identifiable. No per-match files are written.

Switch level at runtime without restarting:
```bash
curl -X PUT http://localhost:8000/admin/log-level -H 'Content-Type: application/json' -d '{"level":"DEBUG"}'
```

---

## Running tests

```bash
pytest tests/          # all tests
pytest tests/ -q       # quiet
pytest tests/ -k "points_table or scheduler"  # filter by name
```

All tests run without a database connection.

---

## Validation tools

```bash
# Bowling selection accuracy vs historical data
python -m tools.validate_bowling_selection --format T20 --n 50

# Score distribution plots
python tools/plot_sim_scores.py --config match_config.json

# Check database connectivity and stat loading
python -m tools.check_db
```
