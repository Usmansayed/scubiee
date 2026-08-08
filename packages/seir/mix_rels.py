"""Hybrid: mix baseline head + compact relationship lines (same char cap)."""

from __future__ import annotations

from typing import Any

from seir.baseline import render_baseline
from seir.caps import DEFAULT_MAX_CHARS, truncate
from seir.rels import render_rels
from seir.types import SpanContext


def render_mix_rels(
    span: SpanContext,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    graph: Any = None,
    baseline_text: str | None = None,
) -> str:
    """Pack mix identity/body first, then append rels if budget remains."""
    # Reserve ~35% of budget for relationship card when possible
    rel_budget = max(64, max_chars // 3)
    mix_budget = max(64, max_chars - rel_budget - 1)
    mix = render_baseline(span, max_chars=mix_budget, baseline_text=baseline_text)
    rels = render_rels(span, max_chars=rel_budget, graph=graph)
    # Drop the redundant "Function:" line from rels if mix already names the symbol
    rel_lines = [ln for ln in rels.splitlines() if not ln.startswith("Function:")]
    rel_body = "\n".join(rel_lines).strip()
    if not rel_body:
        return truncate(mix, max_chars)
    combined = f"{mix.rstrip()}\n{rel_body}"
    return truncate(combined, max_chars)
