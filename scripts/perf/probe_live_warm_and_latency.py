"""Live check on the INSTALLED 0.3.139: (A) cold engine warm-up time to soft-ready
and dense-ready, (B) per-map-config first-call + warm steady latency through the real
scubiee-mcp worker over stdio. Reflects exactly what Kiro sees."""
from __future__ import annotations
import json, subprocess, sys, time, urllib.request
from pathlib import Path

SCUBIEE = r"C:\Users\usman\AppData\Roaming\uv\tools\scubiee\Scripts\scubiee.exe"
MCP = r"C:\Users\usman\AppData\Roaming\uv\tools\scubiee\Scripts\scubiee-mcp.exe"
REPO = r"C:\Users\usman\Downloads\context-engine"
ENGINE = "http://127.0.0.1:8765"


def health(timeout=4):
    try:
        with urllib.request.urlopen(ENGINE + "/health", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def nudge():
    try:
        req = urllib.request.Request(ENGINE + "/v1/search",
            data=json.dumps({"query": "warm nudge", "top_k": 3, "path": REPO}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=90).read()
    except Exception:
        pass


def cold_warmup():
    print("== COLD WARM-UP ==")
    subprocess.run([SCUBIEE, "engine", "stop"], capture_output=True, text=True)
    # wait for port down
    for _ in range(30):
        if health(2) is None:
            break
        time.sleep(1)
    print("  engine stopped")
    t0 = time.perf_counter()
    subprocess.Popen([SCUBIEE, "engine", "run", REPO, "--host", "127.0.0.1", "--port", "8765"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    soft_t = dense_t = None
    first_ok = None
    while time.perf_counter() - t0 < 180:
        h = health(3)
        if h:
            if first_ok is None:
                first_ok = (time.perf_counter() - t0) * 1000
            if soft_t is None and (h.get("warm_ready") or h.get("soft_search_ready")):
                soft_t = (time.perf_counter() - t0) * 1000
            if not h.get("dense_ready"):
                nudge()
            else:
                dense_t = (time.perf_counter() - t0) * 1000
                break
        time.sleep(0.5)
    print(f"  /health first responds : {first_ok:8.0f} ms" if first_ok else "  never responded")
    print(f"  soft/warm ready        : {soft_t:8.0f} ms" if soft_t else "  soft not seen")
    print(f"  dense ready            : {dense_t:8.0f} ms" if dense_t else "  dense not seen")
    return {"first_health_ms": first_ok, "soft_ready_ms": soft_t, "dense_ready_ms": dense_t}


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


def latency():
    print("\n== MAP CONFIG LATENCY (through real scubiee-mcp worker) ==")
    t0 = time.perf_counter()
    w = W(); w.rpc("initialize"); w.notify("notifications/initialized")
    print(f"  worker spawn+init: {(time.perf_counter()-t0)*1000:.0f} ms")
    time.sleep(2.5)  # realistic gap: let the worker's bg warm thread finish
    cases = [
        ("gate", "gate", {}),
        ("status", "status", {}),
        ("find", "map", {"config":"find","query":"where freshness report decides sync strategy"}),
        ("focus", "map", {"config":"focus","names":["choose_strategy"]}),
        ("related", "map", {"config":"related","anchor":"packages/pipeline/freshness.py::choose_strategy","query":"freshness staleness"}),
        ("graph", "map", {"config":"graph","query":"map config dispatch handler"}),
    ]
    out = {}
    for label, tool, args in cases:
        t1=time.perf_counter(); txt=w.call(tool,args); first=(time.perf_counter()-t1)*1000
        warms=[]
        for _ in range(3):
            t2=time.perf_counter(); w.call(tool,args); warms.append((time.perf_counter()-t2)*1000)
        steady=min(warms)
        out[label]={"first_ms":round(first,1),"steady_ms":round(steady,1),"chars":len(txt)}
        print(f"  {label:8s} first={first:8.1f}ms  steady={steady:7.1f}ms  out={len(txt)}c")
    w.close()
    return out


def main():
    warm = cold_warmup()
    lat = latency()
    Path(REPO,"dist","_live_warm_latency.json").write_text(
        json.dumps({"warmup": warm, "latency": lat}, indent=2), encoding="utf-8")
    print("\nWROTE dist/_live_warm_latency.json")


if __name__ == "__main__":
    main()
