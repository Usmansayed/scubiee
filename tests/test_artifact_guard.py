"""Artifact publication must detect corruption before CE claims readiness."""

from __future__ import annotations


def test_atomic_write_replaces_complete_payload(tmp_path) -> None:
    from pipeline.artifact_guard import atomic_write_text

    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob("*.tmp"))


def test_manifest_detects_tampered_artifact(tmp_path) -> None:
    from pipeline.artifact_guard import publish_manifest, validate_manifest

    artifact = tmp_path / "chunks.jsonl"
    artifact.write_text('{"id": 1}\n', encoding="utf-8")
    publish_manifest(tmp_path, [artifact])
    assert validate_manifest(tmp_path)["ok"] is True

    artifact.write_text('{"id": 2}\n', encoding="utf-8")
    report = validate_manifest(tmp_path)
    assert report["ok"] is False
    assert report["reason"] == "checksum_mismatch"


def test_load_engine_refuses_checksum_invalid_manifest(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline.artifact_guard import publish_manifest
    from pipeline.engine import clear_engines, load_engine
    from pipeline.project_id import resolve_project

    repo = tmp_path / "repo"
    repo.mkdir()
    ref = resolve_project(repo)
    store = ref.store_dir
    store.mkdir(parents=True, exist_ok=True)
    chunks = store / "chunks.jsonl"
    graph = store / "graph.json"
    chunks.write_text('{"id":0,"file":"a.py","start_line":1,"end_line":1,"text":"x"}\n', encoding="utf-8")
    graph.write_text('{"nodes":[],"edges":[]}\n', encoding="utf-8")
    (store / "meta.json").write_text('{"chunks":1}\n', encoding="utf-8")
    publish_manifest(store, [chunks, graph, store / "meta.json"])
    chunks.write_text('{"id":0,"file":"a.py","start_line":1,"end_line":1,"text":"tampered"}\n', encoding="utf-8")
    clear_engines()
    try:
        load_engine(repo)
        raise AssertionError("expected RuntimeError for invalid publication")
    except RuntimeError as exc:
        assert "checksum-invalid" in str(exc) or "publication" in str(exc).lower()
