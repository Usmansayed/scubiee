"""Thin wrappers over Graphify serve helpers for CE MCP.

Resolves graph.json from the Context Engine project store (preferred) or
``<repo>/graphify-out/graph.json``. Returns the same plain-text shapes as
``graphify.serve`` so agents get a dense pack, not pointer soup.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import networkx as nx


def resolve_graph_json(repo: Path | str) -> Path:
    root = Path(repo).resolve()
    candidates: list[Path] = []
    try:
        from pipeline.store import PipelineStore

        store = PipelineStore(root)
        candidates.append(store.base / "graph.json")
    except Exception:  # noqa: BLE001
        pass
    candidates.append(root / "graphify-out" / "graph.json")
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError(
        f"graph.json not found for {root} (tried CE store + graphify-out/)"
    )


@lru_cache(maxsize=4)
def _load_cached(graph_path: str, mtime_ns: int) -> nx.Graph:
    from graphify.serve import _load_graph

    _ = mtime_ns  # bust cache when file changes
    return _load_graph(graph_path)


def load_repo_graph(repo: Path | str) -> tuple[nx.Graph, Path]:
    path = resolve_graph_json(repo)
    st = path.stat()
    G = _load_cached(str(path), st.st_mtime_ns)
    return G, path


def query_graph_text(
    repo: Path | str,
    question: str,
    *,
    mode: str = "bfs",
    depth: int = 3,
    token_budget: int = 2000,
    context_filter: list[str] | None = None,
) -> str:
    from graphify.serve import _query_graph_text

    G, path = load_repo_graph(repo)
    depth = max(1, min(int(depth or 3), 6))
    budget = max(200, min(int(token_budget or 2000), 4000))
    mode = "dfs" if str(mode).lower() == "dfs" else "bfs"
    body = _query_graph_text(
        G,
        question,
        mode=mode,
        depth=depth,
        token_budget=budget,
        context_filters=context_filter,
    )
    return f"[graph={path.name}]\n{body}"


def get_node_text(repo: Path | str, label: str) -> str:
    from graphify.security import sanitize_label

    G, _path = load_repo_graph(repo)
    needle = (label or "").lower().strip()
    if not needle:
        return "label required"
    matches = [
        (nid, d)
        for nid, d in G.nodes(data=True)
        if needle in (d.get("label") or "").lower() or needle == nid.lower()
    ]
    if not matches:
        return f"No node matching '{label}' found."
    nid, d = matches[0]
    return "\n".join(
        [
            f"Node: {sanitize_label(d.get('label', nid))}",
            f"  ID: {sanitize_label(nid)}",
            f"  Source: {sanitize_label(str(d.get('source_file', '')))} "
            f"{sanitize_label(str(d.get('source_location', '')))}",
            f"  Type: {sanitize_label(str(d.get('file_type', '')))}",
            f"  Community: {sanitize_label(str(d.get('community_name') or d.get('community', '')))}",
            f"  Degree: {G.degree(nid)}",
        ]
    )


def get_neighbors_text(
    repo: Path | str,
    label: str,
    *,
    relation_filter: str = "",
    token_budget: int = 2000,
) -> str:
    from graphify.build import edge_data
    from graphify.security import sanitize_label
    from graphify.serve import _cut_lines_to_budget, _find_node, find_node_ambiguity

    G, _path = load_repo_graph(repo)
    matches = _find_node(G, label)
    if not matches:
        return f"No node matching '{label}' found."
    rivals = find_node_ambiguity(G, label)
    if rivals:
        listing = "\n".join(
            f"  {G.nodes[r].get('source_file') or r}\n    id: {r}" for r in rivals
        )
        return (
            f"Ambiguous: '{label}' matches {len(rivals)} nodes in different files.\n"
            f"{listing}\n"
            "Retry with the repo-relative path or the full node id."
        )
    nid = matches[0]
    rel_filter = (relation_filter or "").lower()
    lines = [f"Neighbors of {sanitize_label(G.nodes[nid].get('label', nid))}:"]

    def _edge_at(d: dict[str, Any]) -> str:
        loc = str(d.get("source_location") or "")
        return (
            f" at={sanitize_label(str(d.get('source_file') or ''))}:{sanitize_label(loc)}"
            if loc
            else ""
        )

    for nb in G.successors(nid):
        d = edge_data(G, nid, nb)
        rel = d.get("relation", "")
        if rel_filter and rel_filter not in str(rel).lower():
            continue
        lines.append(
            f"  --> {sanitize_label(G.nodes[nb].get('label', nb))} "
            f"[{sanitize_label(str(rel))}] [{sanitize_label(str(d.get('confidence', '')))}]{_edge_at(d)}"
        )
    for nb in G.predecessors(nid):
        d = edge_data(G, nb, nid)
        rel = d.get("relation", "")
        if rel_filter and rel_filter not in str(rel).lower():
            continue
        lines.append(
            f"  <-- {sanitize_label(G.nodes[nb].get('label', nb))} "
            f"[{sanitize_label(str(rel))}] [{sanitize_label(str(d.get('confidence', '')))}]{_edge_at(d)}"
        )
    budget = max(200, min(int(token_budget or 2000), 4000))
    return _cut_lines_to_budget(
        lines, budget, "Narrow with relation_filter or use get_node for a specific symbol"
    )
