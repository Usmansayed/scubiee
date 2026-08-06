"""Baseline arm — text CE would embed today (mix compress of enriched parts)."""

from __future__ import annotations

from seir.caps import DEFAULT_MAX_CHARS, truncate
from seir.types import SpanContext


def render_baseline(
    span: SpanContext,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    baseline_text: str | None = None,
) -> str:
    if baseline_text is not None:
        return truncate(baseline_text.strip(), max_chars)
    # Import CE helpers without changing them
    from pipeline.chunk_compress import compress_chunk, prepare_enriched_from_parts

    enriched = prepare_enriched_from_parts(
        span.file, span.symbol, span.source or "", span.source or ""
    )
    return truncate(compress_chunk(enriched, "mix", max_chars=max_chars).text, max_chars)
