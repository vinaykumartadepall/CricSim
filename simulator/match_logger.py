"""
Match commentary logger for the cricket simulator.

Routes all match output to the shared application logger — no per-match files written.
The [sim_id/m{match_id}] context on every line is injected automatically from
ContextVars set by log_context() in the worker before the simulation starts.

Severity mapping:
  ball / over_summary  → DEBUG   (high-volume ball-by-ball detail)
  scorecard            → DEBUG   (full scorecard text)
  headline             → INFO    (match lifecycle: toss, result, etc.)
  warn                 → WARNING (data issues, fallbacks)
  error                → ERROR   (simulation failures)

Console output (stdout) is controlled by MatchLogger.SILENT:
  False  Headlines and scorecards echo to stdout (CLI / single-match mode).
  True   All stdout suppressed (tournament / API mode).
"""

from simulator.logger import get_logger

_log = get_logger()


class MatchLogger:
    """
    Single output surface for match commentary.
    All output is routed to the shared application logger — no files created.
    """

    SILENT: bool = False

    def __init__(self, match_id: int, log_dir: str = "match_logs"):
        # log_dir kept for backwards-compatible call sites — not used
        self._match_id = match_id
        self.file_path = None
        _log.info("Match %d started", match_id)

    # ── DEBUG — high-volume ────────────────────────────────────────────────────

    def ball(self, text: str) -> None:
        _log.debug("%s", text)

    def over_summary(self, text: str) -> None:
        _log.debug("%s", text)

    # ── INFO + optional console ───────────────────────────────────────────────

    def headline(self, text: str) -> None:
        _log.info("%s", text.strip())
        if not MatchLogger.SILENT:
            print(text)

    def scorecard(self, text: str) -> None:
        _log.debug("%s", text)
        if not MatchLogger.SILENT:
            print(text)

    # ── WARNING / ERROR ───────────────────────────────────────────────────────

    def warn(self, text: str) -> None:
        _log.warning("%s", text)

    def error(self, text: str) -> None:
        _log.error("%s", text)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        _log.info("Match %d closed", self._match_id)

    def __enter__(self) -> "MatchLogger":
        return self

    def __exit__(self, *args) -> None:
        self.close()
