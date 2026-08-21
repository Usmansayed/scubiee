"""Retrieval tools for the Context Agent (thin wrappers over CE + Graphify)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


class BackendResponseError(RuntimeError):
    """Raised when a path-bearing CE request is rejected by the daemon."""

    def __init__(self, response: dict[str, Any]):
        self.response = response
        super().__init__(
            str(response.get("error") or response.get("status") or "backend request failed")
        )


_SUCCESS_STATUSES = {
    "ok",
    "ready",
    "active",
    "activated",
    "success",
    "complete",
    "completed",
    "idle",
    "registered",
    "indexed",
    "published",
}


def _backend_failed(response: Any) -> bool:
    """Return True for explicit and implicit daemon failure states.

    Some CE endpoints return a transient state such as ``warming`` without an
    ``ok`` field. Data-bearing CE responses guarantee ``ok:true`` on success,
    so an absent or false success marker must be treated as a failure instead
    of an empty result.
    """
    if not isinstance(response, dict):
        return True
    if response.get("ok") is not True:
        return True
    if response.get("error"):
        return True
    if response.get("ready") is False:
        return True
    status = str(response.get("status") or "").strip().lower()
    return bool(status and status not in _SUCCESS_STATUSES)


def _copy_backend_metadata(out: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "error",
        "status",
        "http_status",
        "state",
        "ready",
        "warm_state",
        "sync_state",
        "sync_status",
        "root",
        "repo",
        "project_id",
        "pause_reason",
        "hint",
    ):
        if key in out and out[key] is not None:
            result[key] = out[key]
    return result


def _client(repo: Path | None = None):
    from pipeline.client import EngineClient
    from pipeline.daemon import ensure_daemon

    ensure_daemon(repo, force_if_hung=True) if repo else ensure_daemon(force_if_hung=True)
    return EngineClient(workspace_path=str(repo) if repo else None)


def tool_search_code(repo: Path, query: str, top_k: int = 6) -> dict[str, Any]:
    top_k = max(1, min(int(top_k or 6), 8))
    out = _client(repo).search(query, top_k=top_k, path=str(repo))
    hits = []
    for h in (out.get("hits") or [])[:top_k]:
        hits.append(
            {
                "file": h.get("file") or h.get("path"),
                "score": h.get("score"),
                "start_line": h.get("start_line"),
                "end_line": h.get("end_line"),
                "why": (h.get("why") or "")[:160],
                "source": h.get("source"),
            }
        )
    result = {"ok": not _backend_failed(out), "tool": "search_code", "hits": hits}
    return _copy_backend_metadata(out, result)


def tool_grep_code(
    repo: Path, pattern: str, glob: str = "*.py", max_hits: int = 12
) -> dict[str, Any]:
    max_hits = max(1, min(int(max_hits or 12), 20))
    out = _client(repo).grep(pattern, glob=glob or "*.py", max_hits=max_hits, path=str(repo))
    hits = out.get("hits") or out.get("matches") or []
    slim = []
    for h in (hits if isinstance(hits, list) else [])[:max_hits]:
        if isinstance(h, dict):
            slim.append(
                {
                    "file": h.get("file") or h.get("path"),
                    "line": h.get("line") or h.get("start_line"),
                    "text": (h.get("text") or h.get("preview") or "")[:140],
                }
            )
    result = {"ok": not _backend_failed(out), "tool": "grep_code", "hits": slim}
    return _copy_backend_metadata(out, result)


def tool_query_graph(repo: Path, question: str, token_budget: int = 1200) -> dict[str, Any]:
    from pipeline.graphify_mcp_tools import query_graph_text

    budget = max(400, min(int(token_budget or 1200), 2000))
    text = query_graph_text(repo, question, token_budget=budget)
    # Cap tool result size so small model context stays sane
    if len(text) > 4500:
        text = text[:4500] + "\n...[truncated]"
    return {"ok": True, "tool": "query_graph", "text": text}


def tool_get_node(repo: Path, label: str) -> dict[str, Any]:
    from pipeline.graphify_mcp_tools import get_node_text

    return {"ok": True, "tool": "get_node", "text": get_node_text(repo, label)}


def tool_get_neighbors(repo: Path, label: str) -> dict[str, Any]:
    from pipeline.graphify_mcp_tools import get_neighbors_text

    text = get_neighbors_text(repo, label, token_budget=1000)
    if len(text) > 3500:
        text = text[:3500] + "\n...[truncated]"
    return {"ok": True, "tool": "get_neighbors", "text": text}


def tool_read_span(
    repo: Path,
    path: str,
    start_line: int = 0,
    end_line: int = 0,
    max_chars: int = 500,
) -> dict[str, Any]:
    max_chars = max(120, min(int(max_chars or 500), 700))
    out = _client(repo).read_span(
        path,
        start_line=start_line or None,
        end_line=end_line or None,
        max_chars=max_chars,
        avoid=["figma", "seo", "dribbble"],
        repo=str(repo),
    )
    if isinstance(out, dict):
        # slim
        text = out.get("text") or out.get("span") or out.get("content") or ""
        if isinstance(text, str) and len(text) > max_chars:
            text = text[:max_chars]
        result = {
            "ok": not _backend_failed(out),
            "tool": "read_span",
            "path": path,
            "start_line": out.get("start_line") or start_line,
            "end_line": out.get("end_line") or end_line,
            "text": text if text else out,
        }
        return _copy_backend_metadata(out, result)
    return {"ok": True, "tool": "read_span", "result": out}


TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "search_code": lambda repo, args: tool_search_code(
        repo, str(args.get("query") or ""), int(args.get("top_k") or 6)
    ),
    "grep_code": lambda repo, args: tool_grep_code(
        repo,
        str(args.get("pattern") or ""),
        str(args.get("glob") or "*.py"),
        int(args.get("max_hits") or 12),
    ),
    "query_graph": lambda repo, args: tool_query_graph(
        repo, str(args.get("question") or ""), int(args.get("token_budget") or 1200)
    ),
    "get_node": lambda repo, args: tool_get_node(repo, str(args.get("label") or "")),
    "get_neighbors": lambda repo, args: tool_get_neighbors(
        repo, str(args.get("label") or "")
    ),
    "read_span": lambda repo, args: tool_read_span(
        repo,
        str(args.get("path") or ""),
        int(args.get("start_line") or 0),
        int(args.get("end_line") or 0),
        int(args.get("max_chars") or 500),
    ),
}


def dispatch_tool(repo: Path, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {"ok": False, "error": f"unknown tool {name}", "allowed": list(TOOL_HANDLERS)}
    try:
        return handler(repo, args or {})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "tool": name, "error": str(exc)}


def dump_tool_result(result: dict[str, Any], *, limit: int = 3500) -> str:
    text = json.dumps(result, indent=2, default=str)
    if len(text) > limit:
        return text[:limit] + "\n...[truncated]"
    return text
