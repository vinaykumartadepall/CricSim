"""
Coloured terminal output for the tournament simulator.

Handles tournament-specific presentation only: banner, points table, leaderboards,
and player-of-the-tournament. Match scorecards and results are presented by
``simulator.presentation.formatters.print_match_scorecard`` and
``print_match_result``.

Color scheme:
  - Points table rows  : team primary bg, secondary text
  - Leaderboard rows   : plain (no team context per row)
  - Column headings    : fixed muted gray (#AAAAAA)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from simulator.presentation.colors import rgb, bg, bold, dim, hdr, sep, section_hdr

if TYPE_CHECKING:
    from simulator.tournament.config import TournamentConfig, TeamConfig
    from simulator.tournament.points_table import PointsTable
    from simulator.tournament.leaderboards import TournamentLeaderboards, BatterStats, BowlerStats
    from simulator.awards import PlayerAward, TournamentAwards


# ── Presenter ──────────────────────────────────────────────────────────────────

class Presenter:

    def __init__(self, config: "TournamentConfig"):
        self._config = config
        self._teams: Dict[str, "TeamConfig"] = config.team_by_name

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _bold_name(self, name: str) -> str:
        t = self._teams.get(name)
        color = t.primary_color if t else None
        return rgb(name, color, bold=True) if color else bold(name)

    def _team_colors(self, name: str) -> Tuple[str, str]:
        t = self._teams.get(name)
        return (t.primary_color, t.secondary_color) if t else ("#333333", "#FFFFFF")

    def _plain_badge(self, name: str) -> str:
        t = self._teams.get(name)
        short = t.short_name if t else name[:3].upper()
        return f"[{short}]"

    # ── Tournament banner ──────────────────────────────────────────────────────

    def print_tournament_header(self) -> None:
        cfg = self._config
        print()
        print(section_hdr(f"  {cfg.tournament_name}  ·  {cfg.format}  ·  {cfg.season}  "))
        print(f"  {len(cfg.teams)} teams  ·  format: {cfg.format}  ·  gender: {cfg.gender}")
        print(dim("─" * 72))
        print()

    # ── Points table ───────────────────────────────────────────────────────────

    def print_points_table(self, table: "PointsTable") -> None:
        print()
        print(section_hdr("  POINTS TABLE  "))
        hdr_line = (f"  {'#':<3} {'Cd':<4} {'Team':<22} {'M':>3} {'W':>3} {'L':>3}"
                    f" {'T':>3} {'NR':>3} {'Pts':>4} {'NRR':>8}")
        print(hdr(hdr_line))
        print(dim("─" * 72))
        for i, rec in enumerate(table.standings()):
            t      = self._teams.get(rec.name)
            pcolor = t.primary_color   if t else "#333333"
            scolor = t.secondary_color if t else "#FFFFFF"
            sname  = t.short_name if t else rec.name[:4]
            row    = (f"  {i+1:<3} {sname:<4} {rec.name:<22} {rec.played:>3} {rec.won:>3}"
                      f" {rec.lost:>3} {rec.tied:>3} {rec.no_result:>3}"
                      f" {rec.points:>4} {rec.nrr:>+8.3f}")
            print(bg(row, pcolor, scolor))
        print()

    # ── Leaderboards ──────────────────────────────────────────────────────────

    def print_leaderboards(self, boards: "TournamentLeaderboards") -> None:
        print()
        print(section_hdr("  TOURNAMENT LEADERBOARDS  "))

        self._batting_table("Most Runs",
                             boards.most_runs(10),
                             ["Runs", "Inn", "Avg", "SR", "HS", "4s", "6s"])
        self._batting_table("Highest Individual Scores",
                             boards.highest_score(10),
                             ["HS", "Runs", "Inn", "SR"])
        self._batting_table("Best Batting Average (min 3 dismissals)",
                             boards.best_batting_average(min_innings=3, top_n=10),
                             ["Avg", "Runs", "Inn", "SR"])
        self._batting_table("Best Strike Rate (min 50 balls)",
                             boards.best_strike_rate(min_balls=50, top_n=10),
                             ["SR", "Runs", "Balls"])
        self._batting_table("Most Sixes", boards.most_sixes(10), ["6s", "Runs", "SR"])
        self._batting_table("Most Fours", boards.most_fours(10), ["4s", "Runs", "SR"])

        self._bowling_table("Most Wickets",
                             boards.most_wickets(10),
                             ["Wkts", "Runs", "Overs", "Avg", "Eco", "BB"])
        self._bowling_table("Best Bowling Average (min 5 wickets)",
                             boards.best_bowling_average(min_wickets=5, top_n=10),
                             ["Avg", "Wkts", "Runs", "Eco"])
        self._bowling_table("Best Economy (min 10 overs)",
                             boards.best_economy(min_balls=60, top_n=10),
                             ["Eco", "Wkts", "Overs", "Avg"])

    def _batting_table(self, title: str, rows: List["BatterStats"], cols: List[str]) -> None:
        if not rows:
            return
        print(f"\n  {bold(title)}")
        hdr_line = f"  {'#':>3}  {'Player':<24} {'Team':<5}"
        for c in cols:
            hdr_line += f"  {c:>7}"
        print(hdr(hdr_line))
        print(dim("─" * 70))
        vals_map = {
            "Runs":  lambda s: str(s.runs),
            "Inn":   lambda s: str(s.innings),
            "Avg":   lambda s: s.average_display,
            "SR":    lambda s: f"{s.strike_rate:.1f}",
            "HS":    lambda s: f"{s.highest_score}{'*' if s.highest_score_not_out else ''}",
            "4s":    lambda s: str(s.fours),
            "6s":    lambda s: str(s.sixes),
            "Balls": lambda s: str(s.balls),
        }
        for i, s in enumerate(rows):
            pcolor, scolor = self._team_colors(s.team)
            badge = self._plain_badge(s.team)
            row   = f"  {i+1:>3}  {s.player_name:<24} {badge}"
            for c in cols:
                row += f"  {vals_map.get(c, lambda _: '-')(s):>7}"
            print(bg(row, pcolor, scolor))

    def _bowling_table(self, title: str, rows: List["BowlerStats"], cols: List[str]) -> None:
        if not rows:
            return
        print(f"\n  {bold(title)}")
        hdr_line = f"  {'#':>3}  {'Player':<24} {'Team':<5}"
        for c in cols:
            hdr_line += f"  {c:>7}"
        print(hdr(hdr_line))
        print(dim("─" * 70))
        vals_map = {
            "Wkts":  lambda s: str(s.wickets),
            "Runs":  lambda s: str(s.runs),
            "Overs": lambda s: f"{s.overs:.1f}",
            "Avg":   lambda s: f"{s.average:.2f}" if s.average != float("inf") else "inf",
            "Eco":   lambda s: f"{s.economy:.2f}",
            "BB":    lambda s: s.best_figures,
            "SR":    lambda s: f"{s.strike_rate:.1f}" if s.strike_rate != float("inf") else "inf",
        }
        for i, s in enumerate(rows):
            pcolor, scolor = self._team_colors(s.team)
            badge = self._plain_badge(s.team)
            row   = f"  {i+1:>3}  {s.player_name:<24} {badge}"
            for c in cols:
                row += f"  {vals_map.get(c, lambda _: '-')(s):>7}"
            print(bg(row, pcolor, scolor))

    # ── Awards ─────────────────────────────────────────────────────────────────

    def print_potm(self, potm: "PlayerAward", match_number: int) -> None:
        if not potm:
            return
        bd = potm.breakdown
        print(f"\n  Player of the Match #{match_number}: "
              f"{bold(potm.player_name)}  "
              f"({bd.get('batting_pts', 0.0):.1f} bat + {bd.get('bowling_pts', 0.0):.1f} bowl"
              f" + {bd.get('fielding_pts', 0.0):.1f} fld = {potm.total:.1f} pts)")

    def print_pott(self, awards: "TournamentAwards") -> None:
        lb = awards.leaderboard(10)
        if not lb:
            return
        print()
        print(section_hdr("  PLAYER OF THE TOURNAMENT  "))
        pott = lb[0]
        pcolor, scolor = self._team_colors(pott.team)
        winner_row = f"  ★  {pott.player_name}  —  {pott.total:.1f} points  ★"
        print()
        print(bg(winner_row, pcolor, scolor, bold=True))
        print()
        print(f"  Top-10 award points:")
        print(hdr(f"  {'#':>3}  {'Player':<24}  {'Team':<5}  {'Bat':>7}  {'Bowl':>7}  {'Field':>7}  {'Total':>7}"))
        print(dim("─" * 72))
        for i, p in enumerate(lb):
            pc, sc = self._team_colors(p.team)
            badge  = self._plain_badge(p.team)
            bd     = p.breakdown
            row    = (f"  {i+1:>3}  {p.player_name:<24}  {badge:<5}  {bd.get('batting_pts', 0.0):>7.1f}  "
                      f"{bd.get('bowling_pts', 0.0):>7.1f}  {bd.get('fielding_pts', 0.0):>7.1f}  {p.total:>7.1f}")
            print(bg(row, pc, sc))
        print()
