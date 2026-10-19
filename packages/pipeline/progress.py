"""Shared progress engine behind every CLI loader.

Two pieces:

- ``ProgressModel`` — thread-safe state. Work is split into *stages* (planned,
  with relative weights) or *milestones* (legacy ``set(pct, phase)`` callers).
  A stage is either **measurable** (``update(done, total)``) or
  **indeterminate**. Overall fraction = completed stage weight + current stage
  weight x measured fraction. It never moves backward and only reaches 1.0 on
  ``complete()``.
- ``ProgressRenderer`` — draws one in-place line from a model snapshot. A
  background ticker keeps the spinner and elapsed clock moving even while the
  producer is silent. A numeric percent is shown only while the current stage
  is measurable; indeterminate stages show the stage name, step counter and
  elapsed time instead of a frozen number.
"""

from __future__ import annotations

import re
import shutil
import threading
import time
from dataclasses import dataclass
from typing import IO, Any, Callable, Sequence, TextIO

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ASCII_SPINNER_FRAMES = "|/-\\"
_BEFORE_COMPLETE = 0.99
_ETA_MIN_ELAPSED_S = 3.0
_ELAPSED_MIN_S = 3.0
_NON_TTY_BUCKET = 10


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    weight: float = 1.0


@dataclass(frozen=True)
class Snapshot:
    fraction: float
    stage_fraction: float | None
    percent: int | None
    label: str
    detail: str
    step: int | None
    steps: int | None
    measurable: bool
    stage_elapsed: float
    eta_s: float | None
    done: bool


def format_bytes(n: float) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.0f} {unit}" if unit in ("B", "KB") else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} GB"


def format_clock(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def format_eta(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"~{max(5, (s + 4) // 5 * 5)}s left"
    if s < 300:
        s = (s + 5) // 10 * 10
        return f"~{s // 60}m{s % 60:02d}s left"
    if s < 3600:
        return f"~{(s + 30) // 60}m left"
    return f"~{s // 3600}h{(s % 3600) // 60:02d}m left"


_ELAPSED_SUFFIX_RE = re.compile(r"\s*\(\d+s\)\s*$")
_ELLIPSIS_RE = re.compile(r"(\u2026|\.\.\.)\s*$")


def clean_label(label: str) -> str:
    """Strip caller-side elapsed suffixes / trailing ellipses; the renderer adds its own."""
    text = _ELAPSED_SUFFIX_RE.sub("", str(label or "")).strip()
    return _ELLIPSIS_RE.sub("", text).strip()


class ProgressModel:
    """Monotonic, thread-safe progress state shared by producer and renderer."""

    def __init__(self, stages: Sequence[Stage] = (), *, clock: Callable[[], float] = time.monotonic):
        self._stages = list(stages)
        self._index = {s.key: i for i, s in enumerate(self._stages)}
        weights = [max(0.0, float(s.weight)) for s in self._stages]
        total = sum(weights) or 1.0
        self._bounds: list[tuple[float, float]] = []
        acc = 0.0
        for w in weights:
            self._bounds.append((acc / total, (acc + w) / total))
            acc += w
        self._clock = clock
        self._lock = threading.RLock()
        self._cur = -1
        self._lo = 0.0
        self._hi = 0.0
        self._label = ""
        self._done = 0.0
        self._total: float | None = None
        self._unit = "count"
        self._stage_t0 = clock()
        self._rate_t0 = self._stage_t0
        self._rate_d0 = 0.0
        self._progress_t = self._stage_t0
        self._high = 0.0
        self._complete = False

    @property
    def planned(self) -> bool:
        return bool(self._stages)

    def _reset_measure(self, total: float | None, unit: str) -> None:
        self._done = 0.0
        self._total = float(total) if total else None
        self._unit = unit
        now = self._clock()
        self._stage_t0 = now
        self._rate_t0 = now
        self._rate_d0 = 0.0
        self._progress_t = now

    def begin(
        self,
        key: str,
        *,
        label: str | None = None,
        total: float | None = None,
        unit: str = "count",
    ) -> None:
        """Enter a planned stage. Earlier stages count as complete; going back is ignored."""
        with self._lock:
            if self._complete:
                return
            idx = self._index.get(key)
            if idx is None or idx < self._cur:
                if label:
                    self._label = clean_label(label)
                return
            if idx == self._cur:
                if label:
                    self._label = clean_label(label)
                if total:
                    self._total = float(total)
                return
            self._cur = idx
            self._lo, self._hi = self._bounds[idx]
            self._label = clean_label(label or self._stages[idx].label)
            self._reset_measure(total, unit)
            self._bump()

    def milestone(self, fraction: float, label: str, *, until: float | None = None) -> None:
        """Legacy ``set(pct, phase)``: committed floor + new indeterminate segment."""
        with self._lock:
            if self._complete:
                return
            lo = max(0.0, min(1.0, float(fraction)))
            label = clean_label(label)
            if lo <= self._lo and label == self._label:
                if until is not None:
                    self._hi = max(self._hi, min(1.0, float(until)))
                return
            self._lo = max(self._lo, lo, self._high)
            self._hi = max(self._lo, min(1.0, float(until))) if until is not None else self._lo
            self._label = label
            self._reset_measure(None, "count")
            self._bump()

    def set_label(self, label: str) -> None:
        with self._lock:
            if not self._complete:
                self._label = clean_label(label)

    def update(
        self,
        done: float,
        total: float | None = None,
        *,
        label: str | None = None,
        unit: str | None = None,
    ) -> None:
        """Report measured work in the current stage (``total=None`` = count only)."""
        with self._lock:
            if self._complete:
                return
            if unit:
                self._unit = unit
            if total:
                self._total = float(total)
            if label:
                self._label = clean_label(label)
            if float(done) > self._done:
                self._done = float(done)
                self._progress_t = self._clock()
            self._bump()

    def complete(self, label: str | None = None) -> None:
        with self._lock:
            self._complete = True
            self._high = 1.0
            if label:
                self._label = clean_label(label)

    def _stage_frac(self) -> float | None:
        if not self._total:
            return None
        return max(0.0, min(1.0, self._done / self._total))

    def _bump(self) -> None:
        frac = self._stage_frac()
        overall = self._lo + (self._hi - self._lo) * (frac or 0.0)
        self._high = max(self._high, min(overall, _BEFORE_COMPLETE))

    def _eta(self, now: float) -> float | None:
        frac = self._stage_frac()
        if frac is None or frac >= 1.0:
            return None
        progressed = self._done - self._rate_d0
        measured = self._progress_t - self._rate_t0
        if now - self._rate_t0 < _ETA_MIN_ELAPSED_S or progressed <= 0 or measured <= 0:
            return None
        # Rate up to the last real progress, counted down since then. A stall that
        # outlives the estimate (last batch, post-embed write) means the estimate
        # was wrong: show elapsed time instead of a countdown pinned at "~5s".
        eta = (float(self._total or 0) - self._done) / (progressed / measured)
        left = eta - (now - self._progress_t)
        return left if left > 0 else None

    def snapshot(self) -> Snapshot:
        with self._lock:
            now = self._clock()
            frac = self._stage_frac()
            measurable = frac is not None
            if self._unit == "bytes":
                detail = (
                    f"{format_bytes(self._done)} / {format_bytes(self._total)}"
                    if self._total
                    else (format_bytes(self._done) if self._done else "")
                )
            elif self._total:
                detail = f"{int(self._done):,}/{int(self._total):,}"
            else:
                detail = f"{int(self._done):,}" if self._done else ""
            if self._complete:
                percent: int | None = 100
            elif measurable and self._hi > self._lo:
                percent = min(99, int(self._high * 100))
            else:
                percent = None
            return Snapshot(
                fraction=self._high,
                stage_fraction=frac,
                percent=percent,
                label=self._label,
                detail=detail,
                step=(self._cur + 1) if self.planned and self._cur >= 0 else None,
                steps=len(self._stages) if self.planned else None,
                measurable=measurable,
                stage_elapsed=now - self._stage_t0,
                eta_s=None if self._complete else self._eta(now),
                done=self._complete,
            )


class ProgressRenderer:
    """One in-place progress line driven by a ``ProgressModel``.

    ``bar="overall"`` always draws the overall bar; ``bar="stage"`` draws a bar
    only for measurable stages (stage-local fraction). Non-TTY streams get
    sparse log lines (label change or each 10% step) and no ticker thread.
    """

    def __init__(
        self,
        model: ProgressModel,
        stream: IO[str] | TextIO,
        *,
        tty: bool | None = None,
        color: bool | None = None,
        bar: str = "overall",
        width: int = 24,
        interval: float = 0.1,
        indent: int = 2,
        idle_label: str = "Working",
    ):
        self.model = model
        self._stream = stream
        self._tty_override = tty
        self._color_override = color
        self._bar_mode = bar
        self._width = width
        self._interval = interval
        self._indent = " " * indent
        self._idle_label = idle_label
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._frame = 0
        self._line_open = False
        self._last_len = 0
        self._active = False
        self._non_tty_key: tuple[Any, ...] | None = None
        self._configure_stream()

    def _configure_stream(self) -> None:
        s = self._stream
        if self._tty_override is not None:
            self.tty = bool(self._tty_override)
        else:
            self.tty = bool(getattr(s, "isatty", lambda: False)())
        if self._color_override is not None:
            color = bool(self._color_override)
        else:
            from pipeline.cli_ui import colors

            color = colors(s).enabled
        self._esc = (lambda code: f"\033[{code}m") if color else (lambda code: "")
        enc = (getattr(s, "encoding", "") or "utf-8").lower()
        utf = "utf" in enc
        self._frames = SPINNER_FRAMES if utf else ASCII_SPINNER_FRAMES
        self._fill, self._empty = ("\u2588", "\u2591") if utf else ("#", "-")

    @property
    def stream(self) -> IO[str] | TextIO:
        return self._stream

    @stream.setter
    def stream(self, value: IO[str] | TextIO) -> None:
        with self._lock:
            self._stream = value
            self._configure_stream()

    # ── lifecycle ─────────────────────────────────────────────────────────

    def activate(self) -> None:
        """Show the live line (starts the ticker on a TTY)."""
        with self._lock:
            self._active = True
            if self.tty and self._thread is None:
                self._stop.clear()
                self._thread = threading.Thread(target=self._tick, name="scubiee-progress", daemon=True)
                self._thread.start()
        self.refresh()

    def deactivate(self) -> None:
        """Hide the live line without stopping the ticker (between phased steps)."""
        with self._lock:
            self._active = False
            self._clear()

    def stop(self, *, clear: bool = True) -> None:
        """Stop the ticker. ``clear=False`` keeps the last drawn line on screen."""
        with self._lock:
            self._active = False
            self._stop.set()
            thread = self._thread
            self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with self._lock:
            if clear:
                self._clear()
            elif self.tty and self._line_open:
                self._stream.write("\n")
                self._stream.flush()
                self._line_open = False
                self._last_len = 0

    def _tick(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                with self._lock:
                    if not self._active:
                        continue
                    self._frame += 1
                    self._draw()
            except Exception:  # noqa: BLE001
                return

    # ── output ────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        with self._lock:
            if self._active:
                self._draw()

    def write_above(self, text: str) -> None:
        """Print a permanent line (must end with newline) above the live line."""
        with self._lock:
            self._clear()
            self._stream.write(text)
            self._stream.flush()
            if self._active:
                self._draw()

    def _clear(self) -> None:
        if self.tty and self._line_open:
            self._stream.write("\r" + " " * self._last_len + "\r")
            self._stream.flush()
        self._line_open = False
        self._last_len = 0

    def _bar_text(self, frac: float) -> str:
        frac = max(0.0, min(1.0, frac))
        filled = int(self._width * frac)
        return "[" + self._fill * filled + self._empty * (self._width - filled) + "]"

    def compose(self, snap: Snapshot, *, spinner: str | None) -> tuple[str, str]:
        """Return (plain, styled) line text for ``snap``."""
        blue, muted, green, reset = self._esc("34"), self._esc("90"), self._esc("32"), self._esc("0")
        parts: list[tuple[str, str]] = []
        if spinner is not None:
            if snap.done:
                parts.append(("\u2713" if self._fill == "\u2588" else "+", green))
            else:
                parts.append((spinner, blue))
        bar_frac: float | None = None
        if self._bar_mode == "overall":
            bar_frac = snap.fraction
        elif self._bar_mode == "stage" and snap.stage_fraction is not None:
            bar_frac = 1.0 if snap.done else snap.stage_fraction
        if bar_frac is not None:
            parts.append((self._bar_text(bar_frac), ""))
        if self._bar_mode == "stage":
            # Stage-local bar: the step's own measured work, so 100% is truthful
            # once its total is reached (the overall run may continue).
            if snap.done:
                pct: int | None = 100
            elif snap.stage_fraction is not None:
                pct = int(snap.stage_fraction * 100)
            else:
                pct = None
        elif self._bar_mode != "overall":
            pct = None
        elif snap.percent is not None:
            pct = snap.percent
        elif not self.tty:
            # A log line is a point-in-time record of completed work, not a live
            # number that can sit frozen on screen.
            pct = int(snap.fraction * 100)
        else:
            pct = None
        if pct is not None:
            parts.append((f"{pct:>3d}%", ""))
        label = snap.label or self._idle_label
        if snap.detail:
            label = f"{label} {snap.detail}"
        parts.append((label, ""))
        extras: list[str] = []
        if not snap.done:
            if snap.measurable and snap.eta_s is not None:
                extras.append(format_eta(snap.eta_s))
            if not snap.measurable and snap.step and snap.steps:
                extras.append(f"step {snap.step}/{snap.steps}")
            no_eta = not snap.measurable or snap.eta_s is None
            if no_eta and snap.stage_elapsed >= _ELAPSED_MIN_S and self.tty:
                extras.append(format_clock(snap.stage_elapsed))
        if extras:
            parts.append(("\u00b7 " + " \u00b7 ".join(extras), muted))
        plain = self._indent + " ".join(p for p, _ in parts)
        styled = self._indent + " ".join(f"{c}{p}{reset}" if c else p for p, c in parts)
        return plain, styled

    def _max_cols(self) -> int:
        try:
            return max(20, shutil.get_terminal_size((100, 24)).columns - 1)
        except Exception:  # noqa: BLE001
            return 99

    def _draw(self) -> None:
        snap = self.model.snapshot()
        if not self.tty:
            self._draw_non_tty(snap)
            return
        spinner = self._frames[self._frame % len(self._frames)]
        plain, styled = self.compose(snap, spinner=spinner)
        cols = self._max_cols()
        if len(plain) > cols:
            plain = plain[: cols - 1] + "\u2026"
            styled = plain
        pad = max(0, self._last_len - len(plain))
        self._stream.write("\r" + styled + " " * pad)
        self._stream.flush()
        self._line_open = True
        self._last_len = len(plain)

    def _draw_non_tty(self, snap: Snapshot) -> None:
        bucket = int(snap.fraction * 100) // _NON_TTY_BUCKET
        key = (snap.label, bucket, snap.done)
        if key == self._non_tty_key:
            return
        self._non_tty_key = key
        plain, _ = self.compose(snap, spinner=None)
        self._stream.write(plain + "\n")
        self._stream.flush()
