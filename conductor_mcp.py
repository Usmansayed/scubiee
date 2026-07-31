"""MCP stdio server: Graphify / D_rerank / R_gated A/B.

Tools:
  conductor_status
  conductor_search          — one mode
  conductor_compare         — graphify vs d_rerank
  conductor_compare_rgated  — d_rerank vs r_gated (soft router)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from conductor.service import get_engine  # noqa: E402

mcp = MCPServer(
    name="conductor-ab",
    instructions=(
        "Code retrieval A/B on frontend-mcp. "
        "For soft/vague agent queries prefer conductor_compare_rgated "
        "(d_rerank vs r_gated). For structure vs hybrid use conductor_compare "
        "(graphify vs d_rerank). Do not use host IDE semantic search for these tests."
    ),
)


@mcp.tool()
def conductor_status() -> dict[str, Any]:
    """Corpus readiness and index sizes for the conductor A/B server."""
    eng = get_engine()
    eng.ensure_loaded()
    return eng.status()


@mcp.tool()
def conductor_search(query: str, mode: str = "d_rerank", top_k: int = 8) -> dict[str, Any]:
    """Search with one retriever.

    Args:
        query: Natural language or identifier query.
        mode: graphify | d_rerank | d_floor | r_gated
        top_k: Max files (1-30).
    """
    mode_norm = (mode or "d_rerank").strip().lower()
    if mode_norm not in ("graphify", "d_rerank", "d_floor", "r_gated"):
        return {
            "error": "mode must be graphify, d_rerank, d_floor, or r_gated",
            "got": mode,
        }
    eng = get_engine()
    eng.ensure_loaded()
    return eng.search(query, mode=mode_norm, top_k=top_k)  # type: ignore[arg-type]


@mcp.tool()
def conductor_compare(query: str, top_k: int = 8) -> dict[str, Any]:
    """Compare Graphify vs D_rerank (structure vs production hybrid)."""
    eng = get_engine()
    eng.ensure_loaded()
    return eng.search(query, mode="both", top_k=top_k)


@mcp.tool()
def conductor_compare_rgated(query: str, top_k: int = 8) -> dict[str, Any]:
    """Compare D_rerank vs R_gated (production vs soft router).

    Use this for agent-style soft queries. Returns both lists + agreement
    (same_top1, jaccard, d_rerank_only, r_gated_only).
    """
    eng = get_engine()
    eng.ensure_loaded()
    return eng.search(query, mode="both_rg", top_k=top_k)


def main() -> None:
    print("Loading conductor indexes…", file=sys.stderr, flush=True)
    get_engine().ensure_loaded()
    print(json.dumps(get_engine().status()), file=sys.stderr, flush=True)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
