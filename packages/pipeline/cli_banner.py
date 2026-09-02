"""Large stylized terminal banner for scubiee branded commands."""

from __future__ import annotations

import sys
from typing import IO, TextIO

# Figlet "ansi_shadow" — block letters with built-in 3D shadow (matches patorjk.com).
_SCUBIEE_BANNER = """
███████╗ ██████╗██╗   ██╗██████╗ ██╗███████╗███████╗
██╔════╝██╔════╝██║   ██║██╔══██╗██║██╔════╝██╔════╝
███████╗██║     ██║   ██║██████╔╝██║█████╗  █████╗
╚════██║██║     ██║   ██║██╔══██╗██║██╔══╝  ██╔══╝
███████║╚██████╗╚██████╔╝██████╔╝██║███████╗███████╗
╚══════╝ ╚═════╝ ╚═════╝ ╚═════╝ ╚═╝╚══════╝╚══════╝
""".strip("\n")

_INDENT = 2


def _banner_width() -> int:
    return max(len(line) for line in _SCUBIEE_BANNER.splitlines())


def _rule_line(*, enabled: bool, width: int) -> str:
    pad = " " * _INDENT
    line = "─" * width
    if enabled:
        return f"{pad}\033[90m{line}\033[0m\n"
    return f"{pad}{line}\n"


def render_scubiee_banner(*, enabled: bool = True, indent: int = _INDENT) -> str:
    """Return the banner — bold bright white when colors are enabled."""
    pad = " " * indent
    lines = _SCUBIEE_BANNER.splitlines()
    if not enabled:
        return "\n".join(f"{pad}{line}" for line in lines)
    return "\n".join(f"{pad}\033[1;97m{line}\033[0m" for line in lines)


def print_brand_banner(
    cmd: str,
    *,
    stream: IO[str] | TextIO | None = None,
    tagline: str = "local AI code context engine",
) -> None:
    """Print framed SCUBIEE banner + command subtitle."""
    from pipeline.cli_ui import _is_tty, colors

    s = stream or sys.stderr
    if not _is_tty(s):
        return

    c = colors(s)
    width = _banner_width()
    pad = " " * _INDENT

    s.write("\n")
    s.write(_rule_line(enabled=c.enabled, width=width))
    s.write("\n")
    s.write(render_scubiee_banner(enabled=c.enabled))
    s.write("\n\n")
    s.write(_rule_line(enabled=c.enabled, width=width))

    if cmd:
        s.write("\n")
        s.write(f"{pad}{c.blue}>{c.reset} {c.bold}scubiee {cmd}{c.reset}\n")
        if tagline:
            s.write(f"{pad}  {c.muted}{tagline}{c.reset}\n")

    s.write("\n")
    s.flush()
