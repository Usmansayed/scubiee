"""CLI graphify queries for Cursor subagent A/B (no OpenCode).

Usage:
  python graphify_cli.py query "browser session vanished agent guidance"
  python graphify_cli.py neighbors "src/navigation/mcp/agent_guidance.py" --depth 2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GRAPH = (
    Path.home()
    / ".context-engine"
    / "projects"
    / "ce_312fe25bcf4127b33feb5275c4b918ec"
    / "graph.json"
)

if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["query", "neighbors", "stats"])
    ap.add_argument("arg", nargs="?", default="")
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--budget", type=int, default=2000)
    ap.add_argument("--graph", default=str(GRAPH))
    args = ap.parse_args()

    from graphify.serve import _load_graph, _query_graph_text

    G = _load_graph(args.graph)
    if args.cmd == "stats":
        print(json.dumps({"nodes": G.number_of_nodes(), "edges": G.number_of_edges()}))
        return 0
    if args.cmd == "query":
        text = _query_graph_text(G, args.arg, depth=args.depth, token_budget=args.budget)
        print(text)
        return 0
    if args.cmd == "neighbors":
        # label/path lookup via query_graph with narrow question
        q = f"neighbors of {args.arg} dispatch session browser"
        text = _query_graph_text(G, q, depth=args.depth, token_budget=args.budget)
        print(text)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
