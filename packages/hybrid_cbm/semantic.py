"""CE-backed soft search for the hybrid facade."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_SOFT_CAP = 4


def default_repo() -> Path:
    env = os.environ.get("CTX_REPO") or os.environ.get("CONTEXT_ENGINE_REPO")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def _norm_query(query: str) -> str:
    return " ".join((query or "").lower().split())


def thrash_gate(repo: Path, query: str) -> dict[str, Any] | None:
    """Refuse duplicate / over-budget soft searches (nav-style caps)."""
    from pipeline.session_store import load_store, save_store

    store = load_store(repo)
    thrash = store.setdefault("locate_thrash", {"soft": [], "exact": [], "seen": []})
    soft = thrash.setdefault("soft", [])
    seen = thrash.setdefault("seen", [])
    qn = _norm_query(query)
    if qn in seen:
        return {
            "ok": False,
            "tool": "search",
            "error": f"duplicate search blocked: {query[:160]}",
            "thrash_blocked": True,
            "hint": "Same query already ran. get_code_snippet / edit — do not re-search.",
            "next": "snippet or edit",
        }
    if len(soft) >= _SOFT_CAP:
        return {
            "ok": False,
            "tool": "search",
            "error": f"soft search budget exhausted ({_SOFT_CAP}/{_SOFT_CAP})",
            "thrash_blocked": True,
            "hint": "soft≤4/task. Use graph/snippet and EDIT.",
            "next": "edit",
        }
    soft.append(qn)
    seen.append(qn)
    save_store(repo, store)
    return None


def soft_search(
    repo: Path,
    query: str,
    *,
    k: int = 8,
    fetch: bool = False,
    max_chars: int = 1200,
) -> dict[str, Any]:
    """Run CE dense/fused locate; return facade-shaped payload."""
    blocked = thrash_gate(repo, query)
    if blocked is not None:
        return blocked

    from pipeline.locate import _read_excerpt, _search_hits

    hits = _search_hits(repo, query, top_k=k)
    results: list[dict[str, Any]] = []
    for rank, h in enumerate(hits[:k], 1):
        f = h.get("file")
        item: dict[str, Any] = {
            "rank": rank,
            "file": f,
            "start_line": h.get("start_line"),
            "end_line": h.get("end_line"),
            "score": round(float(h.get("score") or 0.0), 4),
            "why": h.get("why") or "",
        }
        if fetch and f:
            ex = _read_excerpt(
                repo,
                str(f),
                int(h.get("start_line") or 0),
                int(h.get("end_line") or 0),
                max_chars=max_chars,
            )
            item["code"] = ex.get("excerpt") or ex.get("text") or ""
        results.append(item)

    if results:
        nxt = (
            "If structure needed: search_graph / trace_path; else "
            "get_code_snippet once, then EDIT. soft≤2/topic."
        )
    else:
        nxt = "no hits — one sharper soft query or search_graph(name_pattern)."

    return {
        "ok": True,
        "tool": "search",
        "mode": "soft",
        "backend": "ce",
        "query": query,
        "k": k,
        "fetch": fetch,
        "count": len(results),
        "results": results,
        "next": nxt,
    }


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)
