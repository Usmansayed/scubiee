"""Light CFG: branch/block control edges between enclosing functions."""

from __future__ import annotations

import ast
from pathlib import Path

from trace_lab.corpus import iter_python_files, rel_posix
from trace_lab.facts import TypedEdge
from trace_lab.types import TraceNode


def build_cfg_edges(root: Path, nodes: dict[str, TraceNode]) -> list[TypedEdge]:
    """Emit CONTROLS from a function to callees appearing only inside if/try bodies (heuristic)."""
    root = root.resolve()
    by_file: dict[str, list[TraceNode]] = {}
    for n in nodes.values():
        by_file.setdefault(n.file, []).append(n)

    out: list[TypedEdge] = []
    seen: set[tuple[str, str]] = set()

    for path in iter_python_files(root):
        rel = rel_posix(root, path)
        group = [n for n in by_file.get(rel, []) if n.kind in {"function", "method"}]
        if not group:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, SyntaxError):
            continue

        def owner(lineno: int) -> TraceNode | None:
            hits = [n for n in group if n.start_line <= lineno <= n.end_line]
            if not hits:
                return None
            hits.sort(key=lambda n: n.end_line - n.start_line)
            return hits[0]

        name_to_id = {
            n.symbol.split(".")[-1]: n.id for n in by_file.get(rel, []) if n.kind != "class"
        }

        class V(ast.NodeVisitor):
            def visit_If(self, node: ast.If) -> None:
                own = owner(getattr(node, "lineno", 0) or 0)
                if own is not None:
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Call):
                            nm = None
                            if isinstance(sub.func, ast.Name):
                                nm = sub.func.id
                            elif isinstance(sub.func, ast.Attribute):
                                nm = sub.func.attr
                            if nm and nm in name_to_id:
                                tgt = name_to_id[nm]
                                key = (own.id, tgt)
                                if key not in seen and tgt != own.id:
                                    seen.add(key)
                                    out.append(
                                        TypedEdge(own.id, tgt, "CONTROLS", 0.80, confidence="cfg")
                                    )
                self.generic_visit(node)

            def visit_Try(self, node: ast.Try) -> None:
                self.visit_If(node)  # type: ignore[arg-type]

        V().visit(tree)
    return out
