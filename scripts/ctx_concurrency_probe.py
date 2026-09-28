"""Concurrency + lifecycle: parallel MCP sessions, engine PID stability, idle standby."""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from mcp_stdio_client import McpStdioClient  # noqa: E402

PID = "ce_3536ac8e8e83bb8e4d888db37847729c"
REPO = str(ROOT).replace("\\", "/")


def _client(session: str):
    cfg = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    e = cfg["mcpServers"]["scubiee"]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env.update(e.get("env") or {})
    env.pop("PYTHONPATH", None)
    env["CTX_MCP_SESSION_ID"] = session
    c = McpStdioClient(e["command"], e.get("args", []))
    c.env = env
    return c


def engine_pid():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=10) as r:
            return json.loads(r.read().decode()).get("pid")
    except Exception:  # noqa: BLE001
        return None


def session_worker(n: int) -> dict:
    q = [
        "graph catch-up child process merge commit keeper rename graph.json",
        "fast_stat GetFileAttributesExW GIL convoy root_probe stat",
        "prewarm phase stale warm_autoload watchdog restart embedder loaded",
        "incremental_sync hot lane force_files chunk merkle embed vectors publish",
    ][n % 4]
    out = {"session": f"conc{n}", "calls": [], "pid_seen": set()}
    try:
        with _client(f"conc{n}") as c:
            c.call_text("gate", project_id=PID)
            for _ in range(20):
                s = json.loads(c.call_text("status", project_id=PID, detail="full"))
                out["pid_seen"].add(s.get("engine", {}).get("pid") if isinstance(s.get("engine"), dict) else s.get("pid"))
                if s.get("embedder_loaded") or (s.get("warm_wait") or {}).get("done"):
                    break
                time.sleep(3)
            for i in range(4):
                t0 = time.perf_counter()
                m = json.loads(c.call_text("map", query=q, project_id=PID, path=REPO))
                ms = round((time.perf_counter() - t0) * 1000, 1)
                out["calls"].append({"i": i, "ok": m.get("ok"), "ms": ms,
                                     "cards": len(m.get("cards") or []), "cache": m.get("cache")})
    except Exception as exc:  # noqa: BLE001
        out["error"] = repr(exc)
    out["pid_seen"] = sorted(p for p in out["pid_seen"] if p)
    return out


def main() -> int:
    print(f"engine pid before: {engine_pid()}", flush=True)
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 4
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=n) as ex:
        results = list(ex.map(session_worker, range(n)))
    wall = round(time.perf_counter() - t0, 1)
    pid_after = engine_pid()
    print(f"\n{n} parallel MCP sessions in {wall}s; engine pid after: {pid_after}\n", flush=True)
    all_pids = set()
    for r in results:
        errs = r.get("error")
        oks = [c["ok"] for c in r["calls"]]
        mss = [c["ms"] for c in r["calls"]]
        all_pids.update(r["pid_seen"])
        print(f"  {r['session']}: calls_ok={sum(1 for o in oks if o)}/{len(oks)} "
              f"ms={mss} pids={r['pid_seen']} err={errs}", flush=True)
    print(f"\ndistinct engine pids seen across sessions: {sorted(all_pids)}", flush=True)
    if len(all_pids) > 1:
        print("  FINDING: engine PID changed under concurrent load (restart mid-session)", flush=True)
    if any(r.get("error") for r in results):
        print("  FINDING: a parallel session raised an error", flush=True)
    if all(all(c["ok"] for c in r["calls"]) for r in results if r["calls"]):
        print("  all parallel map calls ok", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
