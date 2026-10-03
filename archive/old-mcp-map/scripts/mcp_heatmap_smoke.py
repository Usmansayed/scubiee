"""Proper MCP client smoke for heatmap-only pack_context (0.3.25+)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP = Path(os.environ["USERPROFILE"]) / "AppData/Roaming/uv/tools/scubiee/Scripts/scubiee-mcp.exe"


async def _run() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from pipeline.mcp_hot_reload import nudge_mcp_hot_reload

    report = nudge_mcp_hot_reload("0.3.25")
    print("hot_reload_ok", report.get("ok"), flush=True)

    env = os.environ.copy()
    env.update(
        {
            "CTX_REPO": str(ROOT),
            "CTX_PROJECT_ID": "ce_d9cb766c3820091ed9ffbc64ef33063c",
            "CTX_ENGINE_URL": "http://127.0.0.1:8765",
            "CTX_TOKEN_MODE": "savings",
            "CTX_MCP_SURFACE": "phase",
            "CTX_MCP_EXPERIMENT": "ship",
            "CTX_TRUST_ID_FILE": "1",
            "PYTHONUTF8": "1",
        }
    )
    env.pop("CTX_MCP_PACK_BODIES", None)

    params = StdioServerParameters(command=str(MCP), args=[], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            pc = next((t for t in tools.tools if t.name == "pack_context"), None)
            desc = (pc.description if pc else "") or ""
            print("pack_desc", desc, flush=True)
            mode_desc = ""
            if pc and pc.inputSchema:
                mode_desc = (
                    ((pc.inputSchema.get("properties") or {}).get("mode") or {}).get(
                        "description"
                    )
                    or ""
                )
            print("mode_desc", mode_desc[:140], flush=True)

            result = await session.call_tool(
                "pack_context",
                {
                    "query": (
                        "connect cursor install mcp permissions allowlist "
                        "write tool surface"
                    ),
                    "seed_file": "packages/pipeline/rules_installer.py",
                    "seed_symbol": "write_project_tool_surface",
                    "mode": "lean",
                    "root": str(ROOT),
                    "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c",
                    "session_id": "mcp-sdk-smoke-0325",
                },
            )
            text = ""
            for block in result.content or []:
                t = getattr(block, "text", None)
                if t:
                    text += t
            print("text_len", len(text), flush=True)
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                start, end = text.find("{"), text.rfind("}")
                payload = (
                    json.loads(text[start : end + 1])
                    if start >= 0 and end > start
                    else {}
                )

            keys = sorted(payload.keys()) if isinstance(payload, dict) else []
            heat = payload.get("heatmap") if isinstance(payload, dict) else []
            checks = {
                "keys": keys,
                "n_heat": len(heat or []),
                "has_read": isinstance((payload or {}).get("read"), dict),
                "read_top": ((payload or {}).get("read") or {}).get("top"),
                "no_pack": "pack" not in keys,
                "no_chain": "chain" not in keys,
                "no_cold": "cold" not in keys,
                "no_body_def": "def write_project_tool_surface" not in text,
                "desc_ok": ("no bodies" in desc.lower())
                or ("heatmap locs" in desc.lower()),
                "mode_ok": ("heatmap" in mode_desc.lower())
                or ("no bodies" in mode_desc.lower()),
            }
            print("checks", json.dumps(checks, indent=2), flush=True)
            if heat:
                print("first", heat[0], flush=True)
            ok = (
                checks["n_heat"] > 0
                and checks["has_read"]
                and checks["read_top"] == 5
                and checks["no_pack"]
                and checks["no_body_def"]
                and checks["desc_ok"]
                and checks["mode_ok"]
            )
            print("PASS" if ok else "FAIL", flush=True)
            return 0 if ok else 1


def main() -> int:
    sys.path.insert(0, str(ROOT / "packages"))
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
