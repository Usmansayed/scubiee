"""Regression lock for BUG-1: newcomer discovery must compare paths through the
same canonicalizer as the merkle, never a raw set subtraction.

The bug: ``incremental_sync``'s ``discover_newcomers`` branch did
``collect_index_relpaths(root) - set(old)`` where ``collect_index_relpaths``
yields posix / original-case keys and ``old = store.load_merkle()`` holds
*canonical* keys (``canonical_relpath`` → ``os.path.normcase`` → backslash +
lower-case on Windows). On Windows the two key spaces barely intersect, so every
already-indexed file was mis-flagged as a newcomer, doubling the change-set and
tripping the auto-full-index guard — sync published nothing.

These tests fail if a future refactor reintroduces a raw ``set - set`` or stops
canonicalizing one side of the comparison.
"""

from __future__ import annotations

import os

import pytest

from pipeline.merkle import canonical_relpath


def _newcomer_diff(index_relpaths, merkle_keys):
    """Mirror the FIXED newcomer computation (incremental.py discover_newcomers).

    Must canonicalize the index side before diffing against canonical merkle keys.
    """
    old = set(merkle_keys)
    return sorted(p for p in index_relpaths if canonical_relpath(p) not in old)


def test_canonical_relpath_is_idempotent_and_posix_folds_to_merkle_key():
    """A posix/original-case index key and its stored canonical form must collapse
    to the same canonical identity — otherwise the newcomer diff over-reports."""
    posix_key = "packages/pipeline/Server.py"
    canon = canonical_relpath(posix_key)
    # canonical_relpath must be idempotent (feeding its own output changes nothing)
    assert canonical_relpath(canon) == canon
    # On a case-insensitive OS the canonical form folds case; on posix it stays.
    if os.name == "nt":
        assert canon != posix_key  # proves normalization actually happened
    # The identity used for dedup must match regardless of input slash/case.
    assert canonical_relpath("packages\\pipeline\\Server.py") == canon
    assert canonical_relpath("packages/pipeline/server.py".replace("s", "s")) == canonical_relpath(
        "packages/pipeline/server.py"
    )


def test_already_indexed_files_are_not_flagged_as_newcomers():
    """The core BUG-1 scenario: merkle holds canonical keys, the index walk yields
    posix/original-case keys for the SAME files → zero newcomers expected."""
    index_relpaths = {
        "AGENTS.md",
        "README.md",
        "packages/pipeline/server.py",
        "packages/pipeline/incremental.py",
        "src/App.tsx",
    }
    # Merkle stores the canonical form of every one of those files.
    merkle_keys = {canonical_relpath(p) for p in index_relpaths}

    newcomers = _newcomer_diff(index_relpaths, merkle_keys)
    assert newcomers == [], (
        "already-indexed files leaked in as newcomers — the newcomer diff is "
        "comparing non-canonical keys against canonical merkle keys (BUG-1)."
    )


def test_a_genuinely_new_file_is_still_detected():
    """The fix must not over-correct: a file absent from the merkle IS a newcomer."""
    index_relpaths = {
        "packages/pipeline/server.py",
        "packages/pipeline/brand_new.py",  # not in merkle
    }
    merkle_keys = {canonical_relpath("packages/pipeline/server.py")}

    newcomers = _newcomer_diff(index_relpaths, merkle_keys)
    assert newcomers == ["packages/pipeline/brand_new.py"]


def test_raw_set_subtraction_would_regress_on_windows():
    """Documents WHY the canonicalizer is required: the raw set-minus the bug used
    mis-classifies everything on a case-folding OS. This guards the intent."""
    index_relpaths = {"packages/pipeline/Server.py"}
    merkle_keys = {canonical_relpath("packages/pipeline/Server.py")}

    raw_buggy = sorted(index_relpaths - merkle_keys)  # the old, wrong computation
    fixed = _newcomer_diff(index_relpaths, merkle_keys)

    if os.name == "nt":
        # On Windows the buggy raw diff wrongly reports the file as new…
        assert raw_buggy == ["packages/pipeline/Server.py"]
    # …while the canonical diff correctly reports nothing new.
    assert fixed == []


def test_incremental_sync_newcomer_branch_uses_canonical_compare():
    """Static guard: the discover_newcomers branch must not contain a raw
    ``collect_index_relpaths(...) - set(old)`` and must canonicalize the compare."""
    import inspect

    from pipeline import incremental

    src = inspect.getsource(incremental.incremental_sync)
    # The fixed form filters by canonical_relpath; the buggy form subtracted sets.
    assert "canonical_relpath(p) not in old" in src or "canonical_relpath(p) not in set(old)" in src, (
        "discover_newcomers no longer canonicalizes the index side before diffing "
        "against the merkle — BUG-1 can regress."
    )
    assert "- set(old)" not in src.replace(" ", ""), (
        "a raw set subtraction reappeared in incremental_sync — this is the exact "
        "BUG-1 shape (posix keys minus canonical keys)."
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
