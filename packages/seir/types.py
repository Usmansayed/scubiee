"""Shared SEIR types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpanContext:
    """One embeddable code span (typically a function or class)."""

    file: str  # repo-relative, forward slashes
    start_line: int
    end_line: int
    symbol: str | None
    source: str
    node_kind: str  # "function" | "class" | "async_function"
