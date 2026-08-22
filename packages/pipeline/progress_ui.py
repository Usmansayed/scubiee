"""Single in-place 0–100% terminal bar for install/setup.

Most CLIs (pip, rustup, uv, Hugging Face) rewrite one progress line with a
carriage return instead of printing a log dump. This module does that with
the stdlib only so setup does not need an extra UI package.
"""

from __future__ import annotations

import os
import sys
from typing import IO, TextIO


def _block_chars(stream: IO[str] | TextIO) -> tuple[str, str]:
    encoding = getattr(stream, "encoding", None) or getattr(sys.stderr, "encoding", None) or "utf-8"
    fill, empty = "█", "░"
    try:
        fill.encode(encoding)
        empty.encode(encoding)
        return fill, empty
    except LookupError:
        return "#", "-"
    except UnicodeEncodeError:
        return "#", "-"


def render_bar(pct: int, width: int = 28, *, fill: str | None = None, empty: str | None = None) -> str:
    pct = max(0, min(100, int(pct)))
    if fill is None or empty is None:
        fill, empty = _block_chars(sys.stderr)
    filled = int(round(width * pct / 100.0))
    filled = max(0, min(width, filled))
    return f"[{fill * filled}{empty * (width - filled)}] {pct:3d}%"


class InstallProgress:
    """One banner + one rewriting bar. Non-TTY prints sparse percent lines."""

    def __init__(
        self,
        stream: IO[str] | TextIO | None = None,
        *,
        enabled: bool | None = None,
        tty: bool | None = None,
        width: int = 28,
    ) -> None:
        self.stream: IO[str] | TextIO = stream if stream is not None else sys.stderr
        if enabled is None:
            flag = (os.environ.get("CTX_PROGRESS") or "1").strip().lower()
            enabled = flag not in {"0", "false", "no", "off"}
        self.enabled = bool(enabled)
        if tty is None:
            tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self._tty = bool(tty)
        self.width = width
        self._fill, self._empty = _block_chars(self.stream)
        self._pct = 0
        self._phase = ""
        self._last_drawn = ""
        self._last_emitted_pct = -100
        self._last_emitted_phase = ""
        self._started = False

    def start(self, notice: str | None = None) -> None:
        if not self.enabled:
            return
        msg = notice or (
            "This may take a few minutes. Downloading and installing the Scubiee engine."
        )
        self.stream.write(msg + "\n")
        self.stream.flush()
        self._started = True
        self.set(0, "Starting")

    def set(self, pct: int, phase: str) -> None:
        if not self.enabled:
            return
        pct = max(self._pct, max(0, min(100, int(pct))))
        self._pct = pct
        self._phase = str(phase)
        self._draw()

    def pulse(self, phase: str, *, until: int) -> None:
        if not self.enabled:
            return
        until = max(0, min(100, int(until)))
        nxt = min(until, self._pct + 1)
        if nxt == self._pct and phase == self._phase:
            return
        self._pct = max(self._pct, nxt)
        self._phase = str(phase)
        self._draw()

    def finish(self, phase: str = "Ready") -> None:
        if not self.enabled:
            return
        self._pct = 100
        self._phase = phase
        self._draw(force=True)
        if self._tty:
            self.stream.write("\n")
            self.stream.flush()

    def fail(self, phase: str) -> None:
        if not self.enabled:
            return
        if self._tty and self._started:
            self.stream.write("\n")
        self.stream.write(f"Failed: {phase}\n")
        self.stream.flush()

    def notice(self, message: str) -> None:
        """Print a user-facing notice without labeling it as a failure."""
        if self._tty and self._started:
            self.stream.write("\n")
        self.stream.write(f"{message}\n")
        self.stream.flush()

    def _draw(self, *, force: bool = False) -> None:
        if not self.enabled:
            return
        line = f"{render_bar(self._pct, self.width, fill=self._fill, empty=self._empty)}  {self._phase}"
        if self._tty:
            pad = max(0, len(self._last_drawn) - len(line))
            self.stream.write("\r" + line + (" " * pad))
            self.stream.flush()
            self._last_drawn = line
            return
        jumped = self._pct - self._last_emitted_pct >= 5
        phase_changed = force or self._phase != self._last_emitted_phase
        if not force and not jumped and not phase_changed:
            return
        self.stream.write(line + "\n")
        self.stream.flush()
        self._last_emitted_pct = self._pct
        self._last_emitted_phase = self._phase
