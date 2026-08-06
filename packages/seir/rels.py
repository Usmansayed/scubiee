"""Experiment 2 — relationship-oriented representation."""

from __future__ import annotations

import ast
from typing import Any

from seir.caps import DEFAULT_MAX_CHARS, truncate
from seir.types import SpanContext

_WRITE_ATTR = frozenset({"append", "extend", "update", "add", "setdefault", "pop", "clear"})


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = _call_name(func.value)
        return f"{base}.{func.attr}" if base else func.attr
    return ""


def _attr_path(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _attr_path(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _extract_from_ast(source: str) -> dict[str, list[str]]:
    calls: list[str] = []
    reads: list[str] = []
    writes: list[str] = []
    returns: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {"calls": [], "reads": [], "writes": [], "returns": []}

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name and name not in calls:
                calls.append(name)
            if isinstance(node.func, ast.Attribute) and node.func.attr in _WRITE_ATTR:
                path = _attr_path(node.func.value)
                if path and path not in writes:
                    writes.append(path)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                path = _attr_path(t)
                if path and path not in writes:
                    writes.append(path)
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            path = _attr_path(node.target)
            if path and path not in writes:
                writes.append(path)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            path = _attr_path(node)
            if path and "." in path and path not in reads and path not in writes:
                reads.append(path)
        elif isinstance(node, ast.Return) and node.value is not None:
            if isinstance(node.value, ast.Name):
                returns.append(node.value.id)
            elif isinstance(node.value, ast.Constant):
                returns.append(repr(node.value.value))
            else:
                cn = _call_name(node.value) if isinstance(node.value, ast.Call) else ""
                if cn:
                    returns.append(cn)
                elif not returns:
                    returns.append(type(node.value).__name__)
    return {
        "calls": calls[:12],
        "reads": reads[:8],
        "writes": writes[:8],
        "returns": returns[:4],
    }


def _called_by(graph: Any, span: SpanContext) -> list[str]:
    """Best-effort callers from a NetworkX graphify graph."""
    if graph is None:
        return []
    try:
        import networkx as nx
    except ImportError:
        return []
    if not isinstance(graph, nx.Graph) and not hasattr(graph, "nodes"):
        return []
    sym = (span.symbol or "").split(".")[-1]
    if not sym:
        return []
    # Find nodes whose label/id matches symbol; gather neighbors that look like callers
    matches: list[str] = []
    try:
        for nid, data in graph.nodes(data=True):
            label = str(data.get("label") or data.get("name") or nid)
            if label == sym or label.endswith("." + sym) or str(nid).endswith(":" + sym):
                matches.append(str(nid))
    except Exception:  # noqa: BLE001
        return []
    callers: list[str] = []
    for nid in matches[:5]:
        try:
            for pred in list(graph.predecessors(nid)) if hasattr(graph, "predecessors") else graph.neighbors(nid):
                data = graph.nodes[pred]
                label = str(data.get("label") or data.get("name") or pred)
                if label not in callers and label != sym:
                    callers.append(label)
        except Exception:  # noqa: BLE001
            continue
    return callers[:8]


def render_rels(
    span: SpanContext,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    graph: Any = None,
) -> str:
    bits = _extract_from_ast(span.source)
    lines = [f"Function: {span.symbol or '?'}"]
    if bits["calls"]:
        lines.append("Calls: " + " ".join(bits["calls"]))
    called = _called_by(graph, span)
    if called:
        lines.append("CalledBy: " + " ".join(called))
    if bits["reads"]:
        lines.append("Reads: " + " ".join(bits["reads"]))
    if bits["writes"]:
        lines.append("Writes: " + " ".join(bits["writes"]))
    if bits["returns"]:
        lines.append("Returns: " + " ".join(bits["returns"]))
    return truncate("\n".join(lines), max_chars)
