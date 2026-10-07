"""Release 0.3.143 — sync freshness + grep correctness hardening."""

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
        "UnicodeDecodeError that crashed the handler on non-cp1252 bytes. No map "
        "surface change (still find|focus)."
    ),
)
def v0_3_143() -> None:
    return None
