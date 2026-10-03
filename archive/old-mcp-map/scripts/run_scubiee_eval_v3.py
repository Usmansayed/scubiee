#!/usr/bin/env python3
"""Re-run scubiee MCP agent evaluation v3 (no daemon hang).

Uses local helpers + phase tool fns with ensure_daemon patched.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

SESSION = "scubiee-eval-3"
REPO = ROOT
PID = "ce_36dc8f7856b3b6b994ee8624b36f881b"


def _load_tools():
    os.environ["CTX_MCP_SURFACE"] = "phase"
    os.environ["CTX_REPO"] = str(REPO)
    import mcp  # noqa: F401
    import pipeline.mcp_locate as ml

    ml._is_repo_managed = lambda: True  # type: ignore[method-assign]
    return ml, {
        n: ml.create_mcp(name="eval")._tool_manager._tools[n].fn
        for n in ml.create_mcp(name="eval")._tool_manager._tools
    }


def _call(fn, **kw) -> dict[str, Any]:
    kw.setdefault("session_id", SESSION)
    kw.setdefault("project_id", PID)
    raw = fn(**kw)
    return json.loads(raw) if isinstance(raw, str) else raw


def main() -> int:
    ml, tools = _load_tools()
    from pipeline.capability import file_outline, read_python_source
    from pipeline.mcp_locate import _read_line_range, _resolve_symbol_lines, _find_repo_files
    from pipeline.session_store import clear_store, expand as store_expand

    clear_store(REPO, session_id=SESSION)
    results: list[dict[str, Any]] = []

    def record(test: str, ok: bool, **extra: Any) -> None:
        results.append({"test": test, "ok": ok, **extra})
        print(f"[{'PASS' if ok else 'FAIL'}] {test}" + (f" — {extra}" if extra else ""))

    # ---- surface ----
    record("phase_has_expand", "expand" in tools, tools=sorted(tools.keys()))
    record(
        "phase_tool_set",
        {"gate", "map", "focus", "grep", "glob", "workspace", "expand", "status"}.issubset(tools.keys()),
    )

    # ---- P0: BOM outline (local file_outline) ----
    bom_files = [
        "packages/pipeline/embedder.py",
        "packages/pipeline/mcp_locate.py",
        "packages/pipeline/sync_loop.py",
        "packages/pipeline/ce_service.py",
        "packages/pipeline/daemon.py",
    ]
    for path in bom_files:
        syms = file_outline(REPO, path)
        record(f"outline_bom:{Path(path).name}", len(syms) > 0, count=len(syms))
        # BOM stripped from source read
        src = read_python_source(REPO / path)
        record(f"bom_stripped:{Path(path).name}", not src.startswith("\ufeff"))

    # ---- P0: symbol resolution ----
    acq = _resolve_symbol_lines(REPO, "packages/pipeline/fair_schedule.py", "FairEmbedScheduler.acquire")
    record("symbol_acquire_lines", acq is not None and acq[0] >= 46, range=acq)
    bud = _resolve_symbol_lines(REPO, "packages/pipeline/resources.py", "ResourceManager.budget")
    record("symbol_budget_lines", bud is not None and bud[0] >= 248, range=bud)

    # ---- P0: truncation pagination ----
    trunc = _read_line_range(REPO, "packages/pipeline/indexer.py", 105, 529, 2000)
    record(
        "truncation_next_start_line",
        bool(trunc.get("next_start_line")),
        next_start_line=trunc.get("next_start_line"),
        lines_returned=trunc.get("lines_returned"),
    )

    # ---- P0: already_in_session + expand (via focus tool, daemon patched) ----
    noop_daemon = patch("pipeline.daemon.ensure_daemon", return_value={"ok": True})
    with noop_daemon:
        first = _call(tools["focus"], target="packages/pipeline/resources.py", start_line=248, end_line=310, mode="span", max_chars=12000)
        second = _call(tools["focus"], target="packages/pipeline/resources.py", start_line=248, end_line=310, mode="span", max_chars=12000)
        handle = first.get("handle")
        expanded = _call(tools["expand"], handle=handle, max_chars=12000) if handle else {}
    record(
        "already_in_session_strips_code",
        second.get("status") == "already_in_session" and not (second.get("code") or "").strip(),
        status=second.get("status"),
    )
    exp_code = expanded.get("text") or expanded.get("code") or expanded.get("body") or ""
    record("expand_restores_body", "def budget" in exp_code, code_len=len(exp_code))

    # ---- focus symbol via tool (needs engine client patched) ----
    class _OutlineClient:
        def healthy(self):
            return True

        def outline(self, path, **_k):
            return {"ok": True, "symbols": file_outline(REPO, path)}

        def note_locate(self, **_k):
            pass

        def status(self, *_a, **_k):
            return {"ok": True}

    with noop_daemon, patch("pipeline.mcp_locate._client_for", return_value=_OutlineClient()):
        sym_focus = _call(
            tools["focus"],
            target="packages/pipeline/fair_schedule.py",
            query="FairEmbedScheduler.acquire",
            mode="span",
            max_chars=12000,
        )
    record(
        "focus_symbol_acquire",
        int(sym_focus.get("start_line") or 0) >= 46 and "def acquire" in (sym_focus.get("code") or ""),
        start=sym_focus.get("start_line"),
        focus_ok=sym_focus.get("ok"),
    )

    # ---- subsystem spans ----
    keeper = _read_line_range(REPO, "packages/pipeline/sync_loop.py", 612, 679, 12000)
    record("keeper_tick_full", "def keeper_tick" in keeper.get("excerpt", ""), truncated=keeper.get("truncated"))
    embed = _read_line_range(REPO, "packages/pipeline/embedder.py", 600, 833, 12000)
    record("embed_many_full", "def embed_many" in embed.get("excerpt", ""), truncated=embed.get("truncated"))

    # ---- glob worktrees ----
    found, _ = _find_repo_files(REPO, "**/sync_loop.py", 10)
    record("glob_no_worktrees", not any(".worktrees" in f for f in found), files=found)

    # ---- grep (local scan — no daemon) ----
    from pipeline.capability import grep_scan

    ge = grep_scan(REPO, "class Embedder", max_hits=5)
    gg = grep_scan(REPO, "def _extract_generic", max_hits=5)
    record("grep_embedder", any("embedder.py" in h.get("file", "") for h in ge.get("hits", [])))
    record("grep_extract_generic_engine", any("engine.py" in h.get("file", "") for h in gg.get("hits", [])))

    # ---- map ranking (skip if index cold — optional smoke) ----
    try:
        from pipeline.locate import _search_hits

        code_hits = _search_hits(REPO, "keeper_tick budget sync", top_k=3)
        code_top = (code_hits[0].get("file") if code_hits else "") or ""
        record("map_code_vocab_ranks_sync_loop", "sync_loop.py" in str(code_top), rank1=code_top)
    except Exception as exc:  # noqa: BLE001
        record("map_code_vocab_ranks_sync_loop", False, error=str(exc)[:80])

    # ---- missing file ----
    miss = _read_line_range(REPO, "packages/pipeline/nonexistent_file.py", 1, 10, 1000)
    record("missing_file_clear_error", miss.get("ok") is False and "not found" in str(miss.get("error", "")).lower())

    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    print(f"\n=== {passed}/{total} checks passed ===")
    out = ROOT / "docs" / "scubiee-mcp-eval-v3-results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
