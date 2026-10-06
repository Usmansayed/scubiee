"""In-process ship-surface check for the Map V3 MCP server.

Validates the shipped surface — one ``map`` tool with configs find|focus, plus
gate|status — and drives the real ladder (gate → map find → focus → graph-fallback)
through ``pipeline.map_v3_server`` against the live engine. No MCP bridge required.
(v0.3.142 narrowed the advertised surface to find|focus; graph/related stay as hidden
graceful fallbacks.)

Rewritten for the Map V3 migration: the old pack_context/expand_context/
collect_hot_context tool ladder is retired; those tools no longer ship.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# Shipped Map V3 surface.
SHIP_TOOLS: frozenset[str] = frozenset({"map", "gate", "status"})
# v0.3.142: advertised surface narrowed to find|focus. graph/related remain as hidden
# graceful fallbacks (served, not advertised) — see map_v3_server.CONFIGS vs HANDLERS.
SHIP_CONFIGS: frozenset[str] = frozenset({"find", "focus"})
# Tools from the retired tool-layer that must NOT ship on Map V3.
FORBIDDEN_SHIP_TOOLS: frozenset[str] = frozenset(
    {
        "pack_context",
        "expand_context",
        "collect_hot_context",
        "workspace",
        "expand",
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
    "where freshness report decides sync strategy choose_strategy "
    "packages/pipeline/freshness.py incremental background full"
)


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
    return root


def check_registered_tools() -> dict[str, Any]:
    """Static surface check: map_v3_server exposes exactly map/gate/status + 4 configs."""
    from pipeline import map_v3_server

    registered = set(getattr(map_v3_server, "TOOLS", {}))
    configs = set(getattr(map_v3_server, "CONFIGS", ()))
    missing = sorted(SHIP_TOOLS - registered)
    leaked = sorted(FORBIDDEN_SHIP_TOOLS & registered)
    missing_cfg = sorted(SHIP_CONFIGS - configs)
    return {
        "ok": not missing and not leaked and not missing_cfg,
        "count": len(registered),
        "tools": sorted(registered),
        "configs": sorted(configs),
        "missing": missing,
        "leaked": leaked,
        "missing_configs": missing_cfg,
    }


def run_ship_ladder(
    *,
    repo: Path | None = None,
    query: str = DEFAULT_QUERY,
) -> dict[str, Any]:
    """Run the Map V3 surface + ladder; returns a report dict with ``ok`` bool.

    Drives the tool implementations directly (gate/status/map configs) exactly as
    the server's JSON-RPC dispatch would.
    """
    ensure_ship_env(repo)
    report: dict[str, Any] = {"ok": False, "checks": {}, "errors": []}
    t0 = time.perf_counter()
    try:
        from pipeline import map_v3_server as srv

        # 1. Surface registration
        reg = check_registered_tools()
        report["checks"]["registered"] = reg
        if not reg["ok"]:
            if reg["missing"]:
                report["errors"].append(f"missing tools: {reg['missing']}")
            if reg["leaked"]:
                report["errors"].append(f"leaked tools: {reg['leaked']}")
            if reg["missing_configs"]:
                report["errors"].append(f"missing configs: {reg['missing_configs']}")

        def _call(name: str, args: dict) -> str:
            fn = srv.TOOLS[name]["fn"]
            return fn(args or {})

        # 2. gate
        gate_text = str(_call("gate", {}))
        report["checks"]["gate"] = {
            "ok": gate_text.strip().startswith("1") or "ce_" in gate_text,
            "preview": gate_text[:160],
        }
        if not report["checks"]["gate"]["ok"]:
            report["errors"].append(f"gate unexpected: {gate_text[:240]}")

        # 3. status
        status_text = str(_call("status", {}))
        status_ok = any(k in status_text.lower() for k in ("ok=", "warm", "chunks"))
        report["checks"]["status"] = {"ok": status_ok, "preview": status_text[:160]}
        if not status_ok:
            report["errors"].append(f"status not ok: {status_text[:240]}")

        # 4. map find
        find_text = str(_call("map", {"config": "find", "query": query}))
        find_ok = len(find_text) > 150 and ("find:" in find_text or ".py" in find_text)
        report["checks"]["map_find"] = {"ok": find_ok, "chars": len(find_text)}
        if not find_ok:
            report["errors"].append(f"map find failed: {find_text[:240]}")

        # 5. map focus (a known public symbol)
        focus_text = str(
            _call("map", {"config": "focus", "names": ["choose_strategy"]})
        )
        focus_ok = "choose_strategy" in focus_text and (
            "wiring" in focus_text or "lines" in focus_text
        )
        report["checks"]["map_focus"] = {"ok": focus_ok, "chars": len(focus_text)}
        if not focus_ok:
            report["errors"].append(f"map focus failed: {focus_text[:240]}")

        # 6. dropped config (graph) must DEGRADE GRACEFULLY, not crash — it is folded
        #    into find in v0.3.142 (hidden fallback). Any usable text is a pass; a bare
        #    "error:"/traceback is a fail.
        graph_text = str(_call("map", {"config": "graph", "query": query}))
        graph_ok = len(graph_text) > 60 and not graph_text.lower().startswith("error")
        report["checks"]["map_graph_fallback"] = {"ok": graph_ok, "preview": graph_text[:120]}
        if not graph_ok:
            report["errors"].append(f"graph fallback failed: {graph_text[:240]}")

        # 7. unknown config must not crash
        bad_text = str(_call("map", {"config": "nonsense"}))
        bad_ok = "error" in bad_text.lower() or "must be one of" in bad_text.lower()
        report["checks"]["map_bad_config"] = {"ok": bad_ok, "preview": bad_text[:120]}
        if not bad_ok:
            report["errors"].append(f"bad config not handled: {bad_text[:160]}")
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(str(exc))
        report["checks"]["exception"] = {"ok": False, "error": str(exc)}

    report["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    oks = [c.get("ok") for c in report["checks"].values() if isinstance(c, dict) and "ok" in c]
    report["ok"] = bool(oks) and all(oks) and not report["errors"]
    return report
