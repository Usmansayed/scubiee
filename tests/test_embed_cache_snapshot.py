"""The embed cache survives a restart without rewriting the .npz on every save.

``embed_many`` used to re-compress the whole cache into ``embed_cache.npz`` after
every call (~1.5s at 10k entries), which alone ate a third of the 5s save→map
budget. The ``.jsonl`` append log already persists each new row, so small
batches now skip the snapshot rewrite — which is only safe if a restart replays
log rows appended after the last snapshot.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

from pipeline.embedder import Embedder


def _bare_embedder(cache_path: Path) -> Embedder:
    """An Embedder with only the cache machinery initialised (no model load)."""
    emb = Embedder.__new__(Embedder)
    emb.cache_path = cache_path
    emb.cache = {}
    emb._cache_dirty = []
    emb.cache_flush_every = 1_000_000
    return emb


def test_restart_replays_log_rows_written_after_the_snapshot(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"

    first = _bare_embedder(cache)
    first.cache["d:old"] = [0.1, 0.2]
    first._cache_dirty.append(("d:old", [0.1, 0.2]))
    first.flush_cache()
    snapshot = first.save_cache_npz()
    assert snapshot is not None and snapshot.is_file()

    # A later small batch: appended to the log, snapshot deliberately not rewritten.
    time.sleep(0.02)
    first._cache_dirty.append(("d:new", [0.3, 0.4]))
    first.flush_cache()
    os.utime(cache, (time.time() + 1, time.time() + 1))  # log strictly newer

    restarted = _bare_embedder(cache)
    restarted._load_cache()

    assert "d:old" in restarted.cache, "snapshot rows must load"
    assert "d:new" in restarted.cache, "log rows after the snapshot must not be lost"
    assert np.allclose(restarted.cache["d:new"], [0.3, 0.4])


def test_snapshot_rows_win_over_duplicate_log_rows(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    cache.write_text(json.dumps({"key": "d:k", "embedding": [9.0, 9.0]}) + "\n", encoding="utf-8")

    snap = _bare_embedder(cache)
    snap.cache["d:k"] = [1.0, 1.0]
    snap.save_cache_npz()
    os.utime(cache, (time.time() + 1, time.time() + 1))

    restarted = _bare_embedder(cache)
    restarted._load_cache()
    assert np.allclose(restarted.cache["d:k"], [1.0, 1.0])


def test_log_only_cache_still_loads(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    cache.write_text(
        "\n".join(
            json.dumps({"key": f"d:{i}", "embedding": [float(i)]}) for i in range(3)
        )
        + "\n",
        encoding="utf-8",
    )
    restarted = _bare_embedder(cache)
    restarted._load_cache()
    assert set(restarted.cache) == {"d:0", "d:1", "d:2"}
