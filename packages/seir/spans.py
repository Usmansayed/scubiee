"""Derive function/class spans from Python source via stdlib ast (post-parse)."""

from __future__ import annotations

import ast
from pathlib import Path

from seir.types import SpanContext

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".eggs",
        "graphify-out",
        ".context-engine",
    }
)


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _source_segment(src: str, node: ast.AST) -> str:
    try:
        seg = ast.get_source_segment(src, node)
        if seg is not None:
            return seg
    except Exception:  # noqa: BLE001
        pass
    lines = src.splitlines()
    start = max(int(getattr(node, "lineno", 1)) - 1, 0)
    end = int(getattr(node, "end_lineno", start + 1) or (start + 1))
    return "\n".join(lines[start:end])


def _walk_module(file_rel: str, src: str) -> list[SpanContext]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out: list[SpanContext] = []

    def add(node: ast.AST, symbol: str, kind: str) -> None:
        start = int(getattr(node, "lineno", 1) or 1)
        end = int(getattr(node, "end_lineno", start) or start)
        out.append(
            SpanContext(
                file=file_rel,
                start_line=start,
                end_line=end,
                symbol=symbol,
                source=_source_segment(src, node),
                node_kind=kind,
            )
        )

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            add(node, node.name, "function")
        elif isinstance(node, ast.AsyncFunctionDef):
            add(node, node.name, "async_function")
        elif isinstance(node, ast.ClassDef):
            add(node, node.name, "class")
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    add(child, f"{node.name}.{child.name}", "function")
                elif isinstance(child, ast.AsyncFunctionDef):
                    add(child, f"{node.name}.{child.name}", "async_function")
    return out


def iter_python_spans(
    repo: Path,
    *,
    limit: int | None = None,
) -> list[SpanContext]:
    """Walk ``repo`` for ``.py`` files and return function/class spans."""
    root = repo.resolve()
    spans: list[SpanContext] = []
    for path in sorted(root.rglob("*.py")):
        if any(p in _SKIP_DIR_NAMES for p in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        spans.extend(_walk_module(_rel(root, path), text))
        if limit is not None and len(spans) >= limit:
            return spans[:limit]
    return spans
