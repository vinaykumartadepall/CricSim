"""
Read-side serializer: queries simulation.deliveries / simulation.matches and
joins history.players / history.venues to produce scorecard and commentary dicts.

All public functions take a RealDictCursor (repo.dict_cursor) so every row is
accessed by column name — no hardcoded indices.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple


# ── Scorecard ──────────────────────────────────────────────────────────────────

def get_scorecard(cur, match_id: int) -> dict:
    match_row = _fetch_match_row(cur, match_id)
    if not match_row:
        return {}

    innings_data = _fetch_innings_deliveries(cur, match_id)
    innings = [_build_inning_scorecard(inning_num, rows)
               for inning_num, rows in innings_data.items()]

    return {
        "match_id":           match_id,
        "match_label":        match_row['match_label'],
        "home_team":          match_row['home_team'],
        "away_team":          match_row['away_team'],
        "venue":              match_row['venue_name'],
        "result_description": _build_result_description(match_row),
        "innings":            innings,
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
               m.match_format,
               wt.name  AS winner,
               m.result, m.win_type, m.win_by, m.is_super_over
        FROM   simulation.matches m
        JOIN   simulation.teams ht  ON ht.team_id = m.home_team_id
        JOIN   simulation.teams at  ON at.team_id = m.away_team_id
        LEFT JOIN simulation.teams wt ON wt.team_id = m.winner_id
        LEFT JOIN history.venues   v  ON v.venue_id  = m.venue_id
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

def get_tournament_result(cur, sim_id: str) -> dict:
    cur.execute(
        """
        SELECT tournament_name, season, format
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
    points_table = _build_points_table(cur, sim_id, group_matches)

    # User team placement
    cur.execute(
        """
        SELECT gs.user_team_id, gs.mode, gs.source_tournament_id,
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
        LIMIT 1
        """,
        (sim_id, sim_id, sim_id),
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
               m.result, m.win_type, m.win_by,
               (m.is_super_over OR (m.match_format != 'Test' AND EXISTS (
                   SELECT 1 FROM simulation.deliveries dso
                   WHERE dso.match_id = m.match_id AND dso.inning_number = 3
               ))) AS is_super_over
        FROM   simulation.matches m
        JOIN   simulation.teams ht  ON ht.team_id = m.home_team_id
        JOIN   simulation.teams at  ON at.team_id = m.away_team_id
        LEFT JOIN simulation.teams wt ON wt.team_id = m.winner_id
        LEFT JOIN history.venues   v  ON v.venue_id  = m.venue_id
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
               d.runs_batter, d.runs_extras,
               d.outcome_type, d.outcome_kind,
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


def _build_inning_scorecard(inning_num: int, rows: list) -> dict:
    if not rows:
        return {}

    batting_team = rows[0]['batting_team_name']
    bowling_team = rows[0]['bowling_team_name']

    # ── Batting ────────────────────────────────────────────────────────────────
    # Seed both openers from the first delivery so the non-striker opener
    # appears at #2 even if they haven't faced a ball when the first wicket falls.
    batter_order: list = []
    batter_stats: Dict[int, dict] = {}

    def _ensure_batter(bid, name):
        if bid and bid not in batter_stats:
            batter_order.append(bid)
            batter_stats[bid] = {
                'name': name or str(bid),
                'runs': 0, 'balls': 0, 'fours': 0, 'sixes': 0,
                'dismissal': 'not out',
            }

    _ensure_batter(rows[0]['batter_id'],      rows[0]['batter_name'])
    _ensure_batter(rows[0]['non_striker_id'], rows[0]['non_striker_name'])

    for row in rows:
        bid = row['batter_id']
        _ensure_batter(bid, row['batter_name'])
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
        batter_rows.append({
            'name': b['name'], 'runs': b['runs'], 'balls': b['balls'],
            'fours': b['fours'], 'sixes': b['sixes'],
            'strike_rate': sr, 'dismissal': b['dismissal'],
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
        'extras_lb':       extras_lb,
        'extras_byes':     extras_byes,
        'batters':         batter_rows,
        'bowlers':         bowler_rows,
    }


def _build_result_description(row) -> Optional[str]:
    result   = row.get('result') if hasattr(row, 'get') else row['result']
    if result == 'no result':
        return "No result"
    if result == 'tie':
        return "Match tied"
    winner   = row['winner']
    win_type = row['win_type']
    win_by   = row['win_by']
    is_so    = bool(row.get('is_super_over'))
    if is_so and winner:
        return f"Match tied · {winner} won Super Over"
    if winner and win_type and win_by is not None:
        unit   = 'run' if win_type == 'runs' else 'wicket'
        plural = 's' if win_by != 1 else ''
        return f"{winner} won by {win_by} {unit}{plural}"
    return None


def _dismissal_text(okind: Optional[str], bowler: Optional[str], fielder: Optional[str]) -> str:
    if not okind:
        return "out"
    kind = okind.lower()
    if kind == 'bowled':
        return f"b {bowler}" if bowler else "bowled"
    if kind == 'caught':
        if fielder and fielder != bowler:
            return f"c {fielder} b {bowler}"
        return f"c&b {bowler}" if bowler else "caught"
    if kind == 'lbw':
        return f"lbw b {bowler}" if bowler else "lbw"
    if kind in ('run out', 'runout', 'run_out'):
        return f"run out ({fielder})" if fielder else "run out"
    if kind == 'stumped':
        return f"st {fielder} b {bowler}" if fielder else f"st b {bowler}"
    return okind


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
    prefix = "[FREE HIT] " if is_free_hit else ""

    if outcome_type == "Wicket":
        kind = (outcome_kind or "out").lower()
        if kind == "caught":
            if outcome_player and outcome_player != bowler:
                dismissal = f"caught by {outcome_player}, bowled {bowler}"
            else:
                dismissal = f"caught and bowled {bowler}"
        elif kind == "bowled":
            dismissal = f"bowled by {bowler}"
        elif kind == "lbw":
            dismissal = f"lbw, bowled {bowler}"
        elif kind == "stumped":
            dismissal = f"stumped by {outcome_player or bowler}, bowled {bowler}"
        elif kind in ("run out", "runout", "run_out"):
            dismissal = f"run out by {outcome_player or 'fielder'}"
        else:
            dismissal = f"{outcome_kind} by {outcome_player or bowler}"
        return f"{label}  {prefix}WICKET! {batter} is out — {dismissal}"

    if outcome_kind and outcome_kind.lower() in ("wide", "noball", "no ball"):
        ext        = "wide" if "wide" in outcome_kind.lower() else "no ball"
        extra_runs = f"+{runs_extras}" if runs_extras > 1 else ""
        return f"{label}  {prefix}{bowler} to {batter} — {ext}{extra_runs}"

    if outcome_type == "Extras" and outcome_kind:
        kind = outcome_kind.lower().rstrip("s")
        return f"{label}  {prefix}{bowler} to {batter} — {runs_extras} {kind}"

    if runs_batter == 0:
        return f"{label}  {prefix}{bowler} to {batter} — dot ball"
    if runs_batter == 4:
        return f"{label}  {prefix}{bowler} to {batter} — FOUR!"
    if runs_batter == 6:
        return f"{label}  {prefix}{bowler} to {batter} — SIX!"
    return f"{label}  {prefix}{bowler} to {batter} — {runs_batter} run{'s' if runs_batter != 1 else ''}"


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
    Points: win=2, loss=0, tie/no-result=1.
    NRR uses ICC all-out rule: full allocation used when team is dismissed.
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
            rs, bf = nrr_row['runs_scored'],   nrr_row['balls_faced']
            rc, bb = nrr_row['runs_conceded'],  nrr_row['balls_bowled']
            nrr = round((rs / (bf / 6) if bf else 0) - (rc / (bb / 6) if bb else 0), 3)
        else:
            nrr = 0.0
        table.append({
            'team': team, 'played': rec['played'],
            'won':  rec['won'],  'lost':      rec['lost'],
            'tied': rec['tied'], 'no_result': rec['no_result'],
            'points': points, 'nrr': nrr,
        })

    table.sort(key=lambda x: (-x['points'], -x['nrr']))
    return table
