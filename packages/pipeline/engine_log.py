"""engine.log plumbing: per-line timestamps, self-redirected stdio, stop/kill audit.

Every line the engine writes (``print(..., file=sys.stderr)``, socketserver
tracebacks, ``http.server`` request lines) gets a ``YYYY-MM-DD HH:MM:SS.mmm``
prefix, so a restart timeline can be read straight from the log.

``note_stop`` is the one place every stop/kill path reports to: target, pid,
caller pid/role/function and a reason, appended to engine.log (and
watchdog.log when the watchdog is the target). A kill that is *not* in the
log came from outside Scubiee (host tree kill, job close, crash).
"""

from __future__ import annotations

import io
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

_WRITE_LOCK = threading.Lock()


def stamp() -> str:
    now = time.time()
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)) + f".{int(now * 1000) % 1000:03d}"


class TimestampedStream(io.TextIOBase):
    """Text stream wrapper that prefixes each new line with a timestamp."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._bol = True

    def write(self, s: str) -> int:  # type: ignore[override]
        if not s:
            return 0
        out: list[str] = []
        with _WRITE_LOCK:
            i = 0
            n = len(s)
            while i < n:
                j = s.find("\n", i)
                end = n if j < 0 else j + 1
                if self._bol:
                    out.append(stamp() + " ")
                out.append(s[i:end])
                self._bol = j >= 0
                i = end
            self._inner.write("".join(out))
        return len(s)

    def flush(self) -> None:
        try:
            self._inner.flush()
        except Exception:  # noqa: BLE001
            pass

    def fileno(self) -> int:
        return self._inner.fileno()

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return getattr(self._inner, "encoding", "utf-8")

    @property
    def errors(self) -> str | None:  # type: ignore[override]
        return getattr(self._inner, "errors", None)

    @property
    def buffer(self) -> Any:
        return getattr(self._inner, "buffer", None)


def install_line_timestamps() -> None:
    """Wrap sys.stdout / sys.stderr (idempotent; no-op when a stream is missing)."""
    for name in ("stdout", "stderr"):
        cur = getattr(sys, name, None)
        if cur is None or isinstance(cur, TimestampedStream):
            continue
        setattr(sys, name, TimestampedStream(cur))


def enable_fault_dumps() -> None:
    """Python stacks of every thread on a native crash (access violation) → engine.log."""
    try:
        import faulthandler

        target = sys.stderr
        if target is None:
            return
        faulthandler.enable(file=target, all_threads=True)
    except Exception:  # noqa: BLE001
        pass


def redirect_stdio_to(path: Path | str, *, banner: str = "") -> None:
    """Point fds 1/2 (and the Win32 std handles) at ``path`` in append mode.

    Used when the engine was created by WMI (no inherited handles): native
    libraries writing to stderr land in the same file as Python output.
    """
    fh = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    if banner:
        fh.write(banner)
        fh.flush()
    fd = fh.fileno()
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    if os.name == "nt":
        try:
            import ctypes
            import msvcrt

            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            k32.SetStdHandle(-11, msvcrt.get_osfhandle(1))  # STD_OUTPUT_HANDLE
            k32.SetStdHandle(-12, msvcrt.get_osfhandle(2))  # STD_ERROR_HANDLE
        except Exception:  # noqa: BLE001
            pass
    sys.stdout = open(1, "w", encoding="utf-8", buffering=1, closefd=False)  # noqa: SIM115
    sys.stderr = open(2, "w", encoding="utf-8", buffering=1, closefd=False)  # noqa: SIM115
    fh.close()


def _home() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home()


def _caller_role() -> str:
    role = (os.environ.get("CTX_SCUBIEE_ROLE") or "").strip()
    if role:
        return role
    if os.environ.get("CTX_MCP_BRIDGE"):
        return "mcp_bridge"
    argv = " ".join(sys.argv[:4]).replace("\\", "/")
    return argv[-80:] if argv else "?"


def classify_pid(pid: int) -> str:
    """engine | watchdog | supervisor | mcp_bridge | mcp_worker | other | gone."""
    try:
        import psutil

        cmd = " ".join(psutil.Process(int(pid)).cmdline()).lower().replace("/", "\\")
    except Exception:  # noqa: BLE001
        return "gone"
    if "engine run" in cmd:
        return "engine"
    if "watchdog" in cmd:
        return "watchdog"
    if "supervisor" in cmd:
        return "supervisor"
    if "mcp_bridge" in cmd or "mcp-bridge" in cmd:
        return "mcp_bridge"
    if "mcp_locate" in cmd or "scubiee-mcp" in cmd or "mcp_server" in cmd:
        return "mcp_worker"
    return "other"


def note_stop(
    target: str,
    pid: int | None,
    *,
    reason: str,
    method: str,
    **extra: Any,
) -> None:
    """Append one audit line for a stop/kill of an engine/watchdog/MCP process. Never raises."""
    try:
        # Short call chain (innermost first): who asked, not just who killed.
        frames = []
        frame = sys._getframe(1)  # noqa: SLF001
        while frame is not None and len(frames) < 4:
            frames.append(f"{Path(frame.f_code.co_filename).stem}.{frame.f_code.co_name}")
            frame = frame.f_back
        caller = "<".join(frames)
    except Exception:  # noqa: BLE001
        caller = "?"
    bits = " ".join(f"{k}={v}" for k, v in extra.items() if v is not None)
    line = (
        f"{stamp()} [stop] target={target} pid={pid} reason={reason} method={method} "
        f"by_pid={os.getpid()} by={_caller_role()} at={caller} {bits}".rstrip()
        + "\n"
    )
    names = ["engine.log"]
    if target == "watchdog":
        names.append("watchdog.log")
    for name in names:
        try:
            if name == "engine.log" and os.environ.get("CTX_SCUBIEE_ROLE") == "engine" and sys.stderr:
                # Inside the engine: its own stderr *is* engine.log (keeps ordering).
                sys.stderr.write(line.split(" ", 2)[2])
                sys.stderr.flush()
                continue
            home = _home()
            home.mkdir(parents=True, exist_ok=True)
            with open(home / name, "a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:  # noqa: BLE001
            pass


def hard_exit(code: int = 0, *, reason: str) -> None:
    """Leave the engine process without running DLL detach routines.

    ``os._exit`` → ExitProcess still calls every DLL's PROCESS_DETACH, where
    ONNX Runtime / DirectML static destructors have been seen to fault
    (0xc0000005 in onnxruntime_pybind11_state.pyd) while other threads were
    killed mid-inference. TerminateProcess skips DLL detach. State must already
    be on disk; logs are flushed here.
    """
    try:
        note_stop("engine", os.getpid(), reason=reason, method="self_terminate", code=code)
    except Exception:  # noqa: BLE001
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.flush()
        except Exception:  # noqa: BLE001
            pass
    if os.name == "nt" and (os.environ.get("CTX_ENGINE_EXIT_TERMINATE") or "1").strip() not in {"0", "false", "off", "no"}:
        try:
            import ctypes

            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            k32.TerminateProcess(k32.GetCurrentProcess(), int(code))
        except Exception:  # noqa: BLE001
            pass
    os._exit(int(code))
