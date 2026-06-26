# Cricket Simulator — Key Commands

All commands run from the repo root: `/Users/vnaykumart/vinay/cricket-simulator`

---

## Database Setup & Ingestion

### 1. Create schema (first time or after reset)
```bash
python -c "from db.database import get_db_connection; conn = get_db_connection(); conn.cursor().execute(open('db/schema.sql').read()); conn.commit()"
```
Or apply schema directly via psql:
```bash
psql -d <your_db> -f db/schema.sql
```

### 2. Ingest all data from `data/all_json/`
```bash
python -m db.ingest_data
```
Skips already-ingested matches (checkpoint by `original_id`).

### 3. Ingest with a file limit (for testing)
```bash
python -m db.ingest_data --limit 100
```

### 4. Reset database (DROP schemas — destructive!)
```bash
python -m db.reset_db
```
Drops `history` and `simulation` schemas with CASCADE.

### 5. Populate venue countries (geocoding + manual overrides)
```bash
python -m db.populate_venue_countries            # dry run
python -m db.populate_venue_countries --commit   # write to DB
```

---

## Running Simulations

### Run a single match
```bash
python run_match.py --config match_config.json
python run_match.py --config match_config.json --silent
```

### Run a tournament
```bash
python run_tournament.py --config tournament_config.json
python run_tournament.py --config tournament_config.json --seed 42
python run_tournament.py --config tournament_config.json --seed 42 --silent
```

### Run IPL tournament
```bash
python run_tournament.py --config ipl_config.json
```

---

## Validation & Analysis

### Run comprehensive model validation (T20 / ODI / Test)
```bash
python run_comprehensive_validation_v2.py
```

### Validate bowling selection accuracy against historical data
```bash
python -m tools.validate_bowling_selection --format Test --n 30
python -m tools.validate_bowling_selection --format T20  --n 50
python -m tools.validate_bowling_selection --format ODI  --n 50 --gender female
```

### Check DB stats are loading correctly
```bash
python -m tools.check_db
```

### Optimize strategy parameters
```bash
python -m tools.optimize_params
```

### Plot simulation scores
```bash
python -m tools.plot_sim_scores
```

### Plot bowling scores
```bash
python -m tools.plot_bowling_scores
```

---

## Tests

### Run all tests
```bash
python -m pytest tests/
```

### Run a specific test file
```bash
python -m pytest tests/test_bowling_eligibility.py
python -m pytest tests/test_super_over_selector.py
python -m pytest tests/test_historical_bowling_order.py
```
