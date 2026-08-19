"""CE-backed soft search for the hybrid facade."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def default_repo() -> Path:
    env = os.environ.get("CTX_REPO") or os.environ.get("CONTEXT_ENGINE_REPO")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def _norm_query(query: str) -> str:
    return " ".join((query or "").lower().split())


def _record_search_query(repo: Path, query: str) -> str | None:
    """Track queries for recall; return advisory hint on duplicates (never block)."""
    from pipeline.session_store import load_store, save_store

    store = load_store(repo)
    thrash = store.setdefault("locate_thrash", {"soft": [], "exact": [], "seen": []})
    qn = _norm_query(query)
    duplicate = qn in (thrash.get("seen") or [])
    thrash.setdefault("soft", []).append(qn)
    thrash.setdefault("seen", []).append(qn)
    save_store(repo, store)
    if not duplicate:
        return None
    return (
        "Advisory: this search query already ran. Use get_code_snippet / graph tools on "
        "prior hits — only search again if the topic changed or prior results were empty."
    )


def soft_search(
    repo: Path,
    query: str,
    *,
    k: int = 8,
    fetch: bool = False,
    max_chars: int = 1200,
) -> dict[str, Any]:
    """Run CE dense/fused locate; return facade-shaped payload."""
    usage_hint = _record_search_query(repo, query)

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
            "get_code_snippet once, then EDIT."
        )
    else:
        nxt = "No hits — sharpen the query once, then try graph/snippet paths."

    out: dict[str, Any] = {
        "ok": True,
        "backend": "ce",
        "tool": "search",
        "query": query,
        "count": len(results),
        "results": results,
        "next": nxt,
    }
    if usage_hint:
        out["usage_hint"] = usage_hint
    return out


def soft_search_json(repo: Path, query: str, **kwargs: Any) -> str:
    return json.dumps(soft_search(repo, query, **kwargs), indent=2, default=str)


def dumps(obj: Any, **kwargs: Any) -> str:
    return json.dumps(obj, indent=2, default=str, **kwargs)
