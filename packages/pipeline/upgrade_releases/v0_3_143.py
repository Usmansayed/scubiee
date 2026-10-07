"""Release 0.3.143 — sync freshness + grep correctness + bad-day reliability hardening."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.143",
    notes=(
        "Fixes the sync-freshness regression where newly added / modified files "
        "could stay unsearchable after churn, plus three related correctness bugs. "
        "(1) Incremental newcomer discovery compared posix/original-case index keys "
        "against canonical (normcase) merkle keys, so on Windows every indexed file "
        "was mis-flagged as new, doubling the change-set and tripping the auto-full "
        "guard — sync then published nothing. Now canonicalizes both sides; a new "
        "file is searchable in ~0.7s again. (2) An oversize change-set now raises "
        "`needs_full` on the interval sync path and surfaces as a STALE (not fully "
        "ready) locate state with a repair hint, instead of serving stale results "
        "that looked healthy. (3) `graph_pending` now gets an unconditional hygiene "
        "pass that drops ghost entries (deleted files) and collapses duplicate path "
        "forms on every sync branch, not just the happy path. (4) `/v1/grep` prefers "
        "a resolved ripgrep (env override -> PATH -> editor-bundled @vscode/ripgrep) "
        "so it is fast and gitignore-aware; the Python fallback stats file size "
        "before reading (never slurps multi-GB binaries), scans source roots first, "
        "and honors .scubieeignore — fixing false-empty results on large repos. Grep "
        "now reports `complete=false` + an incomplete note when a scan runs out of "
        "budget, so count=0 is never silently read as 'absent'. (5) `scubiee index "
        "--force` now hands off to `ensure_daemon` (direct owner) after a successful "
        "rebuild so the serving engine is restored instead of being left down by the "
        "demand-gated watchdog. (6) GREP PERF: the engine spawns ripgrep with "
        "CREATE_NO_WINDOW + hidden STARTUPINFO on Windows — a no-console daemon "
        "spawning the console-subsystem rg.exe without it made Windows allocate a "
        "fresh console per call (~3.3s tax); grep drops from ~3.5s to ~275ms. rg "
        "output is now decoded UTF-8 (not platform cp1252), fixing a "
        "UnicodeDecodeError that crashed the handler on non-cp1252 bytes. (7) "
        "Interrupted `index --force` no longer leaks: a hard-killed staged reindex "
        "orphaned its `<base>.staging-<pid>/` dir + staged collection (the finally "
        "cleanup is skipped on kill); the next index now sweeps any staging whose "
        "owner pid is dead, so they can't accumulate. The live index is never "
        "touched by a killed staged build (no torn generation). (8) CORRUPT-STORE "
        "RECOVERY: `republish_manifest_if_coherent` used to re-seal the manifest "
        "over a present-but-corrupt graph.json (it only checked existence + chunk "
        "count), and `graphify`'s graph loader called `sys.exit(1)` on an "
        "unparseable graph — on an engine worker/publish thread that `SystemExit` "
        "wedged `load_engine`, hanging the open. The republish now parses "
        "graph.json/graph_ir.json before re-sealing (corrupt -> declines, heals "
        "instead), and the loader raises `RuntimeError` rather than exiting; a "
        "truncated graph now degrades to a clean mixed-generation refusal with no "
        "hang. (9) CONCURRENT COLD-START no longer 409s: under a burst of "
        "simultaneous first requests, the registry read (`_read_json`) could catch "
        "the file mid atomic-replace and return empty, so admission wrongly reported "
        "`requires_initialize` (HTTP 409) for a managed, warm repo. The read now "
        "retries transient OSError/parse failures (mirroring the write-side R11 "
        "retry); 180 concurrent cold calls return 200 with zero spurious 409s. "
        "(10) OUT-OF-REPO DIRTY PATH no longer wedges sync: a dirty entry that "
        "resolved outside the repo root made the keeper's `relative_to(root)` raise "
        "and fail the entire bulk sub-batch on every tick — a permanent sync stall "
        "that also blocked every legitimate edit queued behind it. Foreign paths are "
        "now rejected at ingestion (`filter_dirty_paths`, reason `outside_repo`), "
        "filtered defensively before parsing, and any such entry already in the "
        "ledger is completed/drained (not re-queued) so the backlog clears. No map "
        "surface change (still find|focus)."
    ),
)
def v0_3_143() -> None:
    return None
