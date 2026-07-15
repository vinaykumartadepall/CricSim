"""
Neutral international venues used for multiplayer rooms.

Multiplayer teams are freely drafted (no real home city), so matches are
played across a fixed, curated pool of well-known international grounds per
format. Names must match history.venues exactly so venue context stats apply.
"""

from __future__ import annotations

_INTERNATIONAL_VENUES: dict[str, list[str]] = {
    "T20": [
        "Melbourne Cricket Ground",
        "Sydney Cricket Ground",
        "Sher-e-Bangla National Cricket Stadium",
        "Sylhet International Cricket Stadium",
        "Wankhede Stadium",
        "Eden Gardens",
        "Eden Park",
        "Sky Stadium",
        "Gaddafi Stadium",
        "National Stadium, Karachi",
        "The Wanderers Stadium",
        "Newlands",
        "R Premadasa Stadium",
        "Pallekele International Cricket Stadium",
        "Daren Sammy National Cricket Stadium",
        "Kensington Oval",
    ],
    "ODI": [
        "Sydney Cricket Ground",
        "Melbourne Cricket Ground",
        "Sher-e-Bangla National Cricket Stadium",
        "Zahur Ahmed Chowdhury Stadium, Chattogram",
        "Narendra Modi Stadium",
        "M Chinnaswamy Stadium",
        "Seddon Park",
        "Eden Park",
        "Gaddafi Stadium",
        "National Stadium, Karachi",
        "SuperSport Park",
        "The Wanderers Stadium",
        "R Premadasa Stadium",
        "Rangiri Dambulla International Stadium",
        "Kensington Oval",
        "Queen's Park Oval",
    ],
    "Test": [
        "Adelaide Oval",
        "Western Australia Cricket Association Ground",
        "Sher-e-Bangla National Cricket Stadium",
        "Zahur Ahmed Chowdhury Stadium, Chattogram",
        "Eden Gardens",
        "MA Chidambaram Stadium, Chepauk",
        "Basin Reserve",
        "Seddon Park",
        "Rawalpindi Cricket Stadium",
        "National Stadium, Karachi",
        "Newlands",
        "SuperSport Park",
        "Galle International Stadium",
        "Sinhalese Sports Club Ground",
        "Kensington Oval",
        "Sabina Park, Kingston",
    ],
}


def venues_for_format(fmt: str) -> list[dict]:
    names = _INTERNATIONAL_VENUES.get(fmt, _INTERNATIONAL_VENUES["T20"])
    return [{"name": n} for n in names]
