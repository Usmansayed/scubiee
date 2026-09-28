"""Remaining feature coverage: rename propagation + workspace pin/clear +
error-path behavior. Runs inside one warm MCP session."""

from __future__ import annotations

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
BASE = "http://127.0.0.1:8765"


def http(method, path, body=None, timeout=30.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _client():
    cfg = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    e = cfg["mcpServers"]["scubiee"]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env.update(e.get("env") or {})
    env.pop("PYTHONPATH", None)
    argv = json.loads(env["CTX_MCP_BRIDGE_SPAWN_JSON"])
    c = McpStdioClient(argv[0], argv[1:])
    c.env = env
    return c


def poll(fn, timeout_s, interval=0.5):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            if fn():
                return time.time() - t0
        except Exception:  # noqa: BLE001
            pass
        time.sleep(interval)
    return None


def search_has(token, rel):
    hits = http("POST", "/v1/search", {"query": token, "top_k": 12, "path": REPO}).get("hits") or []
    return any(str(h.get("file") or "").replace("\\", "/") == rel for h in hits)


def main() -> int:
    stamp = int(time.time())
    lines = []
    created = []

    def line(s):
        print(s, flush=True)
        lines.append(s)

    with _client() as c:
        c.call_text("gate", project_id=PID)

        def mcp(tool, **a):
            try:
                return json.loads(c.call_text(tool, **a))
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": repr(exc)}

        # === RENAME: old symbol goes, new arrives ===
        old = f"zzfeat{stamp}old"
        rel = f"packages/pipeline/zz_feat_{stamp}.py"
        p = ROOT / rel
        p.write_text(f'def {old}_fn():\n    """{old}."""\n    return 1\n', encoding="utf-8")
        created.append(p)
        http("POST", "/v1/dirty", {"paths": [rel], "path": REPO})
        s1 = poll(lambda: search_has(f"{old}_fn", rel), timeout_s=20)
        line(f"rename: original searchable in {'%.1fs' % s1 if s1 else 'MISS'}")
        # rename the symbol
        new = f"zzfeat{stamp}new"
        p.write_text(f'def {new}_fn():\n    """{new}."""\n    return 1\n', encoding="utf-8")
        http("POST", "/v1/dirty", {"paths": [rel], "path": REPO})
        s2 = poll(lambda: search_has(f"{new}_fn", rel), timeout_s=20)
        line(f"rename: new symbol searchable in {'%.1fs' % s2 if s2 else 'MISS'}")
        s3 = poll(lambda: not search_has(f"{old}_fn", rel), timeout_s=20)
        line(f"rename: old symbol gone in {'%.1fs' % s3 if s3 else 'STILL PRESENT (stale)'}")

        # === WORKSPACE pin / show / clear ===
        # workspace pin uses path= (repo-relative file), and root binding via root=.
        pin = mcp("workspace", action="pin", project_id=PID, root=REPO,
                  path="packages/pipeline/graph_merge_worker.py")
        line(f"workspace pin: ok={pin.get('ok')} keys={list(pin)[:6]}")
        show = mcp("workspace", action="show", project_id=PID, path=REPO)
        pins = show.get("pins") or []
        line(f"workspace show after pin: pins={len(pins) if hasattr(pins,'__len__') else pins}")
        clr = mcp("workspace", action="clear", project_id=PID, path=REPO)
        line(f"workspace clear: ok={clr.get('ok')}")

        # === ERROR PATHS ===
        e1 = mcp("pack_context", query="", seed_file="", project_id=PID, path=REPO)
        line(f"pack empty seed -> ok={e1.get('ok')} error={str(e1.get('error'))[:50]}")
        e2 = mcp("expand", handle="does/not/exist.py:9-9", project_id=PID, path=REPO)
        line(f"expand bad handle -> ok={e2.get('ok')} error={str(e2.get('error'))[:50]}")
        e3 = mcp("map", query="x", project_id="ce_wrongwrongwrong", path=REPO)
        line(f"map wrong project_id -> ok={e3.get('ok')} keys={list(e3)[:5]}")

    for pp in created:
        pp.unlink(missing_ok=True)
    for stray in (ROOT / "packages" / "pipeline").glob("zz_feat_*.py"):
        stray.unlink(missing_ok=True)

    Path(os.environ["TEMP"], "features.txt").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
