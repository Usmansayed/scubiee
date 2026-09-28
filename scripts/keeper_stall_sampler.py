"""Issue 4 follow-up: what is the keeper thread doing while a save waits?

Writes one new file (plain disk write), then py-spy dumps the engine every
~0.8s until the file is searchable (max 40s), keeping only the ``ctx-keeper``
thread's stack. Prints a tally of the top frames so a stall names its code.

    python scripts/keeper_stall_sampler.py <repo> [--pid N]
"""

from __future__ import annotations

import collections
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
BASE = "http://127.0.0.1:8765"


def post(path, body, timeout=30.0):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)}


def engine_pid() -> int:
    if "--pid" in sys.argv:
        return int(sys.argv[sys.argv.index("--pid") + 1])
    with urllib.request.urlopen(BASE + "/health", timeout=10) as r:
        return int(json.loads(r.read().decode())["pid"])


def keeper_stack(pid: int) -> list[str]:
    out = subprocess.run(["uvx", "--from", "py-spy==0.4.1", "py-spy", "dump", "--pid", str(pid)],
                         capture_output=True, text=True, timeout=60).stdout
    block: list[str] = []
    grab = False
    for line in out.splitlines():
        if line.startswith("Thread "):
            grab = "ctx-keeper" in line
            if grab:
                block = [line]
            continue
        if grab and line.strip():
            block.append(line.strip())
    return block


def main() -> int:
    pid = engine_pid()
    tok = f"zzstall{int(time.time())}"
    rel = f"packages/pipeline/zz_stall_{int(time.time())}.py"
    (REPO / rel).write_text(f'def {tok}_handler():\n    """{tok}"""\n    return 1\n', encoding="utf-8")
    t0 = time.perf_counter()
    samples: list[tuple[float, list[str]]] = []
    found_ms = None
    try:
        while time.perf_counter() - t0 < 40:
            st = keeper_stack(pid)
            samples.append((time.perf_counter() - t0, st))
            hits = post("/v1/search", {"query": f"{tok}_handler", "top_k": 5, "path": str(REPO)}).get("hits") or []
            if any(str(h.get("file") or "").replace("\\", "/") == rel for h in hits):
                found_ms = round((time.perf_counter() - t0) * 1000)
                break
            post("/v1/client/touch", {"client_id": "mcp:stall-sampler", "kind": "mcp", "pid": os.getpid()}, 5)
    finally:
        (REPO / rel).unlink(missing_ok=True)
    print(f"searchable after {found_ms} ms; {len(samples)} keeper samples")
    tally: collections.Counter[str] = collections.Counter()
    for at, st in samples:
        frames = [f for f in st[1:] if re.search(r"\(.*\.py:\d+\)", f)]
        top = " <- ".join(frames[:4]) if frames else "(idle / not found)"
        print(f"  +{at:5.1f}s {top[:300]}")
        for f in frames[:6]:
            tally[f] += 1
    print("\nmost frequent keeper frames:")
    for f, n in tally.most_common(12):
        print(f"  {n:3d}  {f[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
