"""
Seed simulation.tournament_seeded.config for all simulation-ready tournaments.

Step 1 of 2: builds tournament metadata, venue list, team list (with colors/home
venues), schedule, and playoffs.  players arrays are left empty - they are filled
by db/precompute.py --seed-squads (step 2).

Run with:
    conda run -n cricsim python -m db.seed_sim_configs [--dry-run]

config schema (TournamentConfig-compatible):
  tournament_name  - display name
  format           - T20 | ODI
  gender           - male | female
  season           - e.g. "2025"
  venues[]         - {name, city} from history.matches
  teams[]          - {team_id, name, short_name, primary_color, secondary_color,
                       home_venue, players:[]}
  schedule         - {type, neutral_venues, [groups], [within/cross_matches_per_pair]}
  playoffs         - {format, top_n}

schedule.type values:
  round_robin | double_round_robin | two_group_hybrid

playoffs.format values:
  none | two_teams | semis_final | ipl | quarters_semis_final

IPL schedule notes:
  - Pre-2022: double_round_robin.
  - 2022+: two_group_hybrid (within=1, cross=2).  Groups derived from historical
    pair counts via bipartite detection or K5 brute-force.
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations

import psycopg2
import psycopg2.extras

from db.database import get_db_connection


# ── Team metadata lookup ───────────────────────────────────────────────────────
# Keyed by exact history.teams.name.  Absent teams get auto-derived short_name
# and default colors.

_TEAM_META: dict[str, dict] = {
    # ── IPL current ──────────────────────────────────────────────────────────
    "Mumbai Indians":           {"short_name": "MI",   "primary_color": "#004B8D", "secondary_color": "#D4AF37"},
    "Chennai Super Kings":      {"short_name": "CSK",  "primary_color": "#F9CD05", "secondary_color": "#0047AB"},
    "Royal Challengers Bengaluru": {"short_name": "RCB", "primary_color": "#E81020", "secondary_color": "#FFD700"},
    "Royal Challengers Bangalore": {"short_name": "RCB", "primary_color": "#E81020", "secondary_color": "#FFD700"},
    "Delhi Capitals":           {"short_name": "DC",   "primary_color": "#004C97", "secondary_color": "#EF1C25"},
    "Kolkata Knight Riders":    {"short_name": "KKR",  "primary_color": "#3A225D", "secondary_color": "#B3992C"},
    "Rajasthan Royals":         {"short_name": "RR",   "primary_color": "#F50247", "secondary_color": "#0B4EA2"},
    "Punjab Kings":             {"short_name": "PBKS", "primary_color": "#CE3746", "secondary_color": "#384DC7"},
    "Sunrisers Hyderabad":      {"short_name": "SRH",  "primary_color": "#FF6700", "secondary_color": "#000000"},
    "Gujarat Titans":           {"short_name": "GT",   "primary_color": "#1C3D70", "secondary_color": "#C4A661"},
    "Lucknow Super Giants":     {"short_name": "LSG",  "primary_color": "#0F0F87", "secondary_color": "#8C0808"},
    # ── IPL historical ───────────────────────────────────────────────────────
    "Deccan Chargers":          {"short_name": "DCH",  "primary_color": "#F7A700", "secondary_color": "#000000"},
    "Kings XI Punjab":          {"short_name": "KXIP", "primary_color": "#CE3746", "secondary_color": "#384DC7"},
    "Delhi Daredevils":         {"short_name": "DD",   "primary_color": "#004C97", "secondary_color": "#EF1C25"},
    "Pune Warriors India":      {"short_name": "PWI",  "primary_color": "#5BBDE7", "secondary_color": "#004080"},
    "Kochi Tuskers Kerala":     {"short_name": "KTK",  "primary_color": "#F76900", "secondary_color": "#009929"},
    "Rising Pune Supergiant":   {"short_name": "RPS",  "primary_color": "#870E4F", "secondary_color": "#FFFFFF"},
    "Rising Pune Supergiants":  {"short_name": "RPS",  "primary_color": "#870E4F", "secondary_color": "#FFFFFF"},
    "Gujarat Lions":            {"short_name": "GL",   "primary_color": "#F26C23", "secondary_color": "#005A9B"},
    # ── Big Bash League ──────────────────────────────────────────────────────
    "Sydney Sixers":            {"short_name": "SIX",  "primary_color": "#FF007B", "secondary_color": "#FFFFFF"},
    "Melbourne Stars":          {"short_name": "STA",  "primary_color": "#00A650", "secondary_color": "#FFFFFF"},
    "Perth Scorchers":          {"short_name": "SCO",  "primary_color": "#F15A22", "secondary_color": "#003087"},
    "Brisbane Heat":            {"short_name": "HEA",  "primary_color": "#FF0000", "secondary_color": "#001B6E"},
    "Adelaide Strikers":        {"short_name": "STR",  "primary_color": "#005BAA", "secondary_color": "#00B5E2"},
    "Sydney Thunder":           {"short_name": "THU",  "primary_color": "#00843D", "secondary_color": "#FFCD00"},
    "Hobart Hurricanes":        {"short_name": "HUR",  "primary_color": "#7B2D8B", "secondary_color": "#FFFFFF"},
    "Melbourne Renegades":      {"short_name": "REN",  "primary_color": "#E21E26", "secondary_color": "#000000"},
    # ── SA20 ─────────────────────────────────────────────────────────────────
    "Paarl Royals":             {"short_name": "PAR",  "primary_color": "#F50247", "secondary_color": "#0B4EA2"},
    "MI Cape Town":             {"short_name": "MCT",  "primary_color": "#004B8D", "secondary_color": "#D4AF37"},
    "Joburg Super Kings":       {"short_name": "JSK",  "primary_color": "#F9CD05", "secondary_color": "#0047AB"},
    "Sunrisers Eastern Cape":   {"short_name": "SEC",  "primary_color": "#FF6700", "secondary_color": "#000000"},
    "Durban's Super Giants":    {"short_name": "DSG",  "primary_color": "#7B2D8B", "secondary_color": "#FFFFFF"},
    "Pretoria Capitals":        {"short_name": "CAP",  "primary_color": "#003087", "secondary_color": "#E31837"},
    # ── Pakistan Super League ─────────────────────────────────────────────────
    "Karachi Kings":            {"short_name": "KAR",  "primary_color": "#01338E", "secondary_color": "#FFFFFF"},
    "Lahore Qalandars":         {"short_name": "LAH",  "primary_color": "#009A44", "secondary_color": "#FFFFFF"},
    "Multan Sultans":           {"short_name": "MUL",  "primary_color": "#7B2D8B", "secondary_color": "#FABD05"},
    "Peshawar Zalmi":           {"short_name": "PES",  "primary_color": "#F7A800", "secondary_color": "#000000"},
    "Quetta Gladiators":        {"short_name": "QUE",  "primary_color": "#E31837", "secondary_color": "#FFFFFF"},
    "Islamabad United":         {"short_name": "ISU",  "primary_color": "#E31837", "secondary_color": "#003087"},
    # ── Caribbean Premier League ──────────────────────────────────────────────
    "Trinbago Knight Riders":   {"short_name": "TKR",  "primary_color": "#3A225D", "secondary_color": "#B3992C"},
    "Guyana Amazon Warriors":   {"short_name": "GAW",  "primary_color": "#F7A800", "secondary_color": "#006400"},
    "Barbados Royals":          {"short_name": "BAR",  "primary_color": "#F50247", "secondary_color": "#003087"},
    "Barbados Tridents":        {"short_name": "BAR",  "primary_color": "#F50247", "secondary_color": "#003087"},
    "Jamaica Tallawahs":        {"short_name": "JAM",  "primary_color": "#FFCD00", "secondary_color": "#000000"},
    "Saint Lucia Kings":        {"short_name": "SLK",  "primary_color": "#0047AB", "secondary_color": "#FFFFFF"},
    "Saint Lucia Zouks":        {"short_name": "SLZ",  "primary_color": "#640A60", "secondary_color": "#FFFFFF"},
    "St Kitts and Nevis Patriots": {"short_name": "SKN", "primary_color": "#009C4E", "secondary_color": "#FFFFFF"},
    "Antigua and Barbuda Falcons": {"short_name": "ANT", "primary_color": "#003087", "secondary_color": "#E31837"},
    "St Lucia Zouks":           {"short_name": "SLZ",  "primary_color": "#640A60", "secondary_color": "#FFFFFF"},
}


# ── IPL helpers ────────────────────────────────────────────────────────────────

def _ipl_first_year(season: str) -> int:
    """'2007/08' → 2007,  '2022' → 2022."""
    return int(season[:4])


def _ipl_playoff_format(season: str) -> str:
    return "semis_final" if _ipl_first_year(season) <= 2011 else "ipl"


def _derive_groups_from_db(cur, tournament_id: int) -> list[list[str]] | None:
    """
    Derive two groups of 5 teams from historical group-stage pair counts.

    Two formats appear in the DB:
      bipartite  - within×1, ALL cross×2 (2023, 2026).
      within×2   - within×2 + some cross×2 (2022, 2024, 2025).

    Returns None if fewer than 30 group-stage pair rows are found.
    """
    cur.execute(
        """
        SELECT LEAST(ht.name, at.name)    AS team_a,
               GREATEST(ht.name, at.name) AS team_b,
               COUNT(*) AS games
        FROM history.matches m
        JOIN history.teams ht ON ht.team_id = m.home_team_id
        JOIN history.teams at ON at.team_id = m.away_team_id
        WHERE m.tournament_id = %s
          AND m.name ~ E'^Match [0-9]+'
        GROUP BY 1, 2
        """,
        (tournament_id,),
    )
    rows = cur.fetchall()

    teams = sorted(
        {r["team_a"] for r in rows} | {r["team_b"] for r in rows}
    )
    if len(teams) < 10 or len(rows) < 30:
        return None

    pc: dict[tuple[str, str], int] = {
        (r["team_a"], r["team_b"]): r["games"] for r in rows
    }

    def cnt(a: str, b: str) -> int:
        return pc.get((min(a, b), max(a, b)), 0)

    n    = len(teams)
    half = n // 2

    # Bipartite detection (2023 / 2026 format)
    x2 = {t: frozenset(t2 for t2 in teams if cnt(t, t2) >= 2) for t in teams}
    t0      = teams[0]
    group_b = sorted(x2[t0])
    group_a = [t0] + sorted(t for t in teams if t != t0 and t not in x2[t0])

    if len(group_a) == half and len(group_b) == half:
        fa, fb = frozenset(group_a), frozenset(group_b)
        if all(x2[t] == fb for t in group_a) and all(x2[t] == fa for t in group_b):
            return [group_a, group_b]

    # Within×2 K5 brute-force (2022 / 2024 / 2025 format)
    best_partition: list[list[str]] | None = None
    best_score = -1
    for idx in combinations(range(n), half):
        ga = [teams[i] for i in idx]
        gb = [teams[i] for i in range(n) if i not in idx]
        score = (
            sum(1 for a, b in combinations(ga, 2) if cnt(a, b) >= 2)
            + sum(1 for a, b in combinations(gb, 2) if cnt(a, b) >= 2)
        )
        if score > best_score:
            best_score = score
            best_partition = [ga, gb]

    return best_partition


def _build_ipl_schedule(cur, tournament_id: int, season: str) -> dict:
    """Return just the schedule + playoffs sub-dicts for one IPL season."""
    playoff_fmt = _ipl_playoff_format(season)
    playoffs_cfg = {"format": playoff_fmt, "top_n": 4}
    year = _ipl_first_year(season)

    if year < 2022:
        return {
            "schedule": {"type": "double_round_robin", "neutral_venues": True},
            "playoffs": playoffs_cfg,
        }

    groups = _derive_groups_from_db(cur, tournament_id)
    if groups is None:
        print(
            f"  WARNING: could not derive groups for IPL {season} "
            "(insufficient match data) - using double_round_robin fallback",
            file=sys.stderr,
        )
        return {
            "schedule": {"type": "double_round_robin", "neutral_venues": True},
            "playoffs": playoffs_cfg,
        }

    return {
        "schedule": {
            "type": "two_group_hybrid",
            "within_matches_per_pair": 1,
            "cross_matches_per_pair": 2,
            "neutral_venues": True,
            "groups": groups,
        },
        "playoffs": playoffs_cfg,
    }


# ── Non-IPL schedule / playoff configs ────────────────────────────────────────

_NON_IPL_SCHED: dict[str, dict] = {
    "Big Bash League": {
        "schedule": {"type": "double_round_robin", "neutral_venues": True},
        "playoffs": {"format": "ipl", "top_n": 4},
    },
    "SA20": {
        "schedule": {"type": "double_round_robin", "neutral_venues": False},
        "playoffs": {"format": "semis_final", "top_n": 4},
    },
    "Pakistan Super League": {
        "schedule": {"type": "double_round_robin", "neutral_venues": True},
        "playoffs": {"format": "semis_final", "top_n": 4},
    },
    "Caribbean Premier League": {
        "schedule": {"type": "double_round_robin", "neutral_venues": True},
        "playoffs": {"format": "semis_final", "top_n": 4},
    },
    "ICC Cricket World Cup": {
        "schedule": {"type": "round_robin", "matches_per_pair": 1, "neutral_venues": True},
        "playoffs": {"format": "semis_final", "top_n": 4},
    },
    "World Cup": {
        "schedule": {"type": "round_robin", "matches_per_pair": 1, "neutral_venues": True},
        "playoffs": {"format": "semis_final", "top_n": 4},
    },
}


# ── Config builder ─────────────────────────────────────────────────────────────

def _build_full_config(
    cur,
    tournament_id: int,
    tournament_name: str,
    season: str,
    sched_po: dict,          # {"schedule": {...}, "playoffs": {...}}
    existing_config: dict | None,
) -> dict:
    """Build a complete TournamentConfig-format document for one tournament-season."""

    # 1. Format + gender from any match in this tournament
    cur.execute(
        "SELECT match_format, gender FROM history.matches WHERE tournament_id = %s LIMIT 1",
        (tournament_id,),
    )
    m_row = cur.fetchone()
    fmt    = m_row["match_format"] if m_row else "T20"
    gender = m_row["gender"]       if m_row else "male"

    # 2. Distinct venues
    cur.execute(
        """
        SELECT DISTINCT v.name, COALESCE(v.city, '') AS city
        FROM history.matches m
        JOIN history.venues v ON v.venue_id = m.venue_id
        WHERE m.tournament_id = %s
        ORDER BY v.name
        """,
        (tournament_id,),
    )
    venues = [{"name": r["name"], "city": r["city"]} for r in cur.fetchall()]

    # 3. Teams from history.tournament_teams
    cur.execute(
        """
        SELECT t.team_id, t.name
        FROM history.tournament_teams tt
        JOIN history.teams t ON t.team_id = tt.team_id
        WHERE tt.tournament_id = %s
        ORDER BY t.name
        """,
        (tournament_id,),
    )
    team_rows = cur.fetchall()

    # 4. Most-frequent home venue per team (from history.matches)
    cur.execute(
        """
        SELECT m.home_team_id, v.name AS venue_name, COUNT(*) AS cnt
        FROM history.matches m
        JOIN history.venues v ON v.venue_id = m.venue_id
        WHERE m.tournament_id = %s
        GROUP BY m.home_team_id, v.name
        ORDER BY m.home_team_id, cnt DESC
        """,
        (tournament_id,),
    )
    home_venue_map: dict[int, str] = {}
    for row in cur.fetchall():
        tid = row["home_team_id"]
        if tid not in home_venue_map:  # first = most frequent due to ORDER BY
            home_venue_map[tid] = row["venue_name"]

    # 5. Preserve existing players if already seeded
    existing_players: dict[int, list[int]] = {}  # team_id → [player_ids]
    if existing_config:
        for t in existing_config.get("teams", []):
            tid = t.get("team_id")
            if tid and t.get("players"):
                existing_players[tid] = t["players"]

    # 6. Build teams array
    teams = []
    venue_names = {v["name"] for v in venues}
    for row in team_rows:
        meta        = _TEAM_META.get(row["name"], {})
        db_home     = home_venue_map.get(row["team_id"])
        meta_home   = meta.get("home_venue")
        # prefer explicit meta, then DB-derived, but only if in venues list
        home_venue  = None
        for candidate in [meta_home, db_home]:
            if candidate and candidate in venue_names:
                home_venue = candidate
                break

        teams.append({
            "team_id":         row["team_id"],
            "name":            row["name"],
            "short_name":      meta.get("short_name", row["name"][:3].upper()),
            "primary_color":   meta.get("primary_color", "#1E88E5"),
            "secondary_color": meta.get("secondary_color", "#FFFFFF"),
            "home_venue":      home_venue,
            "players":         existing_players.get(row["team_id"], []),
        })

    return {
        "tournament_name": tournament_name,
        "format":          fmt,
        "gender":          gender,
        "season":          season,
        "venues":          venues,
        "teams":           teams,
        "schedule":        sched_po["schedule"],
        "playoffs":        sched_po["playoffs"],
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> None:
    conn = get_db_connection(autocommit=False)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # ── IPL ───────────────────────────────────────────────────────────────
        cur.execute(
            """
            SELECT t.tournament_id, t.season,
                   ts.config AS existing_config
            FROM history.tournaments t
            LEFT JOIN simulation.tournament_seeded ts USING (tournament_id)
            WHERE t.tournament_name = 'Indian Premier League'
            ORDER BY t.season
            """
        )
        ipl_rows = cur.fetchall()
        print(f"\n=== Indian Premier League ({len(ipl_rows)} seasons) ===")

        for row in ipl_rows:
            tid     = row["tournament_id"]
            season  = row["season"]
            sched_po = _build_ipl_schedule(cur, tid, season)
            cfg = _build_full_config(cur, tid, "Indian Premier League", season,
                                     sched_po, row["existing_config"])

            sched_type  = cfg["schedule"]["type"]
            playoff_fmt = cfg["playoffs"]["format"]
            groups      = cfg["schedule"].get("groups")
            print(f"\n  IPL {season} (id={tid})  schedule={sched_type}  playoffs={playoff_fmt}")
            if groups:
                print(f"    Group A ({len(groups[0])}): {groups[0]}")
                print(f"    Group B ({len(groups[1])}): {groups[1]}")

            if not dry_run:
                cur.execute(
                    """
                    INSERT INTO simulation.tournament_seeded (tournament_id, config)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (tournament_id) DO UPDATE SET config = EXCLUDED.config
                    """,
                    (tid, json.dumps(cfg)),
                )

        # ── Other tournaments ─────────────────────────────────────────────────
        for t_name, sched_po in _NON_IPL_SCHED.items():
            cur.execute(
                """
                SELECT t.tournament_id, t.season, ts.config AS existing_config
                FROM history.tournaments t
                LEFT JOIN simulation.tournament_seeded ts USING (tournament_id)
                WHERE t.tournament_name = %s
                ORDER BY t.season
                """,
                (t_name,),
            )
            rows = cur.fetchall()
            if not rows:
                print(f"\n{t_name}: no tournaments in history DB - skipping")
                continue

            sched_type = sched_po["schedule"]["type"]
            po_fmt     = sched_po["playoffs"]["format"]
            print(f"\n{t_name}: {len(rows)} season(s)  schedule={sched_type}  playoffs={po_fmt}")

            for row in rows:
                tid    = row["tournament_id"]
                season = row["season"]
                cfg = _build_full_config(cur, tid, t_name, season,
                                         sched_po, row["existing_config"])
                player_counts = [len(t["players"]) for t in cfg["teams"]]
                seeded_note = (
                    f"{sum(1 for c in player_counts if c > 0)}/{len(cfg['teams'])} teams with squads"
                    if any(player_counts)
                    else "squads not yet seeded"
                )
                print(f"  {season} (id={tid}, {seeded_note})")

                if not dry_run:
                    cur.execute(
                        """
                        INSERT INTO simulation.tournament_seeded (tournament_id, config)
                        VALUES (%s, %s::jsonb)
                        ON CONFLICT (tournament_id) DO UPDATE SET config = EXCLUDED.config
                        """,
                        (tid, json.dumps(cfg)),
                    )

        if not dry_run:
            conn.commit()
            print("\n✓ config committed for all tournaments.")
        else:
            print("\n(dry-run - no changes written)")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed config for all simulation-ready tournaments (step 1 of 2)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
