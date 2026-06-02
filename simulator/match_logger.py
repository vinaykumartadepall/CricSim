"""
Match commentary logger for the cricket simulator.

Two files are written per match:

  match_<id>.txt   Ball-by-ball narrative. Plain text, no timestamps.
                   Always written regardless of SILENT flag.

  match_<id>.log   Full structured log for this match. Receives:
                     - Timestamped headline / warn / error entries
                     - All Python logger output routed through a dedicated
                       FileHandler attached during the match's lifetime.
                   This gives the same level of detail as simulation.log
                   but scoped to a single match, making per-match debugging
                   straightforward without hunting through a shared log.

Console output (Tier 2) is controlled by MatchLogger.SILENT:
  False (default)  Headlines and scorecards echo to stdout.
  True             All console output suppressed (tournament / batch mode).
                   Both files are still written in full.
"""

import logging
import os
import time
from simulator.logger import get_logger

_FILE_FMT = logging.Formatter(
    fmt="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)


class MatchLogger:
    """
    Single I/O surface for all match commentary output.
    Instantiate once per match; call close() (or use as a context manager) when done.
    """

    SILENT: bool = False  # suppress ALL console output (tournament/batch mode)

    def __init__(self, match_id: int, log_dir: str = "match_logs"):
        os.makedirs(log_dir, exist_ok=True)
        self._match_id = match_id

        # .txt — ball-by-ball narrative
        self.file_path = os.path.join(log_dir, f"match_{match_id}.txt")
        self._file     = open(self.file_path, "w", encoding="utf-8", buffering=1)

        # .log — full structured log, including Python logger output
        self._log_path = os.path.join(log_dir, f"match_{match_id}.log")
        self._logfile  = open(self._log_path, "w", encoding="utf-8", buffering=1)

        # Attach a FileHandler on the shared app logger so all log.debug/info/warning
        # calls during this match also land in the per-match .log file.
        self._app_log  = get_logger()
        self._handler  = logging.StreamHandler(self._logfile)
        self._handler.setLevel(logging.DEBUG)
        self._handler.setFormatter(_FILE_FMT)
        self._app_log.addHandler(self._handler)

        self._log_entry("INFO", f"Match {match_id} started")

    # ── .txt file only ────────────────────────────────────────────────────────

    def ball(self, text: str) -> None:
        self._write(text)

    def over_summary(self, text: str) -> None:
        self._write(text)

    # ── .txt + .log + optional console ───────────────────────────────────────

    def headline(self, text: str) -> None:
        self._write(text)
        self._log_entry("INFO", text.strip())
        if not MatchLogger.SILENT:
            print(text)

    def scorecard(self, text: str) -> None:
        self._write(text)
        if not MatchLogger.SILENT:
            print(text)

    # ── .log + simulation.log ─────────────────────────────────────────────────

    def warn(self, text: str) -> None:
        self._app_log.warning(text)
        self._log_entry("WARN", text)

    def error(self, text: str) -> None:
        self._app_log.error(text)
        self._log_entry("ERROR", text)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._log_entry("INFO", f"Match {self._match_id} closed")

        # Detach the per-match handler before closing the file
        self._app_log.removeHandler(self._handler)
        self._handler.close()

        self._file.flush();   self._file.close()
        self._logfile.flush(); self._logfile.close()

    def __enter__(self) -> "MatchLogger":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _write(self, text: str) -> None:
        self._file.write(text + "\n")

    def _log_entry(self, level: str, text: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self._logfile.write(f"{ts}  {level:<5}  {text}\n")
        self._logfile.flush()
