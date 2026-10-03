"""Stage-1 end-to-end verify: spawn the PRODUCTION Map V3 server module
(pipeline.map_v3_server) over stdio with the production CTX_* env (NO MINI_*),
against the live engine, and drive each config through the real product path.
"""
import json, os, subprocess, sys
from pathlib import Path

REPO = r"C:\Users\usman\Downloads\context-engine"
PID = "ce_3536ac8e8e83bb8e4d888db37847729c"
PY = r"C:\Users\usman\Miniconda3\python.exe"

env = dict(os.environ)
env["PYTHONPATH"] = str(Path(REPO) / "packages")
env["PYTHONIOENCODING"] = "utf-8"
# production env names ONLY (prove the CTX_* fallback works; no MINI_*)
for k in ("MINI_ENGINE_URL", "MINI_REPO", "MINI_PROJECT_ID"):
    env.pop(k, None)
env["CTX_ENGINE_URL"] = "http://127.0.0.1:8765"
env["CTX_REPO"] = REPO
env["CTX_PROJECT_ID"] = PID

proc = subprocess.Popen([PY, "-u", "-m", "pipeline.map_v3_server"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, encoding="utf-8", env=env, cwd=REPO)
_id = [0]
def rpc(method, params=None):
    _id[0] += 1
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": _id[0], "method": method,
                                 "params": params or {}}) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())
def call(name, args):
    r = rpc("tools/call", {"name": name, "arguments": args})
    return r.get("result", {}).get("content", [{}])[0].get("text", "")

results = []
def check(label, cond, detail=""):
    results.append((label, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))

try:
    init = rpc("initialize")
    name = init.get("result", {}).get("serverInfo", {}).get("name")
    check("initialize serverInfo = scubiee-map-v3", name == "scubiee-map-v3", str(name))
    check("has instructions", bool(init.get("result", {}).get("instructions")))
    # notification: no response expected — send without reading
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    proc.stdin.flush()
    tl = rpc("tools/list")
    tools = {t["name"] for t in tl.get("result", {}).get("tools", [])}
    check("tools = map/gate/status", tools == {"map", "gate", "status"}, str(sorted(tools)))

    g = call("gate", {})
    check("gate returns managed signal", g.strip().startswith("1") or PID in g, g.strip()[:40])
    s = call("status", {})
    check("status shows engine health", ("warm" in s.lower() or "chunks" in s.lower() or "ok" in s.lower()), s[:60])

    find = call("map", {"config": "find", "query": "where freshness report decides sync strategy choose_strategy"})
    check("find returns ranked locations + code", ("freshness" in find or "find:" in find or ".py" in find) and len(find) > 200, f"{len(find)}c")
    focus = call("map", {"config": "focus", "names": ["choose_strategy"]})
    check("focus returns body + wiring", ("choose_strategy" in focus and ("wiring" in focus or "lines" in focus)), f"{len(focus)}c")
    related = call("map", {"config": "related", "anchor": "packages/pipeline/freshness.py::choose_strategy", "query": "sync strategy"})
    check("related returns related bodies", len(related) > 150 and "related" in related.lower(), f"{len(related)}c")
    graph = call("map", {"config": "graph", "query": "freshness sync strategy"})
    try:
        gj = json.loads(graph)
        check("graph returns JSON nodes+edges (no bodies)", "nodes" in gj and "edges" in gj, f"nodes={len(gj.get('nodes',[]))} edges={len(gj.get('edges',[]))}")
    except Exception:
        check("graph returns JSON nodes+edges (no bodies)", False, graph[:80])

    bad = call("map", {"config": "nonsense"})
    check("bad config -> graceful error", "error" in bad.lower() or "must be one of" in bad.lower(), bad[:60])
finally:
    try: proc.stdin.close(); proc.terminate()
    except Exception: pass

npass = sum(1 for _, ok in results if ok)
print(f"\nOVERALL: {npass}/{len(results)} checks passed")
sys.exit(0 if npass == len(results) else 1)
