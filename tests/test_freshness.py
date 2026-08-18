"""Freshness strategy + Merkle/git conflict policy tests."""

from __future__ import annotations

import time
from pathlib import Path

from pipeline.freshness import check_freshness, choose_strategy, verify_merkle_leaves
from pipeline.hot_patch import hot_patch_texts, read_lines
from pipeline.merkle import diff_hashes, file_sha256, scan_file_hashes
from pipeline.store import ChunkRecord


def test_choose_strategy_thresholds():
    assert choose_strategy(0)[0] == "none"
    assert choose_strategy(1)[0] == "incremental"
    assert choose_strategy(40)[0] == "incremental"
    assert choose_strategy(41)[0] == "background"
    assert choose_strategy(200)[0] == "background"
    assert choose_strategy(201)[0] == "background"
    assert choose_strategy(60, corpus_size=100)[0] == "full"
    assert choose_strategy(1, corpus_size=1)[0] == "incremental"


def test_merkle_detects_edit(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    snap = scan_file_hashes(tmp_path)
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    cur = scan_file_hashes(tmp_path)
    d = diff_hashes(snap, cur)
    assert not d.unchanged
    assert "a.py" in d.modified


def test_check_freshness_clean_vs_dirty(tmp_path: Path):
    (tmp_path / "a.py").write_text("print(1)\n", encoding="utf-8")
    snap = scan_file_hashes(tmp_path)
    report = check_freshness(tmp_path, snap)
    assert report.clean
    assert report.strategy == "none"

    (tmp_path / "a.py").write_text("print(2)\n", encoding="utf-8")
    report2 = check_freshness(tmp_path, snap)
    assert not report2.clean
    assert report2.strategy == "incremental"
    assert "a.py" in report2.diff.modified


def test_disk_beats_vectors_policy():
    strategy, reason = choose_strategy(3)
    assert strategy == "incremental"
    assert "sync before search" in reason


def test_merkle_verify_catches_edit_without_git(tmp_path: Path):
    """gitignored-style: porcelain wouldn't see it; merkle leaves still catch it."""
    f = tmp_path / "secret.py"
    f.write_text("a=1\n", encoding="utf-8")
    snap = {"secret.py": file_sha256(f)}
    mtimes = {"secret.py": f.stat().st_mtime}
    assert verify_merkle_leaves(tmp_path, snap, file_mtimes=mtimes).unchanged

    time.sleep(0.05)
    f.write_text("a=2\n", encoding="utf-8")
    d = verify_merkle_leaves(tmp_path, snap, file_mtimes=mtimes)
    assert not d.unchanged
    assert "secret.py" in d.modified


def test_fast_roots_include_packages_and_lib():
    from pipeline.paths import fast_roots_from_env

    roots = fast_roots_from_env()
    assert any(r.startswith("lib") for r in roots)
    assert any(r.startswith("packages") for r in roots)
    # Fixture trees are intentionally excluded from fast roots.
    assert not any(r.startswith("testdata") for r in roots)


def test_hot_patch_reads_disk(tmp_path: Path):
    f = tmp_path / "mod.py"
    f.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    chunks = [
        ChunkRecord(
            id=0,
            file="mod.py",
            start_line=1,
            end_line=2,
            symbol=None,
            text="OLD",
            enriched="OLD",
        )
    ]
    texts = ["OLD"]
    patched, touched = hot_patch_texts(tmp_path, chunks, texts, ["mod.py"])
    assert touched == [0]
    assert "alpha" in patched[0]
    assert "beta" in patched[0]
    assert read_lines(f, 2, 3) == "beta\ngamma"
