"""LSP-lite index over the trace-lab corpus: defs, refs, registry, overrides.

This is the language-server channel without a live LSP process: the same
queries (go-to-definition, find-references, type/override, callback bind)
that pyright would answer, computed from AST + the AST graph.
"""

from __future__ import annotations

import ast
import textwrap
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from trace_lab.ast_graph import AstTraceGraph, _call_name, _collect_imports
from trace_lab.corpus import (
    iter_python_files,
    module_name_for,
    rel_posix,
)
from trace_lab.types import TraceNode

_REGISTER = frozenset({"bind", "register", "subscribe", "listen", "on", "add_handler"})


@dataclass
class LspIndex:
    defs: dict[str, list[str]] = field(default_factory=dict)
    refs: dict[str, list[str]] = field(default_factory=dict)
    used_by: dict[str, list[str]] = field(default_factory=dict)
    dispatch: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    overrides: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    methods: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    bases: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


def build_lsp_index(
    root: Path,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
) -> LspIndex:
    root = root.resolve()
    idx = LspIndex()
    by_file: dict[str, list[TraceNode]] = defaultdict(list)
    for n in nodes.values():
        by_file[n.file].append(n)
        short = n.symbol.split(".")[-1]
        idx.defs.setdefault(short, []).append(n.id)
        idx.defs.setdefault(n.symbol, []).append(n.id)
        if n.kind == "method" and "." in n.symbol:
            cls = n.symbol.rsplit(".", 1)[0]
            cls_id = f"{n.file}::{cls}"
            idx.methods[cls_id].append(n.id)
        if n.kind == "class":
            idx.methods.setdefault(n.id, idx.methods.get(n.id, []))

    for nid, edges in graph.inc.items():
        for e in edges:
            if e.relation in {"calls", "uses", "imports", "contains"}:
                idx.used_by.setdefault(nid, []).append(e.source)
            # called_by on an incoming edge is callee → caller. Recording
            # e.source here stores the callee as a ref of the caller.
        # called_by lives on the callee's out list; also scrape out
    for nid, edges in graph.out.items():
        for e in edges:
            if e.relation == "called_by":
                idx.refs.setdefault(nid, []).append(e.target)
            if e.relation in {"calls", "uses"}:
                idx.used_by.setdefault(e.target, []).append(nid)

    _uniq_lists(idx.used_by)
    _uniq_lists(idx.refs)

    by_mod = {module_name_for(rel): rel for rel in by_file}
    symbols_in_file = {
        rel: {n.symbol: n.id for n in group} | {n.symbol.split(".")[-1]: n.id for n in group}
        for rel, group in by_file.items()
    }

    registered: list[str] = []
    lookup_nodes: list[str] = []

    for path in iter_python_files(root):
        rel = rel_posix(root, path)
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        imports = _collect_imports(tree, by_mod, symbols_in_file)
        _collect_inheritance(rel, tree, nodes, idx)
        for n in by_file.get(rel, []):
            if n.kind == "class":
                continue
            body = _parse(n.text)
            if body is None:
                continue
            tabled = any(m in n.text for m in ("HANDLERS", "REGISTRY", "DISPATCH", "_HANDLERS"))
            short = n.symbol.split(".")[-1]
            if tabled and short in {"lookup", "dispatch", "get_handler", "resolve_handler"}:
                lookup_nodes.append(n.id)
            registered.extend(_bound_callbacks(body, imports, symbols_in_file.get(rel, {})))

    registered = list(dict.fromkeys(registered))
    lookup_nodes = list(dict.fromkeys(lookup_nodes))
    dispatchers = set(lookup_nodes)
    for src, edges in graph.out.items():
        for e in edges:
            if e.relation == "calls" and e.target in dispatchers:
                dispatchers.add(src)
    for src in dispatchers:
        for dst in registered:
            if dst != src:
                idx.dispatch[src].append(dst)
    _uniq_lists(idx.dispatch)
    _uniq_lists(idx.overrides)
    _uniq_lists(idx.methods)
    return idx


def _uniq_lists(mapping: dict[str, list[str]]) -> None:
    for k, vals in list(mapping.items()):
        mapping[k] = list(dict.fromkeys(vals))


def _parse(text: str) -> ast.AST | None:
    if not text.strip():
        return None
    try:
        return ast.parse(textwrap.dedent(text))
    except SyntaxError:
        return None


def _bound_callbacks(
    tree: ast.AST,
    imports: dict[str, list[str]],
    local: dict[str, str],
) -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        base, attr = _call_name(node.func)
        name = attr or base
        if name not in _REGISTER:
            continue
        for arg in list(node.args) + [
            kw.value for kw in (node.keywords or []) if isinstance(kw.value, ast.Name)
        ]:
            if not isinstance(arg, ast.Name):
                continue
            if arg.id in imports:
                out.extend(imports[arg.id])
            if arg.id in local:
                out.append(local[arg.id])
    return out


def _collect_inheritance(
    rel: str,
    tree: ast.AST,
    nodes: dict[str, TraceNode],
    idx: LspIndex,
) -> None:
    for stmt in tree.body:
        if not isinstance(stmt, ast.ClassDef):
            continue
        child_id = f"{rel}::{stmt.name}"
        if child_id not in nodes:
            continue
        for base in stmt.bases:
            bname = _call_name(base)[0] if not isinstance(base, ast.Name) else base.id
            if isinstance(base, ast.Name):
                bname = base.id
            elif isinstance(base, ast.Attribute):
                bname = base.attr
            else:
                continue
            # match class nodes named bname
            for nid, n in nodes.items():
                if n.kind == "class" and n.symbol == bname:
                    idx.bases[child_id].append(nid)
                    for meth in idx.methods.get(child_id, []):
                        mshort = meth.split("::")[-1].split(".")[-1]
                        for bm in idx.methods.get(nid, []):
                            if bm.split("::")[-1].split(".")[-1] == mshort:
                                idx.overrides[meth].append(bm)
