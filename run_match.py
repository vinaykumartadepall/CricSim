#!/usr/bin/env python3
"""
Single match simulation entry point.

Usage:
    python run_match.py --config match_config.json
    python run_match.py --config match_config.json --silent
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simulator.match_runner import MatchRunner


def main():
    parser = argparse.ArgumentParser(description="Cricket match simulator")
    parser.add_argument(
        "--config", default="match_config.json",
        help="Path to match config JSON",
    )
    parser.add_argument("--silent", action="store_true",
                        help="Suppress match output; only write log files")
    args = parser.parse_args()

    MatchRunner.from_config(args.config, silent=args.silent).run()


if __name__ == "__main__":
    main()
