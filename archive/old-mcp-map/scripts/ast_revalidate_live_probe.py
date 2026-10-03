"""BUG-A live proof: create a file, then map's suggested seed must pack —
without any manual rebake. Verifies the keeper's background revalidate closed
the map/pack corpus split.

    python scripts/ast_revalidate_live_probe.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from mcp_stdio_client import McpStdioClient  # noqa: E402

PID = "ce_3536ac8e8e83bb8e4d888db37847729c"
REPO = str(ROOT).replace("\\", "/")


def _client():
    cfg = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    e = cfg["mcpServers"]["scubiee"]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env.update(e.get("env") or {})
    env.pop("PYTHONPATH", None)
    c = McpStdioClient(e["command"], e.get("args", []))
    c.env = env
    return c


def call(c, tool, **a):
    try:
        return json.loads(c.call_text(tool, **a))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)}


def main() -> int:
    stamp = int(time.time())
    sym = f"zz_revalidate_probe_{stamp}"
    rel = f"packages/pipeline/zz_revalidate_{stamp}.py"
    fpath = ROOT / rel
    q = (f"{sym} background revalidate stale while revalidate ast bundle refresh "
         "pack seed resolve map corpus")
    fpath.write_text(
        f'"""Live BUG-A probe {stamp}."""\n\n\n'
        f"def {sym}(payload):\n"
        f'    """Unique symbol for the revalidate probe {stamp}."""\n'
        f"    return {{'ok': True, 'payload': payload}}\n",
        encoding="utf-8",
    )
    try:
        with _client() as c:
            c.call_text("gate", project_id=PID)
            for _ in range(30):
                s = call(c, "status", project_id=PID, detail="full")
                if s.get("embedder_loaded") or (s.get("warm_wait") or {}).get("done"):
                    break
                time.sleep(4)
            # Wait until map finds the new symbol (dense index catch-up) AND pack
            # resolves the seed (AST bundle revalidate). No manual rebake here.
            t0 = time.time()
            # 1) map until the new symbol shows up (dense index catch-up).
            mine = None
            while time.time() - t0 < 90 and mine is None:
                m = call(c, "map", query=q, project_id=PID, path=REPO)
                seeds = m.get("suggested_seeds") or []
                mine = next((s for s in seeds if s.get("file", "").endswith(f"zz_revalidate_{stamp}.py")), None)
                if mine is None:
                    time.sleep(3)
            map_ok_at = round(time.time() - t0, 1) if mine else None
            # 2) stop mapping (let the locate streak go quiet) and poll pack only,
            #    so the keeper's background revalidate can run. No manual rebake.
            loc = (mine or {}).get("loc") or ""
            ln = int(re.search(r":(\d+)", loc).group(1)) if re.search(r":(\d+)", loc) else 0
            pack_ok_at = None
            last = {}
            deadline = time.time() + 150
            while mine and time.time() < deadline:
                p = call(c, "pack_context", query=q, project_id=PID, path=REPO, mode="lean",
                         seed_file=mine["file"], seed_symbol=mine.get("symbol") or "", seed_line=ln)
                last = {"map_seed": f"{mine['file']}::{mine.get('symbol')}",
                        "pack_ok": p.get("ok"), "pack_err": p.get("error"),
                        "hot": len(p.get("heatmap") or p.get("hot") or [])}
                if p.get("ok"):
                    pack_ok_at = round(time.time() - t0, 1)
                    break
                time.sleep(6)
            print(json.dumps({
                "symbol": sym,
                "map_found_seed_after_s": map_ok_at,
                "pack_resolved_after_s": pack_ok_at,
                "last": last,
                "PASS": bool(pack_ok_at is not None),
            }, indent=2), flush=True)
            return 0 if pack_ok_at is not None else 1
    finally:
        fpath.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
