"""Release 0.3.138 — Map V3 grep fast-path: ~3-7x faster find/focus/related."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.138",
    notes=(
        "Big latency win for the map tool. The bridge's whole-repo identifier grep "
        "(used by find/focus/related to find a symbol's callers/definitions) was "
        "running a regex over ~28 MB of source on every call (~1 s) plus a stat() "
        "per file (~300 ms over ~5k files). Added a required-substring prefilter "
        "(C-level `in` skip before the regex) and a short stat-TTL that reuses the "
        "already-warmed file cache across back-to-back calls. The background warm "
        "pass now stamps that TTL so the first real call is fast too. Results are "
        "byte-identical (prefilter is a strictly necessary condition, never "
        "over-filters). Warm steady-state on this repo: find ~2000ms -> ~300-700ms, "
        "focus ~2460ms -> ~350ms, related ~1320ms -> ~190ms. No engine change; "
        "map/gate/status surface and payloads are unchanged."
    ),
)
def v0_3_138() -> None:
    return None
