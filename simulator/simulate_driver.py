"""
Kept for backward compatibility — delegates to MatchRunner.
New code should use run_match.py or MatchRunner directly.
"""

import argparse
import os

from simulator.match_runner import MatchRunner

_DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "match_config.json")


def main():
    parser = argparse.ArgumentParser(description="Cricket match simulator")
    parser.add_argument("--config", default=_DEFAULT_CONFIG,
                        help="Path to match config JSON")
    parser.add_argument("--silent", action="store_true")
    args = parser.parse_args()
    MatchRunner.from_config(args.config, silent=args.silent).run()


if __name__ == "__main__":
    main()
