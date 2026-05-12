from simulator.entities.rules import MatchRules
from simulator.engines.limited_overs_engine import LimitedOversEngine
from simulator.engines.test_engine import TestMatchEngine

class EngineFactory:
    @staticmethod
    def create(match, ball_outcome_strategy, bowling_strategy=None):
        unified_format = MatchRules.get_unified_format(getattr(match, 'match_format', 'T20'))
        kwargs = {"bowling_strategy": bowling_strategy} if bowling_strategy is not None else {}

        if unified_format == "Test" or "TEST" in unified_format.upper():
            return TestMatchEngine(match, ball_outcome_strategy, **kwargs)

        return LimitedOversEngine(match, ball_outcome_strategy, **kwargs)
