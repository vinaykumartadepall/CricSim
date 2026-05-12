"""
Super Over Engine
=================
Resolves a tied T20/ODI match with a single super-over per team.

Rules
-----
- Each team faces exactly 1 over (6 legal deliveries + extras).
- Innings ends at 2 wickets, not 10.
- Any player from the squad may bat or bowl regardless of main-match performance.
- The team that batted second in the main match bats first in the super over.

Player selection
----------------
Batters (top 3):
    score = 0.60 * global_death_score + 0.30 * match_death_score + 0.10 * match_full_score

    global_death_score  = (death_sr / 150) * 0.30 + (boundary_rate / 0.20) * 0.70
    match_death_score   = (death_sr_today / 160) * 0.30 + (death_bdry_today / 0.20) * 0.70
    match_full_score    = (sr_today / 160) * 0.30 + (bdry_today / 0.20) * 0.70

Bowler (1 per team):
    score = 0.60 * global_death_score + 0.30 * match_death_score + 0.10 * match_full_score

    global_death_score  = eco_part * reliability
    match_death_score   = eco_part from death balls bowled this match
    match_full_score    = eco_part from all balls bowled this match

Fallback: players without enough historical data receive a small non-zero base
score so they are never completely excluded if no alternatives exist.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from db.stats_repository import StatsRepository
from simulator.entities.inning import Inning
from simulator.entities.inning_player import InningPlayer
from simulator.entities.inning_team import InningTeam
from simulator.entities.match import SimulationMatch
from simulator.entities.player import Player
from simulator.entities.team import MatchTeam
from simulator.engines.innings_simulator import InningsSimulator
from simulator.events import MatchEvent, EventType
from simulator.logger import get_logger
from simulator.match_logger import MatchLogger
from simulator.presentation.formatters import format_innings_scorecard
from simulator.strategies.ball_outcome_prediction.strategy_interface import BallOutcomeStrategy
from simulator.strategies.bowling.strategy_interface import BowlingStrategy

_log = get_logger()

_GLOBAL_W       = 0.60
_MATCH_DEATH_W  = 0.30   # death-phase performance in this match
_MATCH_FULL_W   = 0.10   # full-match performance (lower-weight tiebreaker)

_DEATH_SR_REF   = 150.0
_BDRY_RATE_REF  = 0.20
_DEATH_ECO_REF  = 16.0
_DEATH_WR_REF   = 0.15

_FALLBACK_SCORE = 0.05


# ── Result ─────────────────────────────────────────────────────────────────────

@dataclass
class SuperOverResult:
    batting_first_team:     str
    batting_first_runs:     int
    batting_first_wickets:  int
    batting_second_team:    str
    batting_second_runs:    int
    batting_second_wickets: int
    winner:                 Optional[str]
    batting_first_batters:  List[str] = field(default_factory=list)
    batting_first_bowler:   str = ""
    batting_second_batters: List[str] = field(default_factory=list)
    batting_second_bowler:  str = ""

    def report(self, logger: MatchLogger) -> str:
        b1 = f"{self.batting_first_team}: {self.batting_first_runs}/{self.batting_first_wickets}"
        b2 = f"{self.batting_second_team}: {self.batting_second_runs}/{self.batting_second_wickets}"
        if self.winner:
            result_line = f"*** {self.winner} ***"
        else:
            result_line = "*** Super Over Tied! (boundary countback in real cricket) ***"
        lines = [
            "\n" + "=" * 70,
            "  SUPER OVER RESULT",
            f"  {b1}",
            f"  {b2}",
            "-" * 70,
            f"  {result_line}",
            "=" * 70,
        ]
        text = "\n".join(lines)
        logger.headline(text)
        return text


# ── Selector ───────────────────────────────────────────────────────────────────

class SuperOverSelector:
    """Picks 3 batters and 1 bowler per team for a super over."""

    def __init__(self, repo: StatsRepository):
        self._repo = repo

    def select_batters(
        self,
        team: MatchTeam,
        team_inning: Inning,
        match_format: str,
        gender: str,
        n: int = 3,
    ) -> List[Player]:
        player_ids  = [p.id for p in team.players]
        death_stats = self._repo.get_batter_death_stats(player_ids, match_format, gender)
        match_perf  = {ip.id: ip for ip in team_inning.batting_team.inning_players}

        scores: Dict[int, float] = {}
        id_to_player = {p.id: p for p in team.players}
        _log.info("[SuperOver] === %s batter selection ===", team.name)
        for player in team.players:
            pid       = player.id
            bat_death = death_stats.get(pid)
            g         = self._global_bat(bat_death)
            ip        = match_perf.get(pid)
            m_death, m_full = self._match_bat_split(ip)

            if bat_death:
                death_sr  = bat_death.get('death_sr', 0.0)
                bdry_rate = bat_death.get('boundary_rate', 0.0)
                balls     = bat_death.get('balls', 0)
                _log.info(
                    "[SuperOver]   %-22s | global: death_sr=%.1f  bdry_rate=%.3f  balls=%d  g_score=%s",
                    player.name, death_sr, bdry_rate, balls,
                    f"{g:.3f}" if g is not None else "None",
                )
            else:
                _log.info(
                    "[SuperOver]   %-22s | global: no death bat stats  g_score=%s",
                    player.name, f"{g:.3f}" if g is not None else "None",
                )

            if ip and ip.death_balls_faced > 0:
                d_sr   = ip.death_runs_scored / ip.death_balls_faced
                d_bdry = (ip.death_fours + ip.death_sixes) / ip.death_balls_faced
                _log.info(
                    "[SuperOver]   %-22s | match(death): runs=%d  balls=%d  sr=%.2f  bdry=%.3f  m_death=%.3f",
                    player.name, ip.death_runs_scored, ip.death_balls_faced, d_sr, d_bdry, m_death,
                )
            else:
                _log.info("[SuperOver]   %-22s | match(death): no death balls  m_death=0.000", player.name)

            if ip and ip.balls_faced > 0:
                sr_full   = ip.runs_scored / ip.balls_faced
                bdry_full = (ip.fours + ip.sixes) / ip.balls_faced
                _log.info(
                    "[SuperOver]   %-22s | match(full):  runs=%d  balls=%d  sr=%.2f  bdry=%.3f  m_full=%.3f",
                    player.name, ip.runs_scored, ip.balls_faced, sr_full, bdry_full, m_full,
                )
            else:
                _log.info("[SuperOver]   %-22s | match(full):  did not bat  m_full=0.000", player.name)

            m_total = _MATCH_DEATH_W * m_death + _MATCH_FULL_W * m_full
            scores[pid] = (
                _GLOBAL_W * g + m_total
                if g is not None
                else (m_total if m_total > 0 else _FALLBACK_SCORE)
            )
            _log.info(
                "[SuperOver]   %-22s | combined: %.3f  (global=%s×%.2f  death=%s×%.2f  full=%s×%.2f)",
                player.name, scores[pid],
                f"{g:.3f}" if g is not None else "None", _GLOBAL_W,
                f"{m_death:.3f}", _MATCH_DEATH_W,
                f"{m_full:.3f}", _MATCH_FULL_W,
            )

        top_ids  = sorted(scores, key=lambda x: scores[x], reverse=True)[:n]
        selected = [id_to_player[pid] for pid in top_ids if pid in id_to_player]

        ranking = sorted(
            ((id_to_player[pid].name, scores[pid]) for pid in scores if pid in id_to_player),
            key=lambda x: x[1], reverse=True,
        )
        _log.info(
            "[SuperOver] %s batter ranking: %s",
            team.name,
            "  ".join(f"{name}={sc:.3f}" for name, sc in ranking),
        )
        _log.info("[SuperOver] %s selected batters: %s", team.name, ", ".join(p.name for p in selected))
        return selected

    def select_bowler(
        self,
        bowling_team: MatchTeam,
        bowling_inning: Inning,
        match_format: str,
        gender: str,
    ) -> Player:
        player_ids  = [p.id for p in bowling_team.players]
        phase_stats = self._repo.get_bowler_phase_stats(player_ids, match_format, gender)
        match_perf  = {ip.id: ip for ip in bowling_inning.bowling_team.inning_players}

        scores: Dict[int, float] = {}
        id_to_player = {p.id: p for p in bowling_team.players}
        _log.info("[SuperOver] === %s bowler selection ===", bowling_team.name)
        for player in bowling_team.players:
            pid   = player.id
            death = phase_stats.get(pid, {}).get('death')
            g     = self._global_bowl(death)
            ip    = match_perf.get(pid)
            m_death, m_full = self._match_bowl_split(ip)

            if death and death.get('balls', 0) >= 12:
                balls       = death['balls']
                eco         = death.get('economy', _DEATH_ECO_REF)
                reliability = min(1.0, balls / 300.0)
                eco_part    = max(0.0, (_DEATH_ECO_REF - eco) / _DEATH_ECO_REF)
                _log.info(
                    "[SuperOver]   %-22s | global: eco=%.2f  balls=%d  reliability=%.2f  eco_part=%.3f  g_score=%.3f",
                    player.name, eco, balls, reliability, eco_part, g,
                )
            elif death:
                _log.info(
                    "[SuperOver]   %-22s | global: insufficient death balls (%d < 12)  g_score=None",
                    player.name, death.get('balls', 0),
                )
            else:
                _log.info(
                    "[SuperOver]   %-22s | global: no death bowl stats  g_score=None",
                    player.name,
                )

            if ip and ip.death_balls_bowled > 0:
                d_eco = ip.death_runs_conceded / (ip.death_balls_bowled / 6.0)
                _log.info(
                    "[SuperOver]   %-22s | match(death): eco=%.2f  balls=%d  m_death=%.3f",
                    player.name, d_eco, ip.death_balls_bowled, m_death,
                )
            else:
                _log.info("[SuperOver]   %-22s | match(death): no death balls bowled  m_death=0.000", player.name)

            if ip and ip.balls_bowled > 0:
                full_eco = ip.runs_conceded / (ip.balls_bowled / 6.0)
                _log.info(
                    "[SuperOver]   %-22s | match(full):  eco=%.2f  balls=%d  m_full=%.3f",
                    player.name, full_eco, ip.balls_bowled, m_full,
                )
            else:
                _log.info("[SuperOver]   %-22s | match(full):  did not bowl  m_full=0.000", player.name)

            m_total = _MATCH_DEATH_W * m_death + _MATCH_FULL_W * m_full
            scores[pid] = (
                _GLOBAL_W * g + m_total
                if g is not None
                else (m_total if m_total > 0 else _FALLBACK_SCORE)
            )
            _log.info(
                "[SuperOver]   %-22s | combined: %.3f  (global=%s×%.2f  death=%s×%.2f  full=%s×%.2f)",
                player.name, scores[pid],
                f"{g:.3f}" if g is not None else "None", _GLOBAL_W,
                f"{m_death:.3f}", _MATCH_DEATH_W,
                f"{m_full:.3f}", _MATCH_FULL_W,
            )

        best_id  = max(scores, key=lambda x: scores[x])
        selected = id_to_player[best_id]

        ranking = sorted(
            ((id_to_player[pid].name, scores[pid]) for pid in scores if pid in id_to_player),
            key=lambda x: x[1], reverse=True,
        )
        _log.info(
            "[SuperOver] %s bowler ranking: %s",
            bowling_team.name,
            "  ".join(f"{name}={sc:.3f}" for name, sc in ranking),
        )
        _log.info("[SuperOver] %s selected bowler: %s", bowling_team.name, selected.name)
        return selected

    # ── score helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _global_bat(death: Optional[Dict]) -> Optional[float]:
        if not death:
            return None
        # Boundary rate is the primary signal: a super over needs sixes and fours.
        # Strike rate is a secondary confirmation.
        sr_part   = min(1.0, death.get('death_sr',      0.0) / _DEATH_SR_REF)
        bdry_part = min(1.0, death.get('boundary_rate', 0.0) / _BDRY_RATE_REF)
        return bdry_part * 0.70 + sr_part * 0.30

    @staticmethod
    def _match_bat_split(ip: Optional[InningPlayer]):
        """Returns (death_score, full_score) for a batter's match performance."""
        def _bat_score(runs, balls, bdries):
            if balls == 0:
                return 0.0
            bdry_part = min(1.0, (bdries / balls) / _BDRY_RATE_REF)
            sr_part   = min(1.0, (runs / balls) / 1.60)
            return bdry_part * 0.70 + sr_part * 0.30

        if not ip:
            return 0.0, 0.0
        m_death = _bat_score(ip.death_runs_scored, ip.death_balls_faced,
                             ip.death_fours + ip.death_sixes)
        m_full  = _bat_score(ip.runs_scored, ip.balls_faced, ip.fours + ip.sixes)
        return m_death, m_full

    @staticmethod
    def _global_bowl(death: Optional[Dict]) -> Optional[float]:
        if not death or death.get('balls', 0) < 12:
            return None
        balls    = death['balls']
        eco_part    = max(0.0, (_DEATH_ECO_REF - death.get('economy', _DEATH_ECO_REF)) / _DEATH_ECO_REF)
        reliability = min(1.0, balls / 300.0)
        return eco_part * reliability

    @staticmethod
    def _match_bowl_split(ip: Optional[InningPlayer]):
        """Returns (death_score, full_score) for a bowler's match performance."""
        def _bowl_score(runs, balls):
            if balls == 0:
                return 0.0
            eco = runs / (balls / 6.0)
            return max(0.0, (_DEATH_ECO_REF - eco) / _DEATH_ECO_REF)

        if not ip:
            return 0.0, 0.0
        m_death = _bowl_score(ip.death_runs_conceded, ip.death_balls_bowled)
        m_full  = _bowl_score(ip.runs_conceded, ip.balls_bowled)
        return m_death, m_full


# ── Engine ─────────────────────────────────────────────────────────────────────

class SuperOverEngine:
    """
    Runs one super over per team to break a tie in a limited-overs match.

    The ball-outcome and bowling strategies must already be initialised
    (init_model already called on them by the parent match engine).

    Standalone usage for testing::

        engine = SuperOverEngine(match, ball_outcomes, bowling_strategy, logger, repo)
        result = engine.run(team1, team2, team1_inning, team2_inning)
        result.report(logger)
    """

    MAX_WICKETS = 2

    def __init__(
        self,
        match: SimulationMatch,
        ball_outcomes: BallOutcomeStrategy,
        bowling_strategy: BowlingStrategy,
        logger: MatchLogger,
        repo: StatsRepository,
    ):
        self.match            = match
        self.ball_outcomes    = ball_outcomes
        self.bowling_strategy = bowling_strategy
        self.logger           = logger
        self._selector        = SuperOverSelector(repo)

    def run(
        self,
        team1: MatchTeam,
        team2: MatchTeam,
        team1_inning: Inning,
        team2_inning: Inning,
    ) -> SuperOverResult:
        """
        team1 batted second in the main match and bats first in the super over (real cricket rule).
        team2 then chases team1's super-over total.

        The super over is wired as a last-over death situation:
          - match.current_over is set to the final over (0-indexed) so the ball
            prediction sees 'death2' phase stats and death-over pressure.
          - match.overs_per_innings is set to 1 so the pressure math counts
            only 6 balls remaining, not 120.
        """
        fmt    = self.match.match_format
        gender = self.match.gender

        # Save the real over count so we can compute the last-over index.
        # Setting overs_per_innings=1 makes pressure math correct for 6 balls.
        orig_overs = self.match.overs_per_innings or 20
        death_over_0idx = orig_overs - 1   # 0-indexed last over → 1-indexed = orig_overs = death2

        self.logger.headline("\n\n" + "=" * 70 + "\n  SUPER OVER\n" + "=" * 70 + "\n")

        # ── team1 bats first ─────────────────────────────────────────────────
        # Bowling match-perf must come from the inning the team actually BOWLED in.
        # team2 bowled during team1_inning (when team1 batted); team1 bowled during team2_inning.
        t1_batters = self._selector.select_batters(team1, team1_inning, fmt, gender)
        t2_bowler  = self._selector.select_bowler(team2, team1_inning, fmt, gender)
        self.logger.headline(
            f"  {team1.name} batting: {', '.join(p.name for p in t1_batters)}\n"
            f"  {team2.name} bowling: {t2_bowler.name}\n"
        )
        inn1 = self._run_super_innings(
            batting_squad=team1,
            batting_players=t1_batters,
            bowling_squad=team2,
            bowler_override=t2_bowler,
            target=None,
            death_over_0idx=death_over_0idx,
        )

        # ── team2 chases ─────────────────────────────────────────────────────
        t2_batters = self._selector.select_batters(team2, team2_inning, fmt, gender)
        t1_bowler  = self._selector.select_bowler(team1, team2_inning, fmt, gender)
        target     = inn1.batting_team.total_runs + 1
        self.logger.headline(
            f"  {team2.name} batting: {', '.join(p.name for p in t2_batters)}\n"
            f"  {team1.name} bowling: {t1_bowler.name}\n"
            f"  {team2.name} need {target} run{'s' if target != 1 else ''} to win\n"
        )
        inn2 = self._run_super_innings(
            batting_squad=team2,
            batting_players=t2_batters,
            bowling_squad=team1,
            bowler_override=t1_bowler,
            target=target,
            death_over_0idx=death_over_0idx,
        )

        result = self._build_result(team1, inn1, t1_batters, t1_bowler,
                                    team2, inn2, t2_batters, t2_bowler)
        result.report(self.logger)
        return result

    # ── private ──────────────────────────────────────────────────────────────

    def _run_super_innings(
        self,
        batting_squad:    MatchTeam,
        batting_players:  List[Player],
        bowling_squad:    MatchTeam,
        bowler_override:  Player,
        target:           Optional[int],
        death_over_0idx:  int = 19,
    ) -> Inning:
        # Batting side: only the 3 selected players, so 2 wickets = innings over
        bat_team  = MatchTeam(id=batting_squad.id,  name=batting_squad.name,  players=list(batting_players))
        bowl_team = MatchTeam(id=bowling_squad.id,  name=bowling_squad.name,  players=list(bowling_squad.players))

        bat_it   = InningTeam.from_match_team(bat_team)
        bowl_it  = InningTeam.from_match_team(bowl_team)

        inning_num = len(self.match.innings) + 1
        inning     = Inning(inning_num, bat_it, bowl_it)
        self.match.innings.append(inning)

        self.match.current_inning       = inning_num
        self.match.current_batting_team = bat_it
        self.match.current_bowling_team = bowl_it
        # Start at the last over so the ball-prediction model sees 'death2' phase
        # and pressure math treats this as 6 balls left (not 120).
        self.match.current_over         = death_over_0idx
        self.match.overs_per_innings    = 1
        self.match.current_ball         = 0
        self.match.target_score         = target
        self.match.is_super_over        = True

        self.match.event_bus.clear()
        self.match.event_bus.subscribe(bat_it)
        self.match.event_bus.subscribe(bowl_it)
        for ip in bat_it.inning_players:
            self.match.event_bus.subscribe(ip)
        for ip in bowl_it.inning_players:
            self.match.event_bus.subscribe(ip)

        self.match.striker, self.match.non_striker = bat_it.get_openers()

        # Force the pre-selected bowler; fall back to first available if not found
        self.match.current_bowler = next(
            (ip for ip in bowl_it.inning_players if ip.id == bowler_override.id),
            bowl_it.inning_players[0] if bowl_it.inning_players else None,
        )

        def _target_reached() -> bool:
            return (
                target is not None
                and self.match.current_batting_team.total_runs >= target
            )

        sim = InningsSimulator(self.match, self.ball_outcomes, self.logger, self.bowling_strategy)
        # max_overs must be > current_over so the loop runs exactly one over.
        sim.run(
            max_overs=death_over_0idx + 1,
            max_wickets=self.MAX_WICKETS,
            should_terminate=_target_reached if target else None,
        )

        self.logger.scorecard(format_innings_scorecard(inning, is_super_over=True))
        return inning

    @staticmethod
    def _build_result(
        team1: MatchTeam, inn1: Inning, t1_batters: List[Player], t1_bowler: Player,
        team2: MatchTeam, inn2: Inning, t2_batters: List[Player], t2_bowler: Player,
    ) -> SuperOverResult:
        t1r = inn1.batting_team.total_runs
        t1w = inn1.batting_team.total_wickets
        t2r = inn2.batting_team.total_runs
        t2w = inn2.batting_team.total_wickets

        if t2r > t1r:
            winner = f"{team2.name} won the Super Over by {SuperOverEngine.MAX_WICKETS - t2w} wicket(s)!"
        elif t1r > t2r:
            winner = f"{team1.name} won the Super Over by {t1r - t2r} run(s)!"
        else:
            winner = None

        return SuperOverResult(
            batting_first_team     = team1.name,
            batting_first_runs     = t1r,
            batting_first_wickets  = t1w,
            batting_second_team    = team2.name,
            batting_second_runs    = t2r,
            batting_second_wickets = t2w,
            winner                 = winner,
            batting_first_batters  = [p.name for p in t1_batters],
            batting_first_bowler   = t1_bowler.name,
            batting_second_batters = [p.name for p in t2_batters],
            batting_second_bowler  = t2_bowler.name,
        )
