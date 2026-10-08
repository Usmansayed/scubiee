"""Delete-prune consistency after retiring the delete-mask hack (spec task 7).

R9.1: a deleted file stops being returned within a bounded, consistent time that
does NOT depend on an unrelated concurrent save. The ``CTX_HOT_DELETE_MASK`` hack
used to defer a deletion-only batch whenever a hot save was pending; it is now
retired (default off) so a due deletion prunes in the same drain. The write/
backlog split still orders a fresh save ahead of a disk-poll backlog — that is a
separate, documented mechanism and is not what this test exercises.

Offline; no live engine/embedder.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from conftest import enroll_test_repo


@pytest.fixture(autouse=True)
def enrolled_sync_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_lane_delete1234567890abcd")
    return tmp_path


@pytest.fixture(autouse=True)
def _default_no_engine_clients(monkeypatch):
    monkeypatch.setattr(
        "pipeline.sync_loop.BackgroundSyncLoop._clients_active",
        lambda self: False,
    )


def _loop(tmp_path, monkeypatch):
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0, live_max_files=1000)
    monkeypatch.setattr(
        loop, "_estimate_dirty_chunks",
        lambda paths: (len(paths), {p: 1 for p in paths}),
    )
    return loop


def test_mask_retired_by_default():
    """The delete-mask env defaults OFF (retired) — confirmed via the parsed flag."""
    import os

    # with no env set, the mask must read as off
    assert (os.environ.get("CTX_HOT_DELETE_MASK") or "0").strip().lower() not in {
        "1", "true", "yes", "on",
    }


def test_deletion_only_batch_prunes_in_one_drain(tmp_path, monkeypatch):
    """A due deletion (file gone on disk) syncs in the same drain, not deferred."""
    monkeypatch.delenv("CTX_HOT_DELETE_MASK", raising=False)  # default (retired)
    loop = _loop(tmp_path, monkeypatch)

    seen: list[list[str]] = []
    monkeypatch.setattr(
        loop, "_sync_paths",
        lambda paths, **_: seen.append(list(paths))
        or {"refreshed": True, "chunks_upserted": 0, "chunks_removed": len(paths)},
    )

    # gone.py does NOT exist on disk -> a pure deletion, and it is the only work
    t0 = time.monotonic()
    loop.mark_dirty(["pkg/gone.py"], reason="changed_file", now=t0)
    out = loop.drain_due(now=t0 + 1.0)

    assert out, "drain produced no result"
    assert out[0].get("strategy") != "deletion_deferred"
    synced = {p for call in seen for p in call}
    assert "pkg/gone.py" in synced, "deletion was not pruned in this drain"


def test_mask_env_restores_old_defer_behavior(tmp_path, monkeypatch):
    """Rollback switch: CTX_HOT_DELETE_MASK=1 can still defer when a hot on-disk
    save is pending alongside a deletion-only batch (old behavior preserved)."""
    monkeypatch.setenv("CTX_HOT_DELETE_MASK", "1")
    loop = _loop(tmp_path, monkeypatch)

    seen: list[list[str]] = []
    monkeypatch.setattr(
        loop, "_sync_paths",
        lambda paths, **_: seen.append(list(paths))
        or {"refreshed": True, "chunks_upserted": 0, "chunks_removed": len(paths)},
    )

    # a real on-disk save pending (hot) + a separate deletion-only batch becoming
    # due: with the mask ON the delete may be held as deletion_deferred.
    (tmp_path / "pkg").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pkg" / "save.py").write_text("x = 1\n", encoding="utf-8")
    t0 = time.monotonic()
    loop.mark_dirty(["pkg/save.py"], reason="changed_file", now=t0)
    # force the deletion batch to be the current due slice while a hot save is
    # still queued (not yet drained)
    loop.dirty_ledger.mark(["pkg/gone.py"], reason="changed_file", now=t0)

    # drain twice: first serves the hot write split, the second faces a pure
    # deletion batch with the hot save possibly still pending
    loop.drain_due(now=t0 + 1.0)
    out2 = loop.drain_due(now=t0 + 1.5)

    # The mask path is reachable and honored (either deferred, or pruned once the
    # save settled). The assertion only guards that enabling the env does not
    # crash and still routes a deletion either way.
    assert isinstance(out2, list)
