"""Replay a script(1) capture from vm/logs: distinct screen lines with timestamps.

    python vm/analyze_tty.py 07_init [more step ids...]

For each step prints every distinct line state (after \\r rewrites, ANSI stripped)
with the time it first appeared, plus the longest time any single visible
percentage stayed unchanged.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

LOGS = Path(__file__).resolve().parent / os.environ.get("VM_LOGS", "logs")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PCT = re.compile(r"(\d{1,3})%")


def timed_chunks(step: str) -> list[tuple[float, str]]:
    data = (LOGS / f"{step}.log").read_bytes()
    timing = LOGS / f"{step}.timing"
    header_end = data.find(b"\n") + 1  # "Script started ..." line
    body = data[header_end:]
    chunks: list[tuple[float, str]] = []
    if timing.is_file():
        t, pos = 0.0, 0
        for line in timing.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2:  # classic format: delay bytes
                delay, size = float(parts[0]), int(parts[1])
            elif len(parts) >= 3 and parts[0] == "O":  # advanced format: O delay bytes
                delay, size = float(parts[1]), int(parts[2])
            else:
                if len(parts) >= 2:
                    try:
                        t += float(parts[1])
                    except ValueError:
                        pass
                continue
            t += delay
            chunks.append((t, body[pos : pos + size].decode("utf-8", "replace")))
            pos += size
    else:
        chunks.append((0.0, body.decode("utf-8", "replace")))
    return chunks


def frames(step: str) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    line = ""

    def emit(t: float) -> None:
        stripped = line.rstrip()
        if stripped.strip() and (not out or out[-1][1] != stripped):
            out.append((t, stripped))

    for t, text in timed_chunks(step):
        for ch in ANSI.sub("", text):
            if ch in "\r\n":
                emit(t)
                line = ""
            else:
                line += ch
        emit(t)
    return out


def frozen_percent(fr: list[tuple[float, str]]) -> tuple[float, str]:
    worst, worst_line = 0.0, ""
    start_t, start_pct, start_line = None, None, ""
    for t, line in fr:
        m = PCT.search(line)
        pct = m.group(1) if m else None
        if pct != start_pct:
            start_t, start_pct, start_line = t, pct, line
        elif pct is not None and start_t is not None and t - start_t > worst:
            worst, worst_line = t - start_t, start_line
    return worst, worst_line


def main() -> None:
    for step in sys.argv[1:]:
        fr = frames(step)
        print(f"===== {step}: {len(fr)} screen states, last at {fr[-1][0] if fr else 0:.1f}s")
        last_t = None
        for t, line in fr:
            # collapse spinner-only redraws: show a state when text other than the spinner changes
            key = re.sub(r"^\s*\S\s", "", line)
            if last_t is not None and key == last_t:
                continue
            last_t = key
            print(f"  {t:7.1f}s | {line[:140]}")
        worst, line = frozen_percent(fr)
        if line:
            print(f"  longest unchanged visible percent: {worst:.1f}s  ({line.strip()[:80]})")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
