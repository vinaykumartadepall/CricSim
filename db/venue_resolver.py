"""
Shared venue resolution logic used by:
  - db/repository.py            - applied at venue INSERT time during ingestion
  - db/populate_venue_countries.py - batch geocoding + override pass
  - db/dedup_venues.py          - merges existing duplicate venue rows

Two concerns are handled here:

1. Canonical name normalisation
   The same physical ground often appears in Cricsheet data under slightly
   different name strings.  canonical_names in the JSON defines explicit alias
   groups; any alias is rewritten to the canonical name before the DB lookup
   so no duplicate venue rows are ever created.

2. Country resolution
   Three-tier lookup (most specific wins):
     by_name_city    - exact case-insensitive name, optional city
     by_name_pattern - city match + name substring
     by_city         - exact city name
   Then west_indies_countries remaps WI member nations → "West Indies".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_OVERRIDES_PATH = Path(__file__).parent / "venue_country_overrides.json"

_overrides_cache: Optional[dict] = None


def load_overrides(path: Path = _OVERRIDES_PATH) -> dict:
    """Load venue_country_overrides.json (file-level cache after first call)."""
    global _overrides_cache
    if _overrides_cache is None:
        with open(path, encoding="utf-8") as f:
            _overrides_cache = json.load(f)
    return _overrides_cache


def invalidate_cache() -> None:
    """Force a fresh reload on the next load_overrides() call (useful in tests)."""
    global _overrides_cache
    _overrides_cache = None


# ── Canonical name resolution ──────────────────────────────────────────────────

def resolve_canonical(
    name: str, city: Optional[str], overrides: dict
) -> tuple[str, Optional[str], Optional[str]]:
    """
    If `name` (or `city`-qualified name) matches any alias in canonical_names,
    return (canonical_name, canonical_city, canonical_country).
    Otherwise return (name, city, None) unchanged.

    Matching is exact and case-insensitive on the name string.
    The incoming city is ignored when checking alias membership - the alias list
    already encodes which name variants belong to the same ground.
    """
    name_lower = name.lower().strip()
    for entry in overrides.get("canonical_names", []):
        canonical = entry["canonical"]
        # Check canonical itself and all aliases
        all_names = [canonical] + entry.get("aliases", [])
        if any(n.lower().strip() == name_lower for n in all_names):
            return (
                canonical,
                entry.get("city") or city,
                entry.get("country"),
            )
    return name, city, None


def all_canonical_groups(overrides: dict) -> list[dict]:
    """Return all canonical_names entries as-is (convenience accessor)."""
    return overrides.get("canonical_names", [])


# ── Country resolution ─────────────────────────────────────────────────────────

def resolve_country(name: str, city: Optional[str], overrides: dict) -> Optional[str]:
    """
    Three-tier country lookup. Returns the raw country string or None.

    Tier 1 - by_name_city (highest):
      Exact case-insensitive name match; city must also match when specified in
      the entry.  City-less entries match any city.

    Tier 2 - by_name_pattern:
      Both city (exact) and name_contains (substring) must match.

    Tier 3 - by_city (lowest):
      Exact city string match.
    """
    name_lower = name.lower().strip()
    city_lower = (city or "").lower().strip()

    for entry in overrides.get("by_name_city", []):
        entry_name = entry["name"].lower().strip()
        entry_city = (entry.get("city") or "").lower().strip()
        if name_lower == entry_name:
            if not entry_city or city_lower == entry_city:
                return entry["country"]

    for pat in overrides.get("by_name_pattern", []):
        if pat["city"].lower() == city_lower and pat["name_contains"].lower() in name_lower:
            return pat["country"]

    if city and city in overrides.get("by_city", {}):
        return overrides["by_city"][city]

    return None


def apply_west_indies_mapping(country: Optional[str], overrides: dict) -> Optional[str]:
    """Remap any WI member nation to the canonical 'West Indies' string."""
    if not country:
        return country
    wi_set = set(overrides.get("west_indies_countries", []))
    return "West Indies" if country in wi_set else country


def resolve_final_country(
    name: str,
    city: Optional[str],
    overrides: dict,
    geocoded_country: Optional[str] = None,
) -> Optional[str]:
    """
    Full pipeline: canonical country → override → geocoded fallback → WI mapping.

    Priority:
      1. canonical_names[].country (if this name belongs to a canonical group
         that specifies a country - avoids needing a duplicate by_name_city entry)
      2. by_name_city / by_name_pattern / by_city
      3. geocoded_country (Nominatim result, passed in from populate_venue_countries)

    West Indies remapping applied last.
    """
    # Check if this name is part of a canonical group that has a country set
    _, _, canonical_country = resolve_canonical(name, city, overrides)

    override = canonical_country or resolve_country(name, city, overrides)
    raw = override or geocoded_country
    return apply_west_indies_mapping(raw, overrides)
