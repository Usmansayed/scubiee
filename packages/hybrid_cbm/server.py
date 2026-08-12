"""FastMCP entry: CE soft search + CBM graph tools."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated, Any

from hybrid_cbm.instructions import SERVER_INSTRUCTIONS
from hybrid_cbm.proxy import (
    ensure_indexed,
    make_proxy,
    resolve_project_name,
)
from hybrid_cbm.semantic import default_repo, dumps, soft_search

try:
    from mcp.server.fastmcp import FastMCP
    from pydantic import Field
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore
    Field = None  # type: ignore


def _err(tool: str, error: str, **extra: Any) -> str:
    payload: dict[str, Any] = {"ok": False, "tool": tool, "error": error, **extra}
    return dumps(payload)


def create_mcp(name: str = "cbm_ce") -> Any:
    if FastMCP is None:
        raise RuntimeError("pip install 'context-engine[mcp]' (mcp package required)")

    mcp = FastMCP(name, instructions=SERVER_INSTRUCTIONS)
    proxy = make_proxy()

    def _tool(tool_name: str, title: str, fn) -> None:
        mcp.tool(
            name=tool_name,
            annotations={
                "title": title,
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )(fn)

    def search_impl(
        query: Annotated[str, Field(description="NL soft/meaning query (CE embeddings).")],
        k: Annotated[int, Field(description="How many hits.")] = 8,
        fetch: Annotated[bool, Field(description="Inline hit bodies.")] = False,
        max_chars: Annotated[int, Field(description="Per-hit body budget when fetch.")] = 1200,
    ) -> str:
        """Soft semantic locate via Context Engine. Prefer over Grep."""
        try:
            return dumps(
                soft_search(
                    default_repo(),
                    query,
                    k=max(1, min(int(k), 25)),
                    fetch=bool(fetch),
                    max_chars=int(max_chars),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _err("search", str(exc), hint="Check status()/CTX_REPO; ensure CE index is warm.")

    def search_graph_impl(
        name_pattern: Annotated[
            str, Field(description="Regex for symbol names, e.g. .*Handler.*")
        ] = ".*",
        label: Annotated[str, Field(description="Optional CBM label filter (Function, …).")] = "",
        project: Annotated[str, Field(description="CBM project name (default: this repo).")] = "",
        limit: Annotated[int, Field(description="Max results.")] = 20,
    ) -> str:
        """Structural graph search via stock CBM."""
        if not proxy.available():
            return _err(
                "search_graph",
                "CBM binary not found",
                hint="Install codebase-memory-mcp or set CTX_CBM_BIN",
            )
        repo = default_repo()
        proj = (project or "").strip() or resolve_project_name(proxy, repo)
        args: dict[str, Any] = {
            "project": proj,
            "name_pattern": name_pattern or ".*",
            "limit": max(1, min(int(limit), 100)),
        }
        if label.strip():
            args["label"] = label.strip()
        out = proxy.call("search_graph", args)
        out.setdefault("backend", "cbm")
        out.setdefault("project", proj)
        return dumps(out)

    def trace_path_impl(
        function_name: Annotated[str, Field(description="Function/symbol to trace.")],
        direction: Annotated[str, Field(description="callers|callees|both")] = "both",
        project: Annotated[str, Field(description="CBM project name (default: this repo).")] = "",
    ) -> str:
        """Caller/callee paths via stock CBM."""
        if not proxy.available():
            return _err(
                "trace_path",
                "CBM binary not found",
                hint="Install codebase-memory-mcp or set CTX_CBM_BIN",
            )
        repo = default_repo()
        proj = (project or "").strip() or resolve_project_name(proxy, repo)
        out = proxy.call(
            "trace_path",
            {
                "project": proj,
                "function_name": function_name,
                "direction": direction or "both",
            },
        )
        out.setdefault("backend", "cbm")
        out.setdefault("project", proj)
        return dumps(out)

    def get_code_snippet_impl(
        qualified_name: Annotated[
            str, Field(description="CBM qualified name from search_graph / trace_path.")
        ],
        project: Annotated[str, Field(description="CBM project name (default: this repo).")] = "",
    ) -> str:
        """Open one known symbol body via stock CBM (once per target)."""
        if not proxy.available():
            return _err(
                "get_code_snippet",
                "CBM binary not found",
                hint="Install codebase-memory-mcp or set CTX_CBM_BIN",
            )
        repo = default_repo()
        proj = (project or "").strip() or resolve_project_name(proxy, repo)
        out = proxy.call(
            "get_code_snippet",
            {"project": proj, "qualified_name": qualified_name},
        )
        out.setdefault("backend", "cbm")
        out.setdefault("project", proj)
        if out.get("ok"):
            out.setdefault("next", "Edit now — do not re-fetch this qualified_name.")
        return dumps(out)

    def status_impl() -> str:
        """Health: CE repo + CBM binary/project."""
        repo = default_repo()
        cbm_ok = proxy.available()
        project = None
        cbm_detail: dict[str, Any] = {}
        if cbm_ok:
            project = resolve_project_name(proxy, repo)
            listed = proxy.call("list_projects", {})
            cbm_detail = {
                "binary": proxy.binary_path(),
                "project": project,
                "list_ok": bool(listed.get("ok")),
                "project_count": len(listed.get("projects") or [])
                if isinstance(listed.get("projects"), list)
                else None,
            }
        else:
            cbm_detail = {
                "binary": None,
                "hint": "Install codebase-memory-mcp or set CTX_CBM_BIN / CBM_BIN",
            }
        return dumps(
            {
                "ok": True,
                "tool": "status",
                "facade": "cbm_ce",
                "repo": str(repo),
                "ce": {"repo": str(repo), "search": "pipeline.locate._search_hits"},
                "cbm": {"available": cbm_ok, **cbm_detail},
                "tools": [
                    "search",
                    "search_graph",
                    "trace_path",
                    "get_code_snippet",
                    "status",
                ],
            }
        )

    _tool("search", "CE soft search", search_impl)
    _tool("search_graph", "CBM structural search", search_graph_impl)
    _tool("trace_path", "CBM call path", trace_path_impl)
    _tool("get_code_snippet", "CBM snippet", get_code_snippet_impl)
    _tool("status", "Hybrid health", status_impl)
    return mcp


def main() -> None:
    # Optional one-shot index when CTX_CBM_AUTO_INDEX=1 (trial harness also indexes).
    if (os.environ.get("CTX_CBM_AUTO_INDEX") or "").strip() in {"1", "true", "yes"}:
        proxy = make_proxy()
        if proxy.available():
            ensure_indexed(proxy, default_repo())
    mcp = create_mcp()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
