"""Graphify as one structural layer — mapped onto TraceNodes."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from graphify.extract import collect_files, extract
from parse_harness.graphify_adapter import graphify_to_repo_ir
from trace_lab.ast_graph import (
    CALL_W,
    CALLED_BY_W,
    CONTAINS_W,
    IMPORTED_BY_W,
    IMPORTS_W,
    AstTraceGraph,
)
from trace_lab.types import TraceEdge, TraceNode

_CODE_SUFFIX = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}

_REL_W = {
    "calls": CALL_W,
    "imports": IMPORTS_W,
    "imports_from": IMPORTS_W,
    "contains": CONTAINS_W,
    "method": CONTAINS_W,
    "inherits": 0.6,
    "implements": 0.6,
}


def _map_symbol(
    file: str,
    name: str,
    line: int | None,
    nodes: dict[str, TraceNode],
) -> str | None:
    file = file.replace("\\", "/")
    in_file = [n for n in nodes.values() if n.file == file]
    if not in_file:
        return None
    exact = [n for n in in_file if n.symbol == name]
    if exact:
        return exact[0].id
    suffix = [n for n in in_file if n.symbol.endswith("." + name) or n.symbol == name]
    if len(suffix) == 1:
        return suffix[0].id
    if line is not None:
        covering = [n for n in in_file if n.start_line <= line <= n.end_line and n.kind != "class"]
        if covering:
            covering.sort(key=lambda n: (n.end_line - n.start_line, n.start_line))
            return covering[0].id
    if suffix:
        return suffix[0].id
    return None


def _code_paths(root: Path) -> list[Path]:
    return [
        p
        for p in collect_files(root, root=root)
        if p.suffix.lower() in _CODE_SUFFIX and "cases" not in p.parts
    ]


def _clean_label(label: str) -> str:
    name = (label or "").strip()
    if name.startswith("."):
        name = name[1:]
    if name.endswith("()"):
        name = name[:-2]
    return name.strip()


def load_store_graphify_graph(
    root: Path,
    nodes: dict[str, TraceNode],
    *,
    graph_json: Path | None = None,
) -> AstTraceGraph | None:
    """Project the init/index ``graph.json`` onto TraceNode ids (fast path).

    Prefer this over :func:`build_graphify_graph` — init already ran Graphify.
    """
    root = root.resolve()
    path = graph_json
    if path is None:
        try:
            from pipeline.project_id import resolve_project

            ref = resolve_project(root)
            if ref is not None:
                cand = Path(ref.store_dir) / "graph.json"
                if cand.is_file():
                    path = cand
        except Exception:  # noqa: BLE001
            path = None
        if path is None:
            for cand in (root / "graphify-out" / "graph.json",):
                if cand.is_file():
                    path = cand
                    break
    if path is None or not Path(path).is_file():
        return None

    import json
    from graphify.serve import _load_graph

    # Prefer networkx load (handles communities); fall back to raw JSON.
    try:
        G = _load_graph(str(path))
        node_iter = (
            (
                nid,
                {
                    "label": data.get("label"),
                    "source_file": data.get("source_file"),
                    "source_location": data.get("source_location"),
                    "file_type": data.get("file_type"),
                },
            )
            for nid, data in G.nodes(data=True)
        )
        link_iter = (
            {
                "source": u,
                "target": v,
                "relation": (edata or {}).get("relation") or "related",
                "weight": float((edata or {}).get("weight") or 1.0),
            }
            for u, v, edata in G.edges(data=True)
        )
    except Exception:  # noqa: BLE001
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        node_iter = ((n.get("id"), n) for n in (raw.get("nodes") or []) if n.get("id"))
        link_iter = raw.get("links") or []

    gfy_to_nid: dict[str, str] = {}
    for gid, data in node_iter:
        if not gid:
            continue
        ftype = str(data.get("file_type") or "code")
        if ftype not in {"code", "", "None", "none"}:
            # skip rationale / doc nodes
            if ftype == "rationale":
                continue
        src = str(data.get("source_file") or "").replace("\\", "/").lstrip("./")
        if not src:
            continue
        loc = str(data.get("source_location") or "")
        line = None
        if loc.upper().startswith("L") and loc[1:].isdigit():
            line = int(loc[1:])
        name = _clean_label(str(data.get("label") or ""))
        mapped = _map_symbol(src, name, line, nodes) if name else None
        if mapped is None and line is not None:
            mapped = _map_symbol(src, "", line, nodes)
        if mapped:
            gfy_to_nid[str(gid)] = mapped

    edges: list[TraceEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def add(src: str, dst: str, rel: str, w: float) -> None:
        if src == dst:
            return
        key = (src, dst, rel)
        if key in seen:
            return
        seen.add(key)
        edges.append(TraceEdge(src, dst, rel, w))

    for link in link_iter:
        src = gfy_to_nid.get(str(link.get("source") or ""))
        dst = gfy_to_nid.get(str(link.get("target") or ""))
        if not src or not dst:
            continue
        rel = str(link.get("relation") or "related")
        if rel in {"rationale_for"}:
            continue
        w = _REL_W.get(rel, 0.4)
        try:
            w = max(w, float(link.get("weight") or w) * 0.5)
        except (TypeError, ValueError):
            pass
        add(src, dst, rel, w)
        if rel == "calls":
            add(dst, src, "called_by", CALLED_BY_W)
        elif rel in {"imports", "imports_from"}:
            add(dst, src, "imported_by", IMPORTED_BY_W)
        elif rel == "method":
            # class -> method; also treat as contains for hopability
            add(src, dst, "contains", CONTAINS_W)

    if not edges:
        return None
    return AstTraceGraph(nodes, edges)


def build_graphify_graph(
    root: Path,
    nodes: dict[str, TraceNode],
    *,
    cache_root: Path | None = None,
) -> AstTraceGraph:
    """Parse with Graphify and project edges onto the AST TraceNode id space."""
    root = root.resolve()
    paths = _code_paths(root)
    own_tmp = None
    if cache_root is None:
        own_tmp = tempfile.TemporaryDirectory(prefix="trace-lab-graphify-")
        cache_root = Path(own_tmp.name)
    try:
        t0 = time.perf_counter()
        extraction = extract(paths, root=root, cache_root=cache_root, parallel=False)
        ir = graphify_to_repo_ir(
            extraction,
            root=root,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
            file_count=len(paths),
        )
    finally:
        if own_tmp is not None:
            own_tmp.cleanup()

    sid_to_nid: dict[str, str] = {}
    for sid, sym in ir.symbols.items():
        mapped = _map_symbol(sym.file, sym.name, sym.line, nodes)
        if mapped:
            sid_to_nid[sid] = mapped

    edges: list[TraceEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def add(src: str, dst: str, rel: str, w: float) -> None:
        if src == dst:
            return
        key = (src, dst, rel)
        if key in seen:
            return
        seen.add(key)
        edges.append(TraceEdge(src, dst, rel, w))

    for e in ir.edges:
        src = sid_to_nid.get(e.source)
        dst = sid_to_nid.get(e.target)
        if not src or not dst:
            continue
        rel = e.relation or "related"
        w = _REL_W.get(rel, 0.4)
        add(src, dst, rel, w)
        if rel == "calls":
            add(dst, src, "called_by", CALLED_BY_W)
        elif rel in {"imports", "imports_from"}:
            add(dst, src, "imported_by", IMPORTED_BY_W)

    return AstTraceGraph(nodes, edges)
