"""
Populate history.venues.country_id from city/venue name via Nominatim geocoding,
then apply manual overrides from venue_country_overrides.json.

Usage:
    python -m db.populate_venue_countries           # dry run (no DB writes)
    python -m db.populate_venue_countries --commit  # write to DB

Steps:
  1. Ensures country_id column exists on history.venues.
  2. Loads ALL venues; geocodes those with NULL country_id (1 req/s rate limit).
  3. Applies overrides from venue_country_overrides.json to every venue
     (overrides always win, even over a previously resolved value).
     Priority: by_name_city > by_name_pattern > by_city.
  4. Remaps West Indies member countries to "West Indies".
  5. Prints a diff of changes; if --commit, bulk-updates the DB.
  6. Prints any rows that remain unresolved for manual review.
"""

import argparse
import re
import time
from typing import Optional
from geopy.geocoders import Nominatim

from db.database import get_db_connection
from db.venue_resolver import load_overrides, resolve_final_country, invalidate_cache

_VENUE_NOISE = re.compile(
    r"\b(cricket|ground|stadium|oval|park|field|international|club|"
    r"academy|sports|complex|centre|center|arena|pavilion|"
    r"no\.?\s*\d+|'[a-z]')\b",
    re.IGNORECASE,
)


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


def _load_or_insert_country(cur, name: str, name_to_id: dict[str, int]) -> int:
    """Return country_id for name, inserting a new row if it doesn't exist yet."""
    if name in name_to_id:
        return name_to_id[name]
    cur.execute(
        "INSERT INTO history.countries (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING country_id",
        (name,),
    )
    row = cur.fetchone()
    if row:
        country_id = row[0]
    else:
        cur.execute("SELECT country_id FROM history.countries WHERE name = %s", (name,))
        country_id = cur.fetchone()[0]
    name_to_id[name] = country_id
    return country_id


def run(commit: bool) -> None:
    invalidate_cache()
    overrides = load_overrides()
    conn = get_db_connection(autocommit=False)
    cur  = conn.cursor()

    # ── 1. Ensure country_id column exists ──────────────────────────────────
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'history' AND table_name = 'venues'
          AND column_name = 'country_id'
    """)
    if not cur.fetchone():
        print("Adding country_id column to history.venues …")
        cur.execute(
            "ALTER TABLE history.venues "
            "ADD COLUMN country_id INT REFERENCES history.countries(country_id)"
        )
        conn.commit()

    # ── 2. Load countries name→id mapping ───────────────────────────────────
    cur.execute("SELECT name, country_id FROM history.countries")
    name_to_id: dict[str, int] = {row[0]: row[1] for row in cur.fetchall()}

    # ── 3. Load ALL venues — current country name via join ───────────────────
    cur.execute("""
        SELECT v.venue_id, v.name, v.city,
               c.name AS current_country
        FROM   history.venues v
        LEFT JOIN history.countries c ON c.country_id = v.country_id
        ORDER  BY v.city NULLS LAST, v.name
    """)
    all_venues = cur.fetchall()  # (venue_id, name, city, current_country)
    print(f"Loaded {len(all_venues)} venues.\n")

    # ── 4. Geocode venues that still have NULL country_id ───────────────────
    geolocator = Nominatim(user_agent="cricket-simulator-venue-filler/1.0")

    null_venues = [(vid, name, city) for vid, name, city, cc in all_venues if not cc]
    geocoded: dict[int, Optional[str]] = {}

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

    # ── 5. Determine final country for every venue ───────────────────────────
    updates: list[tuple[str, int]] = []   # (resolved_country_name, venue_id)
    unresolved: list[tuple] = []

    print("\n" + "=" * 85)
    print(f"{'venue_id':>9}  {'city':<25}  {'country':<22}  {'source':<12}  name")
    print("-" * 85)

    for vid, name, city, current_country in all_venues:
        geocoded_country = geocoded.get(vid) if not current_country else None
        final = resolve_final_country(name, city, overrides, geocoded_country=geocoded_country or current_country)

        if final:
            had_override = final != (geocoded_country or current_country)
            source = "override" if had_override else ("geocoded" if not current_country else "existing")
            if final != current_country:
                updates.append((final, vid))
                marker = "*" if had_override else "+"
            else:
                marker = " "
            print(f"{marker} {vid:>7}  {str(city):<25}  {final:<22}  {source:<12}  {name}")
        else:
            unresolved.append((vid, name, city))
            print(f"? {vid:>7}  {str(city):<25}  {'*** UNRESOLVED ***':<22}  {'':12}  {name}")

    print("=" * 85)
    print(f"\nChanges: {len(updates)}  (legend: * = override applied, + = newly geocoded)")
    print(f"Unresolved: {len(unresolved)}")

    # ── 6. Write or report ───────────────────────────────────────────────────
    if not commit:
        print("\n[DRY RUN] No changes written. Re-run with --commit to apply.")
    else:
        if updates:
            print(f"\nWriting {len(updates)} updates …")
            for country_name, vid in updates:
                cid = _load_or_insert_country(cur, country_name, name_to_id)
                cur.execute(
                    "UPDATE history.venues SET country_id = %s WHERE venue_id = %s",
                    (cid, vid),
                )
            conn.commit()
            print("Done.")
        else:
            print("\nNothing to update.")

    if unresolved:
        print("\nVenues still needing a country — add to venue_country_overrides.json by_name_city:")
        for vid, name, city in unresolved:
            city_fragment = f', "city": "{city}"' if city else ""
            print(f'  {{"name": "{name}"{city_fragment}, "country": "..."}}  // venue_id={vid}')

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Populate history.venues.country_id")
    parser.add_argument("--commit", action="store_true", help="Write to DB (default: dry run)")
    args = parser.parse_args()
    run(commit=args.commit)
