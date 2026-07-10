# Cricket Simulator - Codebase Write-up

## Overview

A ball-by-ball cricket simulation engine that drives T20, ODI, and Test matches using historical delivery-level data from a PostgreSQL database. Given two squads and a venue, it produces a statistically realistic scorecard with per-ball commentary, bowling figures, and match results including super overs. A tournament layer wraps the engine to run round-robin group stages, playoffs, leaderboards, and award tracking.

---

## Design Patterns

| Pattern | Used where |
|---------|-----------|
| **Template Method** | `BaseEngine.simulate()` → subclasses fill `_run_inning()` |
| **Strategy** | `BallOutcomeStrategy` (predict_next_ball) and `BowlingStrategy` (select_bowler) ABCs |
| **Observer / Event Bus** | `MatchEventBus.publish()` → `InningPlayer`, `InningTeam` accumulate stats |
| **Factory** | `EngineFactory.create()` routes T20/ODI → `LimitedOversEngine`, Test → `TestMatchEngine` |
| **Dependency Injection** | `StatsRepository` injected into all strategies; strategies receive the match object |

---

## Directory Structure

```
cricket-simulator/
├── db/                          # Database layer
│   ├── database.py              # Connection factory (get_db_connection)
│   ├── stats_repository.py      # Query facade - all simulation queries live here
│   ├── entities/                # Plain data classes mirroring DB tables
│   │   ├── match.py  player.py  venue.py  team.py  tournament.py  delivery.py
│   ├── ingest_data.py           # Cricsheet JSON → PostgreSQL ingestion script
│   ├── repository.py            # General-purpose CRUD (not used by simulation)
│   └── populate_venue_countries.py  # One-time venue metadata enrichment
│
├── enums/constants.py           # ExtraType, DismissalType, OutcomeType enums
│
├── parser/cricsheet_parser.py   # Converts raw Cricsheet YAML/JSON to DB rows
│
├── simulator/
│   ├── entities/                # Match-state dataclasses
│   │   ├── match.py             # SimulationMatch - the central mutable state object
│   │   ├── rules.py             # MatchRules - all cricket law logic (pure static methods)
│   │   ├── ball_outcome.py      # BallOutcome (frozen dataclass) - one delivery result
│   │   ├── delivery.py          # SimulationDelivery - persisted delivery record
│   │   ├── player.py            # Player (id, name, is_keeper)
│   │   ├── team.py              # MatchTeam - squad-level representation
│   │   ├── inning.py            # Inning - container for InningTeam + deliveries
│   │   ├── inning_team.py       # InningTeam - running totals, batting order management
│   │   └── inning_player.py     # InningPlayer - per-delivery stat accumulator (MatchObserver)
│   │
│   ├── events.py                # EventType, MatchEvent, MatchObserver, MatchEventBus
│   │
│   ├── engines/
│   │   ├── base_engine.py       # BaseEngine ABC - inning wiring, toss, scorecard output
│   │   ├── limited_overs_engine.py  # T20 / ODI: two innings, run chase, super-over trigger
│   │   ├── test_engine.py       # Test: four innings, follow-on, draw detection
│   │   ├── super_over_engine.py # Super over: 1-over per side, bowler/batter selection
│   │   ├── innings_simulator.py # InningsSimulator - drives overs and balls within an innings
│   │   └── engine_factory.py    # EngineFactory.create() - format → engine class
│   │
│   ├── strategies/
│   │   ├── ball_outcome_prediction/
│   │   │   ├── strategy_interface.py           # BallOutcomeStrategy ABC
│   │   │   ├── common/utils.py                 # Shared constants, helpers, apply_free_hit_modifier
│   │   │   ├── historical_stats/strategy.py    # BaseHistoricalStatsStrategy (RMS v1)
│   │   │   ├── historical_stats/validate.py    # ModelValidator - backtest against held-out data
│   │   │   └── enhanced_historical_stats/strategy.py # EnhancedBaseHistoricalStatsStrategy (RMS v2)
│   │   │
│   │   └── bowling/
│   │       ├── strategy_interface.py     # BowlingStrategy ABC
│   │       ├── historical/base.py        # HistoricalBowlingBase - scoring framework + cache mgmt
│   │       ├── historical/strategies.py  # T20/ODI/TestHistoricalBowlingStrategy + factory
│   │       ├── rotation/strategy.py      # SimpleRotationBowlingStrategy - round-robin fallback
│   │       └── smart/strategy.py         # SmartBowlingStrategy - phase-aware heuristic
│   │
│   ├── tournament/              # Tournament simulation layer
│   │   ├── __init__.py          # Re-exports TournamentEngine, TournamentConfig, load_tournament_config
│   │   ├── engine.py            # TournamentEngine - orchestrates group stage + playoffs
│   │   ├── config.py            # TournamentConfig, TeamConfig, ScheduleConfig, PlayoffConfig
│   │   ├── scheduler.py         # generate_fixtures / generate_playoffs - fixture list builders
│   │   ├── points_table.py      # PointsTable - standings, NRR, points tracking
│   │   ├── leaderboards.py      # TournamentLeaderboards - batting/bowling aggregates
│   │   ├── awards.py            # MatchAwards (POTM) + TournamentAwards (POTT)
│   │   └── presenter.py         # Coloured terminal output - scorecards, points table, leaderboards
│   │
│   ├── presentation/
│   │   └── formatters.py        # format_ball_commentary, format_over_summary, format_innings_scorecard
│   │
│   ├── logger.py                # Centralised logger: console + 2 rotating files; ContextVar injection;
│   │                            #   configure_logger(), log_context(), set_log_level(), get_logger()
│   ├── match_logger.py          # MatchLogger - routes to global logger; NO per-match files
│   └── simulate_driver.py       # CLI entry point - loads config, builds match, calls engine
│
├── tests/                       # pytest unit tests (no DB required)
│   ├── test_rules.py
│   ├── test_inning_player.py
│   ├── test_innings_simulator.py
│   ├── test_free_hit_modifier.py
│   ├── test_stats_repository_parsing.py
│   ├── test_enhanced_strategy.py
│   ├── test_bowling_eligibility.py
│   ├── test_historical_bowling_order.py
│   ├── test_super_over_selector.py
│   ├── test_super_over.py
│   ├── test_leaderboards.py
│   ├── test_points_table.py
│   ├── test_scheduler.py
│   └── test_awards.py
│
├── validation/                  # Backtest and validation scripts
├── tools/                       # Developer tools
├── match_config.json            # Default squad + venue configuration for single-match runs
├── tournament_config.json       # 8-team ODI tournament configuration (Champions Trophy 2025)
└── run_tournament.py            # Tournament entry point: python run_tournament.py --config tournament_config.json
```

---

## Core Data Flow

### 1. Match setup (simulate_driver.py → BaseEngine)

```
match_config.json
       │
       ▼
simulate_driver.py          Reads squad names + venue. Resolves each player name
       │                    to a DB player_id via StatsRepository.get_player_by_name().
       │
       ▼
SimulationMatch             Dataclass holding all mutable match state:
                            current_over, current_ball, striker, non_striker,
                            current_bowler, innings[], target_score, is_free_hit, …
       │
       ▼
EngineFactory.create()      Routes on match_format → LimitedOversEngine | TestMatchEngine
       │
       ▼
BaseEngine.__init__()       Stores match + both strategies (ball-outcome and bowling)
```

### 2. Model initialisation (BaseEngine._prepare_match_logs)

```
ball_outcomes.init_model(match)      For each strategy, loads player data from _PRECOMPUTED_CACHE
bowling_strategy.init_model(match)   (warmed at server startup). Cache reads are pure dict lookups
                                     - no DB round-trips in the hot path.
                                     In tournament mode, init_model is called before every match
                                     so strategies can extend caches for newly-seen players.
                                     All caches are in-memory dicts keyed by player_id,
                                     venue_id, phase name, etc.
```

### 3. Per-innings flow (LimitedOversEngine → InningsSimulator)

```
engine._create_inning()        Builds InningTeam + InningPlayer objects.
                               Rewires event bus: each InningPlayer subscribes.

engine._set_initial_players()  Sets striker / non_striker / current_bowler.

InningsSimulator.run()         Loop: while wickets < max and overs < cap:
    └── _simulate_over()           Loop: while current_ball < 6:
            │
            ├── match.is_free_hit = is_free_hit         ← set before prediction
            ├── ball_outcomes.predict_next_ball(match)  ← returns BallOutcome
            ├── _apply_free_hit_rules(outcome, …)       ← cancel wicket if free hit; update state
            ├── event_bus.publish(BALL_BOWLED)          ← InningPlayer/InningTeam update stats
            └── _advance_batter_after_wicket()
        │
        ├── event_bus.publish(OVER_COMPLETED)           ← maiden detection
        ├── bowling_strategy.select_bowler(match)       ← pick next bowler
        └── on_over_complete callback (if any)
```

### 4. Ball outcome prediction (EnhancedBaseHistoricalStatsStrategy)

```
predict_next_ball(match):
  1. Determine batter_id, bowler_id, current_over, batter_runs.
  2. Get venue_probs via _get_player_venue_probs(batter_id)
     → blends per-player venue cache (up to 65% weight at ≥60 balls) with general venue.
  3. _compute_effective_weights(batter_id, bowler_id, matchup_key)
     → scales base WEIGHTS by data reliability (ball count / threshold).
  4. _compute_distribution(…)
     → for each outcome key in baseline: multiply baseline by 8 RMS context multipliers
       (batter, bowler, matchup, phase, milestone, innings, venue, tournament).
     → Each multiplier = (context_prob / baseline_prob) ^ (k × effective_weight).
  5. _apply_pressure_modifier(weights, keys, pressure_ctx)
     → adjusts for score pressure, consecutive dots, wicket rate, partnership length.
  6. apply_free_hit_modifier(weights, keys) if match.is_free_hit
     → 6s×2.5, 4s×2.0, 1–3×1.2, dots×0.45, non-run-out wickets×0.15.
  7. random.choices(keys, weights=normalised) - sample outcome.
  8. _assign_fielder() - pick catcher/stumper from fielding cache.
```

---

## Entities

### SimulationMatch (`simulator/entities/match.py`)

The single mutable god-object passed throughout the simulation. Key fields:

| Field | Type | Purpose |
|-------|------|---------|
| `innings` | `List[Inning]` | Completed and in-progress innings |
| `current_over` | `int` | 0-indexed over number within the current innings |
| `current_ball` | `int` | Ball count within the current over (legal balls only) |
| `striker / non_striker` | `InningPlayer` | Current batting pair |
| `current_bowler` | `InningPlayer` | Current bowler |
| `target_score` | `Optional[int]` | Second-innings chase target |
| `is_free_hit` | `bool` | Whether the current ball is a free hit |
| `is_super_over` | `bool` | Adjusts commentary and wicket limit |
| `match_format` | `str` | "T20", "ODI", or "Test" |
| `event_bus` | `MatchEventBus` | Pub/sub bus; rewired fresh for each innings |

### MatchRules (`simulator/entities/rules.py`)

Pure static methods encoding cricket law. Used across the entire codebase so phase logic is never duplicated.

- `get_unified_format(s)` - normalise "IT20"→"T20", "MDM"→"Test", etc.
- `is_legal_delivery(extras_type)` - False for Wide/Noball.
- `is_free_hit_awarded(extras_type)` - True for Noball only.
- `supports_free_hit(match_format)` - True for T20/ODI.
- `is_death_over(over_0indexed, format)` - T20≥16, ODI≥40.
- `get_phase(over_0indexed, format)` - "powerplay" / "middle" / "death" / "none".
- `get_fine_grained_phase(over_1indexed, format)` - 6 T20 buckets, 7 ODI, 4 Test.
- `is_bowler_credited_wicket(wicket_kind)` - False for run-out and non-bowling dismissals.

### InningPlayer (`simulator/entities/inning_player.py`)

Implements `MatchObserver`. Subscribes to the event bus at the start of each innings and accumulates both batting and bowling statistics from `BALL_BOWLED` and `OVER_COMPLETED` events. Owns death-phase subset stats used by `SuperOverEngine` for player selection.

### BallOutcome (`simulator/entities/ball_outcome.py`)

Frozen dataclass returned by every `predict_next_ball()` call:

```python
@dataclass(frozen=True)
class BallOutcome:
    runs_batter:    int = 0
    runs_extras:    int = 0
    is_wicket:      bool = False
    wicket_kind:    Optional[str] = None   # "bowled", "caught", "run out", …
    extras_type:    Optional[str] = None   # ExtraType enum value
    outcome_player: Optional[Any] = None  # fielder for catches/stumpings
```

---

## Strategies

### Ball-outcome strategies

Both implement `BallOutcomeStrategy` with two methods: `init_model(match)` and `predict_next_ball(match) → BallOutcome`.

#### BaseHistoricalStatsStrategy (v1 - `historical_stats/strategy.py`)

Relative Multiplicative Scaling with fixed integer-per-over lookup. Good baseline. Weights: batter, bowler, venue, innings, tournament, overs.

#### EnhancedBaseHistoricalStatsStrategy (v2 - `enhanced_historical_stats/strategy.py`)

Four improvements over v1:

1. **Fine-grained phase** - 6 T20 / 7 ODI / 4 Test buckets instead of per-over lookup.
2. **Batter milestone context** - conditions on 10-run score buckets (m0…m100) to capture set vs new batter behaviour.
3. **Reliability-weighted blending** - contexts with sparse ball counts are down-weighted and their budget redistributed.
4. **Outcome-category relevance** - wickets rely more on bowler; boundaries more on batter; extras almost entirely on bowler.

Additional:
- **Pressure modifier** - post-RMS multiplicative modifier for chase urgency, dot-ball pressure, wicket rate, partnership length.
- **Free-hit modifier** - when `match.is_free_hit`, boundaries boosted 2–2.5×, dots reduced to 0.45×.
- **Player venue blending** - `_get_player_venue_probs()` blends per-player historical data at the venue with the general venue distribution (up to 65% player weight at ≥60 balls).

Format subclasses set their `WEIGHTS` dict:

| Context | T20 | ODI | Test |
|---------|-----|-----|------|
| batter | 0.22 | 0.10 | 0.21 |
| bowler | 0.22 | 0.13 | 0.26 |
| matchup | 0.14 | 0.11 | 0.14 |
| phase | 0.17 | 0.37 | 0.08 |
| venue | 0.05 | 0.06 | 0.06 |
| tournament | 0.04 | 0.05 | 0.06 |
| innings | 0.04 | 0.06 | 0.04 |
| milestone | 0.12 | 0.12 | 0.15 |

### Bowling strategies

All implement `BowlingStrategy` with `init_model(match)` and `select_bowler(match) → InningPlayer`.

#### HistoricalBowlingBase / format-specific subclasses (`bowling/historical/`)

Scores each eligible bowler on six factors (F1–F6) and returns the highest scorer:

| Factor | Description |
|--------|-------------|
| F1 | Phase affinity - how well the bowler's historical stats match the current phase |
| F2 | Match form - recent wickets/economy in the current innings |
| F3 | Spell management - avoids bowling the same bowler consecutively |
| F4 | Matchup - head-to-head advantage over the current batter |
| F5 | Quota pacing - urgency to use remaining quota before the innings ends |
| F6 | Death reservation - holds specialists back for the death overs |

**Tournament cache management**: `init_model` is called before every match in a tournament. On the first call it performs a full parallel cache load. On subsequent calls it detects new player IDs not seen before and calls `_extend_global_caches(new_ids)` to load their global-level data, merging into the existing caches. This ensures every team's bowlers are properly scored rather than falling back to a zero-score default.

#### SmartBowlingStrategy (`bowling/smart/strategy.py`)

Lighter phase-aware heuristic used when no historical data is available.

#### SimpleRotationBowlingStrategy (`bowling/rotation/strategy.py`)

Round-robin bowler rotation, useful for testing or minimal dependencies.

---

## Tournament Layer (`simulator/tournament/`)

### TournamentEngine (`engine.py`)

Orchestrates a complete tournament:
1. Pre-loads all player objects via `_preload_players()`.
2. Generates group-stage fixtures via `generate_fixtures()`.
3. Runs each fixture: simulates the match, updates `PointsTable`, `TournamentLeaderboards`, and `MatchAwards`.
4. After the group stage, generates and runs playoff fixtures with bracket propagation.
5. Prints final standings, leaderboards, and Player of the Tournament.

**Output model**: `MatchLogger.SILENT = True` is set in tournament mode so the simulation engine writes per-match `.txt`/`.log` files but produces no console output. The `Presenter` owns all console rendering.

### Config (`config.py`)

Dataclasses: `TournamentConfig`, `TeamConfig` (name, colors, players), `ScheduleConfig` (round_robin / double_round_robin), `PlayoffConfig` (none / semis_final / quarters_semis_final / ipl).

### Presenter (`presenter.py`)

Coloured ANSI 24-bit true-color terminal output. Falls back to identical plain-text layout when stdout is not a TTY.

- **Scorecard**: same layout as `format_innings_scorecard` (100-char width, column-aligned). Out batters: team primary bg. Not-out batters: flipped (secondary bg, primary text, bold). Bowling rows: bowling team's primary bg. Column headings: fixed muted gray.
- **Points table**: each row in team primary bg + secondary text.
- **Leaderboards**: plain text, team badge in team primary color.

### Awards (`awards.py`)

`MatchAwards` records batting/bowling/fielding contribution points per match and selects the Player of the Match. `TournamentAwards` accumulates across matches to rank Player of the Tournament.

### Leaderboards (`leaderboards.py`)

Maintains running `BatterStats` and `BowlerStats` across all matches. Surfaces ranked lists: most runs, highest score, best average, best strike rate, most wickets, best economy, etc.

### Points table (`points_table.py`)

Tracks W/L/T/NR, points, and Net Run Rate for each team. `standings()` returns teams sorted by points then NRR.

---

## Engines

### LimitedOversEngine

T20 / ODI flow:
1. Toss → determine batting order.
2. Innings 1 → runs to target for innings 2.
3. Innings 2 → terminates on target reached.
4. If tied → `SuperOverEngine`.

### TestMatchEngine

Up to four innings. Handles follow-on (deficit > 200 runs). Match ends on:
- 10 wickets in both innings for the side that batted first.
- All wickets in the last innings.
- Draw after 5 days (over limit).

### SuperOverEngine

- Selects 2 batters (best death performers from main innings) and 1 bowler per side.
- Runs 1 over with `max_wickets=2`.
- Compares totals; recurses if still tied.

### InningsSimulator

Owns all delivery-level mechanics. Not an engine (does not call `init_model`); it is called by engines:

```
run(max_overs, should_terminate, on_over_complete, max_wickets)
  └── _simulate_over()
        ├── set match.is_free_hit
        ├── predict_next_ball()
        ├── _apply_free_hit_rules()    ← static; cancels wickets, updates state
        ├── event_bus.publish()        ← stats update
        ├── _build_delivery()          ← builds SimulationDelivery record
        ├── _publish_ball_event()
        └── _advance_batter_after_wicket()
```

---

## Database Layer (`db/stats_repository.py`)

All simulation queries live here. Key method groups:

| Group | Methods |
|-------|---------|
| Player lookup | `get_player_by_name`, `get_venue_by_name` |
| Aggregate baselines | `get_full_aggregate_distribution`, `get_innings_distribution`, `get_phase_distribution` |
| Per-player caches | `get_batters_distribution_with_counts`, `get_bowlers_distribution_with_counts`, `get_matchup_distribution_with_counts` |
| Milestone caches | `get_batter_milestone_distribution`, `get_player_milestone_distributions` |
| Venue/country | `get_venue_distribution`, `get_country_distribution`, `get_player_venue_distribution`, `get_player_country_distribution` |
| Bowling specific | `get_bowler_career_stats`, `get_bowler_workload_stats`, `get_bowler_over_frequency`, `get_bowler_phase_overs_distribution`, `get_batter_bowler_matchups`, `get_bowler_recent_form` |
| Validation | `get_validation_deliveries` |
| Metadata | `get_wicket_keepers`, `get_spinner_ids`, `get_fielding_distribution` |

All results are normalised probability dicts keyed by `(runs_batter, runs_extras, outcome_type, outcome_kind)`.

---

## Logging

Two-layer system:

- `simulator/logger.py` - Python `logging`-backed dual sink: console (WARNING+) + rotating file (DEBUG, 10MB × 5 backups). `configure_logger(log_file, level)` attaches the file handler once at startup. `set_console_level(level)` adjusts the console threshold (used by tournament engine to suppress engine-level noise).
- `simulator/match_logger.py` - `MatchLogger` owns all human-readable output for one match. Opens `match_<id>.txt` (ball-by-ball commentary, always written) and `match_<id>.log` (timestamped structured events). Set `MatchLogger.SILENT = True` before a batch or tournament run to suppress all console output while still writing both files.

---

## Free Hit Mechanics

Free hits apply in T20 and ODI only (after a no-ball).

**State machine (per ball, `InningsSimulator._apply_free_hit_rules`):**

```
no-ball delivered          → is_free_hit = True  (for next ball)
legal delivery on free hit → is_free_hit = False
wide on free hit           → is_free_hit = True  (wide doesn't consume it)
wide not on free hit       → is_free_hit = False
```

**Effect on outcome prediction:**

When `match.is_free_hit` is True before `predict_next_ball()` is called, `apply_free_hit_modifier()` is applied to the final weight vector:

- 6s: ×2.5  
- 4s: ×2.0  
- 1–3 runs: ×1.2  
- Dots: ×0.45  
- Non-run-out wickets: ×0.15 (they will be cancelled by `_apply_free_hit_rules` anyway)

---

## Event System

`MatchEventBus` is a simple list-based observer. Events:

- `BALL_BOWLED` - carries `match`, `batter`, `bowler`, `outcome`. Both batting and bowling `InningPlayer` accumulate per-delivery stats from this event.
- `OVER_COMPLETED` - carries `bowler`, `runs`. Used to detect maiden overs.

The bus is cleared and rewired at the start of each innings so observers from the previous innings don't accumulate stale events.

---

## Adding a New Ball-Outcome Strategy

1. Create a new folder under `simulator/predictors/ball_outcome_prediction/` with `__init__.py` and `strategy.py`.
2. Subclass `BallOutcomeStrategy` from `strategy_interface.py`.
3. Implement `init_model(match)` (load any caches needed) and `predict_next_ball(match) → BallOutcome`.
4. Register it in `simulate_driver.py`'s `_OUTCOME_STRATEGIES` dict.

## Adding a New Bowling Strategy

1. Create a new folder under `simulator/predictors/bowling/` with `__init__.py` and `strategy.py`.
2. Subclass `BowlingStrategy` from `strategy_interface.py`.
3. Implement `init_model(match)` and `select_bowler(match) → InningPlayer`.
4. Pass it to `EngineFactory.create()` or inject directly into `BaseEngine`.

---

## Running Tests

```bash
python -m pytest tests/ -v
```

All tests run without a database connection. They cover:
- `MatchRules` - all phase detection, format normalisation, and rule checks.
- `InningPlayer` - stat accumulation for batters and bowlers across legal/extra deliveries and death overs.
- `InningsSimulator._apply_free_hit_rules` - state transitions and wicket cancellation.
- `apply_free_hit_modifier` - boundary boost, dot suppression, wicket suppression.
- `StatsRepository._parse_rows_to_probs[_with_count]` - probability normalisation.

## Running a Tournament

```bash
python run_tournament.py --config tournament_config.json
python run_tournament.py --config tournament_config.json --seed 42 --silent
```

The config JSON specifies teams (name, colors, player names), schedule type (round_robin / double_round_robin), venues, and playoff format.
