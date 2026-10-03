"""Find the TRUE source of focus's ~550ms first-call-after-idle cost. In one process:
warm fully, idle 90s (no keepalive), then stage-profile a single bare-name focus."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v
import pipeline.map_v3_helpers as mv  # noqa: E402
from pipeline import map_v3_server as srv  # noqa: E402

STATS = {}
def wrap(mod, name):
    orig = getattr(mod, name); STATS[name] = {"n":0,"ms":0.0}
    def inner(*a, **k):
        t0=time.perf_counter()
        try: return orig(*a,**k)
        finally:
            STATS[name]["n"]+=1; STATS[name]["ms"]+=(time.perf_counter()-t0)*1000
    setattr(mod, name, inner)

for fn in ("_grep","_resolve_symbol_name","_resolve_file","_lines","_outline","_http","_text","_text_cached_fast"):
    if hasattr(mv, fn): wrap(mv, fn)
for fn in ("_callers_of","_resolve_one","_pack_bodies"):
    if hasattr(srv, fn): wrap(srv, fn)

def reset():
    for v in STATS.values(): v["n"]=0; v["ms"]=0.0

def main():
    mv._repo_files(); mv._warm()
    srv.tool_map({"config":"focus","names":["choose_strategy"]})  # warm once
    print("warmed; idling 90s ...", flush=True)
    time.sleep(90)
    reset()
    t0=time.perf_counter()
    out=srv.tool_map({"config":"focus","names":["choose_strategy"]})
    total=(time.perf_counter()-t0)*1000
    print(f"\nfocus after 90s idle: {total:.1f}ms  out={len(out)}c")
    for n,v in sorted(STATS.items(), key=lambda x:-x[1]["ms"]):
        if v["n"]: print(f"  {n:20s} n={v['n']:3d} {v['ms']:8.1f}ms")
    Path(REPO,"dist","_focus_idle_stages.json").write_text(json.dumps({n:v for n,v in STATS.items() if v['n']},indent=2),encoding="utf-8")
    print("WROTE dist/_focus_idle_stages.json")

if __name__ == "__main__":
    main()
