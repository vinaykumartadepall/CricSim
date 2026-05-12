"""
Match commentary logger for the cricket simulator.

Owns all human-readable output for a single match. Separates three output tiers:

  Tier 1 — Match file  (match_logs/match_<id>.txt)
              Complete ball-by-ball narrative. Always written. No timestamps.
              Suitable for post-match review or piping into a formatter.

  Tier 2 — Console (stdout)
              Key moments only: match start, toss, session breaks, scorecards, result.
              Keeps terminal output digestible during a long simulation.

  Tier 3 — App logger (simulation.log via Python logging)
              Warnings and errors that affect simulation quality, e.g. player not
              found in cache, DB unavailable, fallback distribution activated.
              Written by the caller via log.warn() / log.error() — MatchLogger
              does not duplicate content that already goes to the match file.

Usage:
  logger = MatchLogger(match_id=1)
  logger.headline("=== Match Start ===")  # → file + console
  logger.ball("0.1  4 runs, Bumrah to Warner")  # → file only
  logger.over_summary(over_text)           # → file only
  logger.scorecard(scorecard_text)         # → file + console
  logger.close()                           # flush and close file
"""

import os
from simulator.logger import get_logger


class MatchLogger:
    """
    Single I/O surface for all match commentary output.
    Instantiate once per match, call close() (or use as a context manager) when done.
    """

    def __init__(self, match_id: int, log_dir: str = "match_logs"):
        os.makedirs(log_dir, exist_ok=True)
        self.file_path = os.path.join(log_dir, f"match_{match_id}.txt")
        self._file = open(self.file_path, "w", encoding="utf-8", buffering=1)
        self._log = get_logger()

    # ── Tier 1: file only ─────────────────────────────────────────────────────

    def ball(self, text: str) -> None:
        """Ball-by-ball delivery line. High volume — file only."""
        self._write(text)

    def over_summary(self, text: str) -> None:
        """Formatted over summary block. File only."""
        self._write(text)

    # ── Tier 2: file + console ────────────────────────────────────────────────

    def headline(self, text: str) -> None:
        """
        Key match moment: match start, toss, innings break, session break, result.
        Written to file and echoed to console.
        """
        self._write(text)
        print(text)

    def scorecard(self, text: str) -> None:
        """
        Full innings scorecard. Written to file and echoed to console.
        """
        self._write(text)
        print(text)

    # ── Tier 3: app logger (warnings / errors) ────────────────────────────────

    def warn(self, text: str) -> None:
        """Data quality warning — goes to the debug log (simulation.log), not the match file."""
        self._log.warning(text)

    def error(self, text: str) -> None:
        """Simulation error — goes to the debug log."""
        self._log.error(text)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Flush and close the match file."""
        self._file.flush()
        self._file.close()

    def __enter__(self) -> "MatchLogger":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _write(self, text: str) -> None:
        self._file.write(text + "\n")
