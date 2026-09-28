"""PERF-1: decompose the pack-after-edit delay into its phases.

Times, from the moment a new file is written:
  t_map      — map first returns the new file as a suggested seed
  t_rebake_started — keeper logs the ast revalidate starting
  t_rebake_done    — keeper logs it done (+ the reported ms)
  t_pack     — pack first resolves the seed
Reads the keeper log to attribute the wait vs the rebake itself.

    python scripts/perf_pack_after_edit.py
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
LOG = Path(os.environ.get("CTX_HOME") or Path.home() / ".scubiee") / "engine.log"


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


class Tail:
    def __init__(self, path: Path):
        self.path = path
        self.pos = path.stat().st_size if path.is_file() else 0

    def new(self) -> list[str]:
        if not self.path.is_file():
            return []
        with self.path.open("rb") as f:
            f.seek(self.pos)
            data = f.read()
            self.pos = f.tell()
        return data.decode("utf-8", "replace").splitlines()


def main() -> int:
    stamp = int(time.time())
    sym = f"zz_perf_probe_{stamp}"
    rel = f"packages/pipeline/zz_perf_{stamp}.py"
    fpath = ROOT / rel
    q = f"{sym} perf probe ast revalidate pack seed resolve map corpus fingerprint"
    tail = Tail(LOG)
    events: dict[str, float] = {}
    rebake_ms = None
    fpath.write_text(f'"""perf {stamp}."""\n\n\ndef {sym}(x):\n    """probe {stamp}"""\n    return x\n',
                     encoding="utf-8")
    t0 = time.time()
    try:
        with _client() as c:
            c.call_text("gate", project_id=PID)
            for _ in range(30):
                s = call(c, "status", project_id=PID, detail="full")
                if s.get("embedder_loaded") or (s.get("warm_wait") or {}).get("done"):
                    break
                time.sleep(3)
            # phase 1: map finds the seed
            mine = None
            while time.time() - t0 < 90 and mine is None:
                m = call(c, "map", query=q, project_id=PID, path=REPO)
                mine = next((s for s in (m.get("suggested_seeds") or [])
                             if s.get("file", "").endswith(f"zz_perf_{stamp}.py")), None)
                for ln in tail.new():
                    if "ast bundle revalidat" in ln and "revalidate_started" not in events:
                        events["revalidate_started"] = time.time() - t0
                if mine is None:
                    time.sleep(2)
            events["map_seed"] = time.time() - t0
            loc = (mine or {}).get("loc") or ""
            line = int(re.search(r":(\d+)", loc).group(1)) if re.search(r":(\d+)", loc) else 0
            # phase 2: stop mapping, poll pack; watch the log for the rebake
            while time.time() - t0 < 120:
                for ln in tail.new():
                    if "ast bundle revalidated" in ln:
                        events.setdefault("rebake_logged", time.time() - t0)
                        mm = re.search(r"ms=([\d.]+)", ln)
                        if mm:
                            rebake_ms = float(mm.group(1))
                p = call(c, "pack_context", query=q, project_id=PID, path=REPO, mode="lean",
                         seed_file=mine["file"], seed_symbol=mine.get("symbol") or "", seed_line=line)
                if p.get("ok"):
                    events["pack_ok"] = time.time() - t0
                    break
                time.sleep(6)
        print(json.dumps({
            "symbol": sym,
            "phases_s": {k: round(v, 1) for k, v in sorted(events.items(), key=lambda kv: kv[1])},
            "rebake_reported_ms": rebake_ms,
            "total_pack_s": round(events.get("pack_ok", -1), 1),
        }, indent=2), flush=True)
        return 0 if "pack_ok" in events else 1
    finally:
        fpath.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
