"""Live trace of the init progress bar during a real index build.

Runs index_repo on a real directory into a temp store with InitProgress drawing
to a recording fake TTY, samples the model every 0.25s, and reports per-stage
timing, monotonicity, the largest jump, and the longest frozen-percent window.

    python scripts/progress_live_trace.py [root]
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages"))

from pipeline.cli_ui import InitProgress  # noqa: E402


class _RecordingTTY(io.TextIOBase):
    encoding = "utf-8"

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.frames: list[tuple[float, str]] = []

    def isatty(self) -> bool:
        return True

    def write(self, s: str) -> int:
        for part in s.split("\r"):
            if part.strip():
                self.frames.append((time.monotonic() - self.t0, part.rstrip()))
        return len(s)

    def flush(self) -> None:
        pass


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "packages/graphify").resolve()
    os.environ["CTX_QUIET"] = "1"
    os.environ["GRAPHIFY_QUIET"] = "1"
    rec = _RecordingTTY()
    bar = InitProgress(stream=rec)
    samples: list[tuple[float, float, int | None, str, str]] = []
    stop = threading.Event()

    def sample() -> None:
        while not stop.wait(0.25):
            s = bar.snapshot()
            samples.append((time.monotonic() - rec.t0, s.fraction, s.percent, s.label, s.detail))

    threading.Thread(target=sample, daemon=True).start()
    real_out, real_err = sys.stdout, sys.stderr
    devnull = open(os.devnull, "w")
    sys.stdout = sys.stderr = devnull
    try:
        from pipeline.indexer import index_repo

        bar.stage("prepare")
        with tempfile.TemporaryDirectory() as store:
            stats = index_repo(root, base_dir=Path(store), progress=bar, confirm=True, force=True, quiesce=False)
        bar.stage("engine")
        bar.done(stats.chunks)
    finally:
        sys.stdout, sys.stderr = real_out, real_err
        devnull.close()
        stop.set()
    s = bar.snapshot()
    samples.append((time.monotonic() - rec.t0, s.fraction, s.percent, s.label, s.detail))

    fr = [x[1] for x in samples]
    monotonic = all(b >= a for a, b in zip(fr, fr[1:]))
    jumps = [(samples[i + 1][0], b - a, samples[i + 1][3]) for i, (a, b) in enumerate(zip(fr, fr[1:]))]
    big = max(jumps, key=lambda j: j[1]) if jumps else (0, 0, "")
    frozen, run_start, last_pct = 0.0, samples[0][0], samples[0][2]
    for t, _f, pct, _l, _d in samples[1:]:
        if pct is None or pct != last_pct:
            run_start, last_pct = t, pct
        else:
            frozen = max(frozen, t - run_start)
    print(f"root={root}  chunks={stats.chunks}  wall={samples[-1][0]:.1f}s  samples={len(samples)}")
    print(f"monotonic={monotonic}  final_percent={samples[-1][2]}  "
          f"largest_jump={big[1]*100:.1f}pts at {big[0]:.1f}s ({big[2]})  "
          f"longest_frozen_visible_percent={frozen:.1f}s")
    print("stage timeline:")
    cur, t_start, f_start = None, 0.0, 0.0
    for t, f, pct, label, detail in samples + [(samples[-1][0], 1.0, 100, "<end>", "")]:
        stage = label.split(" ")[0] if label else ""
        if stage != cur:
            if cur is not None:
                print(f"  {cur:<10} {t_start:6.1f}s -> {t:6.1f}s  ({t - t_start:5.1f}s)  bar {f_start*100:5.1f}% -> {f*100:5.1f}%")
            cur, t_start, f_start = stage, t, f
    print("sample frames:")
    step = max(1, len(rec.frames) // 12)
    for t, line in rec.frames[::step]:
        print(f"  {t:6.1f}s |{line}")
    return 0 if monotonic and samples[-1][2] == 100 else 1


if __name__ == "__main__":
    raise SystemExit(main())
