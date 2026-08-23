"""Minimal terminal UI for scubiee CLI.

Design: clean, focused, zero noise. Inspired by Vercel and Linear.
- Single accent color (blue) on dark terminals
- Single-width status icons (no emoji)
- Progressive disclosure: summary on TTY, full JSON with --json
- Respects NO_COLOR, TERM=dumb, and non-TTY (pipe) contexts
"""

from __future__ import annotations

import os
import sys
import time
from typing import IO, Any, TextIO


# ── Color support ─────────────────────────────────────────────────────────────

def _supports_color(stream: IO[str] | TextIO | None = None) -> bool:
    """Detect whether the output stream supports ANSI colors."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    s = stream or sys.stderr
    if not hasattr(s, "isatty") or not s.isatty():
        return False
    return True


def _is_tty(stream: IO[str] | TextIO | None = None) -> bool:
    s = stream or sys.stdout
    return bool(hasattr(s, "isatty") and s.isatty())


class _Colors:
    """ANSI escape sequences — degrades to empty strings when color is off."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def _esc(self, code: str) -> str:
        return f"\033[{code}m" if self.enabled else ""

    @property
    def reset(self) -> str:
        return self._esc("0")

    @property
    def bold(self) -> str:
        return self._esc("1")

    @property
    def dim(self) -> str:
        return self._esc("2")

    @property
    def green(self) -> str:
        return self._esc("32")

    @property
    def red(self) -> str:
        return self._esc("31")

    @property
    def yellow(self) -> str:
        return self._esc("33")

    @property
    def blue(self) -> str:
        return self._esc("34")

    @property
    def cyan(self) -> str:
        return self._esc("36")

    @property
    def muted(self) -> str:
        return self._esc("90")  # bright black / gray


def colors(stream: IO[str] | TextIO | None = None) -> _Colors:
    return _Colors(enabled=_supports_color(stream))


# ── Icons (single-width, no emoji) ───────────────────────────────────────────

ICON_OK = "✓"
ICON_FAIL = "✗"
ICON_WARN = "!"
ICON_INFO = "·"
ICON_RUN = "▶"
ICON_ARROW = "→"
ICON_BULLET = "·"


# ── Layout helpers ────────────────────────────────────────────────────────────

def header(title: str, *, stream: IO[str] | TextIO | None = None) -> None:
    """Print a section header."""
    s = stream or sys.stderr
    c = colors(s)
    s.write(f"\n{c.bold}{title}{c.reset}\n")
    s.flush()


def divider(*, stream: IO[str] | TextIO | None = None, width: int = 48) -> None:
    """Print a subtle horizontal divider."""
    s = stream or sys.stderr
    c = colors(s)
    s.write(f"{c.muted}{'─' * width}{c.reset}\n")
    s.flush()


def kv(key: str, value: Any, *, stream: IO[str] | TextIO | None = None, indent: int = 2) -> None:
    """Print a key-value pair with alignment."""
    s = stream or sys.stderr
    c = colors(s)
    pad = " " * indent
    s.write(f"{pad}{c.muted}{key:<16}{c.reset} {value}\n")
    s.flush()


def status_line(
    icon: str,
    message: str,
    *,
    detail: str = "",
    stream: IO[str] | TextIO | None = None,
) -> None:
    """Print a status line: ✓ message  (detail)"""
    s = stream or sys.stderr
    c = colors(s)
    color = ""
    if icon == ICON_OK:
        color = c.green
    elif icon == ICON_FAIL:
        color = c.red
    elif icon == ICON_WARN:
        color = c.yellow
    elif icon == ICON_RUN:
        color = c.blue
    else:
        color = c.muted

    detail_str = f"  {c.muted}{detail}{c.reset}" if detail else ""
    s.write(f"  {color}{icon}{c.reset} {message}{detail_str}\n")
    s.flush()


def success(message: str, *, detail: str = "", stream: IO[str] | TextIO | None = None) -> None:
    status_line(ICON_OK, message, detail=detail, stream=stream)


def error(message: str, *, detail: str = "", stream: IO[str] | TextIO | None = None) -> None:
    status_line(ICON_FAIL, message, detail=detail, stream=stream)


def warn(message: str, *, detail: str = "", stream: IO[str] | TextIO | None = None) -> None:
    status_line(ICON_WARN, message, detail=detail, stream=stream)


def info(message: str, *, detail: str = "", stream: IO[str] | TextIO | None = None) -> None:
    status_line(ICON_INFO, message, detail=detail, stream=stream)


# ── Table ─────────────────────────────────────────────────────────────────────

def table(
    rows: list[list[str]],
    *,
    headers: list[str] | None = None,
    stream: IO[str] | TextIO | None = None,
    indent: int = 2,
) -> None:
    """Print a minimal borderless table with aligned columns."""
    s = stream or sys.stderr
    c = colors(s)
    pad = " " * indent

    all_rows = ([headers] if headers else []) + rows
    if not all_rows:
        return

    col_widths = [0] * max(len(row) for row in all_rows)
    for row in all_rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    if headers:
        header_line = pad + "  ".join(
            f"{c.muted}{cell:<{col_widths[i]}}{c.reset}"
            for i, cell in enumerate(headers)
        )
        s.write(header_line + "\n")
        sep = pad + "  ".join("─" * w for w in col_widths)
        s.write(f"{c.muted}{sep}{c.reset}\n")

    for row in rows:
        line = pad + "  ".join(
            f"{cell:<{col_widths[i]}}" for i, cell in enumerate(row)
        )
        s.write(line + "\n")

    s.flush()


# ── Composite outputs ─────────────────────────────────────────────────────────

def format_duration(seconds: float) -> str:
    """Human-readable duration: 2.3s, 1m 42s, etc."""
    if seconds < 0.1:
        return "<0.1s"
    if seconds < 60:
        return f"{seconds:.1f}s"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}m {secs}s"


def format_bytes(n: int | float) -> str:
    """Human-readable byte size."""
    if n < 1024:
        return f"{int(n)}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f}MB"
    return f"{n / (1024 * 1024 * 1024):.1f}GB"


def format_count(n: int) -> str:
    """Format number with comma separators."""
    return f"{n:,}"


def print_status_summary(data: dict[str, Any], *, stream: IO[str] | TextIO | None = None) -> None:
    """Print a clean human-readable status summary from the status JSON."""
    s = stream or sys.stderr
    c = colors(s)

    meta = data.get("meta") or {}
    server = data.get("server") or {}
    freshness = data.get("freshness") or {}
    chunks = data.get("chunks", 0)
    vectors = data.get("vectors") or {}

    # Title
    s.write(f"\n{c.bold}scubiee{c.reset}")
    version = server.get("version", "")
    if version:
        s.write(f" {c.muted}v{version}{c.reset}")
    s.write("\n")
    divider(stream=s, width=40)

    # Engine status
    warm = server.get("warm") or server.get("ok")
    if warm:
        success("Engine running", detail=server.get("warm_state", "ready"), stream=s)
    else:
        error("Engine not running", stream=s)

    # Repository
    root = data.get("root", "")
    if root:
        repo_name = os.path.basename(root) or root
        kv("Repository", repo_name, stream=s)

    # Index stats
    profile = meta.get("embed_backend", "")
    files = meta.get("files_indexed", 0)
    kv("Chunks", format_count(chunks), stream=s)
    kv("Files indexed", format_count(files), stream=s)
    if profile:
        kv("Backend", profile, stream=s)

    # Vectors
    ntotal = vectors.get("ntotal", 0)
    if ntotal:
        kv("Vectors", format_count(ntotal), stream=s)

    # Freshness
    stale = freshness.get("stale_files", [])
    if stale:
        warn(f"{len(stale)} stale file(s)", stream=s)
    else:
        drift = freshness.get("status", "")
        if drift == "fresh" or not stale:
            success("Index is fresh", stream=s)

    s.write("\n")
    s.flush()


def print_init_summary(data: dict[str, Any], *, stream: IO[str] | TextIO | None = None) -> None:
    """Print a clean init result summary."""
    s = stream or sys.stderr
    c = colors(s)

    ok = data.get("ok", False)
    root = data.get("root", "")
    repo_name = os.path.basename(root) or root
    chunks = data.get("chunks", 0)
    state = data.get("state", "")

    s.write("\n")
    if ok:
        success(f"Initialized {c.bold}{repo_name}{c.reset}", stream=s)
        if chunks:
            kv("Chunks", format_count(chunks), stream=s)
        if state:
            kv("State", state, stream=s)
        daemon = data.get("daemon", {})
        if daemon.get("ok"):
            success("Daemon started", stream=s)
    else:
        err = data.get("error", "unknown error")
        error(f"Init failed: {err}", stream=s)
        repair = data.get("repair")
        if repair:
            info(f"Run: {repair}", stream=s)

    s.write("\n")
    s.flush()


def print_connect_summary(
    results: list[dict[str, Any]],
    *,
    action: str = "Connected",
    dry_run: bool = False,
    stream: IO[str] | TextIO | None = None,
) -> None:
    """Print a clean connect/disconnect result table."""
    s = stream or sys.stderr
    c = colors(s)

    s.write("\n")
    rows: list[list[str]] = []
    for r in results:
        tool = r.get("tool") or r.get("slug") or "?"
        ok = r.get("ok", False)
        icon = f"{c.green}{ICON_OK}{c.reset}" if ok else f"{c.red}{ICON_FAIL}{c.reset}"
        detail = ""
        if not ok:
            detail = r.get("error", "failed")
        rows.append([icon, tool, detail])

    table(rows, headers=["", "Tool", ""], stream=s)

    ok_count = sum(1 for r in results if r.get("ok"))
    total = len(results)
    s.write("\n")
    if dry_run:
        info(f"Would {action.lower()} {total} tool(s)", stream=s)
    else:
        if ok_count == total:
            success(f"{action} {ok_count}/{total} tools", stream=s)
        else:
            warn(f"{action} {ok_count}/{total} tools", detail=f"{total - ok_count} failed", stream=s)

    s.write("\n")
    s.flush()


def print_stop_summary(data: dict[str, Any], *, stream: IO[str] | TextIO | None = None) -> None:
    """Print a clean stop result."""
    s = stream or sys.stderr
    c = colors(s)

    s.write("\n")
    ok = data.get("ok", False)
    if ok:
        success("All processes stopped", stream=s)
    else:
        warn("Some processes may still be running", stream=s)
        hint = data.get("hint")
        if hint:
            info(hint, stream=s)

    engine = data.get("engine", {})
    if isinstance(engine, dict) and not engine.get("running", True):
        kv("Engine", "stopped", stream=s)

    watchdog = data.get("watchdog", {})
    if isinstance(watchdog, dict) and watchdog.get("ok"):
        kv("Watchdog", "stopped", stream=s)

    s.write("\n")
    s.flush()


def print_doctor_summary(data: dict[str, Any], *, stream: IO[str] | TextIO | None = None) -> None:
    """Print a clean doctor result."""
    s = stream or sys.stderr
    c = colors(s)

    s.write("\n")
    ok = data.get("ok", False)
    if ok:
        success("All checks passed", stream=s)
    else:
        error("Issues detected", stream=s)

    caps = data.get("capabilities", {})
    if caps:
        missing = caps.get("missing_required", [])
        if missing:
            for dep in missing:
                warn(f"Missing: {dep}", stream=s)
        elif caps.get("ok"):
            success("Dependencies OK", stream=s)

    repairs = data.get("repairs", [])
    if repairs:
        s.write("\n")
        header("Repairs", stream=s)
        for repair in repairs:
            if isinstance(repair, dict):
                kind = repair.get("kind", "")
                rid = repair.get("id", "")
                icon = ICON_OK if kind == "safe" else ICON_WARN
                status_line(icon, rid, detail=kind, stream=s)
            else:
                status_line(ICON_WARN, str(repair), stream=s)

    s.write("\n")
    s.flush()
