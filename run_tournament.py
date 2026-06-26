#!/usr/bin/env python3
"""
Tournament simulation entry point.

Usage:
    python run_tournament.py --config tournament_config.json
    python run_tournament.py --config tournament_config.json --seed 42 --silent
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simulator.tournament.engine import TournamentEngine


def main():
    parser = argparse.ArgumentParser(description="Cricket tournament simulator")
    parser.add_argument(
        "--config", default="tournament_config.json",
        help="Path to tournament config JSON",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--silent", action="store_true",
                        help="Suppress match-by-match output; only print final tables")
    args = parser.parse_args()

    engine = TournamentEngine.from_config(args.config, seed=args.seed, silent=args.silent)
    engine.run()


if __name__ == "__main__":
    main()
