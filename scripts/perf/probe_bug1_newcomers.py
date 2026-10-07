"""BUG-1 stage probe: prove the posix-vs-canonical key mismatch in
`incremental_sync`'s `discover_newcomers` branch.

Root cause hypothesis (from code read + context-gatherer):
  incremental.py ~L835:
      newcomers = sorted(collect_index_relpaths(root, ...) - set(old))
  * collect_index_relpaths() -> p.relative_to(root).as_posix()  (forward slash, ORIGINAL case)
  * old = store.load_merkle() -> load_snapshot -> sanitize_file_hashes -> canonical_relpath()
        -> on Windows: os.path.normcase() -> BACKSLASH + lowercase
  => the two key spaces never intersect on Windows => EVERY indexed file is
     reported as a "newcomer" => chunk count ~doubles => trips
     AUTO_FULL_INDEX_CHUNKS guard => publishes nothing.

This probe loads the REAL on-disk merkle snapshot (no engine mutation) and
reports:
  - len(index_relpaths), len(merkle_keys)
  - len(newcomers) under the CURRENT (buggy) subtraction
  - len(newcomers) under the FIXED (canonicalized) subtraction
  - sample keys from each set to show the slash/case divergence

Run with the installed scubiee python so fastembed/pipeline import cleanly:
  C:/Users/usman/AppData/Roaming/uv/tools/scubiee/Scripts/python.exe \
     scripts/perf/probe_bug1_newcomers.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure packages/ importable when run from repo root with any python.
_REPO = Path(__file__).resolve().parents[2]
_PKGS = _REPO / "packages"
if str(_PKGS) not in sys.path:
    sys.path.insert(0, str(_PKGS))

from pipeline.merkle import canonical_relpath  # noqa: E402
from pipeline.paths import collect_index_relpaths  # noqa: E402
from pipeline.store import PipelineStore  # noqa: E402


def main() -> int:
    root = _REPO
    print(f"[probe] os.name={os.name}  root={root}")

    store = PipelineStore(root)
    print(f"[probe] store.base   = {store.base}")
    print(f"[probe] merkle_path  = {store.merkle_path}  exists={store.merkle_path.exists()}")

    old = store.load_merkle()  # canonical keys
    meta = {}
    try:
        import json

        if store.meta_path.exists():
            meta = json.loads(store.meta_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[probe] meta read failed: {e}")

    index_rel = collect_index_relpaths(
        root, fast=bool(meta.get("fast")), fast_roots=meta.get("fast_roots")
    )  # posix, original case

    merkle_keys = set(old)

    # --- CURRENT (buggy) subtraction, exactly as incremental.py does it ---
    buggy_newcomers = sorted(index_rel - merkle_keys)

    # --- FIXED subtraction: canonicalize the index side before diffing ---
    fixed_newcomers = sorted(p for p in index_rel if canonical_relpath(p) not in merkle_keys)

    print("\n==================== BUG-1 STAGE PROBE ====================")
    print(f"indexed files (collect_index_relpaths) : {len(index_rel)}")
    print(f"merkle keys   (load_merkle, canonical) : {len(merkle_keys)}")
    print(f"newcomers under CURRENT subtraction    : {len(buggy_newcomers)}")
    print(f"newcomers under FIXED   subtraction    : {len(fixed_newcomers)}")

    # Intersection of the two raw key spaces (should be ~0 on Windows)
    raw_overlap = len(index_rel & merkle_keys)
    print(f"raw key overlap (index ∩ merkle)       : {raw_overlap}")

    print("\n-- sample index_rel keys (posix / original case) --")
    for k in sorted(index_rel)[:5]:
        print(f"   {k!r}   -> canonical {canonical_relpath(k)!r}")

    print("\n-- sample merkle keys (as stored) --")
    for k in sorted(merkle_keys)[:5]:
        print(f"   {k!r}")

    print("\n-- sample buggy newcomers (should be real files already indexed) --")
    for k in buggy_newcomers[:5]:
        exists = (root / k).is_file()
        print(f"   {k!r}   file_exists={exists}   canonical_in_merkle={canonical_relpath(k) in merkle_keys}")

    # Count how many "buggy newcomers" are actually already-indexed files
    # (present on disk AND whose canonical form is already in the merkle).
    false_newcomers = [
        k
        for k in buggy_newcomers
        if (root / k).is_file() and canonical_relpath(k) in merkle_keys
    ]

    print(f"\nfalse newcomers (already indexed, mis-flagged): {len(false_newcomers)}")

    print("\n==================== VERDICT ====================")
    # BUG-1 is the mis-flagging: files already in the merkle (canonically)
    # that leak into `newcomers` only because the raw key space differs.
    bug_confirmed = len(false_newcomers) > 0 and len(buggy_newcomers) > len(
        fixed_newcomers
    )
    if bug_confirmed:
        over = len(buggy_newcomers) - len(fixed_newcomers)
        print(f"BUG-1 CONFIRMED: current subtraction over-reports {over} newcomers")
        print(f"                {len(false_newcomers)} of them are already-indexed files that")
        print("                 leak in as 'new' due to posix/original-case vs canonical")
        print("                 backslash/lowercase key mismatch on Windows.")
    else:
        print("BUG-1 NOT reproduced in this environment (keys may align).")
    print("=================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
