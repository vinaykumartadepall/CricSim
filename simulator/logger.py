"""
Application-level logger for the cricket simulator.

Log levels:
  TRACE    5  per-ball/per-over probability tables (outcome distribution dumps,
              bowling-selection scoring breakdowns) — extremely high volume,
              meant for a developer debugging one match closely, not for
              leaving on during a multi-simulation run or load test
  DEBUG   10  moderate per-ball detail, cache timing
  INFO    20  match headlines, scorecard summaries, lifecycle events, SQL
              queries (see db/database.py's make_debug_logging_cursor and
              db/stats_repository.py's _run_query) — kept out of DEBUG/TRACE
              so query visibility doesn't require wading through the above
  WARNING 30  data issues: player not in cache, venue not found, fallback activated
  ERROR   40  unexpected failures that may affect simulation correctness

Every log line carries [sim_id/m{match_id}] context injected automatically from
ContextVars — safe for concurrent runs in the same process.

Usage:
  from simulator.logger import get_logger, log_context
  _log = get_logger()
  with log_context(sim_id="abc123", match_id=5):
      _log.info("Starting match")   # → [abc123/m5]  Starting match

Runtime level switching (API):
  from simulator.logger import set_log_level
  set_log_level("DEBUG")   # accepts TRACE / DEBUG / INFO / WARNING / ERROR

Log files (server mode, set up by configure_logger()):
  logs/simulation.log   configurable level (default INFO), 20MB × 10 = 200MB max
  logs/errors.log       WARNING and above only,            5MB  × 5  =  25MB max
"""

import logging
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from typing import Generator, Optional

TRACE = 5
logging.addLevelName(TRACE, "TRACE")
logging.TRACE = TRACE  # so getattr(logging, "TRACE") resolves like the built-in levels


def _trace(self: logging.Logger, message, *args, **kwargs):
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)


logging.Logger.trace = _trace  # type: ignore[attr-defined]

CONSOLE = 25
logging.addLevelName(CONSOLE, "CONSOLE")


def _console(self: logging.Logger, message, *args, **kwargs):
    if self.isEnabledFor(CONSOLE):
        self._log(CONSOLE, message, args, **kwargs)


logging.Logger.console = _console  # type: ignore[attr-defined]

# Thread-safe context — set per simulation job via log_context()
_sim_id_var:   ContextVar[str] = ContextVar('sim_id',   default='')
_match_id_var: ContextVar[int] = ContextVar('match_id', default=0)

_logger: Optional[logging.Logger] = None

_CONSOLE_FMT = logging.Formatter(
    fmt="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
_FILE_FMT = logging.Formatter(
    fmt="%(asctime)s  %(levelname)-7s  [%(sim_id)s/m%(match_id)s]  %(message)s",
    datefmt="%H:%M:%S",
)


class _ContextFilter(logging.Filter):
    """Injects sim_id and match_id ContextVar values into every log record."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.sim_id   = _sim_id_var.get('')    # type: ignore[attr-defined]
        record.match_id = _match_id_var.get(0)   # type: ignore[attr-defined]
        return True


@contextmanager
def log_context(sim_id: Optional[str] = None, match_id: Optional[int] = None) -> Generator[None, None, None]:
    """
    Set per-thread sim/match context for all log lines within this block.
    Only the vars explicitly passed are changed — others inherit the outer context.
    Safe to nest: outer values are restored on exit.
    """
    tokens = []
    if sim_id is not None:
        tokens.append((_sim_id_var, _sim_id_var.set(sim_id)))
    if match_id is not None:
        tokens.append((_match_id_var, _match_id_var.set(match_id)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def set_log_level(level_name: str) -> None:
    """
    Change the minimum level emitted to simulation.log at runtime.
    errors.log is always fixed at WARNING and is not affected.
    """
    level = getattr(logging, level_name.upper(), None)
    if level is None:
        raise ValueError(f"Unknown log level: {level_name!r}")
    logger = get_logger()
    for h in logger.handlers:
        if isinstance(h, RotatingFileHandler) and "simulation" in getattr(h, 'baseFilename', ''):
            h.setLevel(level)


def get_current_log_level() -> str:
    """Return the current minimum level of simulation.log as a string."""
    logger = get_logger()
    for h in logger.handlers:
        if isinstance(h, RotatingFileHandler) and "simulation" in getattr(h, 'baseFilename', ''):
            return logging.getLevelName(h.level)
    return "INFO"


def is_level_active(level: int) -> bool:
    """
    Whether ANY attached handler would actually persist a record at this level.

    Use this — not logger.isEnabledFor() — to guard expensive log-line construction
    (e.g. building a per-ball probability table before calling log.trace(...)).
    isEnabledFor() only reflects the logger's own floor, which is deliberately kept
    at the lowest possible level (TRACE) so each handler can be switched
    independently at runtime; it would report "enabled" even when every handler's
    actual level is well above what you're checking for.
    """
    logger = get_logger()
    return any(h.level <= level for h in logger.handlers)


def get_logger() -> logging.Logger:
    """Returns the singleton application logger, creating it on first call."""
    global _logger
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("cricket_sim")
    # Floor is kept at the lowest level (TRACE) deliberately — every handler
    # (console, simulation.log, errors.log) sets its OWN level independently
    # and switches at runtime via set_log_level(); if the logger itself were
    # capped at DEBUG, TRACE-level records would never even reach a handler
    # to be filtered, regardless of that handler's configured level.
    _logger.setLevel(TRACE)

    if _logger.hasHandlers():
        return _logger

    level_name    = os.environ.get("LOG_LEVEL", "CONSOLE").upper()
    console_level = getattr(logging, level_name, CONSOLE)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(console_level)
    ch.setFormatter(_CONSOLE_FMT)
    ch.addFilter(_ContextFilter())
    _logger.addHandler(ch)

    return _logger


def set_console_level(level: int) -> None:
    """Adjust the console handler's minimum level (e.g. WARNING to suppress engine-init noise)."""
    logger = get_logger()
    for h in logger.handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            h.setLevel(level)


def configure_logger(
    log_dir: str = "logs",
    sim_log_level: int = logging.INFO,
    sim_log_max_bytes: int = 20 * 1024 * 1024,
    sim_log_backup_count: int = 10,
    err_log_max_bytes: int = 5 * 1024 * 1024,
    err_log_backup_count: int = 5,
) -> logging.Logger:
    """
    Attach rotating file handlers to the application logger. Call once at server startup.

    simulation.log  default INFO, switchable via set_log_level()   20MB × 10 = 200MB max
    errors.log      fixed at WARNING                                 5MB ×  5 =  25MB max
    """
    logger = get_logger()
    os.makedirs(log_dir, exist_ok=True)
    ctx_filter = _ContextFilter()

    sim_log_path = os.path.join(log_dir, "simulation.log")
    if not any(
        isinstance(h, RotatingFileHandler)
        and os.path.abspath(getattr(h, 'baseFilename', '')) == os.path.abspath(sim_log_path)
        for h in logger.handlers
    ):
        fh = RotatingFileHandler(
            sim_log_path, mode="a", encoding="utf-8",
            maxBytes=sim_log_max_bytes, backupCount=sim_log_backup_count,
        )
        fh.setLevel(sim_log_level)
        fh.setFormatter(_FILE_FMT)
        fh.addFilter(ctx_filter)
        logger.addHandler(fh)

    err_log_path = os.path.join(log_dir, "errors.log")
    if not any(
        isinstance(h, RotatingFileHandler)
        and os.path.abspath(getattr(h, 'baseFilename', '')) == os.path.abspath(err_log_path)
        for h in logger.handlers
    ):
        eh = RotatingFileHandler(
            err_log_path, mode="a", encoding="utf-8",
            maxBytes=err_log_max_bytes, backupCount=err_log_backup_count,
        )
        eh.setLevel(logging.WARNING)
        eh.setFormatter(_FILE_FMT)
        eh.addFilter(ctx_filter)
        logger.addHandler(eh)

    return logger
