"""
ANSI 24-bit true-colour helpers for terminal output.

Falls back to plain text automatically when stdout is not a TTY.
"""

from __future__ import annotations

import os
import sys

COLOR: bool = (
    os.environ.get("FORCE_COLOR", "0") not in ("0", "false", "")
    or (hasattr(sys.stdout, "isatty") and sys.stdout.isatty())
)

_MUTED = "#AAAAAA"
_W = 100


def rgb(text: str, hex_color: str, bold: bool = False) -> str:
    if not COLOR or not hex_color or len(hex_color) < 7:
        return text
    try:
        r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    except ValueError:
        return text
    prefix = "\033[1m" if bold else ""
    return f"{prefix}\033[38;2;{r};{g};{b}m{text}\033[0m"


def bg(text: str, bg_hex: str, fg_hex: str = "#FFFFFF", bold: bool = False) -> str:
    if not COLOR or not bg_hex or len(bg_hex) < 7:
        return text
    try:
        br, bg_, bb = int(bg_hex[1:3], 16), int(bg_hex[3:5], 16), int(bg_hex[5:7], 16)
        fr, fg_, fb = int(fg_hex[1:3], 16), int(fg_hex[3:5], 16), int(fg_hex[5:7], 16)
    except ValueError:
        return text
    prefix = "\033[1m" if bold else ""
    return f"{prefix}\033[48;2;{br};{bg_};{bb}m\033[38;2;{fr};{fg_};{fb}m{text}\033[0m"


def bold(text: str) -> str:
    return f"\033[1m{text}\033[0m" if COLOR else text


def dim(text: str) -> str:
    return f"\033[2m{text}\033[0m" if COLOR else text


def hdr(text: str) -> str:
    return rgb(text, _MUTED)


def sep(char: str = "=", width: int = _W) -> str:
    return dim(char * width)


def section_hdr(title: str, width: int = 72) -> str:
    pad = max(0, (width - len(title) - 2) // 2)
    line = "═" * pad + f" {title} " + "═" * pad
    return bold(line[:width])
