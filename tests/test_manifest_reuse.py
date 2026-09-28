"""Issue 4: a hot save must not re-hash unchanged 34MB graph artifacts."""

from __future__ import annotations

import os

import pipeline.artifact_guard as ag


def test_unchanged_files_keep_checksum_changed_files_rehash(tmp_path, monkeypatch):
    store = tmp_path
    big = store / "graph.json"
    small = store / "chunks.jsonl"
    big.write_text("g" * 1000, encoding="utf-8")
    small.write_text("a\n", encoding="utf-8")
    first = ag.publish_manifest(store, [big, small])
    assert ag.validate_manifest(store)["ok"]

    hashed: list[str] = []
    real = ag._checksum
    monkeypatch.setattr(ag, "_checksum", lambda p: hashed.append(p.name) or real(p))
    small.write_text("a\nb\n", encoding="utf-8")
    second = ag.publish_manifest(store, [big, small], previous=ag.read_manifest(store))
    assert hashed == ["chunks.jsonl"]  # graph.json reused (same size + mtime_ns)
    assert second["artifacts"]["graph.json"] == first["artifacts"]["graph.json"]
    assert ag.validate_manifest(store)["ok"]


def test_same_size_rewrite_with_new_mtime_is_rehashed(tmp_path):
    store = tmp_path
    f = store / "meta.json"
    f.write_text("{1}", encoding="utf-8")
    ag.publish_manifest(store, [f])
    f.write_text("{2}", encoding="utf-8")  # same size, different content
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    ag.publish_manifest(store, [f], previous=ag.read_manifest(store))
    assert ag.validate_manifest(store)["ok"]
