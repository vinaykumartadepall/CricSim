# CLAUDE.md — Cricket Simulator Development Guide

## Critical Rules

### 1. NEVER query `history.deliveries` at simulation runtime
`history.deliveries` is an 11.2M-row, 1.3GB table. Any query against it during a simulation run will add seconds of latency per match. It is only safe to access from `db/precompute.py` during the one-time offline precomputation step.

All simulation runtime reads must go through the precomputed tables:
- `history.player_outcome_stats` — per-player distributions (batting, bowling, phase, milestone)
- `history.player_context_stats` — per-player venue/country distributions
- `history.batter_bowler_matchups` — head-to-head distributions
- `history.bowler_order_stats` — bowler rotation frequency and phase distributions
- `history.player_scalar_stats` — career economy, workload, role flags
- `history.aggregate_stats` — format-level baseline distributions

Any new data need identified during development must be added to `db/precompute.py` and surfaced through `StatsRepository` cache methods.

### 2. No duplicate calculation logic — one formula, one function
Any calculation used in more than one place — the live in-memory simulation engine, a SQL-derived display query, the frontend — must live in exactly one function. Every other call site either calls it directly or consumes a value that call already persisted. Never re-derive the formula independently at a second site, even when the two sites have completely different data available (in-memory objects vs. DB rows vs. API JSON) — that's what a thin adapter is for, not a rewrite. SQL should only fetch raw rows; the actual arithmetic belongs in one shared Python function that all callers route through.

When you find an existing duplication and consolidate it into one implementation, verify which version is actually correct against real domain rules/data before picking one to keep — two implementations agreeing with each other is not the same as either of them being correct. (Precedent: NRR was computed twice — the live tournament engine's version silently omitted the ICC all-out rule; the display SQL had it right. Simply deleting the display version to "fix the duplication" would have kept the wrong number live and shipped it everywhere.) A fix that removes the duplicate without checking correctness is not done.

### 3. Write tests for every new feature or fix
Before marking any task complete, add tests in `tests/`. All tests must run without a database connection — mock or bypass it at the class level (see test patterns below).

---

## Architecture Overview

### Process-level singletons
- `StatsRepository._conn` — single PostgreSQL connection shared across all `StatsRepository()` instances in the process. Never opened again after the first call. Protected by `_conn_lock` (double-checked locking).
- `_PRECOMPUTED_CACHE` — module-level dict in `db/stats_repository.py`. Populated once at server startup via `StatsRepository.warm_all_caches()`. All cache reads are pure dict lookups after that.
- `StatsRepository._query_lock` — serialises all DB round-trips (psycopg2 connections are not thread-safe).

### Log system
- No per-match log files. All output goes to rotating files: `logs/simulation.log` (20MB×10) and `logs/errors.log` (5MB×5).
- Every log line carries `[sim_id/m{match_id}]` context injected from `ContextVar`s — safe for concurrent runs.
- Set context with `log_context(sim_id=..., match_id=...)` from `simulator.logger`. Only the vars explicitly passed are changed; others inherit outer context.
- Runtime level switching: `set_log_level("DEBUG")` changes `simulation.log` level; `errors.log` is always WARNING+.
- `MatchLogger` no longer writes files; it routes to the global logger.

### Strategy pipeline
```
predict_next_ball(match)
  → 8 RMS context multipliers (batter, bowler, matchup, phase, milestone, innings, venue, tournament)
  → pressure modifier (chase urgency, dot-ball pressure, wicket rate, partnership)
  → free-hit modifier (if match.is_free_hit)
  → random.choices(outcomes, weights)
```

### Tournament persistence
`_PersistingTournamentEngine` (in `api/worker.py`) batches DB commits every 20 matches (`_DB_BATCH_SIZE = 20`). A final commit flushes the remainder after `engine.run()` returns.

---

## Database Schema Summary

### `history` schema — read-only at runtime
| Table | Purpose |
|-------|---------|
| `history.players` | Player registry (player_id, name, gender) |
| `history.venues` | Venue registry (venue_id, name, city, country) |
| `history.matches` | Historical match metadata |
| `history.deliveries` | **11.2M rows — NEVER query at runtime** |
| `history.player_outcome_stats` | Precomputed per-player distributions by stat_type |
| `history.player_context_stats` | Venue/country distributions per player |
| `history.batter_bowler_matchups` | Head-to-head distributions |
| `history.bowler_order_stats` | Over-frequency and phase-distribution stats |
| `history.player_scalar_stats` | Career stats, workload, roles |
| `history.aggregate_stats` | Format-level baselines |
| `history.global_yearly_baseline` | Era denominators for normalization |

`stat_type` values in `player_outcome_stats`:
- `batting`, `bowling`
- Phase: `phase_pp1`, `phase_pp2`, `phase_mid1`, `phase_mid2`, `phase_mid3`, `phase_death1`, `phase_death2` (T20/ODI); `phase_new`, `phase_early`, `phase_middle`, `phase_late` (Test)
- Milestone: `milestone_m0`, `milestone_m10`, …, `milestone_m100`

### `simulation` schema — written by API
| Table | Purpose |
|-------|---------|
| `simulation.simulations` | Job registry (sim_id, status, created_at, error) |
| `simulation.tournaments` | Tournament metadata |
| `simulation.teams` | Saved team names per simulation |
| `simulation.matches` | Per-match outcomes |
| `simulation.deliveries` | Ball-by-ball records for each match |
| `simulation.match_players` | Player participation per match |
| `simulation.player_awards` | POTM/POTT results |
| `simulation.leaderboard_cache` | Precomputed top-10 snapshots |

---

## Key File Map

| File | Role |
|------|------|
| `simulator/logger.py` | Application logger — `configure_logger`, `log_context`, `set_log_level` |
| `simulator/match_logger.py` | MatchLogger — wraps global logger; no file I/O |
| `simulator/entities/match.py` | `SimulationMatch` — central mutable state object |
| `simulator/entities/rules.py` | `MatchRules` — pure static cricket law helpers |
| `simulator/engines/innings_simulator.py` | Core ball-by-ball loop |
| `simulator/engines/limited_overs_engine.py` | T20/ODI driver; triggers super over on tie |
| `simulator/predictors/factory.py` | Strategy wiring — `StrategyFactory.register()` |
| `simulator/predictors/ball_outcome_prediction/enhanced_historical_stats/strategy.py` | Primary RMS prediction engine |
| `simulator/predictors/bowling/historical/base.py` | Historical bowling selection (F1–F6 scoring) |
| `simulator/tournament/engine.py` | `TournamentEngine` — group stage + playoffs |
| `simulator/awards/mvp_strategy.py` | `MvpStrategy` (ABC), `PlayerAward` — swappable MVP/POTM scoring contract |
| `simulator/awards/statistical_awards.py` | `StatisticalAwardsStrategy` — default MVP rubric, per-format point table |
| `simulator/awards/match_awards.py` | `MatchAwards`, `TournamentAwards` — strategy-agnostic POTM/POTT orchestration |
| `db/stats_repository.py` | All runtime DB queries; singleton connection; `_PRECOMPUTED_CACHE` |
| `db/precompute.py` | Offline precomputation — the only place allowed to query `history.deliveries` |
| `api/worker.py` | Background job runners; `_PersistingTournamentEngine` |
| `api/main.py` | FastAPI app; calls `warm_all_caches()` at startup lifespan |
| `api/routes/admin.py` | `GET/PUT /admin/log-level` |

---

## Testing Conventions

### No database required
All tests in `tests/` must work without a live DB connection. Bypass DB at the object level:

```python
# Bypass DB connection in StatsRepository
repo = StatsRepository.__new__(StatsRepository)
repo.conn = None

# Or patch the class-level connection for singleton tests
import db.stats_repository as sr_mod
original = sr_mod.StatsRepository._conn
sr_mod.StatsRepository._conn = None
# ... test ...
sr_mod.StatsRepository._conn = original
```

### Test file naming
- One test file per module area: `test_<module>.py`
- Class names: `class Test<Feature>:`
- Method names: `def test_<what_it_checks>(self):`

### Running tests
```bash
pytest tests/          # all tests
pytest tests/ -q       # quiet
pytest tests/ -k "logger or singleton"   # filter
```

### What to test
- Any new cache loading path in `StatsRepository` — verify it builds the expected dict shape from mock rows
- Any change to `MatchRules` — pure functions are easy to unit-test
- Any new strategy logic — pass minimal mock match/repo objects
- Any new API route — use `fastapi.testclient.TestClient`

---

## Installing Packages

Always install into the `cricsim` conda environment — never bare `pip` or `sudo pip`:

```bash
conda activate cricsim
pip install <package>
```

After installing, add the package to the right requirements file:
- **Runtime dependency** → `requirements.txt`
- **Dev/test-only tool** → `requirements-dev.txt`

Keep entries unpinned unless a specific version is required for compatibility.

---

## Development Workflow

### Adding a new stat type
1. Add the precompute query to `db/precompute.py`
2. Add a cache loading method to `StatsRepository` using `_PRECOMPUTED_CACHE`
3. Call the new method inside `warm_all_caches()` so it is loaded at startup
4. Add tests that verify the method returns the correct shape from mock rows (no DB)

### Adding a new API route
1. Create or extend a router file under `api/routes/`
2. Include it in `api/main.py`
3. Add a test using `TestClient(app)` in `tests/test_api_<area>.py`

### Strategy extensions
Register new strategies via `StrategyFactory.register()` in `simulator/predictors/factory.py`. Config keys (`outcome_strategy`, `bowling_strategy`) are the registration names.

### MVP scoring extensions
`simulator/awards/mvp_strategy.py` defines the swappable contract: `MvpStrategy.compute(match) -> List[PlayerAward]`. `StatisticalAwardsStrategy` (`simulator/awards/statistical_awards.py`) is the default — a fixed, per-format point table. A different scoring algorithm (e.g. win-probability-based) means writing a new `MvpStrategy` subclass and passing an instance to `MatchAwards(strategy=...)` — nothing else (persistence, API, frontend) needs to change, since they only ever read `PlayerAward.total` (and, best-effort, `.breakdown` for display).
