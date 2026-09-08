"""Lightweight Python DFG summaries: def-use, param/return, attribute flow."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from trace_lab.corpus import iter_python_files, rel_posix
from trace_lab.facts import TypedEdge
from trace_lab.types import TraceNode


def _parse(text: str) -> ast.AST | None:
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def build_dfg_edges(
    root: Path,
    nodes: dict[str, TraceNode],
    call_edges: list[TypedEdge],
) -> list[TypedEdge]:
    """Emit PASSES_DATA_TO between callers/callees and intra-function uses→defs links as CONSUMES."""
    root = root.resolve()
    by_id = nodes
    # Map short name -> node ids for returns/params heuristic
    calls_out: dict[str, list[str]] = defaultdict(list)
    for e in call_edges:
        if e.relation in {"CALLS", "calls", "DISPATCHES"}:
            calls_out[e.source].append(e.target)

    out: list[TypedEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def add(src: str, dst: str, rel: str, w: float) -> None:
        if src == dst or src not in by_id or dst not in by_id:
            return
        key = (src, dst, rel)
        if key in seen:
            return
        seen.add(key)
        out.append(TypedEdge(src, dst, rel, w, confidence="dfg"))

    # Interprocedural: caller PASSES_DATA_TO callee (and PRODUCES back for non-void heuristic)
    for src, targets in calls_out.items():
        src_n = by_id[src]
        short = src_n.symbol.split(".")[-1].lower()
        # Sink-like callees get weaker data edges
        for tgt in targets:
            tgt_n = by_id[tgt]
            tshort = tgt_n.symbol.split(".")[-1].lower()
            sink = tshort in {"log", "logger", "info", "debug", "warn", "error", "track", "print"}
            w = 0.35 if sink else 0.90
            add(src, tgt, "PASSES_DATA_TO", w)
            if not sink:
                add(tgt, src, "PRODUCES", 0.55)

    # Intra-file: name load of another function/const in same file → CONSUMES
    by_file: dict[str, list[TraceNode]] = defaultdict(list)
    for n in nodes.values():
        by_file[n.file].append(n)

    for path in iter_python_files(root):
        rel = rel_posix(root, path)
        group = [n for n in by_file.get(rel, []) if n.kind in {"function", "method"}]
        if not group:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        tree = _parse(text)
        if tree is None:
            continue
        # Build line→node
        def owner(lineno: int) -> TraceNode | None:
            hits = [n for n in group if n.start_line <= lineno <= n.end_line]
            if not hits:
                return None
            hits.sort(key=lambda n: n.end_line - n.start_line)
            return hits[0]

        names_in_file = {
            n.symbol.split(".")[-1]: n.id for n in by_file.get(rel, []) if n.kind != "class"
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                tgt = names_in_file.get(node.id)
                if not tgt or not hasattr(node, "lineno"):
                    continue
                own = owner(int(node.lineno))
                if own is None or own.id == tgt:
                    continue
                add(own.id, tgt, "CONSUMES", 0.70)
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                if not hasattr(node, "lineno"):
                    continue
                own = owner(int(node.lineno))
                if own is None:
                    continue
                # Attribute name may match method short name
                tgt = names_in_file.get(node.attr)
                if tgt and tgt != own.id:
                    add(own.id, tgt, "READS", 0.65)
    return out


def is_data_spine_edge(e: TypedEdge) -> bool:
    return e.relation in {"PASSES_DATA_TO", "PRODUCES", "CONSUMES", "READS", "WRITES"} and e.weight >= 0.5


def data_neighbors(edges: list[TypedEdge], nid: str) -> list[TypedEdge]:
    return [e for e in edges if e.source == nid and is_data_spine_edge(e)]
