"""Release 0.3.132 — engine stays up, map stays fresh, saves stop stalling."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.132",
    notes=(
        "map results are keyed on the index generation, so an edit is never "
        "served from a stale cache. The engine is created outside the MCP "
        "bridge's kill-on-close job (WMI, breakaway fallback), a prewarm lock "
        "self-deadlock and an engine self-quiesce are fixed, prewarm markers "
        "survive Windows share-mode locks, and every stop is logged with who and "
        "why. OpenBLAS runs one thread (about 2.4GB less committed memory). "
        "Graph catch-ups merge in a below-normal child process, so a save during "
        "one is searchable in about 3s instead of 15s. The change poll no longer "
        "convoys on the GIL (per-file stat 18s -> 0.2s with a search running). "
        "Chunk digests hash the chunk's own source, so adding a function no "
        "longer re-embeds the whole file. Reinstalls publish a build stamp and "
        "connected MCP bridges respawn their worker on the next call. Client "
        "disconnects log one line instead of a traceback."
    ),
)
def v0_3_132() -> None:
    return None
