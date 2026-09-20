"""Cheap publication republish when checksums drift but generation is coherent."""

from __future__ import annotations

import json
from pathlib import Path


def test_republish_manifest_if_coherent_rewrites_stale_checksum(tmp_path: Path) -> None:
    from pipeline.artifact_guard import (
        MANIFEST_NAME,
        publish_manifest,
        republish_manifest_if_coherent,
        validate_manifest,
    )

    store = tmp_path / "store"
    store.mkdir()
    (store / "chunks.jsonl").write_text('{"i":0}\n{"i":1}\n', encoding="utf-8")
    (store / "graph.json").write_text("{}", encoding="utf-8")
    (store / "merkle.json").write_text("{}", encoding="utf-8")
    (store / "meta.json").write_text(
        json.dumps({"chunks": 2, "root": str(tmp_path)}),
        encoding="utf-8",
    )
    publish_manifest(
        store,
        [
            store / "chunks.jsonl",
            store / "graph.json",
            store / "meta.json",
            store / "merkle.json",
        ],
    )
    assert validate_manifest(store).get("ok")

    # Stale checksum: mutate chunks without updating the manifest.
    (store / "chunks.jsonl").write_text('{"i":0}\n{"i":1}\n{"i":2}\n', encoding="utf-8")
    (store / "meta.json").write_text(
        json.dumps({"chunks": 3, "root": str(tmp_path)}),
        encoding="utf-8",
    )
    assert not validate_manifest(store).get("ok")

    out = republish_manifest_if_coherent(store)
    assert out.get("ok") is True
    assert out.get("republished") is True
    assert validate_manifest(store).get("ok") is True
    assert (store / MANIFEST_NAME).is_file()
