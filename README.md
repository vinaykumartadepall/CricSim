# Cricket Simulator

A ball-by-ball cricket match and tournament simulator backed by historical Cricsheet data in PostgreSQL, with a FastAPI backend and a React web frontend. Supports T20, ODI, and Test formats with realistic outcome distributions derived from player career stats, venue/country context, matchup history, phase-aware adjustments, and era normalisation.

---

## Features

- **Ball-by-ball simulation** — each delivery sampled from blended historical distributions (batter, bowler, matchup, phase, milestone, venue, innings, tournament)
- **Three match formats** — T20, ODI, Test (including follow-on, draw/tie detection, four innings)
- **Super over** — triggered automatically on ties in limited-overs matches
- **Tournament engine** — round-robin or double round-robin group stage + pluggable playoff brackets (IPL, semis-final, quarters-semis-final)
- **Live points table** — with NRR tracking
- **Leaderboards** — batting (runs, average, strike rate, sixes, fours) and bowling (wickets, economy, average)
- **Player-of-the-Match / Player-of-the-Tournament** — fantasy-points scoring
- **Web UI** — Fun Mode, Challenge Mode, Custom Mode drafting, live multiplayer draft rooms, match/tournament results with worm charts and scorecards
- **Supabase auth** — optional sign-in to save a profile and link anonymous history to an account; simulate/tournament endpoints stay open without login
- **Pluggable strategy architecture** — swap outcome prediction or bowling selection independently; extend via abstract factory

---

## Tech stack

- **Backend:** Python, FastAPI, PostgreSQL (`psycopg2`)
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS, React Router
- **Auth:** Supabase (JWT verification via JWKS; anonymous + linked accounts)

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
│   │   │   ├── historical_stats/           # v1 RMS blending
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
│   ├── serializers/       # Scorecard/commentary read-side serializers for the API
│   ├── events.py          # MatchEventBus, MatchObserver
│   └── simulate_driver.py # Single-match CLI entry point (wrapped by run_match.py)
├── api/
│   ├── main.py               # FastAPI app, CORS, lifespan (logging + memory monitor)
│   ├── deps.py                # Supabase JWT verification dependency
│   ├── worker.py              # Background job runners (match + tournament, via BackgroundTasks)
│   └── routes/
│       ├── simulations.py     # /cricsimapi/simulations/* — create/poll jobs, scorecards, commentary
│       ├── leaderboards.py    # /cricsimapi/simulations/{id}/leaderboards/*
│       ├── lov.py              # /cricsimapi/lov/* — tournaments, squads, underdogs (list-of-values)
│       ├── sim_history.py     # /cricsimapi/sim-history/* — aggregate stats across past sims
│       ├── multiplayer.py     # /cricsimapi/multiplayer/* — WebSocket draft rooms
│       ├── auth.py            # /cricsimapi/auth/* — Supabase profile + anonymous-account linking
│       ├── admin.py           # /admin/log-level — runtime log level control
│       └── admin_squads.py    # /admin/squads/* — squad editing tools
├── db/
│   ├── stats_repository.py  # All simulation-runtime queries; singleton connection; lazy _PRECOMPUTED_CACHE
│   ├── simulation_repository.py  # Writes to simulation.* tables
│   ├── precompute.py        # Offline precomputation — the only place allowed to query history.deliveries
│   ├── database.py          # Connection helpers (DATABASE_URL / DB_* env vars)
│   └── schema.sql
├── frontend/
│   ├── src/pages/          # HomePage, ResultsPage, MatchDetailPage, DraftPage, CustomModePage, …
│   ├── src/components/     # Shared UI (SimCard, SquadEditor, PlayoffBracket, …)
│   ├── src/api/client.ts   # Fetch wrapper, hits same-origin /cricsimapi/*
│   └── src/lib/supabase.ts # Frontend Supabase client (VITE_SUPABASE_URL/ANON_KEY)
├── tests/                   # pytest unit tests (no DB required)
├── tools/                   # Developer utilities (plotting, validation)
├── run_match.py             # Single-match CLI entry point
├── run_tournament.py        # Tournament CLI entry point
└── setup_db.py              # One-shot DB setup: schema, ingestion, precompute
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
- Node.js 20+ (frontend)
- PostgreSQL 14+ running locally

### Backend

```bash
pip install -r requirements.txt          # runtime only
pip install -r requirements-dev.txt      # + pytest + plotting tools
```

Environment variables (see `.env` locally; not committed):

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Full Postgres connection string; takes precedence if set |
| `DB_NAME` / `DB_USER` / `DB_PASS` / `DB_HOST` / `DB_PORT` | Fallback individual connection params if `DATABASE_URL` is unset |
| `SUPABASE_URL` | Supabase project URL, used to verify JWTs via JWKS |
| `SUPABASE_DATABASE_URL` | Connection string for the Supabase-hosted `profiles` table (falls back to `DATABASE_URL`) |
| `CORS_ORIGINS` | Comma-separated extra allowed origins (dev defaults already include the Vite dev server) |
| `LOG_LEVEL` | Console log level (default: a custom `CONSOLE` level) |
| `LOW_RAM_THRESHOLD_MB` | RAM threshold below which the stats cache is evicted (default `250`) |

### Initialise the database and ingest data

```bash
python setup_db.py
```

Runs schema creation, Cricsheet archive download, JSON ingestion, venue dedup/geocoding, precomputed baseline tables, and ESPN player enrichment, in sequence. Steps are idempotent and can be re-run safely.

```bash
python setup_db.py --skip-download           # skip re-downloading the archive
python setup_db.py --only-precompute         # only refresh precomputed tables
python setup_db.py --only-precompute --current-year-only  # fast incremental refresh
python setup_db.py --skip-enrich             # skip ESPN player enrichment (slow, ~1hr for Pass 2)
python setup_db.py --skip-enrich-api         # assign cricinfo_ids but skip the ESPN API calls
python setup_db.py --dry-run                 # print what would happen, no writes
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local   # fill in VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY
npm run dev
```

Dev server runs on `http://localhost:5173` and proxies `/cricsimapi/*` to the backend (`VITE_API_URL`, default `http://localhost:8000`).

```bash
npm run build     # production build → frontend/dist
npm run lint
```

---

## Running a match (CLI)

```bash
python run_match.py --config match_config.json
python run_match.py --config match_config.json --silent
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

## Running a tournament (CLI)

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

## Running the full app (API + frontend)

```bash
uvicorn api.main:app --reload --port 8000
```

The stats cache (`StatsRepository._PRECOMPUTED_CACHE`) is populated **lazily**, per stat type, on first use — not eagerly at startup — to keep steady-state memory lower. The first request touching a given stat type pays a one-time DB-load cost; everything after that is a dict lookup. Interactive API docs at `http://localhost:8000/docs`.

In a separate terminal:
```bash
cd frontend && npm run dev
```

**Key endpoints** (all under `/cricsimapi` unless noted):

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/simulations/createsim` | Submit a single-match simulation job |
| `POST` | `/simulations/tournament` | Submit a tournament simulation job |
| `GET`  | `/simulations/{sim_id}/status` | Poll job status |
| `GET`  | `/simulations/{sim_id}/result` | Tournament result summary |
| `GET`  | `/simulations/{sim_id}/scorecard` | Full scorecard |
| `GET`  | `/simulations/{sim_id}/matches/{match_id}/scorecard` | Per-match scorecard (tournaments) |
| `GET`  | `/simulations/{sim_id}/leaderboards` | Batting/bowling leaderboard dashboard |
| `GET`  | `/lov/tournaments` | List available historical tournaments to simulate |
| `GET`/`POST` | `/auth/profile` | Get/set the signed-in user's display name |
| `POST` | `/multiplayer/rooms` | Create a live draft room |
| `GET`  | `/admin/log-level` | Current `simulation.log` level |
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
