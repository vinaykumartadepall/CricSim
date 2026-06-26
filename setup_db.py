"""
Database setup script — download, ingest, and precompute from scratch.

Steps:
  1. Create DB and initialise schema (idempotent).
  2. Download latest Cricsheet ball-by-ball JSON archive.
  3. Unzip into data/all_json/ (skips files already present).
  4. Ingest un-ingested matches into the DB.
  5. Deduplicate venue rows.
  6. Populate venue countries (geocode + manual overrides).
  7. Populate precomputed tables (history.global_yearly_baseline).
  8. Enrich players from ESPN (cricinfo_id via people.csv, then API for names/roles).
     Pass 2 (ESPN API) takes ~1 hour; use --skip-enrich to skip it.

Usage:
    # Full setup from scratch:
    python setup_db.py

    # Skip download if you already have the data locally:
    python setup_db.py --skip-download

    # Only refresh precomputed tables (e.g. after new ingestion):
    python setup_db.py --only-precompute

    # Refresh only the current year in the precomputed table (fast incremental):
    python setup_db.py --only-precompute --current-year-only

    # Skip the ESPN enrichment step (Pass 1 still runs; Pass 2 is slow):
    python setup_db.py --skip-enrich

    # Skip Pass 2 only (assign cricinfo_ids but don't hit ESPN API):
    python setup_db.py --skip-enrich-api

    # Dry run — print what would happen without writing to DB:
    python setup_db.py --dry-run
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

CRICSHEET_URL = "https://cricsheet.org/downloads/all_json.zip"
DATA_DIR      = Path("data/all_json")
ZIP_PATH      = Path("data/all_json.zip")


def _header(msg: str) -> None:
    print(f"\n{'─'*60}\n  {msg}\n{'─'*60}")


class DatabaseSetupFacade:
    """Facade over the individual DB setup steps."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def create_schema(self) -> None:
        _header("Step 1 — Create DB and initialise schema")
        if self.dry_run:
            print("  [dry-run] would call db.database.create_database() + initialize_schema()")
            return
        from db.database import create_database, initialize_schema
        create_database()
        initialize_schema()

    def download(self) -> None:
        _header("Step 2 — Download Cricsheet archive")
        ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
        if self.dry_run:
            print(f"  [dry-run] would download {CRICSHEET_URL} → {ZIP_PATH}")
            return

        print(f"  Downloading {CRICSHEET_URL} ...")
        t0 = time.perf_counter()

        def _progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                pct = min(100, downloaded * 100 // total_size)
                mb  = downloaded / 1_048_576
                print(f"\r  {pct:3d}%  {mb:.1f} MB", end="", flush=True)

        urllib.request.urlretrieve(CRICSHEET_URL, ZIP_PATH, reporthook=_progress)
        elapsed = time.perf_counter() - t0
        size_mb = ZIP_PATH.stat().st_size / 1_048_576
        print(f"\n  Downloaded {size_mb:.1f} MB in {elapsed:.1f}s")

    def unzip(self) -> None:
        _header("Step 3 — Unzip archive")
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        if not ZIP_PATH.exists():
            print(f"  {ZIP_PATH} not found — skipping unzip")
            return

        if self.dry_run:
            with zipfile.ZipFile(ZIP_PATH) as zf:
                total = len(zf.namelist())
            print(f"  [dry-run] would extract {total} files from {ZIP_PATH} → {DATA_DIR}")
            return

        existing = set(p.name for p in DATA_DIR.glob("*.json"))
        print(f"  Extracting new files from {ZIP_PATH} → {DATA_DIR} ...")
        new_count = 0
        with zipfile.ZipFile(ZIP_PATH) as zf:
            members = [m for m in zf.namelist() if m.endswith(".json")]
            for member in members:
                fname = Path(member).name
                if fname not in existing:
                    zf.extract(member, DATA_DIR.parent if "/" in member else DATA_DIR)
                    new_count += 1
        print(f"  Extracted {new_count} new files ({len(members) - new_count} already present)")

    def ingest(self) -> None:
        _header("Step 4 — Ingest un-ingested matches")
        if not DATA_DIR.exists():
            print(f"  {DATA_DIR} not found — skipping ingestion")
            return

        json_files = list(DATA_DIR.glob("*.json"))
        print(f"  Found {len(json_files)} JSON files in {DATA_DIR}")

        if self.dry_run:
            print("  [dry-run] would call db.ingest_data.ingest_data() — skipped")
            return

        from db.ingest_data import ingest_data
        ingest_data()

    def dedup_venues(self) -> None:
        _header("Step 5 — Deduplicate venue rows")
        from db.dedup_venues import run as dedup_run
        dedup_run(commit=not self.dry_run)

    def populate_venue_countries(self) -> None:
        _header("Step 6 — Populate venue countries")
        cmd = [sys.executable, "-m", "db.populate_venue_countries"]
        if not self.dry_run:
            cmd.append("--commit")
        print(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(Path(__file__).parent))
        if result.returncode != 0:
            print("  Warning: venue country population exited with non-zero status — check output above.")

    def precompute(self, current_year_only: bool = False) -> None:
        _header("Step 7 — Populate precomputed tables")
        from db.precompute import populate_global_yearly_baseline
        populate_global_yearly_baseline(
            current_year_only=current_year_only,
            dry_run=self.dry_run,
        )

    def enrich_players(self, skip_api: bool = False) -> None:
        _header("Step 8 — Enrich players from ESPN")
        cmd_base = [sys.executable, "-m", "db.enrich_players"]
        if not self.dry_run:
            cmd_base.append("--commit")

        # Pass 1: assign cricinfo_id from people.csv (fast, always run)
        cmd1 = cmd_base + ["--pass1-only"]
        print(f"  Running: {' '.join(cmd1)}")
        result = subprocess.run(cmd1, cwd=str(Path(__file__).parent))
        if result.returncode != 0:
            print("  Warning: Pass 1 exited with non-zero status — check output above.")

        if skip_api:
            print("  Pass 2 (ESPN API) skipped via --skip-enrich-api.")
            return

        # Pass 2: fetch display_name / styles / role / country from ESPN API (~1 hour)
        cmd2 = cmd_base + ["--pass2-only"]
        print(f"  Running: {' '.join(cmd2)}")
        result = subprocess.run(cmd2, cwd=str(Path(__file__).parent))
        if result.returncode != 0:
            print("  Warning: Pass 2 exited with non-zero status — check output above.")

    def full_setup(
        self,
        skip_download: bool = False,
        current_year_only: bool = False,
        skip_enrich: bool = False,
        skip_enrich_api: bool = False,
    ) -> None:
        self.create_schema()
        if not skip_download:
            self.download()
            self.unzip()
        self.ingest()
        self.dedup_venues()
        self.populate_venue_countries()
        self.precompute(current_year_only=current_year_only)
        if not skip_enrich:
            self.enrich_players(skip_api=skip_enrich_api)
        else:
            print("\n  Skipping player enrichment (--skip-enrich).")
        _header("Setup complete")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up the cricket simulator DB from scratch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--skip-download",     action="store_true",
                        help="Skip downloading the Cricsheet archive (data already present).")
    parser.add_argument("--only-precompute",   action="store_true",
                        help="Only run the precompute step (skip download/ingest/venues).")
    parser.add_argument("--current-year-only", action="store_true",
                        help="In the precompute step, refresh only the current calendar year.")
    parser.add_argument("--skip-enrich",       action="store_true",
                        help="Skip all player enrichment (Step 8).")
    parser.add_argument("--skip-enrich-api",   action="store_true",
                        help="Skip Pass 2 of enrichment (ESPN API calls); still assigns cricinfo_ids.")
    parser.add_argument("--only-enrich",       action="store_true",
                        help="Only run player enrichment (Step 8).")
    parser.add_argument("--dry-run",           action="store_true",
                        help="Print what would happen without writing to the DB.")
    args = parser.parse_args()

    facade = DatabaseSetupFacade(dry_run=args.dry_run)

    if args.only_precompute:
        facade.precompute(current_year_only=args.current_year_only)
    elif args.only_enrich:
        facade.enrich_players(skip_api=args.skip_enrich_api)
    else:
        facade.full_setup(
            skip_download=args.skip_download,
            current_year_only=args.current_year_only,
            skip_enrich=args.skip_enrich,
            skip_enrich_api=args.skip_enrich_api,
        )


if __name__ == "__main__":
    main()
