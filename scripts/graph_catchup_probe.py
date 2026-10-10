"""Issue 6: a save that lands while another file's graph catch-up runs.

Per round: save file A and wait until it is searchable; wait for the keeper's
``[keeper] graph catch-up start paths=<A>`` line in engine.log (it comes after
CTX_GRAPH_CATCHUP_DELAY_S + the quiet window); immediately save file B and time
how long until B is searchable. Pass: B <= 5s. Reports the catch-up duration
(``graph catch-up done ms=``) and its ``[sync] no chunk delta`` stage line.

Plain disk writes, like an editor. Usage (engine on :8765, PYTHONPATH unset):
    python scripts/graph_catchup_probe.py <repo> [rounds]
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
BASE = "http://127.0.0.1:8765"
LOG = Path(os.environ.get("CTX_HOME") or Path.home() / ".scubiee") / "engine.log"
PKG = REPO / "packages" / "pipeline"


def post(path, body, timeout=60.0):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)}


def health():
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return {}


def touch():
    post("/v1/client/touch", {"client_id": "mcp:graph-catchup-probe", "kind": "mcp", "pid": os.getpid()}, 5.0)


def searchable(token, rel):
    for h in post("/v1/search", {"query": f"{token}_handler graph catchup probe", "top_k": 10, "path": str(REPO)}).get("hits") or []:
        if str(h.get("file") or "").replace("\\", "/") == rel and token in json.dumps(h):
            return True
    return False


def wait_searchable(token, rel, deadline_s=60.0):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < deadline_s:
        if searchable(token, rel):
            return round((time.perf_counter() - t0) * 1000)
        touch()
        time.sleep(0.2)
    return None


def src(token):
    return (
        '"""Graph catch-up probe."""\n\n\n'
        f"def {token}_handler(payload):\n"
        f'    """Graph catchup probe symbol {token}."""\n'
        f'    return {{"token": "{token}", "payload": payload}}\n'
    )


class LogTail:
    def __init__(self, path: Path):
        self.path = path
        self.pos = path.stat().st_size if path.is_file() else 0

    def lines(self):
        if not self.path.is_file():
            return []
        with self.path.open("rb") as fh:
            fh.seek(self.pos)
            data = fh.read()
            self.pos = fh.tell()
        return data.decode("utf-8", "replace").splitlines()


def main():
    rows = []
    for leftover in list(PKG.glob("zz_gca_*.py")) + list(PKG.glob("zz_gcb_*.py")):
        leftover.unlink(missing_ok=True)
    pid0 = health().get("pid")
    try:
        for rnd in range(ROUNDS):
            stamp = f"{int(time.time())}{rnd}"
            ta, tb = f"zzgca{stamp}", f"zzgcb{stamp}"
            rel_a, rel_b = f"packages/pipeline/zz_gca_{stamp}.py", f"packages/pipeline/zz_gcb_{stamp}.py"
            tail = LogTail(LOG)
            (REPO / rel_a).write_text(src(ta), encoding="utf-8")
            a_ms = wait_searchable(ta, rel_a)
            row = {"round": rnd, "a_searchable_ms": a_ms}
            # Wait for A's catch-up to start.
            started = None
            t_wait = time.perf_counter()
            while time.perf_counter() - t_wait < 150:
                touch()
                for line in tail.lines():
                    if "graph catch-up start" in line and f"zz_gca_{stamp}" in line:
                        started = line
                        break
                if started:
                    break
                time.sleep(0.2)
            row["catchup_started_after_s"] = round(time.perf_counter() - t_wait, 1) if started else None
            if not started:
                row["error"] = "catch-up for A never started within 150s"
                rows.append(row)
                print(json.dumps(row), flush=True)
                continue
            (REPO / rel_b).write_text(src(tb), encoding="utf-8")
            b_ms = wait_searchable(tb, rel_b)
            row["b_searchable_ms"] = b_ms
            # Collect the catch-up's own timing.
            done = nd = None
            t_done = time.perf_counter()
            while time.perf_counter() - t_done < 90 and not done:
                for line in tail.lines():
                    if "graph catch-up done" in line and f"zz_gca_{stamp}" in line:
                        done = line
                    if "no chunk delta" in line and f"zz_gca_{stamp}" in line:
                        nd = line
                    if "hot sync" in line and f"zz_gcb_{stamp}" in line:
                        row["b_hot_sync"] = line.split("[keeper] ", 1)[-1][:400]
                if not done:
                    touch()
                    time.sleep(0.5)
            if done:
                row["catchup_ms"] = int(done.split("ms=")[1].split()[0])
            if nd:
                row["catchup_stages"] = nd.split("reconciled=", 1)[-1]
            row["same_pid"] = health().get("pid") == pid0
            row["ok"] = bool(b_ms is not None and b_ms <= 5000 and row["same_pid"])
            rows.append(row)
            print(json.dumps(row), flush=True)
            for rel in (rel_a, rel_b):
                (REPO / rel).unlink(missing_ok=True)
            time.sleep(3)
    finally:
        for leftover in list(PKG.glob("zz_gca_*.py")) + list(PKG.glob("zz_gcb_*.py")):
            leftover.unlink(missing_ok=True)
    ok = sum(1 for r in rows if r.get("ok"))
    print(f"\nSUMMARY {ok}/{len(rows)} B searchable within 5s while A's graph catch-up ran")
    for r in rows:
        print(f"  round {r['round']}: B {r.get('b_searchable_ms')} ms  catch-up {r.get('catchup_ms')} ms  ok={r.get('ok')}")
    return 0 if ok == len(rows) and rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
