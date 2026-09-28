#!/usr/bin/env python3
"""Assemble locate-calibration-corpus-v1.json (Phase A).

Harvests prior blind / Kiro / personal cases, assigns taxonomy labels,
and attaches gold must files/symbols when available.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLANS = ROOT / "docs" / "superpowers" / "plans"
OUT = PLANS / "locate-calibration-corpus-v1.json"
OUT_MD = PLANS / "2026-09-06-locate-calibration-phase-a.md"


def _load(name: str) -> dict[str, Any]:
    return json.loads((PLANS / name).read_text(encoding="utf-8"))


def classify(task: str, enrich: str, family: str = "") -> str:
    """Heuristic taxonomy — reviewable; Phase B may override."""
    blob = f"{task} {enrich} {family}".lower()
    if any(x in blob for x in ("filename", "glob", "by name", "path pattern")):
        return "name_path"
    if any(
        x in blob
        for x in (
            "exact string",
            "error string",
            "import path",
            "literal",
            "findstr",
            "grep for",
            "auth_jwt_trap",
            "jwt trap",
        )
    ):
        return "literal_needle"
    if any(
        x in blob
        for x in (
            "fix a bug",
            "implement",
            "add or inspect",
            "wire",
            "debug the",
            "missing callee",
            "exact edit",
        )
    ):
        return "exact_edit"
    if any(x in blob for x in ("rematerialize", "by handle", "workspace show", "prior pin")):
        return "rematerialize"
    # known_seed: only when task already names a concrete symbol path-style
    if "::" in enrich and enrich.count("::") >= 1 and "how does" not in blob:
        # enrich queries often name symbols without being known_seed tasks
        pass
    return "soft_understand"


def hypo_policy(taxonomy: str) -> dict[str, str]:
    return {
        "soft_understand": {
            "lead": "scubiee_map",
            "next": "conditional_pack",
            "native": "span_read_after_heatmap",
        },
        "exact_edit": {
            "lead": "scubiee_map_or_pack",
            "next": "pack_if_seed_ok",
            "native": "span_read_locs",
        },
        "literal_needle": {
            "lead": "host_grep",
            "next": "host_read",
            "native": "first_class",
        },
        "known_seed": {
            "lead": "scubiee_pack",
            "next": "expand_if_thin",
            "native": "or_direct_read",
        },
        "name_path": {
            "lead": "host_glob",
            "next": "host_read",
            "native": "first_class",
        },
        "rematerialize": {
            "lead": "workspace_or_expand_handle",
            "next": "none",
            "native": "none",
        },
    }.get(taxonomy, {"lead": "unknown", "next": "unknown", "native": "unknown"})


def add_case(
    cases: list[dict[str, Any]],
    *,
    cid: str,
    source: str,
    task: str,
    enrich: str,
    taxonomy: str | None = None,
    must_files: list[str] | None = None,
    must_symbols: list[str] | None = None,
    should_files: list[str] | None = None,
    family: str = "",
    notes: str = "",
) -> None:
    tax = taxonomy or classify(task, enrich, family)
    cases.append(
        {
            "id": cid,
            "source": source,
            "family": family,
            "task": task,
            "enrich_query": enrich,
            "taxonomy": tax,
            "taxonomy_confidence": "heuristic" if taxonomy is None else "manual",
            "hypothesis_policy": hypo_policy(tax),
            "must_files": must_files or [],
            "must_symbols": must_symbols or [],
            "should_files": should_files or [],
            "gold_status": "has_gold" if (must_files or must_symbols) else "needs_gold",
            "notes": notes,
            "baseline_frozen": True,
        }
    )


def main() -> None:
    cases: list[dict[str, Any]] = []

    # --- Blind map-pack 20 ---
    q = _load("2026-09-06-blind-map-pack-20-queries.json")
    gt = _load("2026-09-06-blind-map-pack-20-ground-truth.json")["cases"]
    for c in q["cases"]:
        g = gt.get(c["id"], {})
        add_case(
            cases,
            cid=f"blind20_{c['id']}",
            source="blind_map_pack_20",
            task=c["task"],
            enrich=c["enrich_map_query"],
            family=c.get("family", ""),
            must_files=list(g.get("must_files") or []),
            must_symbols=list(g.get("must_symbols") or []),
            should_files=list(g.get("should_files") or []),
        )

    # --- Blind multipack 20 (NEW u01–u20) ---
    mq = _load("2026-09-06-blind-multipack-20-queries.json")
    mgt = _load("2026-09-06-blind-multipack-20-ground-truth.json")["cases"]
    for c in mq["cases"]:
        g = mgt.get(c["id"], {})
        add_case(
            cases,
            cid=f"multipack_{c['id']}",
            source="blind_multipack_20",
            task=c["task"],
            enrich=c["enrich_map_query"],
            family=c.get("family", ""),
            must_files=list(g.get("must_files") or []),
            must_symbols=list(g.get("must_symbols") or []),
            should_files=list(g.get("should_files") or []),
        )

    # --- Kiro simple locate 5 ---
    simple = _load("2026-09-05-kiro-mcp-ab.json")
    for t in simple.get("tasks") or []:
        add_case(
            cases,
            cid=f"kiro_simple_{t['id']}",
            source="kiro_mcp_ab_simple",
            task=t.get("prompt") or t.get("id", ""),
            enrich=t.get("enrich_query") or t.get("id", ""),
            must_files=list(t.get("gold_files") or []),
            must_symbols=list(t.get("gold_symbols") or []),
            family="kiro_locate",
            notes="prompt may be long; use id if empty enrich",
        )

    # Fix simple prompts if stored only as id
    for t in simple.get("tasks") or []:
        cid = f"kiro_simple_{t['id']}"
        for c in cases:
            if c["id"] != cid:
                continue
            if not c["task"] or c["task"] == t["id"]:
                # prompts live in harness; keep gold, mark soft_understand default
                c["task"] = t["id"].replace("_", " ")
                c["enrich_query"] = " ".join(t.get("gold_symbols") or [t["id"]])
                c["taxonomy"] = classify(c["task"], c["enrich_query"], "kiro_locate")
                c["hypothesis_policy"] = hypo_policy(c["taxonomy"])

    # --- Kiro complex 10 ---
    complex_ab = _load("2026-09-05-kiro-mcp-ab-complex.json")
    # prompts are embedded later in runs; use gold + id
    for t in complex_ab.get("tasks") or []:
        tid = t["id"]
        # taxonomy overrides
        tax = None
        if "jwt" in tid.lower() or "trap" in tid.lower():
            tax = "literal_needle"
        elif "vague" in tid.lower():
            tax = "soft_understand"
        elif "ladder" in tid.lower() or "connect" in tid.lower():
            tax = "exact_edit"
        add_case(
            cases,
            cid=f"kiro_complex_{tid}",
            source="kiro_mcp_ab_complex",
            task=tid.replace("_", " "),
            enrich=" ".join(t.get("gold_symbols") or [tid]),
            taxonomy=tax,
            must_files=list(t.get("gold_files") or []),
            must_symbols=list(t.get("gold_symbols") or []),
            family=t.get("complexity", "kiro_complex"),
        )

    # Pull real prompts from complex runs when present
    for run in complex_ab.get("runs") or []:
        tid = (run.get("task_id") or run.get("id") or "").strip()
        if not tid:
            continue
        prompt = ""
        for key in ("prompt", "user_prompt", "message"):
            if run.get(key):
                prompt = str(run[key])
                break
        # nested
        if not prompt and isinstance(run.get("with"), dict):
            prompt = str(run["with"].get("prompt") or "")
        if not prompt:
            continue
        for c in cases:
            if c["id"] == f"kiro_complex_{tid}" and len(prompt) > 40:
                # first line / short task summary
                c["task"] = prompt.split("\n")[0][:200]
                # enrich: keep gold symbols as vocab
                c["notes"] = (c.get("notes") or "") + " prompt_from_run"
                break

    # --- Personal3 ---
    p3 = _load("2026-09-06-personal3-map-vs-pack.json")
    p3_gold = {
        "p01": {
            "must_files": [
                "packages/pipeline/__main__.py",
                "packages/pipeline/rules_installer.py",
                "packages/pipeline/mcp_permissions.py",
            ],
            "must_symbols": [
                "cmd_connect",
                "write_project_tool_surface",
                "apply_permissions_to_repo_tool_surface",
            ],
            "taxonomy": "soft_understand",
        },
        "p02": {
            "must_files": [
                "packages/pipeline/freshness.py",
                "packages/pipeline/incremental.py",
            ],
            "must_symbols": ["ensure_fresh_for_search", "rebuild_embeddings_if_needed"],
            "taxonomy": "soft_understand",
        },
        "p03": {
            "must_files": [
                "packages/pipeline/context_trace.py",
                "packages/pipeline/locate_cli.py",
            ],
            "must_symbols": ["run_pack_context", "cli_pack"],
            "taxonomy": "soft_understand",
        },
    }
    for c in p3.get("cases") or []:
        g = p3_gold.get(c["id"], {})
        add_case(
            cases,
            cid=f"personal3_{c['id']}",
            source="personal3_map_vs_pack",
            task=c["task"],
            enrich=c["enrich_query"],
            taxonomy=g.get("taxonomy"),
            must_files=list(g.get("must_files") or []),
            must_symbols=list(g.get("must_symbols") or []),
            family="personal3",
            notes="gold from connect/freshness/pack path A/Bs",
        )

    # --- Cursor-style A/B prompts (3) ---
    cursor_cases = [
        {
            "id": "cursor_connect",
            "task": "When I connect Scubiee to Cursor, what is the write path that installs MCP config + permissions?",
            "enrich": "connect cursor install mcp config permissions allowlist autoApprove project rules gate write tool surface",
            "taxonomy": "soft_understand",
            "must_files": [
                "packages/pipeline/__main__.py",
                "packages/pipeline/rules_installer.py",
                "packages/pipeline/mcp_permissions.py",
            ],
            "must_symbols": [
                "cmd_connect",
                "install_tool",
                "write_project_tool_surface",
                "apply_permissions_to_repo_tool_surface",
            ],
        },
        {
            "id": "cursor_session",
            "task": "How does Scubiee keep two parallel Cursor chats from sharing locate state?",
            "enrich": "session isolation parallel chats packed ids pins session_store work_session CTX_MCP_SESSION_ISOLATE fail closed",
            "taxonomy": "soft_understand",
            "must_files": [
                "packages/pipeline/session_isolation.py",
                "packages/pipeline/session_store.py",
            ],
            "must_symbols": ["effective_session_id", "resolve_session"],
        },
        {
            "id": "cursor_engine",
            "task": "How does the warm engine on :8765 get started, kept alive, and used for search?",
            "enrich": "warm engine 8765 start_daemon watchdog health force_restart search_repo EngineClient DEFAULT_URL",
            "taxonomy": "soft_understand",
            "must_files": [
                "packages/pipeline/daemon.py",
                "packages/pipeline/watchdog.py",
                "packages/pipeline/client.py",
            ],
            "must_symbols": ["start_daemon", "force_restart_daemon"],
        },
    ]
    for c in cursor_cases:
        add_case(
            cases,
            cid=c["id"],
            source="cursor_ab_trials",
            task=c["task"],
            enrich=c["enrich"],
            taxonomy=c["taxonomy"],
            must_files=c["must_files"],
            must_symbols=c["must_symbols"],
            family="cursor_ab",
        )

    # --- Explicit needle / name_path calibration anchors ---
    add_case(
        cases,
        cid="anchor_literal_PHASE_LOCATE",
        source="calibration_anchor",
        task="Find the exact definition of the PHASE_LOCATE_TOOLS constant.",
        enrich="PHASE_LOCATE_TOOLS",
        taxonomy="literal_needle",
        must_files=["packages/pipeline/mcp_permissions.py"],
        must_symbols=["PHASE_LOCATE_TOOLS"],
        notes="over-use control: Grep should win",
    )
    add_case(
        cases,
        cid="anchor_literal_CTX_MCP_EXPERIMENT",
        source="calibration_anchor",
        task="Where is the env var string CTX_MCP_EXPERIMENT read for phase experiment?",
        enrich="CTX_MCP_EXPERIMENT",
        taxonomy="literal_needle",
        must_files=["packages/pipeline/mcp_locate.py"],
        must_symbols=["_phase_experiment"],
        notes="over-use control",
    )
    add_case(
        cases,
        cid="anchor_name_mcp_locate",
        source="calibration_anchor",
        task="Find the file named mcp_locate.py",
        enrich="mcp_locate.py",
        taxonomy="name_path",
        must_files=["packages/pipeline/mcp_locate.py"],
        must_symbols=[],
        notes="Glob-first control",
    )
    add_case(
        cases,
        cid="anchor_known_seed_run_pack",
        source="calibration_anchor",
        task="From seed packages/pipeline/context_trace.py::run_pack_context, get the lean heatmap neighborhood.",
        enrich="run_pack_context lean heatmap composite_v1",
        taxonomy="known_seed",
        must_files=["packages/pipeline/context_trace.py"],
        must_symbols=["run_pack_context"],
        notes="pack-first control; skip map",
    )

    # Dedupe by id
    by_id = {c["id"]: c for c in cases}
    cases = list(by_id.values())

    tax_counts: dict[str, int] = {}
    gold_n = 0
    for c in cases:
        tax_counts[c["taxonomy"]] = tax_counts.get(c["taxonomy"], 0) + 1
        if c["gold_status"] == "has_gold":
            gold_n += 1

    doc = {
        "protocol": "locate_calibration_corpus_v1",
        "phase": "A",
        "created": "2026-09-06",
        "framework": "docs/superpowers/specs/2026-09-06-locate-force-routing-research-framework.md",
        "north_star": "Minimize total_proxy (result tokens + round-trip tax) without under/over-use; integrate with Grep/Glob.",
        "n_cases": len(cases),
        "n_with_gold": gold_n,
        "taxonomy_counts": tax_counts,
        "baseline_policy": "current_ship_GATE_MCP_as_of_corpus_freeze",
        "review_notes": [
            "taxonomy_confidence=heuristic needs human spot-check before Phase B scoring claims",
            "kiro_simple/complex prompts may be abbreviated — expand from harness if Phase C needs full text",
            "anchors added for over-use (needle/name) and known_seed controls",
        ],
        "cases": cases,
    }

    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    lines = [
        "# Locate calibration — Phase A complete",
        "",
        f"**Corpus:** `{OUT.relative_to(ROOT).as_posix()}`",
        f"**Cases:** {len(cases)} · **with gold:** {gold_n}",
        "",
        "## Taxonomy counts",
        "",
        "| Class | n |",
        "|-------|---:|",
    ]
    for k, v in sorted(tax_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| `{k}` | {v} |")
    lines += [
        "",
        "## Sources",
        "",
        "- blind_map_pack_20 (+ GT)",
        "- blind_multipack_20 (+ GT)",
        "- kiro_mcp_ab simple + complex (gold files/symbols)",
        "- personal3 + cursor A/B path trials",
        "- calibration anchors (needle / name / known_seed)",
        "",
        "## Next (Phase B)",
        "",
        "Run offline arms per framework §4 with metrics `rounds`, `result_tokens`,",
        "`total_proxy`, `must_*`, `under_use`/`over_use` — start with M1/M2 and N1",
        "(density + over-use bounds) before Prefer/Require text experiments.",
        "",
        "Human: spot-check taxonomy on ~10 soft vs exact_edit labels.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"ok": True, "n": len(cases), "taxonomy": tax_counts, "out": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
