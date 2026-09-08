"""Python AST call / import / name-use graph at TraceNode granularity."""

from __future__ import annotations

import ast
import textwrap
from collections import defaultdict
from pathlib import Path

from trace_lab.corpus import (
    extract_nodes,
    iter_python_files,
    module_name_for,
    rel_posix,
)
from trace_lab.types import TraceEdge, TraceNode

CALL_W = 0.90
USES_W = 0.85
IMPORTS_W = 0.45
CONTAINS_W = 0.35
CALLED_BY_W = 0.50
IMPORTED_BY_W = 0.30

_BUILTINS = frozenset(
    {
        "str",
        "int",
        "float",
        "bool",
        "dict",
        "list",
        "set",
        "tuple",
        "len",
        "range",
        "print",
        "isinstance",
        "getattr",
        "setattr",
        "super",
        "ValueError",
        "TypeError",
        "KeyError",
        "Exception",
    }
)


class AstTraceGraph:
    def __init__(self, nodes: dict[str, TraceNode], edges: list[TraceEdge]):
        self.nodes = nodes
        self.edges = edges
        self.out: dict[str, list[TraceEdge]] = defaultdict(list)
        self.inc: dict[str, list[TraceEdge]] = defaultdict(list)
        for e in edges:
            self.out[e.source].append(e)
            self.inc[e.target].append(e)
        self.degree: dict[str, int] = {}
        for nid in nodes:
            self.degree[nid] = len(self.out.get(nid, [])) + len(self.inc.get(nid, []))

    def neighbors(
        self, nid: str, *, directed: bool
    ) -> list[tuple[str, str, float]]:
        seen: list[tuple[str, str, float]] = []
        for e in self.out.get(nid, []):
            seen.append((e.target, e.relation, e.weight))
        if not directed:
            for e in self.inc.get(nid, []):
                seen.append((e.source, f"rev:{e.relation}", e.weight))
        return seen


def build_ast_graph(root: Path, nodes: dict[str, TraceNode] | None = None) -> AstTraceGraph:
    root = root.resolve()
    nodes = nodes or extract_nodes(root)
    by_file: dict[str, list[TraceNode]] = defaultdict(list)
    for n in nodes.values():
        by_file[n.file].append(n)
    by_mod: dict[str, str] = {}
    for rel in by_file:
        by_mod[module_name_for(rel)] = rel

    symbols_in_file: dict[str, dict[str, str]] = {}
    for rel, group in by_file.items():
        table: dict[str, str] = {}
        for n in group:
            table[n.symbol] = n.id
            short = n.symbol.split(".")[-1]
            table.setdefault(short, n.id)
        symbols_in_file[rel] = table

    edges: list[TraceEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def add(src: str, dst: str, rel: str, w: float) -> None:
        if src == dst or src not in nodes or dst not in nodes:
            return
        key = (src, dst, rel)
        if key in seen:
            return
        seen.add(key)
        edges.append(TraceEdge(src, dst, rel, w))

    for path in iter_python_files(root):
        rel = rel_posix(root, path)
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        imports = _collect_imports(tree, by_mod, symbols_in_file)
        file_nodes = by_file.get(rel, [])
        for n in file_nodes:
            if n.kind == "class":
                continue
            for other in file_nodes:
                if other.kind == "class" and n.symbol.startswith(other.symbol + "."):
                    add(other.id, n.id, "contains", CONTAINS_W)
            snippet = _parse_snippet(n.text)
            if snippet is None:
                continue
            for target, relation, weight in _refs_from_ast(
                snippet, imports, symbols_in_file.get(rel, {})
            ):
                add(n.id, target, relation, weight)

    # Reverse structural edges so callers/importers are reachable when wanted.
    reverse: list[TraceEdge] = []
    for e in edges:
        if e.relation == "calls":
            reverse.append(TraceEdge(e.target, e.source, "called_by", CALLED_BY_W))
        elif e.relation == "imports":
            reverse.append(TraceEdge(e.target, e.source, "imported_by", IMPORTED_BY_W))
    for e in reverse:
        add(e.source, e.target, e.relation, e.weight)

    return AstTraceGraph(nodes, edges)


def _collect_imports(
    tree: ast.AST,
    by_mod: dict[str, str],
    symbols_in_file: dict[str, dict[str, str]],
) -> dict[str, list[str]]:
    """local name -> candidate TraceNode ids."""
    out: dict[str, list[str]] = defaultdict(list)
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.ImportFrom) and stmt.module:
            mod = stmt.module
            rel = by_mod.get(mod)
            if rel is None:
                continue
            table = symbols_in_file.get(rel, {})
            for alias in stmt.names or []:
                if not alias.name or alias.name == "*":
                    continue
                local = alias.asname or alias.name
                if alias.name in table:
                    out[local].append(table[alias.name])
                short_hits = [
                    nid
                    for sym, nid in table.items()
                    if sym == alias.name or sym.endswith("." + alias.name)
                ]
                out[local].extend(short_hits)
                # class name import also maps to its methods
                for sym, nid in table.items():
                    if "." in sym and sym.split(".", 1)[0] == alias.name:
                        out[local].append(nid)
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names or []:
                if not alias.name:
                    continue
                local = alias.asname or alias.name.split(".")[-1]
                rel = by_mod.get(alias.name)
                if rel and rel in symbols_in_file:
                    out[local].extend(symbols_in_file[rel].values())
    # unique preserve order
    uniq: dict[str, list[str]] = {}
    for k, ids in out.items():
        seen: set[str] = set()
        kept: list[str] = []
        for i in ids:
            if i not in seen:
                seen.add(i)
                kept.append(i)
        uniq[k] = kept
    return uniq


def _call_name(func: ast.AST) -> tuple[str | None, str | None]:
    """Return (base_name, attr) for Name, Attribute, or Call().attr."""
    if isinstance(func, ast.Name):
        return func.id, None
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name):
            return func.value.id, func.attr
        if isinstance(func.value, ast.Call):
            base, _ = _call_name(func.value.func)
            return base, func.attr
        if isinstance(func.value, ast.Attribute) and isinstance(func.value.value, ast.Name):
            return func.value.value.id, func.attr
    return None, None


def _refs_from_ast(
    tree: ast.AST,
    imports: dict[str, list[str]],
    local_syms: dict[str, str],
) -> list[tuple[str, str, float]]:
    refs: list[tuple[str, str, float]] = []
    used_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            base, attr = _call_name(node.func)
            if not base or base in _BUILTINS:
                continue
            candidates = list(imports.get(base, []))
            if base in local_syms:
                candidates.append(local_syms[base])
            if attr:
                prefer = [c for c in candidates if c.endswith("::" + f"{base}.{attr}") or c.endswith("::" + attr)]
                if not prefer:
                    prefer = [c for c in candidates if c.split("::")[-1].endswith("." + attr)]
                for c in prefer or candidates:
                    refs.append((c, "calls", CALL_W))
            else:
                for c in candidates:
                    refs.append((c, "calls", CALL_W))
            used_names.add(base)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in _BUILTINS or node.id in used_names:
                continue
            if node.id in imports:
                for c in imports[node.id]:
                    refs.append((c, "uses", USES_W))
            elif node.id in local_syms:
                refs.append((local_syms[node.id], "uses", USES_W))

    for base in used_names:
        for c in imports.get(base, []):
            refs.append((c, "imports", IMPORTS_W))
    return refs


def _parse_snippet(text: str) -> ast.AST | None:
    if not text.strip():
        return None
    try:
        return ast.parse(textwrap.dedent(text))
    except SyntaxError:
        try:
            return ast.parse(textwrap.dedent("class _T:\n" + textwrap.indent(textwrap.dedent(text), "    ")))
        except SyntaxError:
            return None
