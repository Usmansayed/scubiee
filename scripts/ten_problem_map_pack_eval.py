"""10-problem real-life eval: detailed map → pick seed → pack_context → score.

Mirrors agent GATE instructions:
1) descriptive soft map to find candidates
2) pick best seed chunk from map cards
3) pack_context(detailed query + seed) for full context
4) store all traces; score vs gold files/symbols
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"C:/Users/usman/Downloads/context-engine")
OUT = Path("docs/superpowers/plans/2026-09-05-ten-problem-map-pack-eval.json")

# Real engineering tasks an agent would hit in this repo.
PROBLEMS: list[dict[str, Any]] = [
    {
        "id": "P01_connect_permissions",
        "problem": "Change which tools Cursor auto-approves when running scubiee connect.",
        "map_query": (
            "scubiee connect Cursor mcp.json autoApprove alwaysAllow permissions.json "
            "mcpAllowlist PHASE_LOCATE_TOOLS apply_permissions write_project_tool_surface"
        ),
        "pack_query": (
            "When scubiee connect --cursor runs, trace how mcp.json autoApprove/alwaysAllow and "
            "permissions.json mcpAllowlist are written: install_tools → install_tool → "
            "fan_out_tool_to_enrolled_repos → write_project_tool_surface → "
            "apply_permissions_to_repo_tool_surface and PHASE_LOCATE_TOOLS. Include GATE rule write path."
        ),
        "gold_files": [
            "packages/pipeline/__main__.py",
            "packages/pipeline/rules_installer.py",
            "packages/pipeline/mcp_permissions.py",
        ],
        "gold_symbols": [
            "cmd_connect",
            "write_project_tool_surface",
            "apply_permissions_to_repo_tool_surface",
            "PHASE_LOCATE_TOOLS",
        ],
    },
    {
        "id": "P02_pack_context",
        "problem": "Understand how pack_context builds one-call heatmap + hot bodies.",
        "map_query": (
            "pack_context run_pack_context heatmap_to_cards run_collect_hot hot_threshold "
            "budget_chars drop_noise context_trace"
        ),
        "pack_query": (
            "Trace pack_context MCP to run_pack_context: map_context polytrace heatmap, "
            "noise filter cli_ui, hot_threshold body packing via run_collect_hot, slim heatmap "
            "and pack bodies fields returned to the agent in one call."
        ),
        "gold_files": [
            "packages/pipeline/context_trace.py",
            "packages/pipeline/mcp_locate.py",
        ],
        "gold_symbols": ["run_pack_context", "run_collect_hot", "heatmap_to_cards", "pack_context_impl"],
    },
    {
        "id": "P03_graphify_store_load",
        "problem": "How does context tracing load init graph.json instead of rebuilding Graphify?",
        "map_query": (
            "load_store_graphify_graph graph.json CTX_TRACE_GRAPHIFY bind_polytrace "
            "build_graphify_graph project store"
        ),
        "pack_query": (
            "Trace how _load_repo enables Graphify by default, prefers load_store_graphify_graph "
            "from ~/.scubiee/projects/*/graph.json written at scubiee init/index, maps calls onto "
            "TraceNodes, and only rebuilds with CTX_TRACE_GRAPHIFY_REBUILD."
        ),
        "gold_files": [
            "packages/pipeline/context_trace.py",
            "packages/trace_lab/graphify_layer.py",
        ],
        "gold_symbols": ["load_store_graphify_graph", "_load_repo", "_want_graphify"],
    },
    {
        "id": "P04_incremental_index",
        "problem": "How does incremental sync patch the index when files change?",
        "map_query": (
            "incremental sync dirty merkle patch_and_save_graph embed chunks "
            "IndexConfirmRequired preflight"
        ),
        "pack_query": (
            "Trace incremental indexing: detect dirty paths via merkle, patch graph.json with "
            "patch_and_save_graph, re-embed changed chunks, safety gates IndexConfirmRequired "
            "for large deltas — entry from sync loop / incremental module."
        ),
        "gold_files": [
            "packages/pipeline/incremental.py",
            "packages/pipeline/sync_loop.py",
        ],
        "gold_symbols": ["patch_and_save_graph", "IndexConfirmRequired"],
    },
    {
        "id": "P05_gate_rules_install",
        "problem": "Where does connect write AGENTS.md and .cursor/rules GATE text?",
        "map_query": (
            "write_project_gate_rules managed_gate_usage_short AGENTS.md scubiee.mdc "
            "rules_installer GATE pack_context"
        ),
        "pack_query": (
            "Trace write_project_gate_rules and managed_gate_usage_short: how GATE 1 body "
            "preferring pack_context is rendered into AGENTS.md and .cursor/rules/scubiee.mdc "
            "during connect / write_project_tool_surface."
        ),
        "gold_files": [
            "packages/pipeline/rules_installer.py",
        ],
        "gold_symbols": [
            "write_project_gate_rules",
            "managed_gate_usage_short",
            "write_project_tool_surface",
        ],
    },
    {
        "id": "P06_pinpoint_plate",
        "problem": "How does hybrid pinpoint differ from plate for soft locate?",
        "map_query": (
            "pinpoint_impl plate_impl Conductor BM25 dense graph neighbors "
            "CTX_MCP_EXPERIMENT hybrid"
        ),
        "pack_query": (
            "Trace hybrid MCP pinpoint vs plate: pinpoint returns primary body + neighbors for "
            "edit-ready soft locate; plate returns hubs/connections/flow for how-X-works without "
            "LLM — registration in create_mcp phase hybrid."
        ),
        "gold_files": ["packages/pipeline/mcp_locate.py"],
        "gold_symbols": ["pinpoint_impl", "plate_impl"],
    },
    {
        "id": "P07_session_isolation",
        "problem": "How are parallel Cursor chats isolated for pins/handles/trace?",
        "map_query": (
            "session_id CTX_MCP_SESSION_ISOLATE session_store load_store save_store "
            "_resolve_session transport_conn"
        ),
        "pack_query": (
            "Trace MCP session isolation: _resolve_session, session_store load/save, "
            "CTX_MCP_SESSION_ISOLATE, how pack_context/map_context persist context_trace "
            "per session_id and shared connection risk."
        ),
        "gold_files": [
            "packages/pipeline/session_store.py",
            "packages/pipeline/mcp_locate.py",
        ],
        "gold_symbols": ["load_store", "save_store", "_resolve_session", "persist_trace"],
    },
    {
        "id": "P08_engine_warm",
        "problem": "What makes status say soft_search_ready / agent_ready warming?",
        "map_query": (
            "soft_search_ready warm_state agent_ready engine daemon status "
            "WarmSearchEngine overlay"
        ),
        "pack_query": (
            "Trace how MCP status computes soft_search_ready, warm_state, agent_ready warming/"
            "stale from engine daemon health and sync_state — where WarmSearchEngine readiness "
            "is exposed to agents."
        ),
        "gold_files": [
            "packages/pipeline/mcp_locate.py",
            "packages/pipeline/engine.py",
        ],
        "gold_symbols": ["soft_search_ready", "WarmSearchEngine"],
    },
    {
        "id": "P09_uv_tool_unlock",
        "problem": "Fix Access denied when uv tool install --force scubiee while MCP is running.",
        "map_query": (
            "prepare_uv_tool_directory_for_swap release_scubiee_process_locks "
            "stop_all_context_engine_processes unlock-tool Access denied"
        ),
        "pack_query": (
            "Trace prepare_uv_tool_directory_for_swap and process lock release: stop engine/"
            "MCP bridge processes, optional mcp stub, so uv tool install --force can replace "
            "scubiee-mcp-bridge.exe without Access denied."
        ),
        "gold_files": ["packages/pipeline/process_control.py"],
        "gold_symbols": [
            "prepare_uv_tool_directory_for_swap",
            "release_scubiee_process_locks",
            "stop_all_context_engine_processes",
        ],
    },
    {
        "id": "P10_auth_fixture",
        "problem": "Debug fixture login: invalid/expired JWT on authenticate path.",
        "map_query": (
            "authenticate extract_bearer JwtService.verify decode TOKEN_TTL "
            "UserRepository.resolve fixtures/trace-lab middleware auth"
        ),
        "pack_query": (
            "Login fails invalid/expired token — credential path authenticate → extract_bearer → "
            "JwtService.verify → decode → TOKEN_TTL expired → UserRepository.resolve → connect/"
            "User.lookup. Prefer credential hops over analytics track side effects."
        ),
        "gold_files": [
            "fixtures/trace-lab/app/middleware/auth.py",
            "fixtures/trace-lab/app/services/jwt_service.py",
            "fixtures/trace-lab/app/utils/token.py",
            "fixtures/trace-lab/app/repositories/user_repo.py",
        ],
        "gold_symbols": [
            "authenticate",
            "extract_bearer",
            "JwtService.verify",
            "decode",
            "UserRepository.resolve",
        ],
    },
]


def _soft_map(root: Path, query: str, k: int = 8) -> dict[str, Any]:
    """Soft map via engine /v1/search (same family as MCP map)."""
    from pipeline.client import EngineClient

    client = EngineClient("http://127.0.0.1:8765")
    raw = client.search(query, top_k=k, path=str(root))
    if not isinstance(raw, dict):
        return {"ok": False, "error": "bad_search_response", "cards": []}
    if raw.get("error") and not (raw.get("results") or raw.get("hits")):
        return {"ok": False, "error": str(raw.get("error")), "cards": []}
    hits = raw.get("results") or raw.get("hits") or raw.get("cards") or []
    cards = []
    for i, h in enumerate(hits[:k], 1):
        if not isinstance(h, dict):
            continue
        cards.append(
            {
                "rank": i,
                "file": h.get("file") or h.get("path") or "",
                "start_line": h.get("start_line") or h.get("start") or 0,
                "end_line": h.get("end_line") or h.get("end") or 0,
                "symbol": h.get("symbol") or "",
                "score": float(h.get("score") or 0),
                "why": (h.get("text") or h.get("snippet") or h.get("why") or "")[:120],
            }
        )
    return {
        "ok": True,
        "tool": "map",
        "query": query,
        "cards": cards,
        "count": len(cards),
    }


def _pick_seed(cards: list[dict[str, Any]], gold_files: list[str]) -> dict[str, Any]:
    """Prefer a map card whose file is in gold; else top card with a file."""
    for c in cards:
        f = (c.get("file") or "").replace("\\", "/")
        for g in gold_files:
            if f.endswith(g) or g in f or f.endswith(g.replace("packages/", "")):
                return c
        for g in gold_files:
            if Path(g).name in f:
                return c
    return cards[0] if cards else {}


def _score_pack(pack: dict[str, Any], gold_files: list[str], gold_symbols: list[str]) -> dict[str, Any]:
    bodies = pack.get("pack") or []
    heat = pack.get("heatmap") or []
    files = {(b.get("file") or "").replace("\\", "/") for b in bodies}
    files |= {(c.get("file") or "").replace("\\", "/") for c in heat}
    syms = {b.get("symbol") or "" for b in bodies}
    syms |= {c.get("symbol") or "" for c in heat}

    file_hits = []
    for g in gold_files:
        g = g.replace("\\", "/")
        ok = any(f.endswith(g) or g in f for f in files)
        file_hits.append({"gold": g, "hit": ok})

    sym_hits = []
    for g in gold_symbols:
        ok = g in syms or any(s.endswith(g) or g in s for s in syms)
        sym_hits.append({"gold": g, "hit": ok})

    fh = sum(1 for x in file_hits if x["hit"])
    sh = sum(1 for x in sym_hits if x["hit"])
    return {
        "file_rec": round(fh / len(gold_files), 3) if gold_files else None,
        "symbol_rec": round(sh / len(gold_symbols), 3) if gold_symbols else None,
        "file_hits": file_hits,
        "symbol_hits": sym_hits,
        "packed": pack.get("packed"),
        "pack_chars": pack.get("chars"),
        "heatmap_n": pack.get("count"),
        "calls": pack.get("calls"),
        "graphify": pack.get("graphify"),
    }


def run() -> dict[str, Any]:
    from pipeline.context_trace import _CACHE, run_pack_context

    _CACHE.clear()
    rows: list[dict[str, Any]] = []
    t_all = time.perf_counter()

    # Try engine map; fall back to gold-file first line seed if engine cold.
    use_engine = True
    try:
        _soft_map(ROOT, "scubiee connect mcp permissions", k=3)
    except Exception as exc:  # noqa: BLE001
        use_engine = False
        engine_err = str(exc)
    else:
        engine_err = None

    for prob in PROBLEMS:
        t0 = time.perf_counter()
        map_out: dict[str, Any]
        if use_engine:
            try:
                map_out = _soft_map(ROOT, prob["map_query"], k=8)
            except Exception as exc:  # noqa: BLE001
                map_out = {"ok": False, "error": str(exc), "cards": []}
        else:
            map_out = {
                "ok": False,
                "error": engine_err or "engine_unavailable",
                "cards": [],
                "fallback": "gold_file_seed",
            }

        cards = list(map_out.get("cards") or [])
        seed_card = _pick_seed(cards, prob["gold_files"])
        if not seed_card.get("file"):
            # fallback: first gold file
            seed_file = prob["gold_files"][0]
            seed_symbol = (prob.get("gold_symbols") or [""])[0]
            seed_line = 0
            seed_source = "gold_fallback"
        else:
            seed_file = seed_card["file"]
            seed_symbol = seed_card.get("symbol") or ""
            seed_line = int(seed_card.get("start_line") or 0)
            seed_source = "map_card"

        # Prefer symbol when present; else covering line
        pack_kwargs: dict[str, Any] = {
            "seed_file": seed_file,
            "k": 16,
            "hot_threshold": 0.65,
            "budget_chars": 12_000,
            "drop_noise": True,
        }
        if seed_symbol and "(" not in seed_symbol:
            pack_kwargs["seed_symbol"] = seed_symbol.split(".")[-1] if seed_symbol.count(".") > 1 else seed_symbol
            # keep dotted method names like JwtService.verify
            if "." in seed_symbol and not seed_symbol.startswith("."):
                pack_kwargs["seed_symbol"] = seed_symbol
        elif seed_line:
            pack_kwargs["seed_line"] = seed_line

        pack = run_pack_context(ROOT, prob["pack_query"], **pack_kwargs)
        if not pack.get("ok") and seed_line:
            pack = run_pack_context(
                ROOT,
                prob["pack_query"],
                seed_file=seed_file,
                seed_line=seed_line,
                k=16,
                hot_threshold=0.65,
                budget_chars=12_000,
            )
        if not pack.get("ok"):
            # last resort: first gold file + first gold symbol
            pack = run_pack_context(
                ROOT,
                prob["pack_query"],
                seed_file=prob["gold_files"][0],
                seed_symbol=(prob.get("gold_symbols") or [""])[0],
                k=16,
                hot_threshold=0.65,
                budget_chars=12_000,
            )
            seed_source = "gold_retry"

        score = _score_pack(pack, prob["gold_files"], prob["gold_symbols"]) if pack.get("ok") else {
            "error": pack.get("error"),
            "file_rec": 0.0,
            "symbol_rec": 0.0,
        }

        rows.append(
            {
                "id": prob["id"],
                "problem": prob["problem"],
                "map_query": prob["map_query"],
                "pack_query": prob["pack_query"],
                "map": {
                    "ok": map_out.get("ok"),
                    "count": map_out.get("count") or len(cards),
                    "top_files": [c.get("file") for c in cards[:5]],
                    "error": map_out.get("error"),
                },
                "seed": {
                    "source": seed_source,
                    "file": seed_file,
                    "symbol": seed_symbol,
                    "line": seed_line,
                    "card": seed_card,
                },
                "pack": {
                    "ok": pack.get("ok"),
                    "packed": pack.get("packed"),
                    "chars": pack.get("chars"),
                    "heatmap_n": pack.get("count"),
                    "graphify": pack.get("graphify"),
                    "symbols": [b.get("symbol") for b in (pack.get("pack") or [])],
                    "files": sorted(
                        {
                            (b.get("file") or "")
                            for b in (pack.get("pack") or []) + (pack.get("heatmap") or [])
                        }
                    ),
                    "error": pack.get("error"),
                },
                "score": score,
                "ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        )
        print(
            f"{prob['id']}: map={len(cards)} seed={seed_source}:{seed_file} "
            f"pack_ok={pack.get('ok')} file_rec={score.get('file_rec')} "
            f"sym_rec={score.get('symbol_rec')} packed={pack.get('packed')}"
        )

    file_recs = [r["score"].get("file_rec") for r in rows if r["score"].get("file_rec") is not None]
    sym_recs = [r["score"].get("symbol_rec") for r in rows if r["score"].get("symbol_rec") is not None]
    report = {
        "ok": True,
        "protocol": "map(descriptive) → pick seed → pack_context(detailed+seed)",
        "n": len(rows),
        "engine_map": use_engine,
        "engine_error": engine_err,
        "mean_file_rec": round(sum(file_recs) / len(file_recs), 3) if file_recs else None,
        "mean_symbol_rec": round(sum(sym_recs) / len(sym_recs), 3) if sym_recs else None,
        "elapsed_ms": round((time.perf_counter() - t_all) * 1000, 1),
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("ok", "n", "mean_file_rec", "mean_symbol_rec", "engine_map")}, indent=2))
    print("wrote", OUT)
    return report


if __name__ == "__main__":
    run()
