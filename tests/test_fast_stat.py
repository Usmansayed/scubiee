"""Issue 4 follow-up: the change poll's stat loop must not convoy on the GIL."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from pipeline import fast_stat as fs


def test_matches_os_stat_for_files_and_dirs(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    os.utime(f, ns=(1_790_000_000_123_456_700, 1_790_000_000_123_456_700))
    for p in (f, tmp_path):
        got = fs.fast_stat(p)
        st = os.stat(p)
        assert got is not None
        assert got.st_mtime_ns == st.st_mtime_ns
        # Stored merkle mtimes are os.stat floats; equality is what gates a rehash.
        assert got.st_mtime == st.st_mtime
        assert got.is_dir == p.is_dir() and got.is_file == p.is_file()
    assert fs.fast_stat(f).st_size == os.stat(f).st_size


def test_missing_paths_are_none(tmp_path: Path) -> None:
    assert fs.fast_stat(tmp_path / "nope.py") is None
    assert fs.fast_stat(tmp_path / "no_dir" / "nope.py") is None


def test_env_off_falls_back_to_os_stat(tmp_path: Path, monkeypatch) -> None:
    f = tmp_path / "b.py"
    f.write_text("y = 2\n", encoding="utf-8")
    monkeypatch.setenv("CTX_FAST_STAT", "0")
    monkeypatch.setattr(fs, "_impl", None)
    got = fs.fast_stat(f)
    assert got is not None and got.st_mtime == os.stat(f).st_mtime
    monkeypatch.setattr(fs, "_impl", None)  # re-detect for later tests


@pytest.mark.skipif(sys.platform != "win32", reason="the convoy is a Windows GIL-timer effect")
def test_rebuild_universe_stays_fast_with_a_busy_thread(tmp_path: Path, monkeypatch) -> None:
    """Measured live: 78ms idle, 18.3s with one busy thread, for 1167 files."""
    from pipeline import root_probe as rp

    monkeypatch.setattr(fs, "_impl", None)
    snap, mtimes = {}, {}
    for i in range(400):
        p = tmp_path / f"m{i}.py"
        p.write_text("pass\n", encoding="utf-8")
        snap[p.name] = "h"
        mtimes[p.name] = os.stat(p).st_mtime
    stop = threading.Event()

    def spin() -> None:
        x = 0
        while not stop.is_set():
            for i in range(10000):
                x += i

    th = threading.Thread(target=spin, daemon=True)
    th.start()
    try:
        time.sleep(0.1)
        t = time.perf_counter()
        current, hashed = rp._rebuild_universe(tmp_path, snap, mtimes)
        elapsed = time.perf_counter() - t
    finally:
        stop.set()
        th.join()
    assert len(current) == 400 and hashed == 0, "unchanged mtimes must not rehash"
    # os.stat here takes ~15ms per file under contention (~6s for 400).
    assert elapsed < 1.0, f"stat loop took {elapsed:.2f}s with one busy thread"


def test_session_invalidation_uses_the_cache_and_sees_new_spans(tmp_path: Path, monkeypatch) -> None:
    """The mention cache must never hide a span written after it was filled."""
    from pipeline import session_store as ss
    from pipeline.session_store import invalidate_paths, put_span, recall

    monkeypatch.setenv("CTX_SESSION_ID", "sess-a")
    (tmp_path / "pkg").mkdir()
    put_span(tmp_path, path="pkg/a.py", start_line=1, end_line=2, text="def a(): return 1")
    ss._MENTION_CACHE.clear()

    first = invalidate_paths(tmp_path, ["pkg/b.py"])
    assert first["stores_rewritten"] == 0
    assert ss._MENTION_CACHE, "stores were parsed once and cached"

    # A later span for b.py rewrites the store, so its stamp changes.
    time.sleep(0.02)
    put_span(tmp_path, path="pkg/b.py", start_line=1, end_line=2, text="def b(): return 2")
    second = invalidate_paths(tmp_path, ["pkg/b.py"])
    assert second["removed"] == 1 and second["stores_rewritten"] == 1
    assert [s["path"] for s in recall(tmp_path)["spans"]] == ["pkg/a.py"]

    # No read of unchanged stores on the next call: only a stat.
    reads: list[str] = []
    real = Path.read_text

    def _spy(self, *a, **k):
        reads.append(self.name)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", _spy)
    invalidate_paths(tmp_path, ["pkg/zzz.py"])
    assert "session_store.json" not in reads


def test_count_chunks_per_file_matches_a_full_parse(tmp_path: Path) -> None:
    import json
    from dataclasses import asdict

    from pipeline.store import ChunkRecord
    from pipeline.sync_loop import count_chunks_per_file

    rows = [
        ChunkRecord(id=1, file="pkg/a.py", start_line=1, end_line=2, symbol="a",
                    text='x = "file": "pkg/evil.py"', enriched='say "file": "z"\\'),
        ChunkRecord(id=2, file="pkg/a.py", start_line=3, end_line=4, symbol=None, text="", enriched=""),
        ChunkRecord(id=3, file='pkg/we"ird\\name.py', start_line=1, end_line=1, symbol=None,
                    text="", enriched=""),
    ]
    p = tmp_path / "chunks.jsonl"
    p.write_text("".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    assert count_chunks_per_file(p) == {"pkg/a.py": 2, 'pkg/we"ird/name.py': 1}


def test_probe_inputs_cache_sees_a_rewritten_merkle(tmp_path: Path, monkeypatch) -> None:
    """The poll's snapshot cache must never serve an old Merkle after a save."""
    from pipeline import root_probe as rp
    from pipeline.ignore import load_scubiee_ignore
    from pipeline.store import PipelineStore

    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    store = PipelineStore(repo, base_dir=tmp_path / "store", project_id="ce_x", resolve=False)
    store.save_merkle({"pkg/a.py": "h1"})
    rules = load_scubiee_ignore(repo)
    first = rp._probe_inputs(store, repo.resolve(), rules)[0]
    assert first == rp._probe_inputs(store, repo.resolve(), rules)[0]
    time.sleep(0.02)
    store.save_merkle({"pkg/a.py": "h1", "pkg/b.py": "h2"})
    second = rp._probe_inputs(store, repo.resolve(), rules)[0]
    assert len(second) == 2, "a rewritten merkle.json must be re-read"
