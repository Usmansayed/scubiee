"""Fresh-bridge attach race probe (BETA-02 / BETA-05 / BETA-13).

Spawns the Scubiee MCP bridge exactly as Cursor does (``.cursor/mcp.json``),
with ``PYTHONPATH`` stripped so the uv-tool install is what runs, then:

    initialize -> gate -> map -> pack_context(lean) x N -> status

and prints one JSON report. ``ok`` is true when every session's first pack
returned ``ok`` with a non-empty heatmap (a pack that waited on AST hydrate
inside the call still counts; a returned ``ast_warming`` does not).

Usage:
    python scripts/attach_pack_race.py [--sessions 2] [--packs 3] [--out path.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mcp_stdio_client import McpStdioClient  # noqa: E402

PID = "ce_3536ac8e8e83bb8e4d888db37847729c"
MAP_QUERY = (
    "mcp_locate pack_context returns ast_warming heatmap_n=0 on fresh mcp_bridge attach "
    "while derive_agent_ready reports agent_ready=yes; context_trace hydrate_ast_bundle "
    "warm_contract ast_hydrated should_retry"
)
PACK_QUERY = (
    "context_trace.py::hydrate_ast_bundle stale bundle load ast_cache_ready; "
    "mcp_locate pack_context ast_warming wait retry_after_s; sync_status derive_agent_ready"
)


def _client(label: str) -> McpStdioClient:
    cfg = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    entry = cfg["mcpServers"]["scubiee"]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env.update(entry.get("env") or {})
    env.pop("PYTHONPATH", None)
    env["CTX_MCP_CLIENT"] = f"attach_probe_{label}"
    c = McpStdioClient(entry["command"], entry.get("args", []))
    c.env = env
    return c


def _timed(fn, *a, **kw):
    t0 = time.perf_counter()
    out = fn(*a, **kw)
    return out, round((time.perf_counter() - t0) * 1000, 1)


def run_session(label: str, packs: int, wait_warm_s: float = 0.0) -> dict:
    rows: list[dict] = []
    t0 = time.perf_counter()
    with _client(label) as c:
        init_ms = round((time.perf_counter() - t0) * 1000, 1)
        gate, ms = _timed(c.call_text, "gate", project_id=PID)
        rows.append(
            {
                "tool": "gate",
                "ms": ms,
                "index_skip": next(
                    (ln for ln in gate.splitlines() if "index_skip" in ln), None
                ),
                "index_write_hint": any("index_write_hint" in ln for ln in gate.splitlines()),
            }
        )
        if wait_warm_s > 0:
            # Documented agent behavior: wait on status.warm_wait, not a fixed sleep.
            t_w = time.perf_counter()
            polls = 0
            ww: dict = {}
            while time.perf_counter() - t_w < wait_warm_s:
                st = c.call("status", project_id=PID)
                ww = st.get("warm_wait") or {}
                polls += 1
                if ww.get("done"):
                    break
                time.sleep(float(ww.get("retry_after_s") or 5))
            rows.append(
                {
                    "tool": "wait_warm",
                    "ms": round((time.perf_counter() - t_w) * 1000, 1),
                    "polls": polls,
                    "done": bool(ww.get("done")),
                    "stage": ww.get("stage"),
                }
            )
        m, ms = _timed(c.call, "map", query=MAP_QUERY, k=10, project_id=PID)
        seed = m.get("suggested_seed") or {}
        rows.append(
            {
                "tool": "map",
                "ms": ms,
                "ok": bool(m.get("ok")),
                "n": len(m.get("cards") or []),
                "dense": m.get("dense"),
                "err": m.get("error"),
                "seed": f"{seed.get('file')}::{seed.get('symbol')}",
            }
        )
        for i in range(packs):
            p, ms = _timed(
                c.call,
                "pack_context",
                query=PACK_QUERY,
                seed_file=seed.get("file") or "packages/pipeline/context_trace.py",
                seed_symbol=seed.get("symbol") or "hydrate_ast_bundle",
                mode="lean",
                project_id=PID,
            )
            rows.append(
                {
                    "tool": f"pack_{i}",
                    "ms": ms,
                    "ok": bool(p.get("ok")),
                    "n_heat": len(p.get("heatmap") or []),
                    "thin": p.get("thin"),
                    "err": p.get("error"),
                    "should_retry": p.get("should_retry"),
                    "retry_after_s": p.get("retry_after_s"),
                    "ast_wait_ms": p.get("ast_wait_ms"),
                }
            )
        s, ms = _timed(c.call, "status", project_id=PID)
        rows.append(
            {
                "tool": "status",
                "ms": ms,
                "agent_ready": s.get("agent_ready"),
                "pack_ready": s.get("pack_ready"),
                "ast_hydrated": s.get("ast_hydrated"),
                "embedder_loaded": s.get("embedder_loaded"),
                "warm_elapsed_ms": s.get("warm_elapsed_ms"),
                "warm_wait": s.get("warm_wait"),
            }
        )
    first_pack = next(r for r in rows if r["tool"] == "pack_0")
    first_map = next(r for r in rows if r["tool"] == "map")
    return {
        "label": label,
        "init_ms": init_ms,
        "map_ok": bool(first_map["ok"]),
        "first_pack_ok": bool(first_pack["ok"] and first_pack["n_heat"] > 0),
        "results": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=2)
    ap.add_argument("--packs", type=int, default=3)
    ap.add_argument("--out", default="")
    ap.add_argument(
        "--wait-warm-s",
        type=float,
        default=0.0,
        help="After gate, poll status until warm_wait.done (bounded) before map.",
    )
    args = ap.parse_args()
    sessions = [
        run_session(chr(ord("A") + i), args.packs, args.wait_warm_s)
        for i in range(args.sessions)
    ]
    report = {
        "ok": all(s["first_pack_ok"] and s["map_ok"] for s in sessions),
        "sessions": sessions,
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
