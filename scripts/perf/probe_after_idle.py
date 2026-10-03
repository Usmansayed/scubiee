"""Measure response time AFTER 5 min idle. Engine naps per CTX_ENGINE_IDLE_S.
We do NOT touch the engine during the idle window (no polling), then fire each map
config ONCE through the real scubiee-mcp worker and record the single first-call time
(the real 'came back after a break' latency). No warm retries."""
from __future__ import annotations
import json, subprocess, sys, time
from pathlib import Path

MCP = r"C:\Users\usman\AppData\Roaming\uv\tools\scubiee\Scripts\scubiee-mcp.exe"
REPO = r"C:\Users\usman\Downloads\context-engine"
IDLE_S = 300


class W:
    def __init__(self):
        self.p = subprocess.Popen([MCP], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self._id = 0
    def rpc(self, method, params=None):
        self._id += 1
        self.p.stdin.write(json.dumps({"jsonrpc":"2.0","id":self._id,"method":method,"params":params or {}})+"\n")
        self.p.stdin.flush(); return json.loads(self.p.stdout.readline())
    def notify(self, m):
        self.p.stdin.write(json.dumps({"jsonrpc":"2.0","method":m})+"\n"); self.p.stdin.flush()
    def call(self, name, args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})
        return r.get("result",{}).get("content",[{}])[0].get("text","")
    def close(self):
        try: self.p.stdin.close(); self.p.terminate()
        except Exception: pass


def main():
    start = time.strftime("%H:%M:%S")
    print(f"[{start}] idling {IDLE_S}s (no engine contact) ...", flush=True)
    time.sleep(IDLE_S)
    woke = time.strftime("%H:%M:%S")
    print(f"[{woke}] idle done -> spawning worker and firing each config once", flush=True)

    t0 = time.perf_counter()
    w = W(); w.rpc("initialize"); w.notify("notifications/initialized")
    spawn_ms = (time.perf_counter()-t0)*1000
    print(f"  worker spawn+init: {spawn_ms:.0f} ms", flush=True)

    # IMPORTANT: do not sleep/warm here — we want the first call to hit a napped engine.
    cases = [
        ("gate", "gate", {}),
        ("status", "status", {}),
        ("find", "map", {"config":"find","query":"where freshness report decides sync strategy"}),
        ("focus", "map", {"config":"focus","names":["choose_strategy"]}),
        ("related", "map", {"config":"related","anchor":"packages/pipeline/freshness.py::choose_strategy","query":"freshness staleness"}),
        ("graph", "map", {"config":"graph","query":"map config dispatch handler"}),
    ]
    out = {"idle_s": IDLE_S, "spawn_init_ms": round(spawn_ms,1), "first_calls": {}}
    for label, tool, args in cases:
        t1=time.perf_counter(); txt=w.call(tool,args); first=(time.perf_counter()-t1)*1000
        out["first_calls"][label] = {"first_ms": round(first,1), "chars": len(txt)}
        print(f"  {label:8s} first_after_idle = {first:9.1f} ms   out={len(txt)}c", flush=True)
    w.close()
    Path(REPO,"dist","_after_idle.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("WROTE dist/_after_idle.json", flush=True)


if __name__ == "__main__":
    main()
