"""
Populate history.venues.country from city/venue name via Nominatim geocoding,
then apply manual overrides from venue_country_overrides.json.

Usage:
    python -m db.populate_venue_countries           # dry run (no DB writes)
    python -m db.populate_venue_countries --commit  # write to DB

Steps:
  1. Adds country column to history.venues if absent.
  2. Loads ALL venues; geocodes those with a NULL country (1 req/s rate limit).
  3. Applies overrides from venue_country_overrides.json to every venue
     (overrides always win, even over a previously geocoded value).
     Priority: by_venue_id > by_name_pattern > by_city.
  4. Prints a diff of changes; if --commit, bulk-updates the DB.
  5. Prints any rows that remain unresolved for manual review.
"""

import argparse
import json
import re
import time
from pathlib import Path
from typing import Optional
from geopy.geocoders import Nominatim

from db.database import get_db_connection

_OVERRIDES_PATH = Path(__file__).parent / "venue_country_overrides.json"

_VENUE_NOISE = re.compile(
    r"\b(cricket|ground|stadium|oval|park|field|international|club|"
    r"academy|sports|complex|centre|center|arena|pavilion|"
    r"no\.?\s*\d+|'[a-z]')\b",
    re.IGNORECASE,
)


def _load_overrides() -> dict:
    with open(_OVERRIDES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _guess_city_from_name(venue_name: str) -> str:
    if "," in venue_name:
        return venue_name.split(",")[-1].strip()
    cleaned = _VENUE_NOISE.sub("", venue_name).strip(" ,.-")
    return cleaned or venue_name


def _geocode(geolocator, query: str) -> Optional[str]:
    for attempt in range(3):
        try:
            time.sleep(1.1)  # Nominatim requires ≥1 s between requests
            result = geolocator.geocode(query, language="en", addressdetails=True, timeout=10)
            if result:
                addr = result.raw.get("address", {})
                return addr.get("country") or None
            return None
        except Exception as exc:
            wait = 5 * (attempt + 1)
            print(f"    [retry {attempt+1}/3 in {wait}s] {query!r}: {exc}")
            time.sleep(wait)
    return None


def _apply_override(vid: int, name: str, city: Optional[str], overrides: dict) -> Optional[str]:
    """Return the override country for this venue, or None if no override applies."""
    # Most specific: exact venue_id
    entry = overrides["by_venue_id"].get(str(vid))
    if entry:
        return entry["country"]

    # Name pattern match (city must match too when specified)
    name_lower = name.lower()
    city_lower = (city or "").lower()
    for pat in overrides["by_name_pattern"]:
        if pat["city"].lower() == city_lower and pat["name_contains"].lower() in name_lower:
            return pat["country"]

    # Least specific: city-level
    if city and city in overrides["by_city"]:
        return overrides["by_city"][city]

    return None


def run(commit: bool) -> None:
    overrides = _load_overrides()
    conn = get_db_connection(autocommit=False)
    cur = conn.cursor()

    # ── 1. Add column if missing ────────────────────────────────────────────
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'history' AND table_name = 'venues'
          AND column_name = 'country'
    """)
    if not cur.fetchone():
        print("Adding country column to history.venues …")
        cur.execute("ALTER TABLE history.venues ADD COLUMN country TEXT")
        conn.commit()

    # ── 2. Load ALL venues ──────────────────────────────────────────────────
    cur.execute("""
        SELECT venue_id, name, city, country
        FROM history.venues
        ORDER BY city NULLS LAST, name
    """)
    all_venues = cur.fetchall()  # (venue_id, name, city, current_country)
    print(f"Loaded {len(all_venues)} venues.\n")

    # ── 3. Geocode venues that still have NULL country ───────────────────────
    geolocator = Nominatim(user_agent="cricket-simulator-venue-filler/1.0")

    null_venues = [(vid, name, city) for vid, name, city, cc in all_venues if not cc]
    geocoded: dict[int, Optional[str]] = {}   # venue_id → geocoded country

    if null_venues:
        distinct_cities: list[str] = sorted({city for _, _, city in null_venues if city})
        city_to_country: dict[str, Optional[str]] = {}

        print(f"Geocoding {len(distinct_cities)} distinct cities for {len(null_venues)} NULL-country venues …")
        for i, city in enumerate(distinct_cities, 1):
            country = _geocode(geolocator, city)
            city_to_country[city] = country
            print(f"  [{i:>3}/{len(distinct_cities)}]  {city:<35}  →  {country or 'NOT FOUND'}")

        null_city_venues = [(vid, name) for vid, name, city in null_venues if not city]
        if null_city_venues:
            print(f"\nGeocoding {len(null_city_venues)} NULL-city venues by name …")
            for i, (vid, name) in enumerate(null_city_venues, 1):
                guess = _guess_city_from_name(name)
                country = _geocode(geolocator, guess)
                if not country and guess != name:
                    country = _geocode(geolocator, name)
                geocoded[vid] = country
                print(f"  [{i:>3}/{len(null_city_venues)}]  {name:<50}  →  {country or 'NOT FOUND'}")

        for vid, name, city in null_venues:
            if vid not in geocoded:
                geocoded[vid] = city_to_country.get(city) if city else None
    else:
        print("No NULL-country venues — skipping geocoding.\n")

    # ── 4. Determine final country for every venue ───────────────────────────
    updates: list[tuple[str, int]] = []
    unresolved: list[tuple] = []

    print("\n" + "=" * 85)
    print(f"{'venue_id':>9}  {'city':<25}  {'country':<22}  {'source':<12}  name")
    print("-" * 85)

    for vid, name, city, current_country in all_venues:
        base = current_country or geocoded.get(vid)
        override = _apply_override(vid, name, city, overrides)
        final = override or base

        if final:
            source = "override" if override else ("geocoded" if not current_country else "existing")
            if final != current_country:
                updates.append((final, vid))
                marker = "*" if override else "+"
            else:
                marker = " "
            print(f"{marker} {vid:>7}  {str(city):<25}  {final:<22}  {source:<12}  {name}")
        else:
            unresolved.append((vid, name, city))
            print(f"? {vid:>7}  {str(city):<25}  {'*** UNRESOLVED ***':<22}  {'':12}  {name}")

    print("=" * 85)
    print(f"\nChanges: {len(updates)}  (legend: * = override applied, + = newly geocoded)")
    print(f"Unresolved: {len(unresolved)}")

    # ── 5. Write or report ───────────────────────────────────────────────────
    if not commit:
        print("\n[DRY RUN] No changes written. Re-run with --commit to apply.")
    else:
        if updates:
            print(f"\nWriting {len(updates)} updates …")
            cur.executemany(
                "UPDATE history.venues SET country = %s WHERE venue_id = %s",
                updates,
            )
            conn.commit()
            print("Done.")
        else:
            print("\nNothing to update.")

    if unresolved:
        print("\nVenues still needing a country — add to venue_country_overrides.json by_venue_id:")
        for vid, name, city in unresolved:
            print(f'  "{vid}": {{"country": "...", "note": "{name} / city={city}"}}')

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Populate history.venues.country")
    parser.add_argument("--commit", action="store_true", help="Write to DB (default: dry run)")
    args = parser.parse_args()
    run(commit=args.commit)
