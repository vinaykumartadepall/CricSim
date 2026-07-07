"""
Smart Bowling Strategy
======================
Mimics real-world captaincy decisions over-by-over:

  Quota    — T20: 4 overs max, ODI: 10 overs max, Test: unlimited
  No repeats — the same bowler can never bowl consecutive overs
  Spell mgmt — Test only: after 7+ consecutive overs a bowler must rest
               for at least 4 overs before returning
  Scoring  — every eligible bowler gets a score; highest wins:
               • Wickets:  +8 per wicket (reward on-fire bowlers)
               • Economy:  +max(0, 10 - eco) (reward tight bowlers)
               • Workload: -0.5 per over bowled (spread the load)
               • Phase:    powerplay → prefer fresh arms
                           death     → prefer wicket-takers + economy
               • Rest:     Test only, bonus for a well-rested returning bowler
"""

from typing import Optional

from simulator.entities.inning_player import InningPlayer
from simulator.entities.match import SimulationMatch
from simulator.entities.rules import MatchRules
from simulator.predictors.bowling.strategy_interface import BowlingStrategy


# Max overs per bowler (None = no cap)
_QUOTA: dict[str, Optional[int]] = {"T20": 4, "ODI": 10, "Test": None}

# Test spell management
_SPELL_LIMIT = 7   # consecutive overs before mandatory rest
_SPELL_REST  = 4   # overs of rest required after a long spell


class SmartBowlingStrategy(BowlingStrategy):

    def select_bowler(self, match: SimulationMatch) -> Optional[InningPlayer]:
        team = match.current_bowling_team
        if not team or not team.inning_players:
            return match.current_bowler

        fmt   = MatchRules.get_unified_format(match.match_format)
        quota = _QUOTA.get(fmt)

        eligible = self._eligible(team, match.current_bowler, match, fmt, quota)

        if not eligible:
            # Relax spell constraint (Test edge case: very long innings, few bowlers)
            eligible = [
                ip for ip in team.inning_players
                if ip != match.current_bowler and (not quota or ip.balls_bowled // 6 < quota)
            ]

        if not eligible:
            return match.current_bowler

        return max(eligible, key=lambda ip: self._score(ip, match, fmt))

    # ── Eligibility ───────────────────────────────────────────────────────────

    def _eligible(self, team, current_bowler, match, fmt, quota):
        result = []
        for ip in team.inning_players:
            if ip == current_bowler:
                continue
            if quota and ip.balls_bowled // 6 >= quota:
                continue
            if fmt == "Test" and self._needs_rest(ip.id, match):
                continue
            result.append(ip)
        return result

    def _needs_rest(self, player_id: int, match: SimulationMatch) -> bool:
        if self._last_spell_length(player_id, match) < _SPELL_LIMIT:
            return False
        return self._overs_since_bowled(player_id, match) < _SPELL_REST

    # ── Spell helpers (derived from inning deliveries) ────────────────────────

    def _last_spell_length(self, player_id: int, match: SimulationMatch) -> int:
        """Consecutive overs at the END of the player's bowling history this innings."""
        bowled = sorted({
            d.over_number
            for d in match.innings[-1].deliveries
            if d.bowler and d.bowler.id == player_id
        })
        if not bowled:
            return 0
        spell = 1
        for i in range(len(bowled) - 2, -1, -1):
            if bowled[i] == bowled[i + 1] - 1:
                spell += 1
            else:
                break
        return spell

    def _overs_since_bowled(self, player_id: int, match: SimulationMatch) -> int:
        """
        How many overs ago did this player last bowl?
        Returns 999 if they haven't bowled yet this innings.
        over_number in deliveries is 1-indexed; match.current_over is 0-indexed
        (next over), so the next over is match.current_over + 1 in 1-indexed terms.
        """
        bowled = {
            d.over_number
            for d in match.innings[-1].deliveries
            if d.bowler and d.bowler.id == player_id
        }
        if not bowled:
            return 999
        next_over_1idx = match.current_over + 1
        return next_over_1idx - max(bowled)

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score(self, ip: InningPlayer, match: SimulationMatch, fmt: str) -> float:
        score = 0.0

        if ip.balls_bowled >= 6:
            economy = ip.runs_conceded / (ip.balls_bowled / 6)
            score += max(0.0, 10.0 - economy)
        else:
            score += 5.0  # untested this innings — neutral benefit of the doubt

        score += ip.wickets_taken * 8.0
        score -= (ip.balls_bowled // 6) * 0.5

        phase = MatchRules.get_phase(match.current_over, fmt, match.overs_per_innings)
        if phase == "powerplay":
            if ip.balls_bowled == 0:
                score += 6.0
        elif phase == "death":
            score += ip.wickets_taken * 4.0
            if ip.balls_bowled >= 6:
                economy = ip.runs_conceded / (ip.balls_bowled / 6)
                score += max(0.0, 8.0 - economy) * 2.0

        if fmt == "Test":
            rested = self._overs_since_bowled(ip.id, match)
            if _SPELL_REST <= rested <= _SPELL_REST * 2:
                score += 4.0

        return score
