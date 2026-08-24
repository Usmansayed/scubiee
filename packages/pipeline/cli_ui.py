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


def branded_header(cmd: str, *, stream: IO[str] | TextIO | None = None) -> None:
    """Print a branded command header — used only for setup and init."""
    s = stream or sys.stderr
    if not _is_tty(s):
        return
    c = colors(s)
    s.write(f"\n{c.bold}scubiee {cmd}{c.reset}\n\n")
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


# ── Confirmation prompt ───────────────────────────────────────────────────────

def confirm_action(
    message: str,
    *,
    details: list[str] | None = None,
    default: bool = False,
    stream: IO[str] | TextIO | None = None,
    skip_if_not_tty: bool = True,
) -> bool:
    """Ask for y/n confirmation before a destructive action.

    Returns True if confirmed, False if declined.
    Non-TTY (piped) always returns default unless skip_if_not_tty is False.
    """
    s = stream or sys.stderr
    c = colors(s)

    if not _is_tty(sys.stdin):
        if skip_if_not_tty:
            return default
        return default

    # Print the warning
    s.write(f"\n  {c.yellow}{ICON_WARN}{c.reset} {c.bold}{message}{c.reset}\n")
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
        if phase == self._last_phase:
            return
        phase_key = phase.lower().split("(")[0].strip()
        if phase_key == self._last_key:
            return
        self._last_key = phase_key
        self._last_phase = phase
        phase_lower = phase.lower()

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
            self.step_active("Runtime issue — repairing")
            return
        if "reinstalling" in phase_lower:
            self.step_update("Reinstalling runtime\u2026")
            return
        if "runtime fixed" in phase_lower:
            self.step_finish("Runtime fixed")
            return

        if any(key in phase_lower for key in self._MODEL_STEP_KEYS):
            self.step_update("Preparing model\u2026")
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
        "stop_all": "Processes stopped",
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
            success("Repository cleaned", stream=s)
    else:
        if failed_steps:
            hint = "Close Cursor/Kiro, then run: scubiee wipe --all --confirm"
            error(f"{failed_steps[0]}", stream=s)
            info(hint, stream=s)
        else:
            remaining = data.get("remaining") or []
            if remaining:
                warn("Some files remain", detail="close IDE and retry", stream=s)
            else:
                success("Clean", stream=s)
    s.write("\n")
    s.flush()


# ── Init progress helper ──────────────────────────────────────────────────────

class InitProgress:
    """Clean progress display for scubiee init — single updating line."""

    def __init__(self, stream=None):
        self.stream = stream or sys.stderr
        self.c = colors(self.stream)
        self._tty = _is_tty(self.stream)
        self._last_line_len = 0

    def start(self):
        branded_header("init", stream=self.stream)

    def indexing(self, current: int = 0, total: int = 0):
        """Update the indexing progress line in-place."""
        if total > 0:
            msg = f"Indexing\u2026  {current:,}/{total:,} files"
        else:
            msg = "Indexing\u2026"
        if self._tty:
            line = f"  {ICON_RUN} {msg}"
            pad = max(0, self._last_line_len - len(line))
            self.stream.write(f"\r  {self.c.blue}{ICON_RUN}{self.c.reset} {msg}{' ' * pad}")
            self.stream.flush()
            self._last_line_len = max(self._last_line_len, len(line))
        else:
            self.stream.write(f"  {ICON_RUN} {msg}\n")
            self.stream.flush()

    def done(self, chunks: int):
        """Show indexing complete."""
        msg = f"Indexed"
        detail = f"{chunks:,} chunks"
        if self._tty:
            plain = f"  {ICON_OK} {msg}  {detail}"
            pad = max(0, self._last_line_len - len(plain))
            self.stream.write(f"\r  {self.c.green}{ICON_OK}{self.c.reset} {msg}  {self.c.muted}{detail}{self.c.reset}{' ' * pad}\n")
        else:
            self.stream.write(f"  {ICON_OK} {msg}  {detail}\n")
        self.stream.flush()
        self._last_line_len = 0

    def already_initialized(self, chunks: int):
        success(f"Already initialized", detail=f"{chunks:,} chunks", stream=self.stream)

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
        self.stream.write(f"  Cancelled.\n\n")
        self.stream.flush()

    # Adapter for pipeline progress_ui interface
    def set(self, pct, phase):
        phase_lower = phase.lower()
        if "parsing" in phase_lower or "scanning" in phase_lower:
            self.indexing()
        elif "embedding" in phase_lower:
            import re as _re
            m = _re.search(r"(\d+)/(\d+)", phase)
            if m:
                self.indexing(int(m.group(1)), int(m.group(2)))
            else:
                self.indexing()
        elif "chunk" in phase_lower or "indexing" in phase_lower:
            self.indexing()
        elif "daemon" in phase_lower:
            self.daemon_started()

    def pulse(self, phase, *, until=100):
        self.set(until, phase)

    def notice(self, msg):
        warn(msg, stream=self.stream)
