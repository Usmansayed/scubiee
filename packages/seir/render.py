"""Dispatcher for SEIR representation arms."""

from __future__ import annotations

from typing import Any

from seir.ast_tree import render_ast_tree
from seir.baseline import render_baseline
from seir.caps import DEFAULT_MAX_CHARS
from seir.importance import render_importance
from seir.mix_rels import render_mix_rels
from seir.rels import render_rels
from seir.semantic import render_semantic
from seir.types import SpanContext

ARMS = ("baseline", "ast_tree", "rels", "semantic", "importance", "mix_rels")
MATRIX_ARMS = ("baseline", "ast_tree", "mix_rels")


def render(
    arm: str,
    span: SpanContext,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    graph: Any = None,
    baseline_text: str | None = None,
) -> str:
    key = (arm or "").strip().lower()
    if key == "baseline":
        return render_baseline(span, max_chars=max_chars, baseline_text=baseline_text)
    if key == "ast_tree":
        return render_ast_tree(span, max_chars=max_chars)
    if key == "rels":
        return render_rels(span, max_chars=max_chars, graph=graph)
    if key == "semantic":
        return render_semantic(span, max_chars=max_chars)
    if key == "importance":
        return render_importance(span, max_chars=max_chars)
    if key == "mix_rels":
        return render_mix_rels(
            span, max_chars=max_chars, graph=graph, baseline_text=baseline_text
        )
    raise ValueError(f"unknown SEIR arm: {arm!r}; expected one of {ARMS}")
