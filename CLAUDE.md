# CLAUDE.md - Cricket Simulator Development Guide

## Critical Rules

### 1. NEVER query `history.deliveries` at simulation runtime
`history.deliveries` is an 11.2M-row, 1.3GB table. Any query against it during a simulation run will add seconds of latency per match. It is only safe to access from `db/precompute.py` during the one-time offline precomputation step.

All simulation runtime reads must go through the precomputed tables:
- `history.player_outcome_stats` - per-player distributions (batting, bowling, phase, milestone)
- `history.player_context_stats` - per-player venue/country distributions
- `history.batter_bowler_matchups` - head-to-head distributions
- `history.bowler_order_stats` - bowler rotation frequency and phase distributions
- `history.player_scalar_stats` - career economy, workload, role flags
- `history.aggregate_stats` - format-level baseline distributions

Any new data need identified during development must be added to `db/precompute.py` and surfaced through `StatsRepository` cache methods.

### 2. No duplicate calculation logic - one formula, one function
Any calculation used in more than one place - the live in-memory simulation engine, a SQL-derived display query, the frontend - must live in exactly one function. Every other call site either calls it directly or consumes a value that call already persisted. Never re-derive the formula independently at a second site, even when the two sites have completely different data available (in-memory objects vs. DB rows vs. API JSON) - that's what a thin adapter is for, not a rewrite. SQL should only fetch raw rows; the actual arithmetic belongs in one shared Python function that all callers route through.

When you find an existing duplication and consolidate it into one implementation, verify which version is actually correct against real domain rules/data before picking one to keep - two implementations agreeing with each other is not the same as either of them being correct. (Precedent: NRR was computed twice - the live tournament engine's version silently omitted the ICC all-out rule; the display SQL had it right. Simply deleting the display version to "fix the duplication" would have kept the wrong number live and shipped it everywhere.) A fix that removes the duplicate without checking correctness is not done.

### 3. Write tests for every new feature or fix
Before marking any task complete, add tests in `tests/`. All tests must run without a database connection - mock or bypass it at the class level (see test patterns below).

### 4. Keep `db/schema.sql` in sync with `db/migrations/`
`db/schema.sql` is the single "current full schema" reference - it's what `db/database.py::initialize_schema()` runs to set up a fresh database, and it's what anyone reading the codebase treats as ground truth for what tables exist. Every migration that adds/alters a table in the **main app DB** (not the old Supabase-only `profiles` table, which never belonged here) must also be reflected in `schema.sql` in the same change - not as a follow-up. This drifted twice already (migrations 030 and 031 both landed without a `schema.sql` update) before being caught and backfilled; don't let it happen a third time.

---

## Architecture Overview

### Process-level singletons
- `StatsRepository._conn` - single PostgreSQL connection shared across all `StatsRepository()` instances in the process. Never opened again after the first call. Protected by `_conn_lock` (double-checked locking).
- `_PRECOMPUTED_CACHE` - module-level dict in `db/stats_repository.py`. Populated lazily on first use - deliberately NOT warmed at API startup, to keep idle RAM low on the 1GB droplet (`warm_all_caches()` exists for manual/offline warming only).
- `StatsRepository._query_lock` - serialises all DB round-trips (psycopg2 connections are not thread-safe).

### Log system
- No per-match log files. All output goes to rotating files: `logs/simulation.log` (20MB×10) and `logs/errors.log` (5MB×5).
- **Every exception in runtime code must be findable in `errors.log`.** The file handlers are attached only to the `"cricket_sim"` logger — always use `simulator.logger.get_logger()`, never `logging.getLogger(__name__)` (an unconfigured stdlib logger whose output silently goes to stderr; this hid a prod job failure entirely). Never swallow a failure with `except: pass` — log it. Bare pass is only acceptable for genuine control flow (e.g. `WebSocketDisconnect` on client leave).
- Every log line carries `[sim_id/m{match_id}]` context injected from `ContextVar`s - safe for concurrent runs.
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

### Identity system - resolve, don't migrate
`simulation.identity_links` (`db/identity_repository.py::IdentityRepository`) is the single source of identity for both anonymous and authenticated users, with a real, enforced, case-insensitive unique username. Every `client_id`-consuming method resolves it through `resolve_client_id`/`link_account` first (see `SimulationRepository._resolve_client_id`), rather than mutating historical `client_id`/`participant_ids`/`game_sessions`/`rooms` columns when someone signs in. That "resolve, don't migrate" pattern is deliberate: it means no per-table migration logic is ever needed again when a new client_id-bearing table is added - the old `link_anonymous` approach broke exactly this way (it updated `simulations.client_id` on sign-in but missed `participant_ids`/`game_sessions.client_id`/`rooms.host_id`/`room_members.client_id`, leaving some multiplayer participants stuck showing as spectators; see `db/diagnose_legacy_identity_gaps.py`, which is read-only precisely because that gap turned out to be unrepairable after the fact - there was no stored mapping from an old anon id to the auth id it became).

Never re-add a second identity/profile store, and never mutate historical `client_id` columns in place on sign-in - route any new identity-touching code through `IdentityRepository` instead.

---

## Database Schema Summary

### `history` schema - read-only at runtime
| Table | Purpose |
|-------|---------|
| `history.players` | Player registry (player_id, name, gender) |
| `history.venues` | Venue registry (venue_id, name, city, country_id) |
| `history.matches` | Historical match metadata |
| `history.deliveries` | **11.2M rows - NEVER query at runtime** |
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

### `simulation` schema - written by API
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
| `simulation.game_sessions` | Per-participant UI/team context for a sim (fun/challenge mode, swaps) |
| `simulation.rooms` / `simulation.room_members` | Live multiplayer draft rooms and their rosters |
| `simulation.admin_edits` | Audit log of admin UI edits; synced across DBs via `db/replay_admin_edits.py` |
| `simulation.identity_links` | Single source of identity for anonymous + authenticated users (unique username, resolve-don't-migrate design - see `db/identity_repository.py`). Replaces the old Supabase-hosted `simulation.profiles` table entirely. |

---

## Key File Map

| File | Role |
|------|------|
| `simulator/logger.py` | Application logger - `configure_logger`, `log_context`, `set_log_level` |
| `simulator/match_logger.py` | MatchLogger - wraps global logger; no file I/O |
| `simulator/entities/match.py` | `SimulationMatch` - central mutable state object |
| `simulator/entities/rules.py` | `MatchRules` - pure static cricket law helpers |
| `simulator/engines/innings_simulator.py` | Core ball-by-ball loop |
| `simulator/engines/limited_overs_engine.py` | T20/ODI driver; triggers super over on tie |
| `simulator/predictors/factory.py` | Strategy wiring - `StrategyFactory.register()` |
| `simulator/predictors/ball_outcome_prediction/enhanced_historical_stats/strategy.py` | Primary RMS prediction engine |
| `simulator/predictors/bowling/historical/base.py` | Historical bowling selection (F1–F6 scoring) |
| `simulator/tournament/engine.py` | `TournamentEngine` - group stage + playoffs |
| `simulator/awards/mvp_strategy.py` | `MvpStrategy` (ABC), `PlayerAward` - swappable MVP/POTM scoring contract |
| `simulator/awards/statistical_awards.py` | `StatisticalAwardsStrategy` - default MVP rubric, per-format point table |
| `simulator/awards/match_awards.py` | `MatchAwards`, `TournamentAwards` - strategy-agnostic POTM/POTT orchestration |
| `db/stats_repository.py` | All runtime DB queries; singleton connection; `_PRECOMPUTED_CACHE` |
| `db/precompute.py` | Offline precomputation - the only place allowed to query `history.deliveries` |
| `api/worker.py` | Background job runners; `_PersistingTournamentEngine` |
| `api/main.py` | FastAPI app; mounts all routers (admin routers behind `require_admin_user`) |
| `api/deps.py` | `get_current_user_id` (Supabase JWT verification), `require_admin_user` (ADMIN_USER_IDS guard) |
| `api/routes/admin.py` | Runtime ops controls: log level, cache strategy, simulation defaults |
| `api/routes/admin_data.py` | Admin-only cross-user views + tournament/player editors |
| `db/admin_edits.py` + `db/replay_admin_edits.py` | Admin edit log (`simulation.admin_edits`) and cross-DB export/replay CLI |
| `db/identity_repository.py` | `IdentityRepository` - single source of anon+auth identity (`simulation.identity_links`); `resolve_client_id`/`link_account`/`sync_anonymous`/username |
| `api/routes/identity.py` | `/cricsimapi/identity/*` - anon sync, sign-in link, username get/set |
| `db/schema.sql` | Full current schema for the main app DB - keep in sync with `db/migrations/*.sql` (Critical Rule #4) |

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
- Any new cache loading path in `StatsRepository` - verify it builds the expected dict shape from mock rows
- Any change to `MatchRules` - pure functions are easy to unit-test
- Any new strategy logic - pass minimal mock match/repo objects
- Any new API route - use `fastapi.testclient.TestClient`

---

## UI Conventions

- User-facing copy says **"trade"**, never "swap" (e.g. squad edits, multiplayer draft actions). `swap` is still fine as an internal variable/function name - this is about text a player actually reads, not code.

---

## Installing Packages

Always install into the `cricsim` conda environment - never bare `pip` or `sudo pip`:

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
3. Add the new method to `warm_all_caches()` (manual warming); at runtime caches load lazily on first use
4. Add tests that verify the method returns the correct shape from mock rows (no DB)

### Adding a new API route
1. Create or extend a router file under `api/routes/`
2. Include it in `api/main.py`
3. Add a test using `TestClient(app)` in `tests/test_api_<area>.py`

### Strategy extensions
Register new strategies via `StrategyFactory.register()` in `simulator/predictors/factory.py`. Config keys (`outcome_strategy`, `bowling_strategy`) are the registration names.

### MVP scoring extensions
`simulator/awards/mvp_strategy.py` defines the swappable contract: `MvpStrategy.compute(match) -> List[PlayerAward]`. `StatisticalAwardsStrategy` (`simulator/awards/statistical_awards.py`) is the default - a fixed, per-format point table. A different scoring algorithm (e.g. win-probability-based) means writing a new `MvpStrategy` subclass and passing an instance to `MatchAwards(strategy=...)` - nothing else (persistence, API, frontend) needs to change, since they only ever read `PlayerAward.total` (and, best-effort, `.breakdown` for display).
