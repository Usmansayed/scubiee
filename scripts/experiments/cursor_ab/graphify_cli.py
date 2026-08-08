"""Thin Graphify CLI for Cursor-only A/B (no OpenCode).

Usage:
  python scripts/experiments/cursor_ab/graphify_cli.py query_graph "browser session lease"
  python scripts/experiments/cursor_ab/graphify_cli.py get_neighbors "BrowserSessionManager"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = ROOT / "packages"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))

DEFAULT_GRAPH = (
    Path.home()
    / ".context-engine"
    / "projects"
    / "ce_312fe25bcf4127b33feb5275c4b918ec"
    / "graph.json"
)


def _load(graph_path: Path):
    import networkx as nx
    from networkx.readwrite import json_graph

    data = json.loads(graph_path.read_text(encoding="utf-8"))
    if "links" not in data and "edges" in data:
        data = dict(data, links=data["edges"])
    data = {**data, "directed": True}
    try:
        return json_graph.node_link_graph(data, edges="links")
    except TypeError:
        return json_graph.node_link_graph(data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tool", choices=["query_graph", "get_neighbors", "get_node", "graph_stats"])
    ap.add_argument("arg", nargs="?", default="")
    ap.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--budget", type=int, default=1800)
    args = ap.parse_args()

    if not args.graph.is_file():
        print(json.dumps({"ok": False, "error": f"graph missing: {args.graph}"}))
        return 2

    from graphify import serve as gs

    G = _load(args.graph)
    if args.tool == "query_graph":
        text = gs._query_graph_text(
            G, args.arg, mode="bfs", depth=args.depth, token_budget=args.budget
        )
        print(text)
        return 0
    if args.tool == "graph_stats":
        print(
            json.dumps(
                {
                    "nodes": G.number_of_nodes(),
                    "edges": G.number_of_edges(),
                    "graph": str(args.graph),
                },
                indent=2,
            )
        )
        return 0

    # get_node / get_neighbors via label scan
    label = args.arg.strip().lower()
    matches = []
    for nid, data in G.nodes(data=True):
        lab = str(data.get("label") or nid)
        if label and label in lab.lower():
            matches.append((nid, lab, data))
    if not matches:
        print(f"No node matching {args.arg!r}")
        return 1
    nid, lab, data = matches[0]
    if args.tool == "get_node":
        print(json.dumps({"id": nid, "label": lab, "data": {k: data.get(k) for k in list(data)[:20]}}, indent=2, default=str))
        return 0
    neigh = []
    for _, v, ed in G.out_edges(nid, data=True):
        neigh.append({"to": G.nodes[v].get("label", v), "edge": dict(ed)})
    for u, _, ed in G.in_edges(nid, data=True):
        neigh.append({"from": G.nodes[u].get("label", u), "edge": dict(ed)})
    print(json.dumps({"node": lab, "neighbors": neigh[:40]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
