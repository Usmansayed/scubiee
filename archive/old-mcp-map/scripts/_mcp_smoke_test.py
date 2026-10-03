"""Smoke-test MCP stack: registry, disk tools, engine HTTP."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.capability import grep_scan  # noqa: E402
from pipeline.client import EngineClient  # noqa: E402
from pipeline.mcp_locate import _call_sites_for_ident, _is_repo_managed, _slim_spans  # noqa: E402
from pipeline.project_id import read_id_file, update_registry, load_registry  # noqa: E402
from pipeline.repo_lifecycle import activate_repo  # noqa: E402

PID = read_id_file(ROOT) or ""
update_registry(PID, ROOT)
entry = load_registry()["projects"][PID]


def main() -> int:
    client = EngineClient(workspace_path=str(ROOT))
    open_r = client.open_repo(str(ROOT), wait=True)
    grep_r = client.grep("invalidate_paths", glob="packages/pipeline/sync_loop.py")
    map_r = client.locate("session_store invalidate_paths sync_loop", top_k=5)

    sites = _slim_spans(_call_sites_for_ident(ROOT, "invalidate_paths", keep=2), keep=2, body_chars=400)
    glob_env = list(ROOT.glob(".env"))
    glob_ce = list((ROOT / ".scubiee").rglob("*")) if (ROOT / ".scubiee").is_dir() else []

    r = {
        "managed_local": _is_repo_managed(),
        "registry_managed": entry.get("managed"),
        "activate": activate_repo(ROOT).get("status"),
        "engine_version": client.get("/health").get("version"),
        "open_repo": open_r.get("status"),
        "grep_http": {"ok": grep_r.get("ok"), "count": len(grep_r.get("hits") or [])},
        "map_http": {"ok": map_r.get("ok"), "hits": len(map_r.get("hits") or map_r.get("results") or [])},
        "glob_env": len(glob_env),
        "glob_scubiee": len(glob_ce),
        "call_sites": {
            "count": len(sites),
            "first_code_len": len(sites[0].get("code") or "") if sites else 0,
        },
    }
    checks = [
        r["managed_local"],
        r["registry_managed"],
        r["open_repo"] == "activated",
        r["grep_http"]["ok"],
        r["map_http"]["ok"],
        r["glob_env"] >= 1,
        r["glob_scubiee"] >= 1,
        r["call_sites"]["count"] >= 1,
        r["call_sites"]["first_code_len"] > 0,
    ]
    r["_passed"] = sum(1 for c in checks if c)
    r["_total"] = len(checks)
    print(json.dumps(r, indent=2))
    return 0 if r["_passed"] == r["_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
