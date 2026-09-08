"""In-process ship-surface check: registration + gate → map → pack → expand.

Shared by ``scripts/scubiee_mcp_ship_check.py`` and pre-prod pytest.
No MCP bridge required.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

SHIP_TOOLS: frozenset[str] = frozenset(
    {
        "gate",
        "map",
        "pack_context",
        "expand_context",
        "collect_hot_context",
        "workspace",
        "expand",
        "status",
    }
)
FORBIDDEN_SHIP_TOOLS: frozenset[str] = frozenset(
    {
        "pinpoint",
        "plate",
        "focus",
        "grep",
        "glob",
        "pack_poly_embed",
        "pack_semantic",
        "map_context",
    }
)

DEFAULT_QUERY = (
    "pack_context run_pack_context expand_context composite_v1 "
    "packages/pipeline/context_trace.py lean heatmap ladder seed pick"
)


def tool_fn(mcp: Any, name: str):
    tools = mcp._tool_manager._tools
    tool = tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "handler", None) or tool


def parse_tool_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {"ok": False, "raw": raw}
        except json.JSONDecodeError:
            return {"ok": False, "raw": raw}
    return {"ok": False, "raw": str(raw)}


def ensure_ship_env(repo: Path | None = None) -> Path:
    root = Path(repo) if repo is not None else Path.cwd()
    os.environ.setdefault("CTX_REPO", str(root).replace("\\", "/"))
    os.environ.setdefault("CTX_MCP_SURFACE", "phase")
    os.environ["CTX_MCP_EXPERIMENT"] = "ship"
    os.environ.setdefault("CTX_TRACE_ENGINE", "composite_v1")
    return root


def check_phase_tool_names() -> dict[str, Any]:
    from pipeline.mcp_locate import _phase_experiment, _phase_tool_names

    assert _phase_experiment() == "ship"
    names = set(_phase_tool_names())
    missing = sorted(SHIP_TOOLS - names)
    leaked = sorted(FORBIDDEN_SHIP_TOOLS & names)
    return {
        "ok": not missing and not leaked,
        "tools": sorted(names),
        "missing": missing,
        "leaked": leaked,
    }


def check_registered_tools(mcp: Any) -> dict[str, Any]:
    registered = set(mcp._tool_manager._tools)
    missing = sorted(SHIP_TOOLS - registered)
    leaked = sorted(FORBIDDEN_SHIP_TOOLS & registered)
    return {
        "ok": not missing and not leaked,
        "count": len(registered),
        "missing": missing,
        "leaked": leaked,
        "tools": sorted(registered),
    }


def run_ship_ladder(
    *,
    repo: Path | None = None,
    query: str = DEFAULT_QUERY,
    create_mcp: Any | None = None,
) -> dict[str, Any]:
    """Run registration + ladder; returns a report dict with ``ok`` bool."""
    ensure_ship_env(repo)
    report: dict[str, Any] = {"ok": False, "checks": {}, "errors": []}
    t0 = time.perf_counter()
    try:
        from pipeline.mcp_locate import create_mcp as _create

        factory = create_mcp or _create
        phase = check_phase_tool_names()
        report["checks"]["phase_tools"] = phase
        if not phase["ok"]:
            if phase["missing"]:
                report["errors"].append(f"missing: {phase['missing']}")
            if phase["leaked"]:
                report["errors"].append(f"leaked: {phase['leaked']}")

        mcp = factory(name="ship-check")
        registered = check_registered_tools(mcp)
        report["checks"]["registered"] = registered
        if not registered["ok"]:
            if registered["missing"]:
                report["errors"].append(f"registered missing: {registered['missing']}")
            if registered["leaked"]:
                report["errors"].append(f"registered leaked: {registered['leaked']}")

        gate_out = tool_fn(mcp, "gate")()
        gate_text = gate_out if isinstance(gate_out, str) else str(gate_out)
        report["checks"]["gate"] = {
            "ok": "1:ce_" in gate_text or "ce_" in gate_text,
            "preview": gate_text[:160],
        }
        if not report["checks"]["gate"]["ok"]:
            report["errors"].append(f"gate unexpected: {gate_text[:240]}")

        map_json = parse_tool_json(tool_fn(mcp, "map")(query=query, k=8))
        seed = map_json.get("suggested_seed") or {}
        report["checks"]["map"] = {
            "ok": bool(map_json.get("ok")),
            "count": map_json.get("count"),
            "seed_file": seed.get("file"),
            "seed_symbol": seed.get("symbol"),
        }
        if not map_json.get("ok"):
            report["errors"].append(f"map failed: {str(map_json)[:300]}")

        seed_file = seed.get("file") or "packages/pipeline/context_trace.py"
        seed_symbol = seed.get("symbol") or "run_pack_context"
        if not seed_symbol or str(seed_symbol).startswith("_"):
            seed_file = "packages/pipeline/context_trace.py"
            seed_symbol = "run_pack_context"

        pack_json = parse_tool_json(
            tool_fn(mcp, "pack_context")(
                query=query,
                seed_file=seed_file,
                seed_symbol=seed_symbol,
                mode="lean",
                policy="strict",
            )
        )
        heatmap = pack_json.get("heatmap") or []
        report["checks"]["pack_context"] = {
            "ok": bool(pack_json.get("ok")) and bool(heatmap or pack_json.get("chain")),
            "engine": pack_json.get("engine"),
            "heatmap_n": len(heatmap) if isinstance(heatmap, list) else 0,
            "seed": (pack_json.get("seed") or {}).get("id")
            if isinstance(pack_json.get("seed"), dict)
            else None,
            "bodies_present": bool(pack_json.get("pack") or pack_json.get("bodies")),
        }
        if not report["checks"]["pack_context"]["ok"]:
            report["errors"].append(f"pack failed: {str(pack_json)[:300]}")

        node = report["checks"]["pack_context"].get("seed")
        if node:
            exp_json = parse_tool_json(
                tool_fn(mcp, "expand_context")(
                    node=node, direction="callees", with_bodies=True, query=query
                )
            )
            report["checks"]["expand_context"] = {
                "ok": bool(exp_json.get("ok")),
                "count": exp_json.get("count"),
                "direction": exp_json.get("direction"),
            }
            if not exp_json.get("ok"):
                report["errors"].append(f"expand failed: {str(exp_json)[:300]}")
        else:
            report["checks"]["expand_context"] = {"ok": False, "error": "no seed id"}
            report["errors"].append("no seed id from pack")

        # Soft extras: must not crash; collect_hot needs ids or prior heatmap.
        try:
            status_raw = tool_fn(mcp, "status")()
            status_json = parse_tool_json(status_raw)
            # Non-empty alone is not enough — ok:false means daemon down / paused.
            status_ok = bool(status_json.get("ok")) and not status_json.get("paused")
            report["checks"]["status"] = {
                "ok": status_ok,
                "preview": str(status_raw)[:120],
                "engine_healthy": (status_json.get("engine") or {}).get("healthy")
                if isinstance(status_json.get("engine"), dict)
                else None,
            }
            if not status_ok:
                report["errors"].append(f"status not ok: {str(status_raw)[:300]}")
        except Exception as exc:  # noqa: BLE001
            report["checks"]["status"] = {"ok": False, "error": str(exc)}
            report["errors"].append(f"status: {exc}")

        try:
            ws_raw = tool_fn(mcp, "workspace")(action="show")
            report["checks"]["workspace"] = {
                "ok": bool(ws_raw),
                "preview": str(ws_raw)[:120],
            }
            if not report["checks"]["workspace"]["ok"]:
                report["errors"].append("workspace empty")
        except Exception as exc:  # noqa: BLE001
            report["checks"]["workspace"] = {"ok": False, "error": str(exc)}
            report["errors"].append(f"workspace: {exc}")

        try:
            ids = str(node) if node else ""
            hot_raw = (
                tool_fn(mcp, "collect_hot_context")(ids=ids)
                if ids
                else tool_fn(mcp, "collect_hot_context")()
            )
            hot = parse_tool_json(hot_raw)
            text = str(hot_raw).lower()
            # Success, or graceful empty-heatmap envelope when no ids yet.
            hot_ok = bool(hot.get("ok")) or (
                not ids and "no session heatmap" in text
            )
            report["checks"]["collect_hot_context"] = {
                "ok": hot_ok,
                "preview": str(hot_raw)[:120],
            }
            if not hot_ok:
                report["errors"].append(f"collect_hot failed: {str(hot_raw)[:200]}")
        except Exception as exc:  # noqa: BLE001
            report["checks"]["collect_hot_context"] = {"ok": False, "error": str(exc)}
            report["errors"].append(f"collect_hot_context: {exc}")
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(str(exc))
        report["checks"]["exception"] = {"ok": False, "error": str(exc)}

    report["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    oks = [c.get("ok") for c in report["checks"].values() if isinstance(c, dict) and "ok" in c]
    report["ok"] = bool(oks) and all(oks) and not report["errors"]
    return report
