"""
Application-level logger for the cricket simulator.

Log levels (low → high):
  DEBUG   10  per-ball probability tables, bowling factor breakdowns (file only)
  INFO    20  per-cache timing detail during model init (file only)
  CONSOLE 25  top-level lifecycle messages shown on the console AND written to file
  WARNING 30  data issues: player not in cache, DB unavailable, fallback activated
  ERROR   40  unexpected failures that may affect simulation correctness

Usage:
  from simulator.logger import get_logger
  log = get_logger()
  log.console("Loading model…")   # console + file
  log.info("cache took 0.3s")    # file only
  log.warning("player missing")   # console + file

Configuration:
  Call configure_logger(log_file, level) once at startup to attach a file handler.
  Console always shows CONSOLE (25) and above.
  Set LOG_LEVEL=DEBUG in the environment to also show DEBUG on console.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

CONSOLE = 25
logging.addLevelName(CONSOLE, "CONSOLE")


def _console(self: logging.Logger, message, *args, **kwargs):
    if self.isEnabledFor(CONSOLE):
        self._log(CONSOLE, message, args, **kwargs)


logging.Logger.console = _console  # type: ignore[attr-defined]

_logger: Optional[logging.Logger] = None

_CONSOLE_FMT = logging.Formatter(
    fmt="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
_FILE_FMT = logging.Formatter(
    fmt="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)


def get_logger() -> logging.Logger:
    """Returns the singleton application logger, creating it on first call."""
    global _logger
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("cricket_sim")
    _logger.setLevel(logging.DEBUG)  # handlers control what they actually emit

    if _logger.hasHandlers():
        return _logger

    # Console: CONSOLE level and above by default; LOG_LEVEL env var can lower it
    level_name    = os.environ.get("LOG_LEVEL", "CONSOLE").upper()
    console_level = getattr(logging, level_name, CONSOLE)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(console_level)
    ch.setFormatter(_CONSOLE_FMT)
    _logger.addHandler(ch)

    return _logger


def set_console_level(level: int) -> None:
    """Adjust the console handler's minimum level (e.g. WARNING to suppress engine-init noise)."""
    logger = get_logger()
    for h in logger.handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            h.setLevel(level)


def configure_logger(
    log_file: str,
    level: int = logging.DEBUG,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB per file
    backup_count: int = 5,
) -> logging.Logger:
    """
    Attaches a rotating file handler to the application logger.
    Rotates at max_bytes, keeping backup_count old files (.1, .2, …).
    Call once at startup before simulation begins.
    """
    logger = get_logger()

    already_attached = any(
        isinstance(h, RotatingFileHandler)
        and os.path.abspath(h.baseFilename) == os.path.abspath(log_file)
        for h in logger.handlers
    )
    if already_attached:
        return logger

    fh = RotatingFileHandler(
        log_file, mode="a", encoding="utf-8",
        maxBytes=max_bytes, backupCount=backup_count,
    )
    fh.setLevel(level)
    fh.setFormatter(_FILE_FMT)
    logger.addHandler(fh)

    return logger
