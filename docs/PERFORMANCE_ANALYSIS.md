# Performance Analysis: Cricket Simulator - Simulation Loop

**Context:** 94-match IPL tournament, ~22,560 balls total (240 per T20 match × 2 innings × 94 matches).
Simulation loop is the dominant cost at ~11s out of ~13s end-to-end. Analysis is purely observational - no code changes made.

---

## 1. Per-Ball Work in `innings_simulator.py`

**File:** `simulator/engines/innings_simulator.py`

### Current cost

Every legal delivery runs the following chain:

```
predict_next_ball(match)         # strategy: the dominant per-ball cost
_apply_free_hit_rules(...)       # 2-3 attribute reads + 2-3 condition checks
_build_delivery(...)             # constructs a SimulationDelivery dataclass
inning.deliveries.append(d)      # list append (O(1) amortised)
_publish_ball_event(outcome)     # event bus: dispatches to 22 observers
format_ball_commentary(delivery) # string formatting (DEBUG level)
logger.ball(text)                # logger.debug() call
```

### Bottlenecks

**B1 – `MatchRules` static method calls on every ball (medium cost)**
`_simulate_over` calls `MatchRules.supports_free_hit()` once per over (fine) but inside `_publish_ball_event` and the body, `MatchRules.is_legal_delivery()` is called per ball. More expensive: each `InningPlayer.on_event()` calls `MatchRules.is_death_over()`, `MatchRules.is_legal_delivery()` (×2), and `MatchRules.is_bowler_credited_wicket()` - four static method calls plus dict lookups inside each. With 22 observers per ball (11 players × 2 teams), that is up to 4 × 22 = 88 attribute-lookup + function-call overheads per ball. See `inning_player.py:58,68,88,90`.

**Recommendation (medium impact):** Hoist the is_death flag and is_legal_delivery result into the `MatchEvent.data` dict once in `_publish_ball_event()` (already has `match` in there) so each observer reads a precomputed value instead of recomputing it:
```python
# In _publish_ball_event(), add:
"is_legal": MatchRules.is_legal_delivery(outcome.extras_type),
"is_death": MatchRules.is_death_over(match.current_over, match.match_format),
```

**B2 – `_build_delivery` creates a new dataclass object per ball (low individual cost, adds up)**
`simulator/engines/innings_simulator.py:183-197`. A `SimulationDelivery` dataclass is constructed per ball - 15 field assignments. In CPython, dataclass construction is roughly 2–3 µs. At 22,560 balls that is ~50ms. Minor but avoidable if delivery objects were pooled or replaced with a lighter tuple/namedtuple appended directly to a preallocated list.

**B3 – `format_ball_commentary` string formatting per ball (low cost when SILENT)**
`simulator/engines/innings_simulator.py:140-142` calls `format_ball_commentary(delivery, ...)` on every ball unconditionally, then passes the result to `logger.ball()` which calls `log.debug()`. Because the logger's root level is `DEBUG` (set at line 120 of `logger.py`), the logger does accept the call - it is only the console handler that is at level CONSOLE (25 > INFO 20). However with no file handler registered in tournament mode, `log.debug()` will still evaluate the `%s` format string after the handler-level check. The string is built *before* the log call, so `format_ball_commentary` runs unconditionally on every ball even when output is suppressed. Wrapping both the format and the log call in `if log.isEnabledFor(logging.DEBUG):` would eliminate ~22,560 function calls and string allocations.

---

## 2. `predict()` / `_compute_distribution()` in `EnhancedHistoricalStatsStrategy`

**File:** `simulator/predictors/ball_outcome_prediction/enhanced_historical_stats/strategy.py`

### Current cost (dominant bottleneck)

`predict_next_ball()` is called once per ball and does the following work:

1. **`_compute_effective_weights()`** - 3 dict lookups, 8 multiplications, a conditional T20 redistribution block, and a dict comprehension to normalise. Called once per ball. Cheap individually (~1 µs) but uncached.

2. **`_compute_phase_probs()`** - 3–4 dict lookups, a dict-union (`set(global_phase) | set(bp) | set(bd)`), and a dict comprehension over all outcome keys. Called once per ball (line 1040). The phase and batter are stable across an entire over (6 balls minimum); batter's phase and the bowler typically do not change mid-over.

3. **`_get_player_venue_probs()`** - 3 dict lookups, arithmetic (weight computation), a `set(general) | set(vp) | set(cp)` union, and a full dict comprehension over all keys. Called once per ball (line 1237). The batter ID changes only on a wicket; the venue never changes. This is recomputed every single delivery despite being stable until wicket fall.

4. **`_compute_distribution()` inner loop** - iterates over every key in `baseline_outcome_probs` (typically ~30–50 distinct outcome tuples for T20). Per key:
   - 8 dict `.get()` calls (batter, bowler, matchup, phase, milestone, innings, venue, tournament)
   - `_apply_category_relevance(eff_w, outcome_key)` - creates a new 8-key dict, computes 8 multiplications, sums 8 values, creates a second normalised 8-key dict. This is called **once per outcome key per ball**, i.e. ~40 × 22,560 = ~900,000 invocations.
   - 8 `_clean_multiplier()` calls, each with a branch, a `max/min`, and a `**` (power) operation.

5. **`ordered_keys = list(self.baseline_outcome_probs.keys())`** - creates a new list every call (line 1052). `list(d.keys())` is O(n) allocation on every ball.

6. After `_compute_distribution`, `predict_next_ball` extracts `list(distribution.keys())` and `list(distribution.values())` (lines 1281–1282) - two more O(n) list allocations from the newly-created dict.

7. **`_compute_pressure()`** - two O(k) reverse scans of `match.innings[-1].deliveries` (lines 891, 907): one to count consecutive dots, one to count balls since last wicket. At ball 240 of the second innings, each scan walks up to 240 delivery objects. Across 22,560 balls the average scan length is ~120, giving ~22,560 × 120 × 2 = ~5.4M delivery-object iterations just for pressure computation.

8. **`_apply_pressure_modifier()`** - iterates over all `ordered_keys` again with per-key tuple unpacking and conditional arithmetic. A second O(n_outcomes) pass.

9. **Per-ball `log.info()` call (line 1347)** - this is an unconditional INFO-level log call that builds 4 f-strings and a formatted pressure string on every single ball, regardless of whether any handler will consume it. At level INFO (20) < CONSOLE (25), the console handler will suppress it, but the logger still constructs and passes the args to the handler machinery (Python's `log.info()` does check the effective level first via `isEnabledFor`, so if the file handler is absent and the console is at level CONSOLE/WARNING, this call will be a no-op at the handler level - but the f-string arguments `pressure_s`, `result_desc` etc. are evaluated *before* the call because they are not lazy. Only `%`-style lazy formatting helps here).

### Recommendations

**R1 – Cache `_get_player_venue_probs()` result per batter, reset on wicket (HIGH impact)**
The venue never changes and the batter only changes on a wicket. Cache the blended venue-probs dict per `batter_id` as an instance variable (e.g. `self._venue_probs_cache: dict = {}`). On wicket, the cache entry for the out batter is already stale but the new batter will compute and cache on first access. This eliminates the set-union and dict-comprehension for ~90% of deliveries (the ~95% that are not wickets).

**R2 – Cache `_compute_phase_probs()` result per (batter_id, bowler_id, phase), invalidated per over (HIGH impact)**
Phase changes at most every few overs (T20 has 6 phase buckets). Batter changes only on wicket. Bowler changes only at over-end. Cache the result in a small `dict` keyed by `(batter_id, bowler_id, phase)`, cleared at the start of each over or innings. This eliminates the set-union and dict-comprehension for every ball within an over (~6 balls per key re-use).

**R3 – Hoist `_apply_category_relevance` out of the per-key loop (HIGH impact)**
`_apply_category_relevance(eff_w, outcome_key)` creates a new normalised 8-key dict per outcome key. The `eff_w` dict is constant for the entire ball. The only variable is the outcome key's category (5 possible values: boundary/wicket/extra/dot/default). Pre-compute all 5 normalised category-weight dicts once per ball:
```python
# Before the loop:
cw_by_category = {
    cat: _normalise(_apply_relevance(eff_w, cat))
    for cat in ('boundary', 'wicket', 'extra', 'dot', 'default')
}
```
Then inside the loop: `cw = cw_by_category[_outcome_category(outcome_key)]`.
This replaces ~40 dict creations per ball with 5 pre-built ones.

**R4 – Pre-compute `ordered_keys` as a stable class-level or instance list (MEDIUM impact)**
`ordered_keys = list(self.baseline_outcome_probs.keys())` is called on every ball (line 1052) and again in `predict_next_ball` (lines 1281–1282). The baseline never changes after `init_model()`. Store it once:
```python
# In init_model(), after setting baseline_outcome_probs:
self._ordered_keys = list(self.baseline_outcome_probs.keys())
```
Similarly, `_last_raw_weights` is rebuilt as `dict(zip(ordered_keys, raw_weights))` every ball purely for debug logging; this can be skipped unless debug logging is active.

**R5 – Replace the two delivery-list scans in `_compute_pressure()` with O(1) counters (HIGH impact)**
Lines 891 and 907 do linear scans over the growing deliveries list. These can be replaced with counters maintained on `InningTeam` or passed into the innings simulator:
- `consecutive_dots`: reset to 0 on any scoring ball or wicket; increment on dot. Update via the existing event bus.
- `balls_since_last_wicket`: reset to 0 on a wicket; increment on legal delivery. Also maintainable via the event bus.

Both values are already implicitly tracked via the event-bus-driven `InningTeam` and `InningPlayer` state. Adding two integer fields to `InningTeam` and updating them in `on_event()` would remove the O(n) scans entirely.

**R6 – Guard per-ball `log.info()` string construction (MEDIUM impact)**
Lines 1309–1350: `ball_label`, `batter_name`, `bowler_name`, `result_desc`, `pressure_s` are string-formatted unconditionally before the `log.info()` call. Because Python evaluates arguments before passing them, even though the log handler may discard the message, the f-strings are built. Wrap in:
```python
if log.isEnabledFor(logging.INFO):
    ball_label = f"Inn{inning} Ov{over}"
    ...
    log.info(...)
```
Similarly, `phase` and `milestone` (lines 1312–1313) are computed outside any guard solely for logging. Move them inside the guard.

---

## 3. `select_bowler()` in `HistoricalBowlingBase`

**File:** `simulator/predictors/bowling/historical/base.py`

### Current cost

`select_bowler()` is called once per over (20 times per T20 innings, 40 total per match, 3,760 total for 94 matches).

1. **`_eligible()`** - two list comprehensions over `team.inning_players` (11 players). O(11) each, cheap.

2. **`_score_and_breakdown()`** per eligible bowler (~5–8 candidates):
   - `_f_over_affinity()` - 4–5 dict lookups, a 3-level blend (3 multiplications + additions). Per candidate.
   - `_f_match_form()` - 2 arithmetic ops. Cheap.
   - `_f_matchup()` - 2 dict lookups + arithmetic for striker and non-striker.
   - `_f_phase_pacing()` - a loop over `range(overs_per_innings)` (20 iterations for T20) with set membership checks (lines 447–455). Called per candidate bowler. With 8 candidates × 20 loop iterations = 160 iterations per over selection.
   - `_f_death_reservation()` - O(1) arithmetic.

3. **`_last_spell_length()` and `_overs_since_bowled()`** - each does a full O(n_deliveries) scan of `match.innings[-1].deliveries` with a `d.bowler and d.bowler.id == player_id` filter. At over 15 of the second innings this is scanning ~90 deliveries per candidate bowler per factor. With 8 candidates × 2 scans each = 16 delivery-list scans per over selection. These are called only in the Test strategy (`_f_spell_breakdown`), not T20/ODI.

4. **`scored.sort()`** - sorting a list of ~5–8 elements; negligible.

### Recommendations

**R7 – Replace `_last_spell_length()` and `_overs_since_bowled()` delivery scans with per-bowler over-index (MEDIUM impact, Test-only)**
Maintain a `dict[player_id, list[int]]` of overs bowled per player (updated via the event bus `OVER_COMPLETED` event). This makes both lookups O(1) lookups into already-sorted per-player data instead of O(n_deliveries) scans of the full delivery list.

**R8 – Memoize `_f_phase_pacing()` computation per (bowler_id, current_over) (LOW impact)**
The `range(overs_per_innings)` inner loop recomputes the same frequency values for past overs on every `select_bowler()` call. Cache the result per `(ip.id, current_over)` - the current_over increments by 1 per call, so the cache is automatically invalidated.

---

## 4. Event Bus / Observer Pattern

**File:** `simulator/events.py`, `simulator/entities/inning_player.py`, `simulator/entities/inning_team.py`

### Current cost

`MatchEventBus.publish()` iterates over `self.observers` (22 total: 2 InningTeam + 20 InningPlayer) and calls `on_event()` on each. This happens **twice per ball** - once for `BALL_BOWLED` (line 200 of innings_simulator) and once for `OVER_COMPLETED` (line 68 of innings_simulator). So 22 × 1 + 22 × 1 = 44 Python method calls per ball.

```python
# events.py:36-37 - no fast-path:
def publish(self, event: MatchEvent):
    for observer in self.observers:
        observer.on_event(event)
```

Inside `InningPlayer.on_event()` (22 times per ball):
- Creates a `data.get()` dict lookup 4 times (outcome, batter, bowler, match).
- Calls `MatchRules.is_death_over()` once.
- Checks `batter.id == self.id` and `bowler.id == self.id` - identity tests on all 22 players even though only 2 (striker + bowler) have relevant data.

### Bottlenecks

**B4 – All 22 observers process every `BALL_BOWLED` event with 4 dict-get calls each (medium)**
`InningTeam.on_event()` checks `batting_team.id == self.id` - needed. But each `InningPlayer.on_event()` does `batter.id == self.id` and `bowler.id == self.id` on every ball regardless of whether that player has any role. 20 of 22 observer calls are mostly no-ops after the identity check, but each still performs 4 `data.get()` calls and a `MatchRules.is_death_over()` call before branching.

**Recommendation (MEDIUM impact):**
Split the event data pattern: instead of broadcasting to all 22 observers, pass the batter and bowler InningPlayer objects directly to their specific `on_event` methods. Or: maintain a `dict[player_id, InningPlayer]` on `InningTeam` so the ball handler calls `batter_ip.update_batting(outcome, is_death)` and `bowler_ip.update_bowling(outcome, is_death)` directly - eliminating 20 redundant observer dispatches per ball.

Alternatively, pre-extract the `data` dict values in `_publish_ball_event` and pass a typed event object instead of a raw dict, eliminating 4 × 22 = 88 `dict.get()` calls per ball.

---

## 5. Python-Level Optimisations

### 5a – Repeated `_outcome_category()` calls per ball

`_outcome_category(outcome_key)` (strategy.py:236) is called inside the inner loop once per outcome key (line 1066) via `_apply_category_relevance`. With ~40 keys, this is ~40 tuple-unpacks + string comparisons per ball, or ~900,000 per tournament. Since `outcome_key` is a tuple `(runs_batter, runs_extras, outcome_type, outcome_kind)` with a stable mapping to one of 5 categories, precompute a lookup `dict[outcome_key, category_str]` over `baseline_outcome_probs` at `init_model()` time:
```python
self._outcome_category_map = {k: _outcome_category(k) for k in self.baseline_outcome_probs}
```
**Impact: MEDIUM** (eliminates 40 tuple-unpack + branching per ball).

### 5b – `_blend_with_parttime()` creates a new dict on every `_compute_distribution()` call

`_blend_with_parttime(self.parttime_bowler_probs, _raw_bowler, _pt_alpha)` (line 1035) is called per ball. For genuine bowlers (alpha = 0), it returns the player dict unchanged (fast path at line 186). But for part-timers or borderline bowlers, it creates a new merged dict on every ball even though alpha is constant for a given bowler throughout the match. Memoize by `(bowler_id, alpha_bucket)` - where alpha_bucket is `round(alpha, 2)`.

**Impact: LOW** (only affects bowlers with < threshold balls).

### 5c – `_get_milestone()` called twice per ball (once in `_compute_distribution`, once in `predict_next_ball` for logging)

Line 1313 calls `_get_milestone(batter_runs)` and line 1020 also calls it indirectly via `_compute_distribution`. This is cheap (integer division) but called unconditionally at line 1313 even when the result is only used for debug logging. Guard it.

### 5d – `random.choices(ordered_keys, weights=normalised, k=1)[0]` creates a temporary list

`random.choices(..., k=1)` allocates a 1-element list. Use `random.choices(..., k=1)[0]` - already correct. A very minor saving would be to use `_random_choice_with_weights` via numpy `np.random.choice` over a pre-built weights array, but this requires numpy and changes semantics slightly.

### 5e – `PressureContext.is_significant` property evaluated after pressure is computed

`PressureContext.is_significant` (line 338) is checked at line 929. The four component values are computed regardless of whether pressure is significant. This is unavoidable since you need to know the values to check significance. No saving here.

### 5f – `isinstance` or type checks

No `isinstance` checks are found in the hot ball-by-ball path. Not a bottleneck.

---

## 6. Data Structure Choices

### 6a – `InningTeam.wicket_keeper` is O(n) scan on every caught/stumped ball

`inning_team.py:83`: `next((ip for ip in self.inning_players if ip.is_keeper), None)` - linear scan of 11 players. Called from `_assign_fielder()` in the strategy for every stumped dismissal. Rare in practice but structurally O(n). Cache at construction time:
```python
# In from_match_team():
self._wicket_keeper = next((ip for ip in self.inning_players if ip.is_keeper), None)
```

### 6b – `InningTeam.get_next_batter()` is O(n) scan after every wicket

`inning_team.py:94-101`: iterates `inning_players` to find the first non-out non-crease player. Called after every wicket (~8 per match). Minor.

### 6c – `format_over_summary` scans all deliveries for current over every over

`formatters.py:81`: `over_balls = [d for d in inning.deliveries if d.over_number == current_over]`
This is O(total deliveries) per over call. At over 20, it scans 120+ deliveries to find the last 6. Called once per over (20 times per innings), so 40 times per match × 94 = 3,760 calls. Maintaining a `list[list[SimulationDelivery]]` keyed by over number (or slicing the tail of `inning.deliveries` using a start index stored per over) would make this O(6) instead of O(n_deliveries).

**Impact: LOW** (formatter is only called at over-end, not per-ball; total work is manageable at ~20 * 120 / 2 = 1200 iteration-steps per innings).

### 6d – `_last_spell_length()` builds a set then sorts it on every bowler-selection

`base.py:595-608`: builds `sorted({d.over_number for d in match.innings[-1].deliveries if d.bowler and d.bowler.id == player_id})`. The inner comprehension is O(all deliveries), the sort is O(k log k) where k is overs bowled. See R7 for the recommended fix (maintain a per-bowler overs list incrementally).

---

## 7. DB Persist Overhead (1.7s for 94 matches)

**File:** `db/simulation_repository.py`

### Current implementation

`save_deliveries()` (lines 274–332):
1. Builds a Python list of tuples, one per delivery (~240 per T20 innings, ~480 per match, ~45,120 total for 94 matches).
2. Calls `psycopg2.extras.execute_batch(..., page_size=500)`. With ~480 rows per match this issues 1 batch per match per inning call.
3. `save_deliveries` is called **per inning** (2 per match = 188 calls). Each call gets its own `execute_batch` invocation.

The `commit()` timing is controlled by the caller. With `autocommit=False` (line 44), every `execute_batch` runs inside a transaction - but the transaction is committed in a batch at the caller's discretion.

### Bottleneck

**B5 – 188 separate `execute_batch` calls (2 innings × 94 matches) with ~240 rows each**

Each `execute_batch` call has round-trip overhead even with `page_size=500`. The 94 commits (one per match or one per tournament) are the more significant factor, but 188 separate server round-trips for batches that could be combined is the primary overhead.

### Recommendations

**R9 – Accumulate all deliveries for a full match into a single `execute_batch` call (MEDIUM impact)**

`save_all_deliveries()` (line 334) already iterates innings but calls `save_deliveries()` per inning - each issues its own `execute_batch`. Flatten this to a single call:
```python
def save_all_deliveries(self, match_id, sim_match, team_id_map):
    all_rows = []
    for inning in sim_match.innings:
        all_rows.extend(self._build_delivery_rows(match_id, inning, team_id_map))
    psycopg2.extras.execute_batch(self.cur, INSERT_SQL, all_rows, page_size=1000)
```
This halves the number of `execute_batch` calls and allows a larger `page_size`.

**R10 – Use `execute_values` instead of `execute_batch` for deliveries (LOW-MEDIUM impact)**

`psycopg2.extras.execute_values` generates a single multi-row `INSERT ... VALUES (row1), (row2), ...` statement rather than individual prepared statements. For 480 rows this significantly reduces server parse/plan overhead. The `page_size` parameter controls how many rows are combined per statement.

```python
psycopg2.extras.execute_values(
    self.cur,
    "INSERT INTO simulation.deliveries (...) VALUES %s",
    all_rows,
    page_size=1000,
)
```

**R11 – Batch-persist all 94 matches in a single transaction (LOW additional impact)**

If the tournament persist currently commits after each match (calling `SimulationRepository.commit()` per match), reducing to a single commit at the end of the tournament would eliminate ~93 extra network round-trips. Check whether the caller of `save_deliveries` commits once per match or once per tournament. If per-match, deferring to per-tournament saves ~90 round-trips at the cost of a longer open transaction window.

---

## Priority Ranking

| Rank | ID  | Area                     | Location                                    | Estimated Impact |
|------|-----|--------------------------|---------------------------------------------|-----------------|
| 1    | R5  | Pressure delivery scans  | `strategy.py:891,907`                       | HIGH             |
| 2    | R1  | Venue probs cache miss   | `strategy.py:1237` / `_get_player_venue_probs` | HIGH          |
| 3    | R2  | Phase probs cache miss   | `strategy.py:1040` / `_compute_phase_probs` | HIGH             |
| 4    | R3  | `_apply_category_relevance` per key | `strategy.py:1066`             | HIGH             |
| 5    | R4  | `list(baseline.keys())` per ball | `strategy.py:1052,1281-1282`     | MEDIUM           |
| 6    | B1  | MatchRules calls in observers | `inning_player.py:58,68,88,90`         | MEDIUM           |
| 7    | B4  | All 22 observers per ball | `events.py:36-37`                          | MEDIUM           |
| 8    | R6  | Per-ball `log.info` string build | `strategy.py:1309-1350`           | MEDIUM           |
| 9    | 5a  | `_outcome_category` in loop | `strategy.py:1066` (via _apply_category_relevance) | MEDIUM  |
| 10   | R9  | DB: 188 execute_batch calls | `simulation_repository.py:311`           | MEDIUM           |
| 11   | R10 | DB: execute_values vs execute_batch | `simulation_repository.py:311`  | LOW-MEDIUM       |
| 12   | R7  | Spell-scan in Test bowling | `base.py:595-618`                         | MEDIUM (Test)    |
| 13   | 6c  | Over-summary delivery scan | `formatters.py:81`                        | LOW              |
| 14   | 6a  | wicket_keeper O(n) scan  | `inning_team.py:83`                         | LOW              |
| 15   | R8  | Phase-pacing memoize     | `base.py:413-460`                           | LOW              |
| 16   | B2  | Delivery dataclass alloc | `innings_simulator.py:183-197`              | LOW              |

### Quick wins (low effort, meaningful combined saving)

The following require only 1–3 line changes each:

1. **Store `self._ordered_keys` at `init_model()` time** (`strategy.py:1052`) - eliminates one O(n) list allocation per ball.
2. **Store `self._wicket_keeper` at `from_match_team()` time** (`inning_team.py:83`).
3. **Precompute `self._outcome_category_map`** at init time and use it in the inner loop.
4. **Pass `is_legal` and `is_death` in `MatchEvent.data`** from `_publish_ball_event()` - eliminates 4 static-method calls per observer per ball (88 calls/ball eliminated).
5. **Guard `log.info` per-ball call** with `if log.isEnabledFor(logging.INFO):` and move string formatting inside.

### High-effort, highest-return changes

- **Replace delivery scans in `_compute_pressure()` with O(1) counters on `InningTeam`** - eliminates two growing-list scans called on every single ball. At ball 120 of innings 2, each scan is ~120 iterations; the problem grows quadratically across the innings.
- **Cache `_get_player_venue_probs()` and `_compute_phase_probs()` results per ball context** - the venue-prob blending (set unions + dict comprehensions) is currently O(n_keys) on every ball despite being stable for 6 consecutive balls (same batter, same over, same bowler).
- **Precompute 5 `_apply_category_relevance` dicts once per ball** - eliminates 40 dict creations per ball.
