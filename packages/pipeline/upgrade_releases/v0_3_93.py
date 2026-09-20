"""Release 0.3.93 — map always dense D_channel; FastEmbed warm while MCP connected."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.93",
    notes=(
        "Map/search always use real FastEmbed → retrieve_D_channel_best "
        "(no skip_freshness/hash pseudo-dense). Soft warm first; dense via "
        "attach warm + map ensure_embedder_ready; keepalive default 15s with "
        "immediate first tick + async reload if clients present but model cold; "
        "client touch re-arms keepalive; nested run_embed_infer re-entrancy "
        "(LazyEmbedder unwrap) so dense map cannot deadlock the embed worker; "
        "engine-process ORT/DML encodes (sync+map+keepalive) share one worker; "
        "keepalive lock is RLock (already_running no longer deadlocks touch/register); "
        "locate-worker soft probe no longer dense-searches on attach (Lane A settle). "
        "Watchdog hung-PID heal (0.3.92)."
    ),
)
class Release_0_3_93:
    pass
