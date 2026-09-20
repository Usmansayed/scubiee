"""Release 0.3.95 — Cursor-open: dense before AST; no watchdog kill mid-ORT."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.95",
    notes=(
        "Cursor-open reliability: locate-worker kicks /v1/embed/prewarm before "
        "AST hydrate (pickle GIL was starving DML → SETTLE_EMBED_NOT_READY). "
        "register_client always arms keepalive loop so soft→dense poll starts. "
        "prewarm stamps embed_prewarm.busy so watchdog skips force-restart while "
        "/health times out under ORT GIL. Soft binder check in keepalive uses "
        "in-memory engine texts (no health()). Prewarm primes a dense retrieve. "
        "Lane A settle_join treats successful map as dense-ready when health lags."
    ),
)
class Release_0_3_95:
    pass
