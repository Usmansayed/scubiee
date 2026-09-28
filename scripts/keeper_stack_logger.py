"""Log the engine's ``ctx-keeper`` thread stack about once a second (JSONL).

Run next to a probe, then line the timestamps up with slow ``hot sync`` lines.

    python scripts/keeper_stack_logger.py <out.jsonl> [seconds]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request


def main() -> int:
    out_path = sys.argv[1]
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
    end = time.time() + seconds
    with open(out_path, "a", encoding="utf-8") as out:
        while time.time() < end:
            try:
                with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=5) as r:
                    pid = int(json.loads(r.read().decode())["pid"])
            except Exception:  # noqa: BLE001
                time.sleep(1)
                continue
            t = time.strftime("%H:%M:%S")
            dump = subprocess.run(["uvx", "--from", "py-spy==0.4.1", "py-spy", "dump", "--pid", str(pid)],
                                  capture_output=True, text=True, timeout=60).stdout
            frames: list[str] = []
            grab = False
            for line in dump.splitlines():
                if line.startswith("Thread "):
                    grab = "ctx-keeper" in line
                    continue
                if grab and re.search(r"\(.*\.py:\d+\)", line):
                    frames.append(line.strip())
            out.write(json.dumps({"t": t, "pid": pid, "frames": frames[:12]}) + "\n")
            out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
