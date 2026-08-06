"""Experiment 1 — compact AST tree serialization."""

from __future__ import annotations

import ast

from seir.caps import DEFAULT_MAX_CHARS, truncate
from seir.types import SpanContext

_SKIP_TYPES = (
    ast.Load,
    ast.Store,
    ast.Del,
    ast.Pass,
)


def _label(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = [a.arg for a in node.args.args if a.arg not in {"self", "cls"}]
        prefix = "AsyncFunction" if isinstance(node, ast.AsyncFunctionDef) else "Function"
        arg_s = " ".join(args[:8])
        return f"{prefix} {node.name}" + (f" params {arg_s}" if arg_s else "")
    if isinstance(node, ast.ClassDef):
        bases = []
        for b in node.bases[:3]:
            if isinstance(b, ast.Name):
                bases.append(b.id)
        base_s = " ".join(bases)
        return f"Class {node.name}" + (f" bases {base_s}" if base_s else "")
    if isinstance(node, ast.Return):
        if node.value is None:
            return "Return"
        if isinstance(node.value, ast.Name):
            return f"Return {node.value.id}"
        if isinstance(node.value, ast.Constant):
            return f"Return {node.value.value!r}"
        return "Return"
    if isinstance(node, ast.Assign):
        targets = []
        for t in node.targets[:3]:
            if isinstance(t, ast.Name):
                targets.append(t.id)
            elif isinstance(t, ast.Attribute):
                targets.append(t.attr)
        return "Assign " + (" ".join(targets) if targets else "")
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return f"AnnAssign {node.target.id}"
    if isinstance(node, ast.Call):
        name = _call_name(node.func)
        return f"Call {name}" if name else "Call"
    if isinstance(node, ast.If):
        return "If"
    if isinstance(node, ast.For):
        return "For"
    if isinstance(node, ast.While):
        return "While"
    if isinstance(node, ast.With):
        return "With"
    if isinstance(node, ast.Try):
        return "Try"
    if isinstance(node, ast.Raise):
        return "Raise"
    if isinstance(node, ast.Assert):
        return "Assert"
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "Import"
    return type(node).__name__


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = _call_name(func.value)
        return f"{base}.{func.attr}" if base else func.attr
    return ""


def _dump(node: ast.AST, depth: int = 0, *, max_depth: int = 4) -> list[str]:
    if depth > max_depth or isinstance(node, _SKIP_TYPES):
        return []
    # Skip pure expression wrappers that add noise
    if isinstance(node, (ast.Expr, ast.Attribute, ast.Name, ast.Constant, ast.arg)):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            return _dump(node.value, depth, max_depth=max_depth)
        return []
    lines = ["  " * depth + _label(node)]
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.arguments, ast.arg, ast.keyword)):
            continue
        if isinstance(child, ast.Constant) and isinstance(getattr(child, "value", None), str):
            # docstring
            continue
        lines.extend(_dump(child, depth + 1, max_depth=max_depth))
    return lines


def render_ast_tree(span: SpanContext, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    try:
        tree = ast.parse(span.source)
    except SyntaxError:
        return truncate(f"{span.node_kind} {span.symbol or '?'}", max_chars)
    body = tree.body
    if not body:
        return truncate(f"{span.node_kind} {span.symbol or '?'}", max_chars)
    lines: list[str] = []
    for node in body:
        lines.extend(_dump(node, 0))
    if not lines:
        lines = [f"{span.node_kind} {span.symbol or '?'}"]
    return truncate("\n".join(lines), max_chars)
