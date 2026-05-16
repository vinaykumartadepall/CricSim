"""
HistoricalBowlingOrder
======================
Replays the actual bowling order from a historical match, over by over.

Used during validation runs where we want to hold the bowling plan fixed
so that errors in the validation are attributable to the ball-outcome model,
not to bowling selection differences.

Toss-flip detection
-------------------
The simulation toss is random and may be opposite to the historical match.
When flipped, the bowling plan's player IDs belong to the *batting* team.
We detect this via a set-intersection check: if none of the plan's IDs for
the current inning match the actual bowling team, the two innings are swapped.
"""

from typing import Dict


class HistoricalBowlingOrder:
    _initialized = True

    def __init__(self, plan: Dict[int, Dict[int, int]]):
        # plan: {inning_number: {over_0indexed: bowler_player_id}}
        self._plan = plan
        # Cache the player-id sets per inning for fast toss-flip detection
        self._inning_ids: Dict[int, set] = {
            inn: set(overs.values()) for inn, overs in plan.items()
        }

    def init_model(self, match) -> None:
        pass

    def select_bowler(self, match):
        bowling_team = match.current_bowling_team
        if not bowling_team or not bowling_team.inning_players:
            return match.current_bowler

        inning_num = match.current_inning if match.current_inning else 1
        over_0     = match.current_over

        # Detect toss flip: if the historical bowlers for this inning belong to
        # the batting team (not bowling team), the toss outcome is the opposite
        # of the historical match.  Swap inning lookup so we follow the correct plan.
        bowling_ids = {ip.id for ip in bowling_team.inning_players}
        plan_ids    = self._inning_ids.get(inning_num, set())
        if plan_ids and not plan_ids.intersection(bowling_ids):
            # No overlap → wrong team is bowling; use the other inning's plan
            inning_num = 3 - inning_num  # 1 ↔ 2

        pid = self._plan.get(inning_num, {}).get(over_0)
        if pid is not None:
            for ip in bowling_team.inning_players:
                if ip.id == pid:
                    return ip

        eligible = [ip for ip in bowling_team.inning_players if ip != match.current_bowler]
        return eligible[0] if eligible else match.current_bowler
