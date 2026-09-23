"""Release 0.3.113 — fixes for eight bugs found via direct MCP/CLI use."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.113",
    notes=(
        "map no longer replays stale embed_ms/retrieve_ms on a cache hit. "
        "pack_context returns a clean structured error (not a raw Pydantic "
        "leak) when seed_symbol is given without seed_file. expand_context "
        "validates direction/intent against the full real vocabulary "
        "(including flow/refs/site/deps/dependents aliases) instead of "
        "accepting any string. workspace(pin) rejects nonexistent paths. "
        "expand's max_chars<=0 no longer bypasses truncation. Windows "
        "console UTF-8 setup now runs even when stdout is piped/redirected, "
        "fixing mojibake in automation. map surfaces the real engine error "
        "instead of a generic engine_down label. A wedged warm_phase:prewarm "
        "now expires on the idle-sweep and watchdog paths instead of "
        "logging forever, and ensure_daemon fails fast instead of blocking "
        "up to 120s against an unresponsive-but-alive daemon."
    ),
)
def v0_3_113() -> None:
    return None
