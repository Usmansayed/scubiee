"""Experiment 4 — importance-filtered representation."""

from __future__ import annotations

import ast
import re

from seir.caps import DEFAULT_MAX_CHARS, truncate
from seir.types import SpanContext

_LOW = re.compile(
    r"^(log|logger|logging|debug|info|warning|error|print|metric|metrics|stats|"
    r"telemetry|analytics|trace|span|counter|histogram)\b",
    re.I,
)
_HIGH = re.compile(
    r"(auth|login|password|bcrypt|jwt|token|oauth|encrypt|decrypt|hash|sign|"
    r"verify|session|permission|sql|query|embed|retrieve|search|index|sync|"
    r"validate|schema|parse|dispatch|handler|browser|playwright)",
    re.I,
)


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = _call_name(func.value)
        return f"{base}.{func.attr}" if base else func.attr
    return ""


def _score_name(name: str) -> float:
    if not name:
        return 0.0
    leaf = name.split(".")[-1]
    if _LOW.match(leaf) or _LOW.match(name):
        return 0.1
    score = 1.0
    if _HIGH.search(name):
        score += 2.0
    if "." in name:
        score += 0.5
    return score


def render_importance(span: SpanContext, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    lines = [f"Function: {span.symbol or '?'}"]
    scored: list[tuple[float, str]] = []
    try:
        tree = ast.parse(span.source)
    except SyntaxError:
        return truncate("\n".join(lines), max_chars)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args if a.arg not in {"self", "cls"}]
            for a in args:
                scored.append((_score_name(a) + 0.5, f"param {a}"))
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name:
                scored.append((_score_name(name), f"call {name}"))
        elif isinstance(node, ast.Return) and node.value is not None:
            if isinstance(node.value, ast.Name):
                scored.append((1.5, f"return {node.value.id}"))
            elif isinstance(node.value, ast.Call):
                n = _call_name(node.value.func)
                if n:
                    scored.append((_score_name(n) + 1.0, f"return {n}"))

    # keep high only
    scored.sort(key=lambda x: (-x[0], x[1]))
    seen: set[str] = set()
    for score, line in scored:
        if score < 1.0:
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if len(lines) >= 14:
            break
    return truncate("\n".join(lines), max_chars)
