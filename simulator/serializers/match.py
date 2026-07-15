"""
Read-side serializer: queries simulation.deliveries / simulation.matches and
joins history.players / history.venues to produce scorecard and commentary dicts.

All public functions take a RealDictCursor (repo.dict_cursor) so every row is
accessed by column name - no hardcoded indices.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from simulator.entities.rules import MatchRules
from simulator.presentation.dismissals import commentary_dismissal, scorecard_dismissal
from simulator.presentation.tiebreak_text import describe_tiebreak_winner


# ── Scorecard ──────────────────────────────────────────────────────────────────

def get_scorecard(cur, match_id: int) -> dict:
    match_row = _fetch_match_row(cur, match_id)
    if not match_row:
        return {}

    innings_data = _fetch_innings_deliveries(cur, match_id)
    squads = _fetch_match_squads(cur, match_id)
    innings = [_build_inning_scorecard(inning_num, rows, squads)
               for inning_num, rows in innings_data.items()]

    potm = None
    if match_row['player_of_match_id'] is not None:
        potm = {
            "player_id": match_row['player_of_match_id'],
            "name":      match_row['potm_player_name'],
            "team":      match_row['potm_team_name'],
            "points":    float(match_row['potm_points']) if match_row['potm_points'] is not None else None,
        }

    return {
        "match_id":           match_id,
        "match_label":        match_row['match_label'],
        "home_team":          match_row['home_team'],
        "away_team":          match_row['away_team'],
        "venue":              match_row['venue_name'],
        "venue_country":      match_row['venue_country'],
        "match_format":       match_row['match_format'],
        "result_description": _build_result_description(match_row),
        "innings":            innings,
        "potm":               potm,
    }


def get_commentary(cur, match_id: int) -> dict:
    match_row = _fetch_match_row(cur, match_id)
    if not match_row:
        return {}

    cur.execute(
        """
        SELECT d.inning_number, d.over_number, d.ball_number,
               COALESCE(bowler_p.display_name, bowler_p.name)  AS bowler_name,
               COALESCE(batter_p.display_name, batter_p.name)  AS batter_name,
               COALESCE(op.display_name, op.name)              AS outcome_player_name,
               COALESCE(ns.display_name, ns.name)              AS non_striker_name,
               d.runs_batter, d.runs_extras,
               d.outcome_type, d.outcome_kind,
               d.is_free_hit
        FROM   simulation.deliveries d
        LEFT JOIN history.players bowler_p ON bowler_p.player_id = d.bowler_id
        LEFT JOIN history.players batter_p ON batter_p.player_id = d.batter_id
        LEFT JOIN history.players op       ON op.player_id       = d.outcome_player_id
        LEFT JOIN history.players ns       ON ns.player_id       = d.non_striker_id
        WHERE  d.match_id = %s
        ORDER  BY d.inning_number, d.over_number, d.ball_number
        """,
        (match_id,),
    )
    deliveries = []
    for row in cur.fetchall():
        bowler = row['bowler_name'] or "Unknown"
        batter = row['batter_name'] or "Unknown"
        deliveries.append({
            "inning_number":   row['inning_number'],
            "over_ball":       f"{row['over_number']}.{row['ball_number']}",
            "bowler":          bowler,
            "batter":          batter,
            "non_striker":     row['non_striker_name'] or "Unknown",
            "runs_batter":     row['runs_batter'],
            "runs_extras":     row['runs_extras'],
            "outcome_type":    row['outcome_type'],
            "outcome_kind":    row['outcome_kind'],
            "is_wicket":       row['outcome_type'] == "Wicket",
            "is_free_hit":     row['is_free_hit'],
            "commentary_text": _format_commentary_text(
                row['over_number'], row['ball_number'],
                bowler, batter, row['outcome_player_name'],
                row['runs_batter'], row['runs_extras'],
                row['outcome_type'], row['outcome_kind'],
                row['is_free_hit'],
            ),
        })

    return {
        "match_id":         match_id,
        "match_label":      match_row['match_label'],
        "match_format":     match_row['match_format'],
        "overs_per_innings": match_row['overs_per_innings'],
        "deliveries":       deliveries,
    }


# ── Tournament match result ────────────────────────────────────────────────────

def get_match_result(cur, match_id: int) -> Optional[dict]:
    cur.execute(
        """
        SELECT m.match_id, m.match_label,
               ht.name  AS home_team,
               at.name  AS away_team,
               v.name   AS venue,
               c.name   AS venue_country,
               m.match_format,
               wt.name  AS winner,
               m.result, m.win_type, m.win_by, m.is_super_over
        FROM   simulation.matches m
        JOIN   simulation.teams ht  ON ht.team_id = m.home_team_id
        JOIN   simulation.teams at  ON at.team_id = m.away_team_id
        LEFT JOIN simulation.teams wt ON wt.team_id = m.winner_id
        LEFT JOIN history.venues   v  ON v.venue_id  = m.venue_id
        LEFT JOIN history.countries c ON c.country_id = v.country_id
        WHERE  m.match_id = %s
        """,
        (match_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "match_id":           row['match_id'],
        "match_label":        row['match_label'],
        "home_team":          row['home_team'],
        "away_team":          row['away_team'],
        "venue":              row['venue'],
        "format":             row['match_format'],
        "winner":             row['winner'],
        "result_description": _build_result_description(row),
        "win_type":           row['win_type'],
        "win_by":             row['win_by'],
        "is_super_over":      row['is_super_over'],
    }


# ── Tournament result reconstruction ──────────────────────────────────────────

def get_tournament_result(cur, sim_id: str, client_id: str | None = None) -> dict:
    cur.execute(
        """
        SELECT tournament_name, season, format, final_standings
        FROM   simulation.tournaments
        WHERE  sim_id = %s
        LIMIT  1
        """,
        (sim_id,),
    )
    t_row = cur.fetchone()

    cur.execute(
        """
        SELECT m.match_id, m.match_label,
               ht.name AS home_team,
               at.name AS away_team,
               wt.name AS winner,
               m.result, m.win_type, m.win_by, m.is_super_over
        FROM   simulation.matches m
        JOIN   simulation.teams ht ON ht.team_id = m.home_team_id
        JOIN   simulation.teams at ON at.team_id = m.away_team_id
        LEFT JOIN simulation.teams wt ON wt.team_id = m.winner_id
        WHERE  m.sim_id = %s
        ORDER  BY m.match_id
        """,
        (sim_id,),
    )
    matches = cur.fetchall()

    playoff_keywords = {'final', 'semi', 'qualifier', 'eliminator', 'playoff'}
    group_matches = [
        m for m in matches
        if not any(kw in (m['match_label'] or '').lower() for kw in playoff_keywords)
    ]

    winner, runner_up = _find_final_result(matches)

    if t_row and t_row.get('final_standings') is not None:
        # Preferred path: the live tournament engine's own standings
        # (simulator/tournament/points_table.py), persisted once when the
        # group stage completed - already correct (ICC all-out rule applied,
        # same points/NRR/won ordering used to decide real playoff seeding).
        points_table = t_row['final_standings']
    else:
        # Fallback for tournaments simulated before final_standings existed
        # (migration 026). Re-derives from raw deliveries - kept only for
        # those older sims, not a second live implementation going forward.
        points_table = _build_points_table(cur, sim_id, group_matches)

    # User team placement
    cur.execute(
        """
        SELECT gs.user_team_id, gs.mode, gs.source_tournament_id, gs.swaps, gs.room_id,
               ut.name AS user_team_name,
               CASE
                   WHEN mf.winner_id = gs.user_team_id THEN 'Winner'
                   WHEN mf.match_id IS NOT NULL
                    AND (mf.home_team_id = gs.user_team_id OR mf.away_team_id = gs.user_team_id)
                    AND mf.winner_id != gs.user_team_id THEN 'Runner-up'
                   WHEN mpo.match_id IS NOT NULL THEN 'Playoffs'
                   WHEN gs.user_team_id IS NOT NULL THEN 'Group stage'
                   ELSE NULL
               END AS user_team_placement
        FROM simulation.game_sessions gs
        LEFT JOIN simulation.teams ut ON ut.team_id = gs.user_team_id
        LEFT JOIN LATERAL (
            SELECT match_id, winner_id, home_team_id, away_team_id
            FROM simulation.matches m2
            WHERE m2.sim_id = %s
              AND m2.match_label ILIKE '%%final%%'
              AND m2.result NOT IN ('no result', 'tie')
            ORDER BY m2.match_id DESC LIMIT 1
        ) mf ON true
        LEFT JOIN LATERAL (
            SELECT match_id FROM simulation.matches m3
            WHERE m3.sim_id = %s
              AND m3.match_label NOT ILIKE '%%group%%'
              AND m3.match_label NOT ILIKE 'match %%'
              AND (m3.home_team_id = gs.user_team_id OR m3.away_team_id = gs.user_team_id)
              AND mf.match_id IS NOT NULL
            LIMIT 1
        ) mpo ON true
        WHERE gs.sim_id = %s
          AND (%s IS NULL OR gs.client_id = %s)
        ORDER BY CASE WHEN gs.client_id = %s THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (sim_id, sim_id, sim_id, client_id, client_id, client_id),
    )
    gs_row = cur.fetchone()

    return {
        "tournament_name":      t_row['tournament_name']         if t_row  else None,
        "season":               t_row['season']                   if t_row  else None,
        "format":               t_row['format']                   if t_row  else None,
        "winner":               winner,
        "runner_up":            runner_up,
        "total_matches":        len(matches),
        "points_table":         points_table,
        "user_team_name":       gs_row['user_team_name']         if gs_row else None,
        "user_team_placement":  gs_row['user_team_placement']    if gs_row else None,
        "mode":                 gs_row['mode']                   if gs_row else None,
        "source_tournament_id": gs_row['source_tournament_id']   if gs_row else None,
        "user_team_id":         gs_row['user_team_id']           if gs_row else None,
        "swaps":                gs_row['swaps']                  if gs_row else [],
        "room_id":              gs_row['room_id']                if gs_row else None,
    }


# ── Private helpers ────────────────────────────────────────────────────────────

def _fetch_match_row(cur, match_id: int) -> Optional[dict]:
    cur.execute(
        """
        SELECT m.match_id, m.match_label,
               m.venue_id, m.match_format, m.overs_per_innings,
               ht.name AS home_team,
               at.name AS away_team,
               wt.name AS winner,
               v.name  AS venue_name,
               c.name  AS venue_country,
               m.result, m.win_type, m.win_by,
               m.player_of_match_id, m.potm_player_name, m.potm_team_name, m.potm_points,
               (m.is_super_over OR (m.match_format != 'Test' AND EXISTS (
                   SELECT 1 FROM simulation.deliveries dso
                   WHERE dso.match_id = m.match_id AND dso.inning_number = 3
               ))) AS is_super_over
        FROM   simulation.matches m
        JOIN   simulation.teams ht  ON ht.team_id = m.home_team_id
        JOIN   simulation.teams at  ON at.team_id = m.away_team_id
        LEFT JOIN simulation.teams wt ON wt.team_id = m.winner_id
        LEFT JOIN history.venues   v  ON v.venue_id  = m.venue_id
        LEFT JOIN history.countries c ON c.country_id = v.country_id
        WHERE  m.match_id = %s
        """,
        (match_id,),
    )
    return cur.fetchone()


def _fetch_innings_deliveries(cur, match_id: int) -> Dict[int, list]:
    """Return {inning_number: [row, ...]} ordered by over/ball."""
    cur.execute(
        """
        SELECT d.inning_number, d.over_number, d.ball_number,
               d.batter_id, d.bowler_id, d.outcome_player_id, d.non_striker_id,
               COALESCE(batter_p.display_name, batter_p.name)  AS batter_name,
               COALESCE(bowler_p.display_name, bowler_p.name)  AS bowler_name,
               COALESCE(op.display_name, op.name)              AS outcome_player_name,
               COALESCE(ns.display_name, ns.name)              AS non_striker_name,
               batter_p.cricinfo_id                            AS batter_cricinfo_id,
               bowler_p.cricinfo_id                            AS bowler_cricinfo_id,
               d.runs_batter, d.runs_extras,
               d.outcome_type, d.outcome_kind,
               d.batting_team_id, d.bowling_team_id,
               bat_t.name AS batting_team_name,
               bowl_t.name AS bowling_team_name,
               d.is_free_hit
        FROM   simulation.deliveries d
        LEFT JOIN history.players batter_p ON batter_p.player_id = d.batter_id
        LEFT JOIN history.players bowler_p ON bowler_p.player_id = d.bowler_id
        LEFT JOIN history.players op       ON op.player_id       = d.outcome_player_id
        LEFT JOIN history.players ns       ON ns.player_id       = d.non_striker_id
        LEFT JOIN simulation.teams bat_t   ON bat_t.team_id      = d.batting_team_id
        LEFT JOIN simulation.teams bowl_t  ON bowl_t.team_id     = d.bowling_team_id
        WHERE  d.match_id = %s
        ORDER  BY d.inning_number, d.over_number, d.ball_number
        """,
        (match_id,),
    )
    innings: Dict[int, list] = {}
    for row in cur.fetchall():
        innings.setdefault(row['inning_number'], []).append(row)
    return innings


def _fetch_match_squads(cur, match_id: int) -> Dict[int, list]:
    """Return {team_id: [{'player_id', 'name', 'role'}, ...]} in batting-lineup
    order, for computing "did not bat" (squad minus who actually batted)."""
    cur.execute(
        """
        SELECT mp.team_id, mp.player_id, mp.batting_position,
               COALESCE(p.display_name, p.name) AS name, p.player_role
        FROM   simulation.match_players mp
        JOIN   history.players p ON p.player_id = mp.player_id
        WHERE  mp.match_id = %s
        ORDER  BY mp.team_id, mp.batting_position NULLS LAST, mp.player_id
        """,
        (match_id,),
    )
    squads: Dict[int, list] = {}
    for row in cur.fetchall():
        squads.setdefault(row['team_id'], []).append({
            'player_id': row['player_id'],
            'name':      row['name'],
            'role':      row['player_role'],
        })
    return squads


def _build_inning_scorecard(inning_num: int, rows: list, squads: Dict[int, list]) -> dict:
    if not rows:
        return {}

    batting_team = rows[0]['batting_team_name']
    bowling_team = rows[0]['bowling_team_name']

    # ── Batting ────────────────────────────────────────────────────────────────
    # Seed both openers from the first delivery so the non-striker opener
    # appears at #2 even if they haven't faced a ball when the first wicket falls.
    batter_order: list = []
    batter_stats: Dict[int, dict] = {}

    def _ensure_batter(bid, name, cricinfo_id=None):
        if bid and bid not in batter_stats:
            batter_order.append(bid)
            batter_stats[bid] = {
                'name': name or str(bid),
                'runs': 0, 'balls': 0, 'fours': 0, 'sixes': 0,
                'dismissal': 'not out',
                'cricinfo_id': cricinfo_id,
            }

    _ensure_batter(rows[0]['batter_id'],      rows[0]['batter_name'],     rows[0]['batter_cricinfo_id'])
    _ensure_batter(rows[0]['non_striker_id'], rows[0]['non_striker_name'], None)

    # ── Fall of wickets ──────────────────────────────────────────────────────────
    fall_of_wickets: list = []
    running_runs  = 0
    running_wkts  = 0

    for row in rows:
        bid = row['batter_id']
        _ensure_batter(bid, row['batter_name'], row['batter_cricinfo_id'])
        if bid:
            b = batter_stats[bid]
            b['runs'] += row['runs_batter']
            if row['outcome_kind'] not in ('Wide', 'wide'):
                b['balls'] += 1
            if row['runs_batter'] == 4:
                b['fours'] += 1
            if row['runs_batter'] == 6:
                b['sixes'] += 1
            if row['outcome_type'] == 'Wicket':
                b['dismissal'] = _dismissal_text(
                    row['outcome_kind'], row['bowler_name'], row['outcome_player_name']
                )

        running_runs += row['runs_batter'] + row['runs_extras']
        if row['outcome_type'] == 'Wicket':
            running_wkts += 1
            fall_of_wickets.append({
                'batter': row['batter_name'] or 'Unknown',
                'score':  running_runs,
                'wicket': running_wkts,
                'over':   f"{row['over_number']}.{row['ball_number']}",
            })

    # ── Bowling ────────────────────────────────────────────────────────────────
    bowler_order: list = []
    bowler_stats: Dict[int, dict] = {}

    for row in rows:
        bid = row['bowler_id']
        if bid and bid not in bowler_stats:
            bowler_order.append(bid)
            bowler_stats[bid] = {
                'name': row['bowler_name'] or str(bid),
                'runs': 0, 'legal_balls': 0, 'wickets': 0, 'dots': 0,
            }
        if bid:
            bw = bowler_stats[bid]
            okind = row['outcome_kind']
            charged = row['runs_batter']
            if okind in ('Wide', 'wide', 'Noball', 'noball'):
                charged += row['runs_extras']
            bw['runs'] += charged
            if okind not in ('Wide', 'wide', 'Noball', 'noball'):
                bw['legal_balls'] += 1
                if charged == 0 and row['outcome_type'] != 'Wicket':
                    bw['dots'] += 1
            if row['outcome_type'] == 'Wicket' and okind not in (
                'run out', 'Run Out', 'RunOut', 'obstructing', 'retired hurt'
            ):
                bw['wickets'] += 1

    # ── Totals ─────────────────────────────────────────────────────────────────
    total_runs    = sum(r['runs_batter'] + r['runs_extras'] for r in rows)
    total_wickets = sum(1 for r in rows if r['outcome_type'] == 'Wicket')
    legal_balls   = sum(1 for r in rows if r['outcome_kind'] not in ('Wide', 'wide', 'Noball', 'noball'))
    extras        = sum(r['runs_extras'] for r in rows)
    extras_wides  = sum(r['runs_extras'] for r in rows if r['outcome_kind'] in ('Wide', 'wide'))
    extras_nb     = sum(r['runs_extras'] for r in rows if r['outcome_kind'] in ('Noball', 'noball'))
    extras_lb     = sum(r['runs_extras'] for r in rows if r['outcome_kind'] in ('Legbyes', 'legbyes', 'LegByes'))
    extras_byes   = sum(r['runs_extras'] for r in rows if r['outcome_kind'] in ('Byes', 'byes'))

    batter_rows = []
    for bid in batter_order:
        b  = batter_stats[bid]
        sr = round(b['runs'] / b['balls'] * 100, 2) if b['balls'] else 0.0
        cid = b.get('cricinfo_id')
        batter_rows.append({
            'name': b['name'], 'runs': b['runs'], 'balls': b['balls'],
            'fours': b['fours'], 'sixes': b['sixes'],
            'strike_rate': sr, 'dismissal': b['dismissal'],
            'headshot_url': f"https://a.espncdn.com/i/headshots/cricket/players/full/{cid}.png" if cid else None,
        })

    bowler_rows = []
    for bid in bowler_order:
        bw  = bowler_stats[bid]
        eco = round(bw['runs'] / (bw['legal_balls'] / 6), 2) if bw['legal_balls'] else 0.0
        bowler_rows.append({
            'name':       bw['name'],
            'overs':      _balls_to_overs(bw['legal_balls']),
            'runs':       bw['runs'],
            'wickets':    bw['wickets'],
            'economy':    eco,
            'dot_balls':  bw['dots'],
        })

    # ── Did not bat ──────────────────────────────────────────────────────────────
    batting_team_id = rows[0]['batting_team_id']
    batted_ids      = set(batter_order)
    did_not_bat = [
        {'name': p['name'], 'role': p['role']}
        for p in squads.get(batting_team_id, [])
        if p['player_id'] not in batted_ids
    ]

    return {
        'inning_number':   inning_num,
        'batting_team':    batting_team,
        'bowling_team':    bowling_team,
        'total_runs':      total_runs,
        'total_wickets':   total_wickets,
        'overs':           _balls_to_overs(legal_balls),
        'extras':          extras,
        'extras_wides':    extras_wides,
        'extras_nb':       extras_nb,
        'fall_of_wickets': fall_of_wickets,
        'did_not_bat':     did_not_bat,
        'extras_lb':       extras_lb,
        'extras_byes':     extras_byes,
        'batters':         batter_rows,
        'bowlers':         bowler_rows,
    }


def _build_result_description(row) -> Optional[str]:
    result   = row.get('result') if hasattr(row, 'get') else row['result']
    winner   = row['winner']
    win_type = row['win_type']
    win_by   = row['win_by']

    # A knockout fixture whose genuine outcome was a draw/tie but still has a
    # winner from TournamentEngine's playoff tiebreak chain - win_type carries
    # which rule decided it (see db/simulation_repository.py::save_match).
    # Checked before the plain result branches below, which would otherwise
    # describe this as a bare "Match drawn"/"Match tied" with no winner.
    if winner and win_type in ('first_innings_lead', 'group_stage_rank'):
        prefix = 'Match tied' if result == 'tie' else 'Match drawn'
        return f"{prefix} · {describe_tiebreak_winner(win_type, winner)}"

    if result == 'no result':
        fmt = row.get('match_format') or ''
        if fmt in ('Test', 'MDM'):
            return "Match drawn"
        return "No result"
    if result == 'tie':
        tie_winner = row.get('winner') if hasattr(row, 'get') else row['winner']
        tie_is_so  = bool(row.get('is_super_over'))
        if tie_is_so and tie_winner:
            return f"Match tied · Super Over tied · {describe_tiebreak_winner('group_stage_rank', tie_winner)}"
        return "Match tied"
    is_so    = bool(row.get('is_super_over'))
    if is_so and winner:
        return f"Match tied · {winner} won Super Over"
    if winner and win_type and win_by is not None:
        if win_type == 'innings':
            n = win_by
            return f"{winner} won by an innings and {n} run{'s' if n != 1 else ''}"
        unit   = 'run' if win_type == 'runs' else 'wicket'
        plural = 's' if win_by != 1 else ''
        return f"{winner} won by {win_by} {unit}{plural}"
    return None


# One classifier for every dismissal display surface - see the module docstring
# in simulator/presentation/dismissals.py.
_dismissal_text = scorecard_dismissal


def _balls_to_overs(balls: int) -> str:
    return f"{balls // 6}.{balls % 6}"


def _format_commentary_text(
    over: int, ball: int,
    bowler: str, batter: str, outcome_player: Optional[str],
    runs_batter: int, runs_extras: int,
    outcome_type: Optional[str], outcome_kind: Optional[str],
    is_free_hit: bool,
) -> str:
    label  = f"{over}.{ball}"
    prefix = "Freehit! " if is_free_hit else ""

    if outcome_type == "Wicket":
        dismissal = commentary_dismissal(outcome_kind, bowler, outcome_player)
        return f"{label}  {prefix}WICKET! {batter} is out - {dismissal}"

    if outcome_kind and outcome_kind.lower() == "wide":
        extra_runs = f"+{runs_extras}" if runs_extras > 1 else ""
        return f"{label}  {prefix}{bowler} to {batter} - wide{extra_runs}"

    if outcome_kind and outcome_kind.lower() in ("noball", "no ball"):
        run_word = f"{runs_batter} run{'s' if runs_batter != 1 else ''}"
        return f"{label}  {prefix}{bowler} to {batter} - {run_word}, and it's a no ball!"

    if outcome_type == "Extras" and outcome_kind:
        kind = outcome_kind.lower().rstrip("s")
        return f"{label}  {prefix}{bowler} to {batter} - {runs_extras} {kind}"

    if runs_batter == 0:
        return f"{label}  {prefix}{bowler} to {batter} - dot ball"
    if runs_batter == 4:
        return f"{label}  {prefix}{bowler} to {batter} - FOUR!"
    if runs_batter == 6:
        return f"{label}  {prefix}{bowler} to {batter} - SIX!"
    return f"{label}  {prefix}{bowler} to {batter} - {runs_batter} run{'s' if runs_batter != 1 else ''}"


def _find_final_result(matches: list) -> Tuple[Optional[str], Optional[str]]:
    for row in reversed(matches):
        label = (row['match_label'] or '').lower()
        if 'final' in label and 'semi' not in label and 'qualifier' not in label:
            winner    = row['winner']
            runner_up = row['away_team'] if winner == row['home_team'] else row['home_team']
            return winner, runner_up
    if matches:
        row       = matches[-1]
        winner    = row['winner']
        runner_up = row['away_team'] if winner == row['home_team'] else row['home_team']
        return winner, runner_up
    return None, None


def _build_points_table(cur, sim_id: str, group_matches: list) -> list:
    """
    DEPRECATED fallback, only reached for tournaments simulated before
    migration 026 added simulation.tournaments.final_standings - every new
    sim gets its points table from the live engine directly (see
    get_tournament_result above), not from this function.

    Points: win=2, loss=0, tie/no-result=1.
    NRR uses the ICC all-out rule (full overs allocation credited when a team
    is dismissed) - mirrors MatchRules.nrr_adjusted_balls, duplicated here in
    raw SQL only because that logic can't be called from a query; the actual
    run-rate division/subtraction below does go through MatchRules.net_run_rate.
    """
    group_match_ids = [row['match_id'] for row in group_matches]
    if not group_match_ids:
        return []

    cur.execute(
        """
        WITH innings_stats AS (
            SELECT
                d.batting_team_id,
                d.bowling_team_id,
                SUM(d.runs_batter + d.runs_extras)                                  AS runs,
                SUM(CASE WHEN d.outcome_kind IS NULL
                              OR d.outcome_kind NOT IN ('Wide','wide','Noball','noball')
                         THEN 1 ELSE 0 END)                                         AS legal_balls,
                SUM(CASE WHEN d.outcome_type = 'Wicket' THEN 1 ELSE 0 END)          AS wickets,
                MAX(m.overs_per_innings) * 6                                        AS max_balls
            FROM   simulation.deliveries d
            JOIN   simulation.matches m ON m.match_id = d.match_id
            WHERE  d.match_id = ANY(%s)
            GROUP  BY d.match_id, d.batting_team_id, d.bowling_team_id
        ),
        adjusted AS (
            SELECT batting_team_id, bowling_team_id, runs,
                   CASE WHEN wickets >= 10 THEN max_balls ELSE legal_balls END AS balls
            FROM   innings_stats
        ),
        batting_side AS (
            SELECT batting_team_id AS team_id, SUM(runs) AS runs_scored, SUM(balls) AS balls_faced
            FROM   adjusted GROUP BY batting_team_id
        ),
        bowling_side AS (
            SELECT bowling_team_id AS team_id, SUM(runs) AS runs_conceded, SUM(balls) AS balls_bowled
            FROM   adjusted GROUP BY bowling_team_id
        )
        SELECT t.name,
               COALESCE(bs.runs_scored,   0) AS runs_scored,
               COALESCE(bs.balls_faced,   0) AS balls_faced,
               COALESCE(bw.runs_conceded, 0) AS runs_conceded,
               COALESCE(bw.balls_bowled,  0) AS balls_bowled
        FROM   simulation.teams t
        JOIN   simulation.tournament_teams tt ON tt.team_id      = t.team_id
        JOIN   simulation.tournaments      tr ON tr.tournament_id = tt.tournament_id
        LEFT JOIN batting_side bs ON bs.team_id = t.team_id
        LEFT JOIN bowling_side bw ON bw.team_id = t.team_id
        WHERE  tr.sim_id = %s
        GROUP  BY t.name, bs.runs_scored, bs.balls_faced, bw.runs_conceded, bw.balls_bowled
        """,
        (group_match_ids, sim_id),
    )
    nrr_rows = {row['name']: row for row in cur.fetchall()}

    team_record: Dict[str, dict] = {}

    def _record(name):
        if name not in team_record:
            team_record[name] = {'played': 0, 'won': 0, 'lost': 0, 'tied': 0, 'no_result': 0}
        return team_record[name]

    for row in group_matches:
        home, away, winner, result = row['home_team'], row['away_team'], row['winner'], row['result']
        h, a = _record(home), _record(away)
        h['played'] += 1
        a['played'] += 1
        if result == 'no result':
            h['no_result'] += 1
            a['no_result'] += 1
        elif result == 'tie':
            h['tied'] += 1
            a['tied'] += 1
        elif winner:
            if winner == home:
                h['won'] += 1; a['lost'] += 1
            else:
                a['won'] += 1; h['lost'] += 1

    table = []
    for team, rec in team_record.items():
        points  = rec['won'] * 2 + rec['tied'] + rec['no_result']
        nrr_row = nrr_rows.get(team)
        if nrr_row:
            nrr = MatchRules.net_run_rate(
                nrr_row['runs_scored'], nrr_row['balls_faced'],
                nrr_row['runs_conceded'], nrr_row['balls_bowled'],
            )
        else:
            nrr = 0.0
        table.append({
            'team': team, 'played': rec['played'],
            'won':  rec['won'],  'lost':      rec['lost'],
            'tied': rec['tied'], 'no_result': rec['no_result'],
            'points': points, 'nrr': nrr,
        })

    # Same tiebreak order as the live engine's PointsTable.standings()
    # (points, nrr, won) - kept in sync so this fallback path (pre-migration
    # 026 sims only) doesn't silently rank differently from real playoff seeding.
    table.sort(key=lambda x: (-x['points'], -x['nrr'], -x['won']))
    return table
