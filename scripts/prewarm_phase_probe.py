"""Issue 2 follow-up: does warm_phase stay "prewarm" after the embedder loaded?

The watchdog force-restarts an engine whose warm_phase.json says "prewarm" for
longer than its grace window. Seen live: the phase stayed "prewarm" for 3+ min
while /health said embedder_loaded=True, and the watchdog killed a healthy
engine mid-probe.

Per round: restart the engine, touch as an MCP client (kicks the prewarm), write
a new file straight away so a save embeds while the prewarm runs, then poll
/health and warm_phase.json for up to 120s. Reports how long the phase stayed
"prewarm" after embedder_loaded became True. Pass: <= 5s every round.
Optionally py-spy dumps the engine when it reproduces (--spy).

    python scripts/prewarm_phase_probe.py <repo> [rounds] [--spy] [--kill]

--kill: taskkill the engine and let the watchdog restart it (the path seen live).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 3
SPY = "--spy" in sys.argv
KILL = "--kill" in sys.argv
BASE = "http://127.0.0.1:8765"
HOME = Path(os.environ.get("CTX_HOME") or Path.home() / ".scubiee")
PHASE = HOME / "warm_phase.json"
SCUBIEE = Path.home() / ".local" / "bin" / "scubiee.exe"


def get(path, timeout=5.0):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return None


def post(path, body, timeout=10.0):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)}


def phase():
    try:
        return json.loads(PHASE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def touch():
    post("/v1/client/touch", {"client_id": "mcp:prewarm-phase-probe", "kind": "mcp", "pid": os.getpid()}, 5.0)


def restart():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    old = (get("/health") or {}).get("pid")
    if KILL and old:
        # Watchdog path: the engine dies, the watchdog brings it back.
        subprocess.run(["taskkill", "/F", "/PID", str(old)], capture_output=True, timeout=30)
    else:
        subprocess.run([str(SCUBIEE), "engine", "stop", str(REPO)], env=env, capture_output=True, timeout=120)
        subprocess.run([str(SCUBIEE), "engine", "ensure", str(REPO)], env=env, capture_output=True, timeout=180)
    t0 = time.time()
    while time.time() - t0 < 120:
        h = get("/health")
        if h and h.get("pid") and h.get("pid") != old:
            return h
        touch()
        time.sleep(0.3)
    return None


def main():
    pkg = REPO / "packages" / "pipeline"
    rows = []
    for rnd in range(ROUNDS):
        h0 = restart()
        if not h0:
            rows.append({"round": rnd, "error": "engine did not come up"})
            continue
        touch()
        rel = pkg / f"zz_prewarmphase_{int(time.time())}{rnd}.py"
        rel.write_text(f"def zzprewarm{rnd}():\n    return {rnd}\n", encoding="utf-8")
        t0 = time.time()
        loaded_at = dense_at = None
        last_phase = None
        stuck_since = None
        while time.time() - t0 < 120:
            touch()
            h = get("/health") or {}
            ph = phase()
            last_phase = ph.get("phase")
            now = time.time() - t0
            if h.get("embedder_loaded") and loaded_at is None:
                loaded_at = now
            if loaded_at is not None and last_phase != "prewarm" and dense_at is None:
                dense_at = now
                break
            if loaded_at is not None and last_phase == "prewarm" and stuck_since is None:
                stuck_since = now
            time.sleep(0.5)
        row = {
            "round": rnd,
            "pid": h0.get("pid"),
            "embedder_loaded_at_s": round(loaded_at, 1) if loaded_at is not None else None,
            "phase_left_prewarm_at_s": round(dense_at, 1) if dense_at is not None else None,
            "final_phase": last_phase,
            "phase_pid": phase().get("pid"),
            "same_pid": (get("/health") or {}).get("pid") == h0.get("pid"),
        }
        lag = (dense_at - loaded_at) if (dense_at is not None and loaded_at is not None) else None
        row["prewarm_after_loaded_s"] = round(lag, 1) if lag is not None else None
        row["ok"] = lag is not None and lag <= 5.0
        if not row["ok"] and SPY and h0.get("pid"):
            spy = subprocess.run(
                ["uvx", "--from", "py-spy==0.4.1", "py-spy", "dump", "--pid", str(h0["pid"])],
                capture_output=True, text=True, timeout=120,
            )
            dump = HOME / f"prewarm_phase_spy_{rnd}.txt"
            dump.write_text(spy.stdout + spy.stderr, encoding="utf-8")
            row["spy"] = str(dump)
        rows.append(row)
        print(json.dumps(row), flush=True)
        rel.unlink(missing_ok=True)
        time.sleep(3)
    ok = sum(1 for r in rows if r.get("ok"))
    print(f"\nSUMMARY {ok}/{len(rows)} phase left prewarm within 5s of embedder_loaded")
    return 0 if rows and ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
