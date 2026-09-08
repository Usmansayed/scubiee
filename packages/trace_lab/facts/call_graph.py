"""Call graph facts: AST + optional Jedi + Graphify."""

from __future__ import annotations

from pathlib import Path

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.facts import TypedEdge
from trace_lab.lsp_index import LspIndex
from trace_lab.types import TraceNode

_REL_MAP = {
    "calls": "CALLS",
    "uses": "USES",
    "contains": "CONTAINS",
    "imports": "IMPORTS",
    "called_by": "CALLED_BY",
    "imported_by": "IMPORTED_BY",
    "dispatches": "DISPATCHES",
    "overrides": "OVERRIDES",
    "method": "CONTAINS",
}


def edges_from_ast(graph: AstTraceGraph) -> list[TypedEdge]:
    out: list[TypedEdge] = []
    for e in graph.edges:
        rel = _REL_MAP.get(e.relation, e.relation.upper())
        out.append(
            TypedEdge(
                source=e.source,
                target=e.target,
                relation=rel,
                weight=float(e.weight),
                confidence="ast",
            )
        )
    return out


def edges_from_dispatch(lsp: LspIndex) -> list[TypedEdge]:
    out: list[TypedEdge] = []
    for src, targets in lsp.dispatch.items():
        for tgt in targets:
            out.append(
                TypedEdge(src, tgt, "DISPATCHES", 0.88, confidence="dispatch")
            )
    for src, targets in lsp.overrides.items():
        for tgt in targets:
            out.append(
                TypedEdge(src, tgt, "OVERRIDES", 0.75, confidence="dispatch")
            )
    return out


def edges_from_jedi(
    root: Path,
    nodes: dict[str, TraceNode],
    *,
    max_files: int = 40,
) -> list[TypedEdge]:
    """Best-effort Jedi goto-def for Call sites inside node bodies."""
    try:
        import jedi
    except ImportError:
        return []

    import ast

    root = root.resolve()
    by_file: dict[str, list[TraceNode]] = {}
    for n in nodes.values():
        if n.kind in {"function", "method"}:
            by_file.setdefault(n.file, []).append(n)

    files = sorted(by_file.keys())
    preferred = [f for f in files if f.startswith(("app/", "packages/", "fixtures/"))]
    files = (preferred or files)[:max_files]

    id_by_file_sym: dict[tuple[str, str], str] = {}
    for n in nodes.values():
        id_by_file_sym[(n.file, n.symbol)] = n.id
        id_by_file_sym[(n.file, n.symbol.split(".")[-1])] = n.id

    out: list[TypedEdge] = []
    seen: set[tuple[str, str]] = set()
    project = jedi.Project(path=str(root))

    for rel in files:
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            continue
        lines = text.splitlines()
        group = by_file.get(rel, [])

        def owner(lineno: int):
            hits = [n for n in group if n.start_line <= lineno <= n.end_line]
            if not hits:
                return None
            hits.sort(key=lambda n: n.end_line - n.start_line)
            return hits[0]

        try:
            script = jedi.Script(code=text, path=str(path), project=project)
        except Exception:  # noqa: BLE001
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not hasattr(node, "lineno"):
                continue
            own = owner(int(node.lineno))
            if own is None:
                continue
            # column at start of call func
            func = node.func
            col = int(getattr(func, "col_offset", 0) or 0) + 1
            line = int(getattr(func, "lineno", node.lineno) or node.lineno)
            try:
                defs = script.goto(line, col, follow_imports=True)
            except Exception:  # noqa: BLE001
                continue
            for d in defs:
                if not d.module_path:
                    continue
                try:
                    drel = Path(d.module_path).resolve().relative_to(root).as_posix()
                except ValueError:
                    continue
                name = d.name or ""
                tgt = id_by_file_sym.get((drel, name))
                if tgt is None:
                    for (f, sym), nid in id_by_file_sym.items():
                        if f == drel and (sym == name or sym.endswith("." + name)):
                            tgt = nid
                            break
                if tgt is None or tgt == own.id:
                    continue
                key = (own.id, tgt)
                if key in seen:
                    continue
                seen.add(key)
                out.append(TypedEdge(own.id, tgt, "CALLS", 0.86, confidence="jedi"))
            if len(seen) > 2500:
                return out
    return out


def merge_call_edges(
    *groups: list[TypedEdge],
) -> list[TypedEdge]:
    best: dict[tuple[str, str, str], TypedEdge] = {}
    for group in groups:
        for e in group:
            key = (e.source, e.target, e.relation)
            prev = best.get(key)
            if prev is None or e.weight > prev.weight:
                best[key] = e
    return list(best.values())


def build_enriched_call_graph(
    root: Path,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lsp: LspIndex,
    *,
    extra: AstTraceGraph | None = None,
    with_jedi: bool = True,
) -> list[TypedEdge]:
    groups = [edges_from_ast(graph), edges_from_dispatch(lsp)]
    if extra is not None:
        gfy: list[TypedEdge] = []
        for e in extra.edges:
            rel = _REL_MAP.get(e.relation, e.relation.upper())
            if rel in {"CALLS", "USES", "CONTAINS", "calls", "uses", "contains"} or e.relation in {
                "calls",
                "uses",
                "contains",
                "method",
            }:
                gfy.append(
                    TypedEdge(
                        e.source,
                        e.target,
                        _REL_MAP.get(e.relation, "CALLS"),
                        float(e.weight) * 0.95,
                        confidence="graphify",
                    )
                )
        groups.append(gfy)
    if with_jedi:
        groups.append(edges_from_jedi(root, nodes))
    return merge_call_edges(*groups)
