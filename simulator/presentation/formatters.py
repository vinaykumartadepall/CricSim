from enums.constants import ExtraType
from simulator.entities.match import SimulationMatch
from simulator.entities.inning import Inning


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


def format_over_summary(match: SimulationMatch, inning: Inning) -> str:
    if getattr(match, 'is_super_over', False):
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
    """
    Distinctive over-summary block for a super over innings.

    Layout (first innings / batting first):
        ══════════════════════
        SUPER OVER | India  14/1          1 W 1 0 6 6 (14 runs)
        ──────────────────────
        RR Pant*   13(4)  |  JJ Bumrah  1-0-14-1
        ══════════════════════

    Chase block also shows the result line:
        ... Australia need 5 more to win  /  Australia reached the target!
    """
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


def format_innings_scorecard(inning: Inning, is_super_over: bool = False) -> str:
    batting = inning.batting_team
    bowling = inning.bowling_team

    ovs = batting.total_balls // 6
    bls = batting.total_balls % 6
    ov_str = f"{ovs}.{bls}" if bls else f"{ovs}"

    innings_label = "Super Over" if is_super_over else "Innings"
    lines = [
        f"\n{'=' * 100}",
        f"{batting.name + ' ' + innings_label:<70} {f'{batting.total_runs}-{batting.total_wickets} ({ov_str} Ov)':>29}",
        "=" * 100,
        f"{'Batter':<71} {'R':<5} {'B':<5} {'4s':<5} {'6s':<5} {'SR':<8}",
        "-" * 100,
    ]

    # Players — skip DNB (hasn't batted, isn't currently at crease)
    # Note: match.striker/non_striker may belong to a later inning at scorecard time,
    # so we determine "currently batting" from is_out=False and balls_faced>0.
    for ip in batting.inning_players:
        if ip.balls_faced == 0 and not ip.is_out:
            continue  # DNB

        name = ip.name
        status = ""

        if ip.is_out:
            for d in inning.deliveries:
                if d.is_wicket and d.batter and d.batter.id == ip.id:
                    status = f"b {d.bowler.name}"
                    if d.wicket_kind == 'caught' and d.outcome_player:
                        status = f"c {d.outcome_player.name} b {d.bowler.name}"
                    elif d.wicket_kind == 'stumped' and d.outcome_player:
                        status = f"st {d.outcome_player.name} b {d.bowler.name}"
                    elif d.wicket_kind == 'run out':
                        status = f"run out ({d.outcome_player.name})" if d.outcome_player else "run out"
                    elif d.wicket_kind == 'lbw':
                        status = f"lbw b {d.bowler.name}"
                    break
        else:
            name += "*"
            status = "not out"

        sr = f"{(ip.runs_scored / ip.balls_faced * 100):.2f}" if ip.balls_faced > 0 else "0.00"
        lines.append(f"{name:<25} {status:<45} {ip.runs_scored:<5} {ip.balls_faced:<5} {ip.fours:<5} {ip.sixes:<5} {sr:<8}")

    lines.append("-" * 100)

    extra_breakdown = (
        f"(b {batting.extras_byes}, lb {batting.extras_legbyes}, "
        f"w {batting.extras_wides}, nb {batting.extras_noballs}, p {batting.extras_penalty})"
    )
    lines.append(f"{'Extras':<71} {batting.extras} {extra_breakdown}")
    lines.append(f"{'Total':<71} {batting.total_runs}-{batting.total_wickets}")

    lines.append("\n")
    lines.append(f"{'Bowler':<40} {'O':<5} {'M':<5} {'R':<5} {'W':<5} {'ECO':<8}")
    lines.append("-" * 100)

    first_over = {
        d.bowler.id: d.over_number
        for d in reversed(inning.deliveries)
        if d.bowler
    }
    bowlers = sorted(
        (ip for ip in bowling.inning_players if ip.balls_bowled > 0 or ip.runs_conceded > 0),
        key=lambda ip: first_over.get(ip.id, float('inf')),
    )
    for ip in bowlers:

        ovs = ip.balls_bowled // 6
        bls = ip.balls_bowled % 6
        ov_str = f"{ovs}.{bls}" if bls else f"{ovs}"
        eco = f"{(ip.runs_conceded / (ip.balls_bowled / 6)):.2f}" if ip.balls_bowled > 0 else "0.00"
        lines.append(f"{ip.name:<40} {ov_str:<5} {ip.maidens:<5} {ip.runs_conceded:<5} {ip.wickets_taken:<5} {eco:<8}")

    lines.append("=" * 100)
    return "\n".join(lines)
