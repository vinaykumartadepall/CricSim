---
name: cricsim-dev
description: Cricket Simulator contributor runbook - environment setup, every common command (tests, dev servers, migrations, DB scripts, CLI simulation), and the project's standing engineering conventions. Use this whenever working in this repo - onboarding, running/debugging something locally, adding a migration, or before opening a PR.
---

# Cricket Simulator - contributor runbook

This skill is the practical, executable companion to `CLAUDE.md` (always-loaded
project rules) and `README.md` (feature/architecture overview) at the repo root.
Read those first for *why* things are the way they are; this file is *how to
actually run things* plus a condensed checklist. If any command below stops
matching reality, fix the drift here in the same change - see the "keep this
skill honest" note at the bottom.

## 1. One-time environment setup

```bash
conda create -n cricsim python=3.11   # if the env doesn't exist yet
conda activate cricsim
pip install -r requirements.txt
pip install -r requirements-dev.txt   # pytest + plotting/dev tools
```

**Never `pip install` outside the `cricsim` conda env, and never `sudo pip`.**
After installing a new package, add it to `requirements.txt` (runtime) or
`requirements-dev.txt` (dev/test-only), unpinned unless a version is required.

Copy `.env` locally (not committed) with at least:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` (or `DB_NAME`/`DB_USER`/`DB_PASS`/`DB_HOST`/`DB_PORT`) | Main app DB connection |
| `SUPABASE_URL` | Verifies sign-in JWTs via JWKS |
| `ADMIN_USER_IDS` | Comma-separated Supabase user UUIDs allowed to hit `/admin/*` (unset = nobody, fail closed) |
| `SUPABASE_DATABASE_URL` | Only needed for the one-time `db/copy_profiles_to_identity_links.py` script (legacy Supabase `profiles` table) |

`.env` is **not** auto-loaded by standalone scripts (`python -m db.<script>`) -
only `api/main.py` calls `load_dotenv()`. Before running a bare script:

```bash
set -a && source .env && set +a
```

Frontend: `cd frontend && npm install && cp .env.example .env.local` (fill in
`VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY`).

## 2. Running the app

```bash
uvicorn api.main:app --reload --port 8000     # backend, docs at /docs
cd frontend && npm run dev                     # frontend, http://localhost:5173
```

```bash
cd frontend && npm run build                   # production build → frontend/dist
cd frontend && npm run lint
```

## 3. Database setup / data ops

```bash
python setup_db.py                              # full one-shot: schema, ingest, precompute, enrich
python setup_db.py --skip-download              # skip re-downloading the Cricsheet archive
python setup_db.py --only-precompute            # only refresh precomputed tables
python setup_db.py --only-precompute --current-year-only   # fast incremental refresh
python setup_db.py --skip-enrich                # skip ESPN player enrichment (~1hr)
python setup_db.py --dry-run                    # print the plan, no writes
```

All steps are idempotent - safe to re-run.

**Applying a migration** (`db/migrations/NNN_*.sql`) - there's no runner script,
apply directly:

```bash
psql "$DATABASE_URL" -f db/migrations/031_identity_links.sql
```

Whoever owns prod applies migrations there manually - don't assume a migration
you wrote locally is live anywhere else. **Every migration that touches the
main app DB must also be reflected in `db/schema.sql` in the same change**
(CLAUDE.md Critical Rule #4) - `schema.sql` is what a fresh `initialize_schema()`
run creates, and it silently drifted out of sync twice (migrations 030 and 031)
before this rule was written down. `simulation.profiles` is the one exception -
it lived only in Supabase, never in `schema.sql`, and is now fully retired.

**One-off/utility scripts** (`db/*.py`, run as `python -m db.<name>`):

| Script | Purpose |
|--------|---------|
| `dedup_venues` | Merge duplicate venue rows (dry run by default, `--commit` to apply) |
| `populate_venue_countries` | Geocode `history.venues.country_id`, then apply manual overrides |
| `enrich_players` | Backfill ESPN/cricinfo player data (two-pass, slow) |
| `seed_sim_configs` | Build `simulation.tournament_seeded.config` for simulation-ready tournaments |
| `replay_admin_edits` | `--export FILE` / `--apply FILE` - sync the admin edit log between DBs |
| `copy_profiles_to_identity_links` | One-time: copy legacy Supabase `profiles` into `simulation.identity_links` (dry run by default, `--commit` to apply; needs `SUPABASE_DATABASE_URL` set to the real Supabase DB) |
| `diagnose_legacy_identity_gaps` | Read-only report on stale ids left by the old (pre-identity_links) sign-in migration bug - does not repair anything, see its docstring for why |
| `reset_db` | Drop and recreate the local DB from scratch |

```bash
python -m tools.check_db                        # verify DB connectivity + stat loading
```

## 4. Running a simulation (CLI, no API needed)

```bash
python run_match.py --config match_config.json
python run_tournament.py --config tournament_config.json --seed 42
```

See `README.md` for the config JSON shape, strategy options
(`ball_outcome_strategy`, `bowling_strategy`), playoff formats, and schedule
types.

## 5. Tests

```bash
pytest tests/                                   # all tests
pytest tests/ -q
pytest tests/ -k "logger or identity"           # filter by name
```

All tests must pass **without a live DB connection** - bypass it at the class
level:

```python
repo = StatsRepository.__new__(StatsRepository)
repo.conn = None
```

or patch a class-level singleton connection directly (see any `test_*_repository.py`
file for the pattern). One test file per module area (`test_<module>.py`),
`class Test<Feature>:`, `def test_<what_it_checks>(self):`.

## 6. Before you consider a change done

The actual rules (and the reasoning/precedents behind each) live in `CLAUDE.md`
at the repo root under **Critical Rules** and **Log system** - it's
always-loaded for every Claude Code session in this repo, so re-stating it
here would just create a second copy that can drift out of sync (the exact
failure mode `schema.sql` had - see §3). Read it there, not here.

## Keep this skill honest

If a command here stops working, or a new recurring workflow shows up that
isn't documented, fix this file in the same commit - don't let it become
another `schema.sql`-style drift.
