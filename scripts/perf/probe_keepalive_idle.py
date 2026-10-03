"""Task 3 — prove the worker keepalive keeps map ms-fast across an idle gap.
Drives the SOURCE map_v3_server worker (python -m, PYTHONPATH=packages) so it exercises
the NEW keepalive code before we build. Two arms, each: spawn worker, idle IDLE_S, then
fire each config ONCE (no warm retries) and record first-call latency.
  arm KEEPALIVE : CTX_MAP_WARM_INTERVAL_S=20  (pulses during idle)
  arm CONTROL   : CTX_MAP_WARM_INTERVAL_S=0   (disabled - the old behavior)
Engine must be warm+dense on 8765 first."""
from __future__ import annotations
import json, os, subprocess, sys, time
from pathlib import Path

REPO = r"C:\Users\usman\Downloads\context-engine"
PY = r"C:\Users\usman\Miniconda3\python.exe"
IDLE_S = 90


def base_env(interval):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(REPO) / "packages")
    env["PYTHONIOENCODING"] = "utf-8"
    env["CTX_ENGINE_URL"] = "http://127.0.0.1:8765"
    env["CTX_REPO"] = REPO
    env["CTX_PROJECT_ID"] = "ce_3536ac8e8e83bb8e4d888db37847729c"
    env["CTX_MAP_WARM_INTERVAL_S"] = str(interval)
    for k in ("MINI_ENGINE_URL", "MINI_REPO", "MINI_PROJECT_ID"):
        env.pop(k, None)
    return env


class W:
    def __init__(self, interval):
        self.p = subprocess.Popen([PY, "-u", "-m", "pipeline.map_v3_server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", env=base_env(interval), cwd=REPO)
        self._id = 0
    def rpc(self, m, p=None):
        self._id += 1
        self.p.stdin.write(json.dumps({"jsonrpc":"2.0","id":self._id,"method":m,"params":p or {}})+"\n")
        self.p.stdin.flush(); return json.loads(self.p.stdout.readline())
    def notify(self, m):
        self.p.stdin.write(json.dumps({"jsonrpc":"2.0","method":m})+"\n"); self.p.stdin.flush()
    def call(self, name, args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})
        return r.get("result",{}).get("content",[{}])[0].get("text","")
    def close(self):
        try: self.p.stdin.close(); self.p.terminate()
        except Exception: pass


CASES = [
    ("gate", "gate", {}),
    ("status", "status", {}),
    ("find", "map", {"config":"find","query":"where freshness report decides sync strategy"}),
    ("focus", "map", {"config":"focus","names":["choose_strategy"]}),
    ("related", "map", {"config":"related","anchor":"packages/pipeline/freshness.py::choose_strategy","query":"freshness staleness"}),
    ("graph", "map", {"config":"graph","query":"map config dispatch handler"}),
]


def arm(label, interval):
    print(f"\n== ARM {label} (CTX_MAP_WARM_INTERVAL_S={interval}) ==", flush=True)
    w = W(interval); w.rpc("initialize"); w.notify("notifications/initialized")
    time.sleep(2.0)  # let the spawn warm thread finish, same for both arms
    print(f"  idling {IDLE_S}s ...", flush=True)
    time.sleep(IDLE_S)
    out = {}
    for lbl, tool, args in CASES:
        t=time.perf_counter(); txt=w.call(tool,args); first=(time.perf_counter()-t)*1000
        out[lbl]={"first_ms":round(first,1),"chars":len(txt)}
        print(f"  {lbl:8s} first_after_idle = {first:9.1f} ms  out={len(txt)}c", flush=True)
    w.close()
    return out


def main():
    res = {"idle_s": IDLE_S}
    res["control"] = arm("CONTROL", 0)
    res["keepalive"] = arm("KEEPALIVE", 20)
    print("\n== SUMMARY first-call-after-idle (ms) ==")
    print(f"  {'config':8s} {'control':>10s} {'keepalive':>10s}")
    for lbl,_,_ in CASES:
        print(f"  {lbl:8s} {res['control'][lbl]['first_ms']:10.1f} {res['keepalive'][lbl]['first_ms']:10.1f}")
    Path(REPO,"dist","_keepalive_idle.json").write_text(json.dumps(res,indent=2),encoding="utf-8")
    print("WROTE dist/_keepalive_idle.json")


if __name__ == "__main__":
    main()
