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
    """One notice + one live bar on the shared progress engine.

    ``set(pct, phase)`` values are caller milestones: they set a monotonic
    floor and start an indeterminate step (spinner + clock, no frozen number).
    ``update(done, total)`` reports measured work. Non-TTY prints sparse lines.
    """

    def __init__(
        self,
        stream: IO[str] | TextIO | None = None,
        *,
        enabled: bool | None = None,
        tty: bool | None = None,
        width: int = 28,
    ) -> None:
        from pipeline.progress import ProgressModel, ProgressRenderer

        stream = stream if stream is not None else sys.stderr
        if enabled is None:
            flag = (os.environ.get("CTX_PROGRESS") or "1").strip().lower()
            enabled = flag not in {"0", "false", "no", "off"}
        self.enabled = bool(enabled)
        if tty is None:
            tty = bool(getattr(stream, "isatty", lambda: False)())
        self._model = ProgressModel()
        self._r = ProgressRenderer(
            self._model, stream, tty=bool(tty), color=False, width=width, indent=0
        )
        self._started = False

    @property
    def stream(self) -> IO[str] | TextIO:
        return self._r.stream

    @stream.setter
    def stream(self, value: IO[str] | TextIO) -> None:
        self._r.stream = value

    @property
    def _tty(self) -> bool:
        return self._r.tty

    @property
    def _pct(self) -> int:
        return int(self._model.snapshot().fraction * 100)

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
        self._model.milestone(max(0, min(100, int(pct))) / 100.0, str(phase))
        self._r.activate()

    def pulse(self, phase: str, *, until: int) -> None:
        if not self.enabled:
            return
        snap = self._model.snapshot()
        self._model.milestone(snap.fraction, str(phase), until=max(0, min(100, int(until))) / 100.0)
        self._r.activate()

    def update(self, done: float, total: float | None = None, *, label: str | None = None, unit: str = "count") -> None:
        if not self.enabled:
            return
        if label:
            self._model.milestone(self._model.snapshot().fraction, label)
        self._model.update(done, total, unit=unit)
        self._r.activate()

    def finish(self, phase: str = "Ready") -> None:
        if not self.enabled:
            return
        self._model.complete(phase)
        self._r.refresh()
        self._r.stop(clear=False)

    def fail(self, phase: str) -> None:
        if not self.enabled:
            return
        self._r.stop()
        self.stream.write(f"Failed: {phase}\n")
        self.stream.flush()

    def notice(self, message: str) -> None:
        """Print a user-facing notice without labeling it as a failure."""
        self._r.write_above(f"{message}\n")
