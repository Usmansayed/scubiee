"""Density helpers — every token must earn its place."""

from __future__ import annotations

DEFAULT_MAX_CHARS = 512


def truncate(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Hard-cap text; keep the head (identity / high-signal lines first)."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars / token) for density reporting."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)
