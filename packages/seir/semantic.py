"""Experiment 3 — rule-based semantic card (no LLM)."""

from __future__ import annotations

import ast
import re

from seir.caps import DEFAULT_MAX_CHARS, truncate
from seir.types import SpanContext

_PURPOSE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"auth|login|password|credential|session|jwt|oauth|token", re.I), "Authentication"),
    (re.compile(r"validat|schema|pydantic|assert", re.I), "Validation"),
    (re.compile(r"embed|vector|faiss|retriev|search|rank", re.I), "Retrieval"),
    (re.compile(r"index|sync|merkle|incremental", re.I), "Indexing"),
    (re.compile(r"browser|playwright|page|screenshot|session_start", re.I), "BrowserAutomation"),
    (re.compile(r"mcp|tool_catalog|dispatch|handler", re.I), "MCPTooling"),
    (re.compile(r"http|request|response|api|endpoint|route", re.I), "HTTP"),
    (re.compile(r"parse|ast|extract|tree.?sitter", re.I), "Parsing"),
    (re.compile(r"log|metric|telemetry|observ", re.I), "Observability"),
    (re.compile(r"test|fixture|mock|assert", re.I), "Testing"),
]

_BOUNDARY_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"auth|login|password|jwt|credential", re.I), "Authentication"),
    (re.compile(r"permission|acl|authorize|rbac", re.I), "Authorization"),
    (re.compile(r"sql|query|db|database|redis", re.I), "DataStore"),
    (re.compile(r"http|request|fetch|axios", re.I), "Network"),
    (re.compile(r"file|path|open\(|read_text|write_text", re.I), "Filesystem"),
]


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = _call_name(func.value)
        return f"{base}.{func.attr}" if base else func.attr
    return ""


def _inputs(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return [a.arg for a in node.args.args if a.arg not in {"self", "cls"}][:8]
    return []


def _outputs(source: str) -> list[str]:
    outs: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            if isinstance(node.value, ast.Name):
                outs.append(node.value.id)
            elif isinstance(node.value, ast.Call):
                n = _call_name(node.value.func)
                if n:
                    outs.append(n)
            elif isinstance(node.value, ast.Constant):
                outs.append(type(node.value.value).__name__)
    # dedupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for o in outs:
        if o not in seen:
            seen.add(o)
            uniq.append(o)
    return uniq[:4]


def _deps(source: str) -> list[str]:
    deps: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            n = _call_name(node.func)
            if not n or n.startswith("self.") or n.startswith("cls."):
                continue
            root = n.split(".")[0]
            if root in {"self", "cls", "super"}:
                continue
            item = n if "." in n else root
            if item not in deps:
                deps.append(item)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in deps:
                    deps.append(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module.split(".")[0]
            if mod not in deps:
                deps.append(mod)
    return deps[:8]


def _match(rules: list[tuple[re.Pattern[str], str]], blob: str) -> str | None:
    for pat, label in rules:
        if pat.search(blob):
            return label
    return None


def render_semantic(span: SpanContext, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    blob = f"{span.file} {span.symbol or ''} {span.source}"
    lines = [f"Function: {span.symbol or '?'}"]
    purpose = _match(_PURPOSE_RULES, blob)
    if purpose:
        lines.append(f"Purpose: {purpose}")
    inputs = _inputs(span.source)
    if inputs:
        lines.append("Inputs: " + " ".join(inputs))
    outputs = _outputs(span.source)
    if outputs:
        lines.append("Output: " + " ".join(outputs))
    boundary = _match(_BOUNDARY_RULES, blob)
    if boundary:
        lines.append(f"Boundary: {boundary}")
    deps = _deps(span.source)
    if deps:
        lines.append("Deps: " + " ".join(deps))
    return truncate("\n".join(lines), max_chars)
