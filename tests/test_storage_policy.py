from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from conductor.bm25_index import BM25Index
from pipeline.incremental import incremental_sync
from pipeline.project_id import save_registry
from pipeline.storage_policy import (
    collect_unused_repos,
    compact_collection,
    repo_storage_status,
)
from pipeline.store import ChunkRecord, PipelineStore
from pipeline.vectordb import VectorDatabase


def _chunk(chunk_id: int, file: str, text: str) -> ChunkRecord:
    return ChunkRecord(
        id=chunk_id,
        file=file,
        start_line=1,
        end_line=2,
        symbol=file.removesuffix(".py"),
        text=text,
        enriched=text,
    )


def _project(
    tmp_path: Path,
    monkeypatch,
    project_id: str,
    *,
    last_access: float | None = None,
    pinned: bool = False,
) -> tuple[Path, Path, VectorDatabase]:
    home = tmp_path / "home"
    vdb_root = home / "vectordb"
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setenv("CTX_VECTORDB_ROOT", str(vdb_root))
    root = tmp_path / project_id
    root.mkdir()
    store_dir = home / "projects" / project_id
    store_dir.mkdir(parents=True)
    save_registry(
        {
            "projects": {
                project_id: {
                    "paths": [str(root)],
                    "managed": True,
                    "pinned": pinned,
                    "last_access_at": last_access,
                }
            }
        }
    )
    return root, store_dir, VectorDatabase(vdb_root)


def test_removed_file_cleans_chunks_bm25_graph_and_faiss_payloads(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    keep_file = root / "keep.py"
    gone_file = root / "gone.py"
    keep_file.write_text("def keep():\n    return 1\n", encoding="utf-8")
    gone_file.write_text("def gone():\n    return 2\n", encoding="utf-8")

    base = tmp_path / "store"
    vdb = VectorDatabase(tmp_path / "vdb")
    store = PipelineStore(root, base_dir=base, vdb=vdb, resolve=False)
    chunks = [
        _chunk(10, "keep.py", "surviving_token"),
        _chunk(20, "gone.py", "deleted_token"),
    ]
    store.save_chunks(chunks)
    store.save_merkle(
        {
            "keep.py": __import__("pipeline.merkle", fromlist=["file_sha256"]).file_sha256(
                keep_file
            ),
            "gone.py": __import__("pipeline.merkle", fromlist=["file_sha256"]).file_sha256(
                gone_file
            ),
        }
    )
    store.save_meta({"dim": 8, "bits": 4, "chunks": 2, "fast": False})
    col = store.upsert_vectors(
        np.eye(2, 8, dtype=np.float32), chunks, dim=8, bits=4
    )
    graph = {
        "nodes": [
            {
                "id": "keep",
                "label": "keep",
                "type": "function",
                "source_file": "keep.py",
                "source_location": "L1",
            },
            {
                "id": "gone",
                "label": "gone",
                "type": "function",
                "source_file": "gone.py",
                "source_location": "L1",
            },
        ],
        "edges": [],
        "hyperedges": [],
    }
    (base / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    gone_file.unlink()

    result = incremental_sync(
        root, base_dir=base, vdb=vdb, force_files=["gone.py"]
    )

    assert result.error is None
    assert result.chunks_removed == 1
    remaining = store.load_chunks()
    assert [(chunk.id, chunk.file) for chunk in remaining] == [(10, "keep.py")]
    bm25 = BM25Index([chunk.enriched for chunk in remaining])
    assert bm25.search("deleted_token", top_k=1) == []
    graph_after = json.loads((base / "graph.json").read_text(encoding="utf-8"))
    assert all(
        node.get("source_file") != "gone.py"
        for node in graph_after.get("nodes", [])
    )
    reloaded = VectorDatabase(vdb.root).get_collection(col.name)
    assert reloaded.ids == [10]
    assert 20 not in reloaded.payloads
    assert [row["id"] for row in reloaded.get([10])] == [10]


def test_compaction_rebuild_preserves_live_vector_ids(tmp_path: Path) -> None:
    vdb = VectorDatabase(tmp_path / "vdb")
    col = vdb.create_collection("stable", dim=8, cwd=tmp_path)
    col.add(
        np.eye(4, 8, dtype=np.float32),
        [101, 205, 309, 412],
        [{"chunk_id": value} for value in [101, 205, 309, 412]],
    )
    assert col.delete([205, 412]) == 2
    assert col.dead_count == 2

    col.compact()
    vdb.save_collection(col.name)
    reloaded = VectorDatabase(vdb.root).get_collection(col.name)

    assert reloaded.ids == [101, 309]
    assert reloaded.dead_count == 0
    assert set(reloaded.payloads) == {101, 309}


def test_dead_ratio_triggers_project_collection_compaction(
    tmp_path: Path, monkeypatch
) -> None:
    project_id = "ce_deadbeef"
    root, store_dir, vdb = _project(tmp_path, monkeypatch, project_id)
    store = PipelineStore(
        root, base_dir=store_dir, vdb=vdb, project_id=project_id
    )
    chunks = [_chunk(i, f"f{i}.py", f"text {i}") for i in range(4)]
    store.save_chunks(chunks)
    col = store.upsert_vectors(
        np.eye(4, 8, dtype=np.float32), chunks, dim=8, bits=4
    )
    store.save_meta(
        {
            "collection": col.name,
            "vectordb_root": str(vdb.root),
            "chunks": 4,
        }
    )
    col.delete([0, 1])
    vdb.save_collection(col.name)
    monkeypatch.setenv("CTX_FAISS_COMPACT_DEAD_RATIO", "0.6")

    skipped = compact_collection(project_id)

    assert skipped["compacted"] is False
    assert skipped["reason"] == "below_dead_ratio_threshold"
    assert skipped["after"]["dead_vectors"] == 2
    monkeypatch.setenv("CTX_FAISS_COMPACT_DEAD_RATIO", "0.4")

    result = compact_collection(project_id)

    assert result["compacted"] is True
    assert result["before"]["dead_vectors"] == 2
    assert result["after"]["dead_vectors"] == 0
    assert result["after"]["live_vectors"] == 2


def test_repo_storage_status_accounts_for_store_and_collection_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    project_id = "ce_accounting"
    root, store_dir, vdb = _project(tmp_path, monkeypatch, project_id)
    store = PipelineStore(
        root, base_dir=store_dir, vdb=vdb, project_id=project_id
    )
    chunk = _chunk(7, "a.py", "payload")
    store.save_chunks([chunk])
    col = store.upsert_vectors(
        np.ones((1, 8), dtype=np.float32), [chunk], dim=8, bits=4
    )
    store.save_meta(
        {
            "collection": col.name,
            "vectordb_root": str(vdb.root),
            "chunks": 1,
        }
    )

    status = repo_storage_status(project_id)

    assert status["store_bytes"] >= store.chunks_path.stat().st_size
    assert status["vector_bytes"] > 0
    assert status["bytes_used"] == status["store_bytes"] + status["vector_bytes"]
    assert status["live_vectors"] == 1
    assert status["dead_vectors"] == 0
    assert status["managed"] is True
    assert status["pinned"] is False


def test_eviction_candidates_exclude_pinned_and_are_lru_ordered(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("CTX_HOME", str(home))
    now = time.time()
    entries = {
        "ce_newer": {
            "paths": [str(tmp_path / "newer")],
            "managed": True,
            "last_access_at": now - 20 * 86400,
        },
        "ce_oldest": {
            "paths": [str(tmp_path / "oldest")],
            "managed": True,
            "last_access_at": now - 40 * 86400,
        },
        "ce_pinned": {
            "paths": [str(tmp_path / "pinned")],
            "managed": True,
            "pinned": True,
            "last_access_at": now - 60 * 86400,
        },
        "ce_unmanaged": {
            "paths": [str(tmp_path / "unmanaged")],
            "managed": False,
            "last_access_at": now - 80 * 86400,
        },
    }
    save_registry({"projects": entries})
    for project_id in entries:
        store = home / "projects" / project_id
        store.mkdir(parents=True)
        (store / "data.bin").write_bytes(project_id.encode("utf-8"))

    result = collect_unused_repos(inactive_days=10, dry_run=True)

    assert [item["project_id"] for item in result["candidates"]] == [
        "ce_oldest",
        "ce_newer",
    ]
    assert all(item["project_id"] != "ce_pinned" for item in result["candidates"])


def test_eviction_dry_run_never_deletes_project_store(
    tmp_path: Path, monkeypatch
) -> None:
    project_id = "ce_dryrun"
    _, store_dir, _ = _project(
        tmp_path,
        monkeypatch,
        project_id,
        last_access=time.time() - 90 * 86400,
    )
    marker = store_dir / "keep.me"
    marker.write_bytes(b"do not delete")

    result = collect_unused_repos(inactive_days=30, dry_run=True)

    assert result["deleted"] == []
    assert result["bytes_reclaimed"] == 0
    assert marker.is_file()
