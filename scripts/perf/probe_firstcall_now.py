"""First-call response time of each tool through the real scubiee-mcp worker, right
now (engine already warm). Fires each config ONCE, no warm retries."""
from __future__ import annotations
import json, subprocess, time
from pathlib import Path

MCP = r"C:\Users\usman\AppData\Roaming\uv\tools\scubiee\Scripts\scubiee-mcp.exe"
REPO = r"C:\Users\usman\Downloads\context-engine"


class W:
    def __init__(self):
        self.p = subprocess.Popen([MCP], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
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


def main():
    t0 = time.perf_counter()
    w = W(); w.rpc("initialize"); w.notify("notifications/initialized")
    spawn = (time.perf_counter()-t0)*1000
    print(f"worker spawn+init: {spawn:.0f} ms")
    # no wait: fire immediately to capture true immediate first-call latency
    cases = [
        ("gate", "gate", {}),
        ("status", "status", {}),
        ("find", "map", {"config":"find","query":"where freshness report decides sync strategy"}),
        ("focus", "map", {"config":"focus","names":["choose_strategy"]}),
        ("related", "map", {"config":"related","anchor":"packages/pipeline/freshness.py::choose_strategy","query":"freshness staleness"}),
        ("graph", "map", {"config":"graph","query":"map config dispatch handler"}),
    ]
    out = {"spawn_init_ms": round(spawn,1), "first_calls": {}}
    for label, tool, args in cases:
        t1=time.perf_counter(); txt=w.call(tool,args); first=(time.perf_counter()-t1)*1000
        out["first_calls"][label]={"first_ms":round(first,1),"chars":len(txt)}
        print(f"  {label:8s} first = {first:8.1f} ms   out={len(txt)}c")
    w.close()
    Path(REPO,"dist","_firstcall_now.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
    print("WROTE dist/_firstcall_now.json")


if __name__ == "__main__":
    main()
