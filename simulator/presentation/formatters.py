from __future__ import annotations

from typing import TYPE_CHECKING

from enums.constants import ExtraType
from simulator.entities.inning import Inning
from simulator.presentation.colors import bg, bold, dim, hdr, rgb, sep
from simulator.presentation.dismissals import scorecard_dismissal

if TYPE_CHECKING:
    from simulator.entities.match import SimulationMatch


def format_ball_commentary(ball, is_super_over: bool = False) -> str:
    bowler_name = ball.bowler.name if ball.bowler else "Unknown"
    batter_name = ball.batter.name if ball.batter else "Unknown"

    if is_super_over:
        label = f"Ball {ball.ball_number:<2}"
    else:
        label = f"{ball.over_number}.{ball.ball_number:<5}"

    if ball.is_wicket:
        desc = ball.wicket_kind
        if ball.outcome_player:
            desc += f" by {ball.outcome_player.name}"
        elif desc in ['caught', 'stumped', 'run out']:
            desc += f" {bowler_name}"

        batter_score = f"{ball.batter.runs_scored}({ball.batter.balls_faced})" if ball.batter else ""
        outcome_str = f"WICKET! {batter_name} {batter_score}"
        return f"{label}  {outcome_str}, {bowler_name} to {batter_name} ({desc})"

    if ball.extras_type:
        ext_type = ball.extras_type[:-1] if ball.extras_type.endswith('s') else ball.extras_type
        outcome_str = f"{ball.runs_extras} {ext_type.capitalize()}"
        return f"{label}  {outcome_str}, {bowler_name} to {batter_name}"

    runs = ball.runs_batter
    outcome_str = f"{runs} run" + ("s" if runs != 1 else "")
    return f"{label}  {outcome_str}, {bowler_name} to {batter_name}"


def _build_over_seq(deliveries):
    """Shared delivery-sequence builder used by both over-summary formatters."""
    seq = []
    for d in deliveries:
        if d.is_wicket:
            seq.append('W')
        elif d.extras_type:
            if d.extras_type == ExtraType.WIDE:
                seq.append(f"{d.runs_extras}Wd")
            elif d.extras_type == ExtraType.NOBALL:
                seq.append(f"{d.runs_extras}Nb")
            elif d.extras_type == ExtraType.LEGBYES:
                seq.append(f"{d.runs_extras}Lb")
            elif d.extras_type == ExtraType.BYES:
                seq.append(f"{d.runs_extras}b")
            else:
                seq.append(f"{d.runs_extras}E")
        else:
            seq.append(str(d.runs_batter))
    return seq


def _bowler_line(bowler) -> str:
    if not bowler:
        return ""
    ovs = bowler.balls_bowled // 6
    bls = bowler.balls_bowled % 6
    ov_str = f"{ovs}.{bls}" if bls else f"{ovs}"
    return f"{bowler.name:<20} {ov_str}-{bowler.maidens}-{bowler.runs_conceded}-{bowler.wickets_taken}"


def format_over_summary(match: SimulationMatch, inning: Inning, is_super_over: bool = False) -> str:
    if is_super_over:
        return _format_super_over_summary(match, inning)

    current_over = match.current_over   # 0-indexed; formatter is called before the increment
    batting = inning.batting_team

    over_balls = [d for d in inning.deliveries if d.over_number == current_over]
    seq        = _build_over_seq(over_balls)
    over_runs  = sum(d.runs_batter + d.runs_extras for d in over_balls)
    seq_str    = " ".join(seq)

    header       = f"Overs {current_over + 1} | {batting.total_runs}-{batting.total_wickets}"
    right_header = f"{seq_str} ({over_runs} runs)"

    lines = [
        "\n" + "=" * 100,
        f"{header:<30} {right_header:>69}",
        "-" * 100,
    ]

    def bat_stats(ip):
        if not ip:
            return ""
        return f"{ip.name:<20} {ip.runs_scored} ({ip.balls_faced})"

    lines.append(f"{bat_stats(match.striker):<45} | {_bowler_line(match.current_bowler)}")
    if match.non_striker:
        lines.append(f"{bat_stats(match.non_striker):<45} |")

    if match.current_inning == 2 and match.target_score and match.overs_per_innings:
        runs_needed = match.target_score - batting.total_runs
        balls_rem = (match.overs_per_innings * 6) - batting.total_balls
        if runs_needed > 0 and balls_rem > 0:
            lines.append("-" * 100)
            lines.append(f"{batting.name} need {runs_needed} runs in {balls_rem} balls")

    lines.append("-" * 100 + "\n")
    return "\n".join(lines)


def _format_super_over_summary(match: SimulationMatch, inning: Inning) -> str:
    _W = 100
    SEP  = "═" * _W
    DASH = "─" * _W

    batting   = inning.batting_team
    seq       = _build_over_seq(inning.deliveries)
    total_runs = sum(d.runs_batter + d.runs_extras for d in inning.deliveries)
    seq_str   = " ".join(seq)

    score_str = f"{batting.total_runs}/{batting.total_wickets}"
    if match.target_score:
        header = f"SUPER OVER | {batting.name} chasing {match.target_score}  {score_str}"
    else:
        header = f"SUPER OVER | {batting.name}  {score_str}"
    right = f"{seq_str} ({total_runs} runs)"

    lines = [
        "\n" + SEP,
        f"{header:<40} {right:>59}",
        DASH,
    ]

    def bat_stats(ip):
        if not ip:
            return ""
        return f"{ip.name:<20} {ip.runs_scored} ({ip.balls_faced})"

    lines.append(f"{bat_stats(match.striker):<45} | {_bowler_line(match.current_bowler)}")
    if match.non_striker:
        lines.append(f"{bat_stats(match.non_striker):<45} |")

    if match.target_score:
        lines.append(DASH)
        runs_needed = match.target_score - batting.total_runs
        if runs_needed <= 0:
            lines.append(f"  {batting.name} reached the target!")
        else:
            lines.append(f"  {batting.name} need {runs_needed} more run{'s' if runs_needed != 1 else ''} to win")

    lines.append(SEP + "\n")
    return "\n".join(lines)


def _build_did_not_bat(inning: Inning) -> list:
    """Returns names of players who never came to the crease."""
    return [
        ip.name for ip in inning.batting_team.inning_players
        if not ip.came_to_crease
    ]


def _build_fall_of_wickets(inning: Inning) -> list:
    """Returns [(name, score_str, over_str), ...] in the order wickets fell."""
    fow = []
    cumulative = 0
    wickets = 0
    for d in inning.deliveries:
        cumulative += d.runs_batter + d.runs_extras
        if d.is_wicket:
            wickets += 1
            name = d.batter.name if d.batter else "Unknown"
            fow.append((name, f"{cumulative}-{wickets}", f"{d.over_number}.{d.ball_number}"))
    return fow


def _build_dismissal_lookup(inning: Inning) -> dict:
    """Pre-build a {player_id: dismissal_string} map from all deliveries in an inning."""
    dismissal: dict = {}
    for d in inning.deliveries:
        if d.is_wicket and d.batter and d.batter.id not in dismissal:
            bowler  = d.bowler.name if d.bowler else ""
            fielder = d.outcome_player.name if d.outcome_player else ""
            dismissal[d.batter.id] = scorecard_dismissal(d.wicket_kind, bowler, fielder)
    return dismissal


def format_innings_scorecard(inning: Inning, is_super_over: bool = False) -> str:
    """
    Format one innings as a scorecard string.

    Uses ANSI 24-bit colour codes when the batting team has a primary_color set;
    falls back to plain text otherwise (safe for log files).
    """
    batting  = inning.batting_team
    bowling  = inning.bowling_team
    colored  = batting.primary_color is not None

    pcolor  = batting.primary_color  or "#333333"
    scolor  = batting.secondary_color or "#FFFFFF"
    bpcolor = bowling.primary_color  or "#333333"
    bscolor = bowling.secondary_color or "#FFFFFF"

    ovs = batting.total_balls // 6
    bls = batting.total_balls % 6
    ov_str = f"{ovs}.{bls}" if bls else f"{ovs}"

    innings_label = "Super Over" if is_super_over else "Innings"
    banner_left  = f"{batting.name} {innings_label}"
    banner_right = f"{batting.total_runs}-{batting.total_wickets} ({ov_str} Ov)"

    if colored:
        banner_plain = f"{banner_left:<70} {banner_right:>29}"
        lines = [
            "\n" + sep("="),
            bg(banner_plain, pcolor, scolor, bold=True),
            sep("="),
            hdr(f"{'Batter':<71} {'R':<5} {'B':<5} {'4s':<5} {'6s':<5} {'SR':<8}"),
            sep("-"),
        ]
    else:
        lines = [
            f"\n{'=' * 100}",
            f"{banner_left:<70} {banner_right:>29}",
            "=" * 100,
            f"{'Batter':<71} {'R':<5} {'B':<5} {'4s':<5} {'6s':<5} {'SR':<8}",
            "-" * 100,
        ]

    dismissal = _build_dismissal_lookup(inning)

    for ip in batting.inning_players:
        if not ip.came_to_crease:
            continue  # DNB

        not_out = not ip.is_out
        name    = ip.name + ("*" if not_out else "")
        status  = "not out" if not_out else dismissal.get(ip.id, "")
        sr      = f"{ip.runs_scored / ip.balls_faced * 100:.2f}" if ip.balls_faced else "0.00"

        row = (f"{name:<25} {status:<45} {ip.runs_scored:<5} {ip.balls_faced:<5}"
               f" {ip.fours:<5} {ip.sixes:<5} {sr:<8}")
        if colored:
            lines.append(bg(row, scolor, pcolor, bold=True) if not_out else bg(row, pcolor, scolor))
        else:
            lines.append(row)

    lines.append(sep("-") if colored else "-" * 100)

    extra_breakdown = (
        f"(b {batting.extras_byes}, lb {batting.extras_legbyes}, "
        f"w {batting.extras_wides}, nb {batting.extras_noballs}, p {batting.extras_penalty})"
    )
    extras_row = f"{'Extras':<71} {batting.extras} {extra_breakdown}"
    total_row  = f"{'Total':<71} {batting.total_runs}-{batting.total_wickets}"

    if colored:
        lines.append(bg(extras_row, pcolor, scolor))
        lines.append(bg(total_row,  pcolor, scolor, bold=True))
    else:
        lines.append(extras_row)
        lines.append(total_row)

    dnb = _build_did_not_bat(inning)
    if dnb:
        dnb_row = f"{'Did not Bat':<25} {', '.join(dnb)}"
        lines.append(bg(dnb_row, pcolor, scolor) if colored else dnb_row)

    lines.append("\n")
    bhdr_line = f"{'Bowler':<40} {'O':<5} {'M':<5} {'R':<5} {'W':<5} {'ECO':<8}"
    lines.append(hdr(bhdr_line) if colored else bhdr_line)
    lines.append(sep("-") if colored else "-" * 100)

    first_over = {d.bowler.id: d.over_number for d in reversed(inning.deliveries) if d.bowler}
    bowlers = sorted(
        (ip for ip in bowling.inning_players if ip.balls_bowled > 0 or ip.runs_conceded > 0),
        key=lambda ip: first_over.get(ip.id, float("inf")),
    )
    for ip in bowlers:
        o   = ip.balls_bowled // 6
        bl  = ip.balls_bowled % 6
        ov  = f"{o}.{bl}" if bl else f"{o}"
        eco = f"{ip.runs_conceded / (ip.balls_bowled / 6):.2f}" if ip.balls_bowled else "0.00"
        row = f"{ip.name:<40} {ov:<5} {ip.maidens:<5} {ip.runs_conceded:<5} {ip.wickets_taken:<5} {eco:<8}"
        lines.append(bg(row, bpcolor, bscolor) if colored else row)

    fow = _build_fall_of_wickets(inning)
    if fow:
        lines.append(sep("-") if colored else "-" * 100)
        fow_hdr = f"{'Fall of Wickets':<40} {'Score':<20} {'Over':<10}"
        lines.append(hdr(fow_hdr) if colored else fow_hdr)
        lines.append(sep("-") if colored else "-" * 100)
        for name, score_str, over_str in fow:
            row = f"{name:<40} {score_str:<20} {over_str:<10}"
            lines.append(bg(row, pcolor, scolor) if colored else row)

    lines.append(sep("=") if colored else "=" * 100)
    return "\n".join(lines)


# ── Match-level presentation (moved here from SimulationMatch) ─────────────────

def print_match_scorecard(match: SimulationMatch) -> None:
    """Print all completed innings scorecards with ANSI colours when team colors are set."""
    for inning in match.innings:
        if not inning.batting_team or not inning.bowling_team:
            continue
        print(format_innings_scorecard(inning))


def print_match_result(match: SimulationMatch, label: str = "", venue: str = "") -> None:
    """Print the match result block: teams, winner, description."""
    home    = match.home_team
    away    = match.away_team
    colored = home.primary_color is not None

    h_str     = rgb(home.name, home.primary_color, bold=True) if colored else bold(home.name)
    a_str     = rgb(away.name, away.primary_color, bold=True) if colored else bold(away.name)
    venue_str = f"  @ {dim(venue)}" if venue else ""

    print(f"\n  {bold(label) if label else ''}{venue_str}")
    print(f"  {h_str}  vs  {a_str}")
    if match.result and match.result.winner:
        winner_team   = home if home.name == match.result.winner else (
                        away if away.name == match.result.winner else None)
        wcolor        = winner_team.primary_color if winner_team else None
        winner_str    = "Winner: " + match.result.winner
        colored_winner = rgb(winner_str, wcolor, bold=True) if wcolor else bold(winner_str)
        print(f"  → {colored_winner}  {match.result.description}")
    else:
        desc = match.result.description if match.result else "No result"
        print(f"  → {desc}")
