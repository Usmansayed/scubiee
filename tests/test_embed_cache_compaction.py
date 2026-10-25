"""Embed cache: float32 rows in RAM, snapshot empties the log, dead rows pruned."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import numpy as np
import pytest

import pipeline.embedder as embedder_mod
from pipeline.embedder import (
    Embedder,
    cache_needs_compaction,
    text_key,
    write_cache_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]


def _bare(cache_path: Path) -> Embedder:
    emb = Embedder.__new__(Embedder)
    emb.cache_path = cache_path
    emb.cache = {}
    emb._cache_dirty = []
    emb.cache_flush_every = 1_000_000
    emb._npz_sig = None
    return emb


def _vec(seed: int, dim: int = 8) -> np.ndarray:
    return np.random.default_rng(seed).normal(size=dim).astype(np.float32)


def _put(emb: Embedder, key: str, vec: np.ndarray) -> None:
    emb.cache[key] = vec
    emb._queue_cache(key, vec)


def _log_keys(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [json.loads(line)["key"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _npz_keys(path: Path) -> list[str]:
    with np.load(path.with_suffix(".npz"), allow_pickle=True) as data:
        return [str(k) for k in data["keys"].tolist()]


def test_loaded_rows_are_float32_arrays(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    first = _bare(cache)
    for i in range(5):
        _put(first, f"k{i}", _vec(i))
    first.save_cache_npz()

    again = _bare(cache)
    again._load_cache()
    assert set(again.cache) == {f"k{i}" for i in range(5)}
    for i in range(5):
        row = again.cache[f"k{i}"]
        assert isinstance(row, np.ndarray) and row.dtype == np.float32
        assert np.array_equal(row, _vec(i))


def test_snapshot_empties_log_and_restart_keeps_everything(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    emb = _bare(cache)
    for i in range(10):
        _put(emb, f"k{i}", _vec(i))
    emb.flush_cache()
    assert len(_log_keys(cache)) == 10
    assert emb.save_cache_npz() is not None
    assert _log_keys(cache) == []
    assert sorted(_npz_keys(cache)) == sorted(f"k{i}" for i in range(10))

    _put(emb, "k10", _vec(10))
    emb.flush_cache()
    restarted = _bare(cache)
    restarted._load_cache()
    assert len(restarted.cache) == 11
    assert np.array_equal(restarted.cache["k10"], _vec(10))


def test_dirty_rows_are_flushed_before_snapshot(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    emb = _bare(cache)
    _put(emb, "pending", _vec(1))
    emb.save_cache_npz()
    assert emb._cache_dirty == []
    assert "pending" in _npz_keys(cache)


def test_two_processes_snapshots_merge_not_clobber(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    a = _bare(cache)
    b = _bare(cache)
    _put(a, "from_a", _vec(1))
    a.save_cache_npz()
    _put(b, "from_b", _vec(2))
    b.save_cache_npz()
    assert sorted(_npz_keys(cache)) == ["from_a", "from_b"]
    _put(a, "from_a2", _vec(3))
    a.save_cache_npz()
    assert sorted(_npz_keys(cache)) == ["from_a", "from_a2", "from_b"]


def test_rows_appended_by_another_writer_survive_truncation(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    a = _bare(cache)
    other = _bare(cache)
    _put(a, "mine", _vec(1))
    a.flush_cache()
    _put(other, "theirs", _vec(2))
    other.flush_cache()
    a.save_cache_npz()
    assert _log_keys(cache) == []
    restarted = _bare(cache)
    restarted._load_cache()
    assert {"mine", "theirs"} <= set(restarted.cache)
    assert np.array_equal(restarted.cache["theirs"], _vec(2))


def test_prune_keeps_live_and_newest_extra(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    emb = _bare(cache)
    for i in range(20):
        _put(emb, f"dead{i}", _vec(i))
    for i in range(5):
        _put(emb, f"live{i}", _vec(100 + i))
    emb.save_cache_npz(live_keys={f"live{i}" for i in range(5)}, keep_extra=3)
    kept = set(_npz_keys(cache))
    assert kept == {f"live{i}" for i in range(5)} | {"dead17", "dead18", "dead19"}
    assert set(emb.cache) == kept
    for i in range(5):
        assert np.array_equal(emb.cache[f"live{i}"], _vec(100 + i))


def test_prune_keep_extra_zero(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    emb = _bare(cache)
    _put(emb, "dead", _vec(1))
    _put(emb, "live", _vec(2))
    emb.save_cache_npz(live_keys={"live"}, keep_extra=0)
    assert _npz_keys(cache) == ["live"]


def test_failed_snapshot_keeps_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    emb = _bare(cache)
    _put(emb, "a", _vec(1))
    emb.flush_cache()

    def boom(*_a, **_k):
        raise PermissionError("locked")

    monkeypatch.setattr(embedder_mod.os, "replace", boom)
    monkeypatch.setattr(embedder_mod.time, "sleep", lambda *_a: None)
    assert emb.save_cache_npz() is None
    assert _log_keys(cache) == ["a"]
    assert not cache.with_suffix(".npz").exists()
    assert not list(tmp_path.glob("*.tmp.npz"))


def test_legacy_compressed_object_key_snapshot_loads(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    keys = np.asarray(["x", "y"], dtype=object)
    vecs = np.stack([_vec(1), _vec(2)])
    np.savez_compressed(cache.with_suffix(".npz"), keys=keys, vecs=vecs)
    emb = _bare(cache)
    emb._load_cache()
    assert np.array_equal(emb.cache["y"], _vec(2))
    _put(emb, "z", _vec(3))
    emb.save_cache_npz()
    assert sorted(_npz_keys(cache)) == ["x", "y", "z"]


def test_corrupt_snapshot_falls_back_to_log(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    cache.with_suffix(".npz").write_bytes(b"not a zip")
    cache.write_text(json.dumps({"key": "a", "embedding": [1.0, 2.0]}) + "\n", encoding="utf-8")
    emb = _bare(cache)
    emb._load_cache()
    assert np.allclose(emb.cache["a"], [1.0, 2.0])


def test_mixed_dims_keep_majority(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    emb = _bare(cache)
    _put(emb, "a", _vec(1, 8))
    _put(emb, "b", _vec(2, 8))
    _put(emb, "odd", _vec(3, 4))
    assert emb.save_cache_npz() is not None
    assert sorted(_npz_keys(cache)) == ["a", "b"]


def test_needs_compaction(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    emb = _bare(cache)
    for i in range(10):
        _put(emb, f"k{i}", _vec(i))
    emb.save_cache_npz()
    live = {f"k{i}" for i in range(10)}
    assert not cache_needs_compaction(cache, live, keep_extra=4)
    assert cache_needs_compaction(cache, set(), keep_extra=4) is False  # 10 dead <= 64 floor
    assert cache_needs_compaction(cache, set(), keep_extra=4, log_bytes=10**9) is False
    cache.write_text("x" * 100, encoding="utf-8")
    assert cache_needs_compaction(cache, live, log_bytes=50)


def test_needs_compaction_many_dead(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    keys = [f"k{i}" for i in range(200)]
    write_cache_snapshot(cache, {k: _vec(i) for i, k in enumerate(keys)})
    assert cache_needs_compaction(cache, set(keys[:10]), keep_extra=50)
    assert not cache_needs_compaction(cache, set(keys[:150]), keep_extra=50)


def test_embed_one_returns_a_copy(tmp_path: Path) -> None:
    emb = _bare(tmp_path / "embed_cache.jsonl")
    emb.backend = "fastembed"
    emb.dim = None
    emb.format_query = lambda t: "Q: " + t
    calls: list[list[str]] = []

    def fake_encode(batch):
        calls.append(list(batch))
        return np.ones((len(batch), 4), dtype=np.float32)

    emb._encode_batch = fake_encode
    first = emb.embed_one("hello", is_query=True)
    first *= 0
    second = emb.embed_one("hello", is_query=True)
    assert np.array_equal(second, np.ones(4, dtype=np.float32))
    second *= 0
    third = emb.embed_one("hello", is_query=True)
    assert np.array_equal(third, np.ones(4, dtype=np.float32))
    assert len(calls) == 1
    key = text_key("q:Q: hello")
    assert isinstance(emb.cache[key], np.ndarray)
    assert _log_keys(emb.cache_path) == [key]


def test_concurrent_threads_append_and_snapshot(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    writers = [_bare(cache) for _ in range(4)]
    errors: list[BaseException] = []

    def work(idx: int, emb: Embedder) -> None:
        try:
            for j in range(40):
                _put(emb, f"w{idx}-{j}", _vec(idx * 1000 + j))
                emb.flush_cache()
                if j % 10 == 9:
                    emb.save_cache_npz()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i, w)) for i, w in enumerate(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    restarted = _bare(cache)
    restarted._load_cache()
    expected = {f"w{i}-{j}" for i in range(4) for j in range(40)}
    assert expected <= set(restarted.cache)
    assert np.array_equal(restarted.cache["w3-39"], _vec(3039))


def test_concurrent_processes_append_and_snapshot(tmp_path: Path) -> None:
    cache = tmp_path / "embed_cache.jsonl"
    script = textwrap.dedent(
        """
        import sys
        from pathlib import Path
        import numpy as np
        from pipeline.embedder import Embedder
        cache = Path(sys.argv[1]); tag = sys.argv[2]
        emb = Embedder.__new__(Embedder)
        emb.cache_path = cache; emb.cache = {}; emb._cache_dirty = []
        emb.cache_flush_every = 10**6; emb._npz_sig = None
        for j in range(60):
            v = np.full(8, float(j), dtype=np.float32)
            k = f"{tag}-{j}"
            emb.cache[k] = v; emb._queue_cache(k, v); emb.flush_cache()
            if j % 15 == 14:
                emb.save_cache_npz()
        """
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "packages") + os.pathsep + env.get("PYTHONPATH", "")
    procs = [
        subprocess.Popen([sys.executable, "-c", script, str(cache), f"p{i}"], env=env)
        for i in range(3)
    ]
    for p in procs:
        assert p.wait(timeout=180) == 0
    restarted = _bare(cache)
    restarted._load_cache()
    expected = {f"p{i}-{j}" for i in range(3) for j in range(60)}
    missing = expected - set(restarted.cache)
    assert not missing, sorted(missing)[:10]
