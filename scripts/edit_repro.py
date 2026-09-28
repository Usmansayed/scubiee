"""Second save to the same file a few seconds after the first was indexed.

Prints generation and the search hit for the new function every second for 20s.
Before the graph_catchup fix the generation never moved: the edit was ignored
until the queued catch-up ran (30-50s).

Usage: python scripts/edit_repro.py <repo>
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
BASE = "http://127.0.0.1:8765"
stamp = str(int(time.time()))
rel = f"packages/pipeline/zz_editrepro_{stamp}.py"
t1, t2 = f"zzalpha{stamp}", f"zzbeta{stamp}"


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def fn(t):
    return f'def {t}_handler(payload):\n    """Unique probe symbol {t}."""\n    return {{"token": "{t}", "payload": payload}}\n'


def show(q):
    for i, h in enumerate(post("/v1/search", {"query": q, "top_k": 10, "path": str(REPO)}).get("hits") or []):
        f = str(h.get("file") or "").replace("\\", "/")
        if f == rel:
            slim = {k: (str(v)[:160] if isinstance(v, str) else v) for k, v in h.items() if k not in {"vector"}}
            print(f"  rank {i}: {json.dumps(slim)[:700]}")
            return True
    print("  file not in top10")
    return False


def gen():
    with urllib.request.urlopen(BASE + "/health", timeout=20) as r:
        h = json.loads(r.read().decode())
    return h.get("generation"), h.get("chunks")


p = REPO / rel
try:
    p.write_text('"""Edit repro."""\n\n\n' + fn(t1), encoding="utf-8")
    print("wrote v1", gen())
    for _ in range(60):
        time.sleep(1)
        if show(f"{t1}_handler unique probe symbol"):
            break
    print("indexed v1", gen())
    time.sleep(3)
    p.write_text('"""Edit repro."""\n\n\n' + fn(t1) + "\n\n" + fn(t2), encoding="utf-8")
    print("wrote v2", gen())
    for s in range(20):
        time.sleep(1)
        print(f"t+{s + 1}s gen={gen()}")
        show(f"{t2}_handler unique probe symbol")
finally:
    p.unlink(missing_ok=True)
