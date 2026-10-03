"""Final check — drive the INSTALLED scubiee-mcp worker (0.3.139) over stdio against
the live installed daemon. Confirms spawn/first-call/steady on the real shipped surface."""
from __future__ import annotations
import json, subprocess, sys, time
from pathlib import Path

MCP = r"C:\Users\usman\AppData\Roaming\uv\tools\scubiee\Scripts\scubiee-mcp.exe"
REPO = r"C:\Users\usman\Downloads\context-engine"


class W:
    def __init__(self):
        self.p = subprocess.Popen([MCP], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self._id = 0
    def rpc(self, method, params=None):
        self._id += 1
        self.p.stdin.write(json.dumps({"jsonrpc":"2.0","id":self._id,"method":method,"params":params or {}})+"\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())
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
    t_init = (time.perf_counter()-t0)*1000
    time.sleep(2.5)  # realistic gap: let the background warm thread finish
    out = {}
    for label, args in [("find", {"config":"find","query":"freshness staleness decision"}),
                        ("focus", {"config":"focus","names":["choose_strategy"]}),
                        ("related", {"config":"related","anchor":"packages/pipeline/freshness.py::choose_strategy","query":"freshness"}),
                        ("graph", {"config":"graph","query":"map config dispatch handler"})]:
        t1=time.perf_counter(); txt=w.call("map", args); first=(time.perf_counter()-t1)*1000
        t2=time.perf_counter(); w.call("map", args); steady=(time.perf_counter()-t2)*1000
        out[label]={"first_ms":round(first,1),"steady_ms":round(steady,1),"chars":len(txt)}
        print(f"  {label:8s} first={first:7.1f}ms steady={steady:7.1f}ms chars={len(txt)}")
    w.close()
    print(f"\n  spawn+init={t_init:.1f}ms")
    out["spawn_init_ms"]=round(t_init,1)
    Path(REPO,"dist","_perf_installed.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
    print("WROTE dist/_perf_installed.json")


if __name__ == "__main__":
    main()
