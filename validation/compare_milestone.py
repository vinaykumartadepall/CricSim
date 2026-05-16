"""
Milestone factor comparison
===========================
Tests three configurations for the milestone context weight/k, plus the
reference state (current: adjusted weights, milestone_k=1).

Run from project root:
    python compare_milestone.py [--format T20|ODI|Test] [--samples N]
"""

import argparse
import sys
import os
import textwrap

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import simulator.strategies.ball_outcome_prediction.enhanced_historical_stats.strategy as _mod
from simulator.strategies.ball_outcome_prediction.enhanced_historical_stats import (
    EnhancedBaseHistoricalStatsStrategy,
)
from validation.delivery_validator import ModelValidator
from db.stats_repository import StatsRepository

# ── Weight definitions ────────────────────────────────────────────────────────

_ORIGINAL_WEIGHTS = {
    'T20': dict(batter=0.22, bowler=0.22, matchup=0.14, phase=0.20,
                venue=0.05, tournament=0.04, innings=0.06, milestone=0.07),
    'ODI': dict(batter=0.10, bowler=0.13, matchup=0.11, phase=0.40,
                venue=0.06, tournament=0.05, innings=0.08, milestone=0.07),
    'Test': dict(batter=0.21, bowler=0.26, matchup=0.14, phase=0.10,
                 venue=0.08, tournament=0.08, innings=0.07, milestone=0.06),
}

_ADJUSTED_WEIGHTS = {
    'T20': dict(batter=0.22, bowler=0.22, matchup=0.14, phase=0.17,
                venue=0.05, tournament=0.04, innings=0.04, milestone=0.12),
    'ODI': dict(batter=0.10, bowler=0.13, matchup=0.11, phase=0.37,
                venue=0.06, tournament=0.05, innings=0.06, milestone=0.12),
    'Test': dict(batter=0.21, bowler=0.26, matchup=0.14, phase=0.08,
                 venue=0.06, tournament=0.06, innings=0.04, milestone=0.15),
}


def _make_strategy(fmt: str, weights: dict) -> EnhancedBaseHistoricalStatsStrategy:
    """Dynamically subclass with fixed weights for the given format."""
    w = weights[fmt]

    class _ConfiguredStrategy(EnhancedBaseHistoricalStatsStrategy):
        @property
        def WEIGHTS(self):
            return w

    return _ConfiguredStrategy()


def _run(label: str, strategy, fmt: str, gender: str, samples: int, validator: ModelValidator,
         milestone_k: float):
    _mod._MILESTONE_K = milestone_k
    print(f"\n{'─'*60}")
    print(f"  Config: {label}")
    print(f"  milestone weight={strategy.WEIGHTS['milestone']:.2f}  milestone_k={milestone_k:.1f}")
    print(f"{'─'*60}")
    result = validator.validate(strategy, fmt, gender, samples)
    result.report()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--format',  default='T20',  choices=['T20', 'ODI', 'Test'])
    parser.add_argument('--gender',  default='male', choices=['male', 'female'])
    parser.add_argument('--samples', default=5000,   type=int)
    args = parser.parse_args()

    fmt, gender, samples = args.format, args.gender, args.samples

    repo      = StatsRepository()
    validator = ModelValidator(repo)

    configs = [
        # (label,                          weights dict,       milestone_k)
        ("Reference  (adjusted_w  k_m=1)", _ADJUSTED_WEIGHTS,  1.0),
        ("Option 1   (original_w  k_m=4)", _ORIGINAL_WEIGHTS,  4.0),
        ("Option 2   (adjusted_w  k_m=1)", _ADJUSTED_WEIGHTS,  1.0),  # same as reference
        ("Option 3   (adjusted_w  k_m=4)", _ADJUSTED_WEIGHTS,  4.0),
    ]

    results = []
    for label, wt, mk in configs:
        s = _make_strategy(fmt, wt)
        r = _run(label, s, fmt, gender, samples, validator, mk)
        results.append((label, r))

    print("\n" + "═"*72)
    print(f"  SUMMARY  {fmt} ({gender})  —  {samples:,} deliveries")
    print("═"*72)
    print(f"  {'Config':<38} {'LogLoss':>8}  {'BndErr':>7}  {'WktErr':>7}  {'DotErr':>7}  {'EcoErr':>7}")
    print(f"  {'─'*68}")
    for label, r in results:
        print(f"  {label:<38} {r.log_loss:>8.4f}  {r.boundary_rate_err:>7.4f}  "
              f"{r.wicket_rate_err:>7.4f}  {r.dot_rate_err:>7.4f}  {r.economy_err:>7.4f}")
    print("═"*72)
    print()
    print("  Lower log-loss = better predictive accuracy.")
    print("  Option 2 = Reference (same config), shown twice as a consistency check.")
    print()

    # Restore default
    _mod._MILESTONE_K = 1.0


if __name__ == '__main__':
    main()
