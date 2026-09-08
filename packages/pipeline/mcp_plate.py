"""Assemble a how-X-works \"plate\" from BM25 + dense + Graphify — no LLM.

Uses the three core channels already in Context Engine:
  1. Hybrid retrieve (BM25 + dense via Conductor / ``_search_hits``)
  2. Graphify affinity seeds + neighbor_files expand
  3. Optional Graphify BFS text sketch (structured, not generated prose)

The agent gets hubs, connections, an ordered flow, and short code peeks —
enough to see how a concern is wired without a summarizing model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def _span_file(s: dict[str, Any]) -> str:
    return str(s.get("path") or s.get("file") or "").replace("\\", "/")


def _span_code(s: dict[str, Any], max_chars: int) -> str:
    return str(s.get("text") or s.get("excerpt") or s.get("code") or "")[:max_chars]


def assemble_plate(
    repo: Path,
    query: str,
    *,
    search_hits: Callable[[Path, str, int], list[dict[str, Any]]],
    read_excerpt: Callable[..., dict[str, Any]],
    graph_neighbors: Callable[..., dict[str, Any]],
    query_graph: Callable[..., dict[str, Any]] | None = None,
    graph_sketch: Callable[[Path, str], str] | None = None,
    k_hubs: int = 4,
    k_connections: int = 6,
    max_chars: int = 600,
) -> dict[str, Any]:
    """Build a plate payload for ``query`` (how-X-works / relatedness)."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query required"}

    hits = search_hits(repo, q, max(k_hubs, 3))
    hubs: list[dict[str, Any]] = []
    seed_files: list[str] = []
    for rank, h in enumerate(hits[:k_hubs], 1):
        file_s = str(h.get("file") or "").replace("\\", "/")
        if not file_s:
            continue
        start_l = int(h.get("start_line") or 0)
        end_l = int(h.get("end_line") or 0)
        code = ""
        try:
            ex = read_excerpt(repo, file_s, start_l, end_l, max_chars=max_chars)
            code = str(ex.get("excerpt") or ex.get("text") or "")[:max_chars]
            start_l = int(ex.get("start_line") or start_l or 0)
            end_l = int(ex.get("end_line") or end_l or 0)
        except Exception:  # noqa: BLE001
            code = ""
        hubs.append(
            {
                "rank": rank,
                "file": file_s,
                "start_line": start_l,
                "end_line": end_l,
                "score": round(float(h.get("score") or 0.0), 4),
                "why": str(h.get("why") or "")[:160],
                "role": "hub",
                "channel": "bm25+dense",
                "code": code,
            }
        )
        if file_s not in seed_files:
            seed_files.append(file_s)

    connections: list[dict[str, Any]] = []
    seen_to: set[str] = set(seed_files)
    hub_set = set(seed_files)

    def _add_connection(
        *,
        fr: str,
        to_f: str,
        via: str,
        start_line: Any = None,
        end_line: Any = None,
        why: str = "",
        code: str = "",
    ) -> None:
        if not to_f or to_f in seen_to:
            return
        if len(connections) >= k_connections:
            return
        seen_to.add(to_f)
        connections.append(
            {
                "from": fr,
                "to": to_f,
                "via": via,
                "channel": "graph",
                "start_line": start_line,
                "end_line": end_line,
                "why": (why or via)[:120],
                "code": code[: min(400, max_chars)],
            }
        )

    connection_errors: list[str] = []

    if seed_files:
        try:
            gn = graph_neighbors(
                seed_files,
                query=q,
                keep=k_connections,
                max_chars=min(400, max_chars),
                repo=str(repo),
            )
            for s in gn.get("spans") or []:
                to_f = _span_file(s)
                _add_connection(
                    fr=seed_files[0],
                    to_f=to_f,
                    via="graph_neighbor",
                    start_line=s.get("start_line"),
                    end_line=s.get("end_line"),
                    why=str(s.get("label") or s.get("why") or "neighbor"),
                    code=_span_code(s, min(400, max_chars)),
                )
        except Exception as exc:  # noqa: BLE001
            connection_errors.append(f"graph_neighbors: {exc}"[:160])

    if query_graph is not None:
        try:
            qg = query_graph(
                q,
                keep=min(4, k_hubs),
                neighbor_keep=min(4, k_connections),
                max_chars=min(400, max_chars),
                repo=str(repo),
            )
            for s in qg.get("spans") or []:
                to_f = _span_file(s)
                label = str(s.get("label") or s.get("why") or "")
                via = "graph_seed" if "seed" in label else "graph_affinity"
                if to_f in hub_set:
                    continue
                fr = seed_files[0] if seed_files else to_f
                _add_connection(
                    fr=fr,
                    to_f=to_f,
                    via=via,
                    start_line=s.get("start_line"),
                    end_line=s.get("end_line"),
                    why=label or via,
                    code=_span_code(s, min(400, max_chars)),
                )
        except Exception as exc:  # noqa: BLE001
            connection_errors.append(f"query_graph: {exc}"[:160])

    flow: list[str] = []
    for h in hubs:
        f = h["file"]
        if f not in flow:
            flow.append(f)
    for c in connections:
        to_f = str(c.get("to") or "")
        if to_f and to_f not in flow:
            flow.append(to_f)

    sketch = ""
    if graph_sketch is not None:
        try:
            sketch = (graph_sketch(repo, q) or "")[:2500]
        except Exception as exc:  # noqa: BLE001
            sketch = f"[graph_sketch unavailable: {exc}]"[:200]

    weak = not hubs or (hubs and float(hubs[0].get("score") or 0) < 5.0)
    return {
        "ok": True,
        "tool": "plate",
        "query": q,
        "channels": "bm25+dense+graph",
        "hubs": hubs,
        "connections": connections,
        "connection_errors": connection_errors,
        "flow": flow,
        "graph_sketch": sketch or None,
        "weak_match": weak,
        "legend": {
            "hubs": "Hybrid BM25+dense hits (where the concern lives)",
            "connections": "Graphify neighbor / affinity links around hubs",
            "flow": "Read order: hubs then graph-linked files",
            "graph_sketch": "BFS/DFS pack from Graphify (no LLM)",
        },
    }
