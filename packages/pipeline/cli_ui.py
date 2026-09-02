"""Minimal terminal UI for scubiee CLI.

Design: clean, focused, zero noise. Inspired by Vercel and Linear.
- Single accent color (blue) on dark terminals
- Single-width status icons (no emoji)
- Progressive disclosure: summary on TTY, full JSON with --json
- Respects NO_COLOR, TERM=dumb, and non-TTY (pipe) contexts
"""

from __future__ import annotations

import os
import re
import sys
import time
from typing import IO, Any, TextIO

from pipeline.tool_registry import connect_restart_hint

# ── Color support ─────────────────────────────────────────────────────────────

_terminal_initialized = False
_color_enabled: bool | None = None


def _init_windows_ansi() -> bool:
    """Enable ANSI colors on legacy Windows consoles (cmd.exe without VT mode)."""
    try:
        import colorama

        if hasattr(colorama, "just_fix_windows_console"):
            colorama.just_fix_windows_console()
        else:
            colorama.init(strip=False, convert=True)
        return True
    except ImportError:
        pass
    except Exception:  # noqa: BLE001
        pass

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        enable_vt = 0x0004
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | enable_vt)
        return True
    except Exception:  # noqa: BLE001
        return False


def _init_windows_console() -> None:
    """UTF-8 output so block-letter banner renders on cmd/PowerShell."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


def init_terminal() -> None:
    """Prepare stdout/stderr for styled CLI output (call once from main())."""
    global _terminal_initialized, _color_enabled
    if _terminal_initialized:
        return
    _terminal_initialized = True

    if sys.platform == "win32":
        any_tty = (
            (hasattr(sys.stdout, "isatty") and sys.stdout.isatty())
            or (hasattr(sys.stderr, "isatty") and sys.stderr.isatty())
        )
        if any_tty:
            _init_windows_console()

    if os.environ.get("SCUBIEE_FORCE_COLOR"):
        _color_enabled = True
        return
    if os.environ.get("NO_COLOR"):
        _color_enabled = False
        return
    if os.environ.get("TERM") == "dumb":
        _color_enabled = False
        return

    if sys.platform == "win32":
        any_tty = (
            (hasattr(sys.stdout, "isatty") and sys.stdout.isatty())
            or (hasattr(sys.stderr, "isatty") and sys.stderr.isatty())
        )
        _color_enabled = _init_windows_ansi() if any_tty else False
    else:
        _color_enabled = True


def _supports_color(stream: IO[str] | TextIO | None = None) -> bool:
    """Detect whether the output stream supports ANSI colors."""
    if _color_enabled is None:
        init_terminal()
    if not _color_enabled:
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

def branded_header(cmd: str, *, stream: IO[str] | TextIO | None = None) -> None:
    """Print a branded command header — used for setup, init, and wipe."""
    from pipeline.cli_banner import print_brand_banner

    print_brand_banner(cmd, stream=stream)

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


def format_index_eta(n_files: int) -> str:
    """Wall-clock range from observed ~0.45–0.55s per indexable file.

    446 files on a typical GPU box takes ~3–4 min, not the old 1 min
    (~600 files/min) estimate.
    """
    n = max(0, int(n_files))
    lo_s = max(20, int(round(n * 0.45)))
    hi_s = max(lo_s, int(round(n * 0.55)))
    lo_m = max(1, int(round(lo_s / 60)))
    hi_m = max(lo_m, int(round(hi_s / 60)))
    if lo_m == hi_m:
        return f"~{lo_m} min"
    return f"~{lo_m}–{hi_m} min"


def _clean_progress_label(label: str) -> str:
    first = (label or "").splitlines()[0].strip()
    first = re.sub(r"\[graphify\]\s*", "", first, flags=re.IGNORECASE)
    first = re.sub(r"(?i)\bgraphify\b", "", first)
    first = re.sub(r"\s{2,}", " ", first).strip(" -·|:;") or "Working"
    return first[:48]


class _ScrubGraphifyStream:
    """Drop the internal ``[graphify]`` brand from anything written to a TTY."""

    __slots__ = ("_inner",)

    def __init__(self, inner: IO[str] | TextIO):
        self._inner = inner

    def write(self, s: str) -> int:  # type: ignore[override]
        if isinstance(s, str) and "graphify" in s.lower():
            s = re.sub(r"\[graphify\]\s*", "", s, flags=re.IGNORECASE)
        return self._inner.write(s)

    def flush(self) -> None:
        self._inner.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._inner, "isatty", lambda: False)())

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def install_graphify_brand_scrubbers() -> None:
    """Wrap stdout/stderr so leaked graphify log tags never reach the user."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or isinstance(stream, _ScrubGraphifyStream):
            continue
        setattr(sys, name, _ScrubGraphifyStream(stream))

def print_status_summary(data: dict[str, Any], *, stream: IO[str] | TextIO | None = None) -> None:
    """Print a clean human-readable status summary from the status JSON."""
    s = stream or sys.stderr
    c = colors(s)

    if data.get("enrolled") is False or data.get("state") == "unmanaged":
        s.write(f"\n{c.bold}scubiee{c.reset}\n")
        divider(stream=s, width=40)
        root = data.get("root", "")
        if root:
            repo_name = os.path.basename(root) or root
            kv("Repository", repo_name, stream=s)
        warn("Not enrolled", detail=data.get("hint", "Run `scubiee init .`"), stream=s)
        s.write("\n")
        return

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
        detail = "" if ok else r.get("error", "failed")
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

    if not dry_run and action == "Connected" and ok_count > 0:
        info(connect_restart_hint(results), stream=s)

    seen_notices: set[str] = set()
    for r in results:
        notice = (r.get("notice") or "").strip()
        if not notice or notice in seen_notices:
            continue
        seen_notices.add(notice)
        info(notice, stream=s)

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

    install = data.get("install")
    if isinstance(install, dict):
        kv("Active binary", install.get("active_binary", "?"), stream=s)
        if install.get("multiple_installs"):
            for extra in install.get("extra_on_path") or []:
                warn(f"Also on PATH: {extra}", stream=s)
        if install.get("hint"):
            info(str(install["hint"]), stream=s)

    caps = data.get("capabilities", {})
    if caps:
        missing = caps.get("missing_required", [])
        if missing:
            for dep in missing:
                warn(f"Missing: {dep}", stream=s)
        elif caps.get("ok"):
            success("Dependencies OK", stream=s)

    connect = data.get("connect_registry")
    if isinstance(connect, dict):
        connected = connect.get("connected_tools") or []
        if connected:
            kv("Connected tools", ", ".join(connected), stream=s)
        managed = connect.get("managed_repos", 0)
        enrolled = connect.get("enrolled_repos", 0)
        if managed or enrolled or connected:
            kv("Managed repos", f"{managed} on disk ({enrolled} enrolled)", stream=s)
        for warning in connect.get("warnings") or []:
            if isinstance(warning, dict):
                warn(str(warning.get("detail") or warning.get("id")), stream=s)
            else:
                warn(str(warning), stream=s)

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

# ── Confirmation prompt ───────────────────────────────────────────────────────

def confirm_action(
    message: str,
    *,
    details: list[str] | None = None,
    default: bool = False,
    stream: IO[str] | TextIO | None = None,
    skip_if_not_tty: bool = True,
    icon: str | None = ICON_WARN,
) -> bool:
    """Ask for y/n confirmation before a destructive action.

    Returns True if confirmed, False if declined.
    Non-TTY (piped) always returns default unless skip_if_not_tty is False.
    Pass ``icon=None`` for a plain prompt (no warning mark).
    """
    s = stream or sys.stderr
    c = colors(s)

    if not _is_tty(sys.stdin):
        if skip_if_not_tty:
            return default
        return default

    s.write("\n")
    if icon:
        s.write(f"  {c.yellow}{icon}{c.reset} {c.bold}{message}{c.reset}\n")
    else:
        s.write(f"  {message}\n")
    if details:
        for detail in details:
            s.write(f"    {c.muted}{detail}{c.reset}\n")
    s.write("\n")
    s.flush()

    # Prompt
    hint = "Y/n" if default else "y/N"
    try:
        answer = input(f"  Continue? [{hint}] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        s.write("\n")
        return False

    if not answer:
        return default
    return answer in ("y", "yes")

# ── Setup progress (phased output) ───────────────────────────────────────────

class SetupProgress:
    """Clean phased progress for scubiee setup — replaces the single % bar.

    Three visible stages: hardware detection, model download/prep, calibration.
    Sub-steps within "getting the model ready" update the SAME line in place
    (properly padded so no leftover characters survive a shorter message),
    so the user always sees exactly one active line, never overlapping text.
    """

    def __init__(self, stream=None):
        self.stream = stream or sys.stderr
        self.c = colors(self.stream)
        self._tty = _is_tty(self.stream)
        self._last_phase = ""
        self._last_key = ""
        self._line_open = False
        self._last_line_len = 0
        self._non_tty_last_emit = ""
        self._last_step_finish_msg = ""

    def start(self, notice=None):
        branded_header("setup", stream=self.stream)

    def _clear_line(self):
        if self._tty and self._line_open:
            pad = " " * self._last_line_len
            self.stream.write("\r" + pad + "\r")
        self._line_open = False
        self._last_line_len = 0

    def step_done(self, message, detail=""):
        self._clear_line()
        detail_str = f"  {self.c.muted}{detail}{self.c.reset}" if detail else ""
        self.stream.write(f"  {self.c.green}{ICON_OK}{self.c.reset} {message}{detail_str}\n")
        self.stream.flush()

    def step_active(self, message):
        self._clear_line()
        if self._tty:
            line = f"  {ICON_RUN} {message}"
            self.stream.write(f"  {self.c.blue}{ICON_RUN}{self.c.reset} {message}")
            self.stream.flush()
            self._line_open = True
            self._last_line_len = len(line)
        else:
            if message != self._non_tty_last_emit:
                self.stream.write(f"  {ICON_RUN} {message}\n")
                self.stream.flush()
                self._non_tty_last_emit = message

    def step_update(self, message):
        if not self._tty:
            return
        line = f"  {ICON_RUN} {message}"
        pad = max(0, self._last_line_len - len(line))
        self.stream.write(f"\r  {self.c.blue}{ICON_RUN}{self.c.reset} {message}{' ' * pad}")
        self.stream.flush()
        self._last_line_len = max(self._last_line_len, len(line))
        self._line_open = True

    def step_finish(self, message, detail=""):
        # Dedup: skip if same message was already finished
        if message == self._last_step_finish_msg:
            return
        self._last_step_finish_msg = message
        detail_str = f"  {self.c.muted}{detail}{self.c.reset}" if detail else ""
        if self._tty:
            plain = f"  {ICON_OK} {message}" + (f"  {detail}" if detail else "")
            pad = max(0, self._last_line_len - len(plain))
            self.stream.write(
                f"\r  {self.c.green}{ICON_OK}{self.c.reset} {message}{detail_str}{' ' * pad}\n"
            )
        else:
            self.stream.write(f"  {ICON_OK} {message}{detail_str}\n")
        self.stream.flush()
        self._line_open = False
        self._last_line_len = 0
        self._non_tty_last_emit = ""

    def finish(self, message):
        self._clear_line()
        self.stream.write(f"\n  {self.c.green}{ICON_OK}{self.c.reset} {self.c.bold}{message}{self.c.reset}\n\n")
        self.stream.flush()

    def fail(self, message):
        if self._tty:
            pad = max(0, self._last_line_len - (len(message) + 4))
            self.stream.write(f"\r  {self.c.red}{ICON_FAIL}{self.c.reset} {message}{' ' * pad}\n\n")
        else:
            self.stream.write(f"  {ICON_FAIL} {message}\n\n")
        self.stream.flush()
        self._line_open = False

    # ── Adapter for the old progress_ui.InstallProgress interface ─────────
    # Sub-steps of "getting the model ready" collapse onto ONE active line
    # instead of each opening/closing their own line — that mismatch (a
    # shorter message not erasing a longer one) was the overlapping-text bug.

    _MODEL_STEP_KEYS = ("downloading", "converting", "preparing", "quantizing", "step 1", "step 2", "step 3", "warming")

    def set(self, pct, phase):
        phase_key = phase.lower().split("(")[0].strip()
        phase_lower = phase.lower()

        # Model step keys use the progress bar — allow repeated calls with
        # different pct values (don't dedup on phase text for these).
        if any(key in phase_lower for key in self._MODEL_STEP_KEYS):
            # Progress bar for model prep (pct 56-85 maps to 0-100%)
            bar_width = 20
            frac = max(0.05, min(1.0, (pct - 56) / (85 - 56))) if pct > 56 else 0.05
            filled = int(bar_width * frac)
            bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
            self.step_update(f"[{bar}] {frac:.0%}  Preparing model")
            self._last_phase = phase
            self._last_key = phase_key
            return

        # For non-model steps, dedup on phase text
        if phase == self._last_phase:
            return
        if phase_key == self._last_key:
            return
        self._last_key = phase_key
        self._last_phase = phase

        if "starting" in phase_lower or "checking" in phase_lower:
            return

        if "detecting" in phase_lower or ("hardware" in phase_lower and "using" not in phase_lower):
            self.step_active("Detecting hardware")
            return
        if "using" in phase_lower and "profile" in phase_lower:
            self.step_finish("Hardware detected", phase.replace("Using ", "").replace(" profile", ""))
            return
        if "already installed" in phase_lower or "runtime already" in phase_lower:
            self.step_done("Runtime installed")
            return
        if "runtime issue" in phase_lower or "auto-repair" in phase_lower or "repairing" in phase_lower:
            self.step_active("Runtime issue \u2014 repairing")
            return
        if "reinstalling" in phase_lower:
            self.step_update("Reinstalling runtime\u2026")
            return
        if "runtime fixed" in phase_lower:
            self.step_finish("Runtime fixed")
            return

        if "embedding model ready" in phase_lower or "model ready" in phase_lower:
            self.step_finish("Model ready")
            return

        if "calibrating" in phase_lower:
            self.step_active("Calibrating speed")
            return
        if "saving" in phase_lower:
            self.step_finish("Calibrated")
            return
        if "supervisor" in phase_lower:
            self.step_done("Supervisor registered")
            return
        if "cursor" in phase_lower or "mcp" in phase_lower:
            self.step_done("MCP registered")
            return
        if "directml" in phase_lower or "coreml" in phase_lower:
            self.step_done(phase)
            return

        if pct >= 90:
            self.step_done(phase)
        else:
            self.step_update(phase)

    def pulse(self, phase, *, until):
        self.set(until, phase)

    def notice(self, message):
        self._clear_line()
        self.stream.write(f"  {self.c.muted}{message}{self.c.reset}\n")
        self.stream.flush()

# ── Additional command summaries ─────────────────────────────────────────────

def print_search_summary(data, *, stream=None):
    """Clean search results: ranked list, no raw JSON."""
    s = stream or sys.stderr
    c = colors(s)
    hits = data.get("hits") or []
    latency = data.get("latency_ms", 0)

    s.write("\n")
    if not hits:
        info("No matches found", stream=s)
        s.write("\n")
        return

    for h in hits:
        rank = h.get("rank", "?")
        file = h.get("file", "?")
        score = h.get("score", 0)
        preview = (h.get("preview") or "").strip().replace("\n", " ")
        if len(preview) > 90:
            preview = preview[:87] + "..."
        s.write(f"  {c.muted}{rank:>2}{c.reset}  {c.bold}{file}{c.reset}  {c.muted}({score:.2f}){c.reset}\n")
        if preview:
            s.write(f"      {c.muted}{preview}{c.reset}\n")
    s.write(f"\n  {c.muted}{len(hits)} result(s) in {latency:.0f}ms{c.reset}\n\n")
    s.flush()

def print_resources_summary(data, *, stream=None):
    """Clean hardware/pressure summary."""
    s = stream or sys.stderr
    c = colors(s)
    res = data.get("resources") or {}
    hw = data.get("hardware") or {}
    sample = res.get("sample") or {}

    s.write("\n")
    pressure = res.get("pressure", "unknown")
    icon = ICON_OK if pressure == "idle" else ICON_WARN
    status_line(icon, f"Resource pressure: {pressure}", stream=s)
    if sample:
        kv("CPU", f"{sample.get('cpu_percent', 0):.0f}%", stream=s)
        kv("RAM", f"{sample.get('ram_percent', 0):.0f}%", stream=s)
    if hw:
        os_name = hw.get("os", "?")
        gpus = hw.get("gpus") or []
        kv("Platform", os_name, stream=s)
        if gpus:
            kv("GPU", ", ".join(g.get("name", "?") for g in gpus[:2]), stream=s)
    s.write("\n")
    s.flush()

def print_preflight_summary(data, *, stream=None):
    """Clean dependency check summary."""
    s = stream or sys.stderr
    ok = data.get("ok", False)

    s.write("\n")
    if ok:
        success("All dependencies present", stream=s)
    else:
        missing = data.get("missing_required") or []
        error("Missing dependencies", stream=s)
        for dep in missing:
            warn(str(dep), stream=s)
    s.write("\n")
    s.flush()

def print_certify_summary(data, *, stream=None):
    """Clean certification gate summary."""
    s = stream or sys.stderr
    ok = data.get("ok", False)
    passed = data.get("passed", 0)
    failed = data.get("failed_required", 0)

    s.write("\n")
    if ok:
        success(f"Certification passed", detail=f"{passed} checks", stream=s)
    else:
        error(f"Certification failed", detail=f"{failed} required check(s) failed", stream=s)
        for f in data.get("failures") or []:
            if isinstance(f, dict):
                warn(f.get("name", "?"), detail=f.get("detail", ""), stream=s)
    s.write("\n")
    s.flush()

def print_register_summary(data, *, stream=None):
    """Clean project registration summary."""
    s = stream or sys.stderr
    ok = data.get("ok", False)

    s.write("\n")
    if ok:
        success("Repository registered", stream=s)
        chunks = data.get("chunks")
        if chunks:
            kv("Chunks", format_count(chunks), stream=s)
    else:
        error(f"Registration failed: {data.get('error', 'unknown')}", stream=s)
    s.write("\n")
    s.flush()

def print_lifecycle_summary(data, *, action, stream=None):
    """Clean repo lifecycle action summary (pause/resume/rebuild/remove/etc)."""
    s = stream or sys.stderr
    ok = data.get("ok", True)

    s.write("\n")
    if ok:
        state = data.get("state") or data.get("status")
        detail = f"state: {state}" if state else ""
        success(f"{action.capitalize()} complete", detail=detail, stream=s)
    else:
        error(f"{action.capitalize()} failed: {data.get('error', 'unknown')}", stream=s)
    s.write("\n")
    s.flush()

def print_migrate_summary(data, *, stream=None):
    """Clean migration check/apply summary."""
    s = stream or sys.stderr
    ok = data.get("ok", True)

    s.write("\n")
    if "needs_migration" in data:
        if data.get("needs_migration"):
            warn("Migration needed", detail=data.get("reason", ""), stream=s)
        else:
            success("No migration needed", stream=s)
    elif "projects" in data:
        projects = data.get("projects") or []
        needing = [p for p in projects if p.get("needs_migration")]
        if needing:
            warn(f"{len(needing)} project(s) need migration", stream=s)
        else:
            success(f"All {len(projects)} project(s) up to date", stream=s)
    elif ok:
        migrated = data.get("migrated", 0)
        success(f"Migration complete", detail=f"{migrated} project(s)", stream=s)
    else:
        error(f"Migration failed: {data.get('error', 'unknown')}", stream=s)
    s.write("\n")
    s.flush()

def print_settings_summary(prefs, *, stream=None):
    """Clean settings/preferences summary."""
    s = stream or sys.stderr
    s.write("\n")
    for key in ("registration_mode", "incremental_indexing", "file_watching"):
        if key in prefs:
            kv(key.replace("_", " ").capitalize(), prefs[key], stream=s)
    if "prefs_path" in prefs:
        kv("Config file", prefs["prefs_path"], stream=s)
    s.write("\n")
    s.flush()

def print_repo_list_summary(repos, *, stream=None):
    """Clean table of managed repositories."""
    s = stream or sys.stderr
    c = colors(s)
    s.write("\n")
    if not repos:
        info("No managed repositories", stream=s)
        s.write("\n")
        return
    rows = []
    for r in repos:
        name = r.get("name") or r.get("root", "?")
        state = r.get("state", "?")
        chunks = r.get("index_state", "?")
        rows.append([name, state, chunks])
    table(rows, headers=["Repository", "State", "Index"], stream=s)
    s.write(f"\n  {c.muted}{len(repos)} repositor{'y' if len(repos)==1 else 'ies'}{c.reset}\n\n")
    s.flush()

def print_dashboard_summary(data, *, stream=None):
    """Clean dashboard start/stop/status summary."""
    s = stream or sys.stderr
    ok = data.get("ok", False)
    s.write("\n")
    if ok:
        url = data.get("url")
        running = data.get("running")
        if running is False:
            success("Dashboard stopped", stream=s)
        elif url:
            success("Dashboard running", detail=url, stream=s)
        else:
            success("Dashboard ready", stream=s)
    else:
        error(f"Dashboard error: {data.get('error', 'unknown')}", stream=s)
    s.write("\n")
    s.flush()

# ── Stderr noise suppression ──────────────────────────────────────────────────

class suppress_stderr_noise:
    """Context manager that silences library stderr noise during TTY mode.

    Redirects stderr writes from known noisy libraries (huggingface_hub,
    fastembed, onnxruntime, tqdm) to devnull. Our own progress output uses
    the stream reference directly so it's not affected.
    """

    def __init__(self, stream: IO[str] | TextIO | None = None):
        self._active = _is_tty(stream or sys.stderr)
        self._original_stderr: TextIO | None = None

    def __enter__(self):
        if not self._active:
            return self
        self._original_stderr = sys.stderr
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115
        return self

    def __exit__(self, *_):
        if self._original_stderr is not None:
            try:
                sys.stderr.close()
            except Exception:  # noqa: BLE001
                pass
            sys.stderr = self._original_stderr
            self._original_stderr = None

# ── Wipe summary ──────────────────────────────────────────────────────────────

def print_wipe_summary(data: dict[str, Any], *, stream: IO[str] | TextIO | None = None) -> None:
    """Print a clean wipe result — step by step status lines."""
    s = stream or sys.stderr
    c = colors(s)
    ok = data.get("ok", False)
    actions = data.get("actions") or []

    s.write("\n")

    # Map action keys to human-readable labels
    step_map = {
        "halt": "Prepared machine (stub MCP, kill, unlock)",
        "process_release": "MCP stubbed + processes stopped",
        "unlock_tool": "uv tool directory unlocked",
        "kill_all": "Scubiee processes killed",
        "final_kill": "Final process sweep",
        "engine_restart": "Engine restarted",
        "pause": None,
        "stop_all": "Processes stopped",
        "disconnect_all_tools": "MCP configs removed",
        "project_tool_surfaces": "Project MCP/rules removed",
        "stop_watchdog": None,  # redundant with stop_all
        "stop_daemon": None,
        "user_cursor_mcp": "MCP configs removed",
        "user_cursor_mcp_early": None,
        "kiro_user_mcp_early": None,
        "kiro_project_mcp_early": None,
        "project_cursor_mcp_early": None,
        "user_mcp": None,  # covered by early removal
        "kiro_user_mcp": None,
        "wipe_repos": "Repository data wiped",
        "models": "Models removed",
        "uninstall_scubiee": "Package uninstalled",
        "tool_shims": None,
        "audit": None,
        "unregister_autostart": None,
    }

    shown_labels: set[str] = set()
    failed_steps: list[str] = []

    for action_dict in actions:
        for key, val in action_dict.items():
            label = step_map.get(key)
            if label is None:
                # Check ctx_home / vectordb keys
                if key.startswith("ctx_home"):
                    label = "Data wiped"
                elif key.startswith("vectordb"):
                    label = "Vector index removed"
                else:
                    continue
            if label in shown_labels:
                continue

            # Determine if this step succeeded
            step_ok = True
            if isinstance(val, dict):
                if val.get("ok") is False and val.get("error") and not val.get("missing") and not val.get("absent"):
                    step_ok = False
                if val.get("removed") is False and val.get("error"):
                    step_ok = False
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and item.get("ok") is False:
                        step_ok = False
                        break

            shown_labels.add(label)
            if step_ok:
                success(label, stream=s)
            else:
                err_detail = ""
                if isinstance(val, dict):
                    err_detail = str(val.get("error", ""))[:60]
                error(label, detail=err_detail, stream=s)
                failed_steps.append(label)

    s.write("\n")
    if ok:
        scope = data.get("scope", "")
        if scope == "all":
            success("Clean. Reinstall: uv tool install scubiee", stream=s)
        else:
            success("Repository wipe complete", stream=s)
    else:
        remaining = data.get("remaining") or []
        if remaining:
            warn(
                "Some Scubiee files remain — quit Cursor completely so MCP releases locks, "
                "then run wipe again",
                stream=s,
            )
        elif data.get("scope") == "all":
            warn(
                "Wipe finished with warnings — quit Cursor so MCP does not recreate `.scubiee/sessions/`",
                stream=s,
            )

    repo_wipes = []
    for action_dict in actions:
        val = action_dict.get("wipe_repos")
        if isinstance(val, list):
            repo_wipes = val
    removed = [
        str(path)
        for item in repo_wipes
        for path in (item.get("removed_id_dirs") or [])
    ]
    if removed:
        info(f"Removed {len(removed)} `.scubiee` folder(s) under wiped repos", stream=s)
        for path in removed[:5]:
            kv("removed", path, stream=s)
        if len(removed) > 5:
            info(f"... and {len(removed) - 5} more", stream=s)
    s.write("\n")
    s.flush()

# ── Init progress helper ──────────────────────────────────────────────────────

class InitProgress:
    """Single progress bar for the entire init process.

    Shows: [????????????????????] 40%  Embedding
    The bar fills as phases progress, text on right shows current phase.
    """

    def __init__(self, stream=None):
        self.stream = stream or sys.stderr
        self.c = colors(self.stream)
        self._tty = _is_tty(self.stream)
        self._last_line_len = 0
        self._pct = 0.0
        self._parse_pulse = 0.0

    def start(self):
        branded_header("init", stream=self.stream)

    def announce_scope(self, n_files: int):
        eta = format_index_eta(n_files)
        info(f"{n_files:,} files  ·  {eta}", stream=self.stream)

    def _bar(self, pct: float, label: str):
        """Render one in-place line. Graphify/other logs must not share this stream."""
        bar_width = 24
        pct = max(0.0, min(1.0, pct))
        self._pct = pct
        label = _clean_progress_label(label)
        filled = int(bar_width * pct)
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
        if pct > 0:
            msg = f"[{bar}] {pct:.0%}  {label}"
        else:
            msg = f"[{bar}]  {label}"
        if self._tty:
            line = f"  {msg}"
            pad = max(0, self._last_line_len - len(line))
            self.stream.write(f"\r  {msg}{' ' * pad}")
            self.stream.flush()
            self._last_line_len = max(self._last_line_len, len(line))
        # Non-TTY: only print at key milestones
        elif pct in (0, 1.0) or label != getattr(self, '_last_label', ''):
            self.stream.write(f"  {msg}\n")
            self.stream.flush()
            self._last_label = label

    def indexing(self, current: int = 0, total: int = 0):
        """Called during embed phase with chunk counts."""
        if total > 0:
            pct = current / total
            # Map embed progress (0-100%) to bar range 40%-90%
            bar_pct = 0.40 + 0.50 * pct
            self._bar(bar_pct, f"Embedding  {current:,}/{total:,}")
        else:
            self._bar(0.05, "Parsing")

    def done(self, chunks: int):
        """Finish the bar at 100% then print the success line."""
        self._bar(1.0, "Done")
        if self._tty:
            # Overwrite bar with final success line
            msg = f"{self.c.green}{ICON_OK}{self.c.reset} Indexed  {self.c.muted}{chunks:,} chunks{self.c.reset}"
            pad = max(0, self._last_line_len - len(f"  {ICON_OK} Indexed  {chunks:,} chunks"))
            self.stream.write(f"\r  {msg}{' ' * pad}\n")
        else:
            self.stream.write(f"  {ICON_OK} Indexed  {chunks:,} chunks\n")
        self.stream.flush()
        self._last_line_len = 0

    def already_initialized(self, chunks: int):
        success(
            "Codebase already indexed",
            detail=f"{chunks:,} chunks",
            stream=self.stream,
        )

    def index_updated(self, chunks: int, *, files: int = 0):
        detail = f"{files} file(s) updated" if files else "incremental sync"
        if chunks:
            detail = f"{detail}, {chunks:,} chunks"
        success("Index updated", detail=detail, stream=self.stream)

    def daemon_started(self):
        success("Daemon started", stream=self.stream)

    def finish(self):
        self.stream.write(f"\n  {self.c.green}{ICON_OK}{self.c.reset} {self.c.bold}Ready{self.c.reset}\n\n")
        self.stream.flush()

    def fail(self, message: str, *, hint: str = ""):
        if self._tty:
            pad = max(0, self._last_line_len - (len(message) + 4))
            self.stream.write(f"\r  {self.c.red}{ICON_FAIL}{self.c.reset} {message}{' ' * pad}\n")
        else:
            self.stream.write(f"  {ICON_FAIL} {message}\n")
        if hint:
            self.stream.write(f"\n    {self.c.muted}{hint}{self.c.reset}\n")
        self.stream.write("\n")
        self.stream.flush()
        self._last_line_len = 0

    def cancelled(self):
        self.stream.write("  Cancelled.\n\n")
        self.stream.flush()

    # Adapter for pipeline progress_ui interface
    def set(self, pct, phase):
        phase_lower = phase.lower()
        # Map internal phases to clean labels + bar percentage
        if "scanning" in phase_lower:
            self._bar(0.03, "Scanning")
        elif "parsing" in phase_lower:
            if self._parse_pulse < 0.08:
                self._parse_pulse = 0.08
            self._bar(self._parse_pulse, "Parsing")
        elif "building" in phase_lower or "chunk" in phase_lower:
            self._parse_pulse = 0.35
            self._bar(0.35, "Chunking")
        elif "embedding" in phase_lower:
            import re as _re
            m = _re.search(r"(\d+)/(\d+)", phase)
            if m:
                done, total = int(m.group(1)), int(m.group(2))
                bar_pct = 0.40 + 0.50 * (done / max(total, 1))
                self._bar(bar_pct, f"Embedding  {done:,}/{total:,}")
            else:
                self._bar(0.40, "Embedding")
        elif "writing" in phase_lower:
            self._bar(0.92, "Writing index")
        elif "daemon" in phase_lower:
            pass  # handled by daemon_started()

    def pulse(self, phase, *, until=100):
        if "parsing" in str(phase).lower():
            self._parse_pulse = min(0.35, max(self._parse_pulse, 0.08) + 0.005)
            self._bar(self._parse_pulse, "Parsing")
            return
        self.set(until, phase)

    def notice(self, msg):
        warn(msg, stream=self.stream)


# ── Wipe progress (single bar) ────────────────────────────────────────────────

class WipeProgress:
    """Single progress bar for wipe — label + % update in place; checkmarks stack above."""

    _BAR_WIDTH = 24
    _INDENT = 2

    def __init__(self, stream: IO[str] | TextIO | None = None):
        self.stream = stream or sys.stderr
        self.c = colors(self.stream)
        self._tty = _is_tty(self.stream)
        self._phase_idx = 0
        self._phase_count = 1
        self._phase_sub = 0.0
        self._phase_start = 0.0
        self._active_label = ""
        self._last_line_len = 0
        self._line_open = False
        self._finished_messages: set[str] = set()
        self._scope = "all"

    def configure(
        self,
        *,
        scope: str = "all",
        models: bool = True,
        package: bool = True,
        halt_first: bool = True,
        restart_engine: bool = True,
    ) -> None:
        self._scope = scope
        if scope == "repo":
            self._phase_count = sum([halt_first, True, restart_engine])
        else:
            n = 6
            if models:
                n += 1
            if package:
                n += 1
            self._phase_count = max(n, 1)

    def start(self) -> None:
        branded_header("wipe", stream=self.stream)

    def _pct(self) -> float:
        if self._phase_count <= 0:
            return 1.0
        step = 1.0 / self._phase_count
        return min(1.0, self._phase_idx * step + step * self._phase_sub)

    def _bar_text(self) -> str:
        pct = self._pct()
        filled = int(self._BAR_WIDTH * pct)
        bar = "\u2588" * filled + "\u2591" * (self._BAR_WIDTH - filled)
        elapsed = int(time.monotonic() - self._phase_start) if self._phase_start else 0
        elapsed_str = f"  {elapsed}s" if elapsed >= 2 else ""
        label = self._active_label or "Working\u2026"
        return f"[{bar}] {pct:.0%}  {label}{elapsed_str}"

    def _render_bar(self) -> None:
        pad = " " * self._INDENT
        line = f"{pad}{self._bar_text()}"

        if not self._tty:
            if line != getattr(self, "_non_tty_last", ""):
                self.stream.write(f"{line}\n")
                self.stream.flush()
                self._non_tty_last = line  # type: ignore[attr-defined]
            return

        if not self._line_open:
            self.stream.write(line)
        else:
            pad_erase = max(0, self._last_line_len - len(line))
            self.stream.write(f"\r{line}{' ' * pad_erase}")
        self.stream.flush()
        self._last_line_len = len(line)
        self._line_open = True

    def step_active(self, message: str) -> None:
        self._active_label = message
        self._phase_sub = 0.05
        self._phase_start = time.monotonic()
        self._render_bar()

    def step_update(self, message: str) -> None:
        self._active_label = message
        match = re.search(r"\((\d+)/(\d+)\)", message)
        if match:
            cur, total = int(match.group(1)), max(int(match.group(2)), 1)
            self._phase_sub = min(1.0, cur / total)
        self._render_bar()

    def step_finish(self, message: str, detail: str = "") -> None:
        if message in self._finished_messages:
            return
        self._finished_messages.add(message)
        self._phase_idx += 1
        self._phase_sub = 0.0
        detail_str = f"  {self.c.muted}{detail}{self.c.reset}" if detail else ""
        pad = " " * self._INDENT
        check = f"{pad}{self.c.green}{ICON_OK}{self.c.reset} {message}{detail_str}"

        if self._tty and self._line_open:
            self.stream.write(f"\033[1A\033[K{check}\n")
            self._line_open = False
        else:
            self.stream.write(f"{check}\n")
            self.stream.flush()

        self._phase_start = 0.0

    def finish(self, message: str = "") -> None:
        pad = " " * self._INDENT
        if self._line_open and self._tty:
            self._active_label = message or "Done"
            self._phase_idx = self._phase_count
            self._phase_sub = 1.0
            self._render_bar()
            erase = " " * self._last_line_len
            self.stream.write(f"\r{erase}\r")
            self._line_open = False
        if message:
            self.stream.write(
                f"{pad}{self.c.green}{ICON_OK}{self.c.reset} {self.c.bold}{message}{self.c.reset}\n\n"
            )
        self.stream.flush()

