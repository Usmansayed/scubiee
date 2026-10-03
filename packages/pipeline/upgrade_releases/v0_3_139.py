"""Release 0.3.139 — Map V3 perf: grep file-list memoization + faster worker startup."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.139",
    notes=(
        "More map-tool latency and startup wins, all behavior-preserving. (1) The "
        "whole-repo grep rebuilt its filtered+sorted file list (recomputing the "
        "per-file kind ~9.8k times) on every call — ~117ms of a ~145ms warm grep. "
        "That list is now memoized per repo file set (byte-identical output), so "
        "each grep drops ~150ms -> ~21ms; focus ~360ms -> ~90ms, and find/related "
        "inherit it. (2) The MCP worker now warms in the background (it never did "
        "before), and the first HTTP request no longer pays urllib's one-time "
        "~350ms init on the user's first call (loopback no-proxy opener + a "
        "throwaway /health on the warm thread): first call ~430ms -> ~60ms. (3) The "
        "repo walk uses os.scandir (~290ms -> ~130ms). (4) The engine's /v1/search "
        "can omit the discarded keeper block (lean) the map tool never reads. "
        "map/gate/status surface and payloads are unchanged; retrieval ranking is "
        "unchanged."
    ),
)
def v0_3_139() -> None:
    return None
