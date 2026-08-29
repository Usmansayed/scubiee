"""Tests for hybrid project identity + incremental graph patch."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.project_id import (
    _norm_path,
    git_common_dir,
    id_file_path,
    index_is_usable,
    load_registry,
    mint_project_id,
    projects_root,
    read_id_file,
    resolve_project,
    save_registry,
    update_registry,
    write_id_file,
)
from pipeline.store import ChunkRecord, PipelineStore


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


def test_mint_unique(tmp_path: Path):
    a = mint_project_id(tmp_path)
    b = mint_project_id(tmp_path)
    assert a.startswith("ce_")
    assert a != b


def test_resolve_mints_and_writes(ce_home: Path, tmp_path: Path):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    ref = resolve_project(repo)
    assert ref.project_id.startswith("ce_")
    assert id_file_path(repo).is_file()
    assert read_id_file(repo) == ref.project_id
    assert ref.store_dir == (ce_home / "projects" / ref.project_id).resolve()
    assert ref.store_dir.is_dir()
    reg = load_registry()
    assert ref.project_id in reg["projects"]
    assert _norm_path(repo) in reg["projects"][ref.project_id]["paths"]


def test_resolve_reuses_id_file(ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "r"
    repo.mkdir()
    write_id_file(repo, "ce_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    # Orphan id.json is untrusted until registry/store match; force-trust for this case.
    monkeypatch.setenv("CTX_TRUST_ID_FILE", "1")
    ref = resolve_project(repo)
    assert ref.project_id == "ce_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_nested_folder_does_not_mint_or_write_id(ce_home: Path, tmp_path: Path):
    repo = tmp_path / "app"
    repo.mkdir()
    parent = resolve_project(repo)
    nested = repo / "test query"
    nested.mkdir()
    ref = resolve_project(nested)
    assert ref.project_id == parent.project_id
    assert ref.root == repo.resolve()
    assert not (nested / ".scubiee" / "id.json").exists()


def test_write_id_file_refuses_missing_directory(tmp_path: Path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        write_id_file(missing, "ce_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    assert not missing.exists()


def test_missing_id_json_does_not_recover_from_registry(ce_home: Path, tmp_path: Path):
    """Safety beats recovering a deleted identity file via a registry alias."""
    repo = tmp_path / "r"
    repo.mkdir()
    ref1 = resolve_project(repo)
    pid = ref1.project_id
    id_file_path(repo).unlink()
    assert read_id_file(repo) is None
    assert (repo / ".scubiee").is_dir()
    from pipeline.project_id import find_id_by_path

    assert find_id_by_path(str(repo.resolve())) is None
    ref2 = resolve_project(repo)
    assert ref2.project_id != pid
    assert read_id_file(repo) == ref2.project_id


def test_stale_registry_alias_without_id_json_is_not_trusted(
    ce_home: Path, tmp_path: Path
):
    from pipeline.project_id import find_id_by_path, save_registry

    old = tmp_path / "old"
    old.mkdir()
    ref = resolve_project(old)
    vacated = tmp_path / "vacated"
    vacated.mkdir()
    (vacated / ".scubiee").mkdir()
    save_registry(
        {
            "projects": {
                ref.project_id: {
                    "paths": [str(vacated.resolve()), str(old.resolve())],
                    "updated_at": 1.0,
                    "name": "vacated",
                }
            }
        }
    )
    assert find_id_by_path(str(vacated.resolve())) is None
    fresh = resolve_project(vacated)
    assert fresh.project_id != ref.project_id


def test_both_missing_mints_new(ce_home: Path, tmp_path: Path):
    repo = tmp_path / "r"
    repo.mkdir()
    ref1 = resolve_project(repo)
    id_file_path(repo).unlink()
    from pipeline.project_id import save_registry

    save_registry({"projects": {}})
    ref2 = resolve_project(repo)
    assert ref2.project_id != ref1.project_id


def test_legacy_migration(ce_home: Path, tmp_path: Path):
    from pipeline.project_id import legacy_indexes_root, legacy_repo_key

    repo = tmp_path / "legacyrepo"
    repo.mkdir()
    legacy = legacy_indexes_root() / legacy_repo_key(repo)
    legacy.mkdir(parents=True)
    (legacy / "chunks.jsonl").write_text("{}\n", encoding="utf-8")
    (legacy / "meta.json").write_text("{}", encoding="utf-8")
    ref = resolve_project(repo, migrate=True)
    assert (ref.store_dir / "chunks.jsonl").is_file()
    assert not legacy.exists()


def test_index_is_usable(tmp_path: Path):
    assert index_is_usable(tmp_path) is False
    (tmp_path / "chunks.jsonl").write_text('{"id":0}\n', encoding="utf-8")
    assert index_is_usable(tmp_path) is False
    (tmp_path / "graph.json").write_text("{}", encoding="utf-8")
    assert index_is_usable(tmp_path) is True


def _seed_store(repo: Path, store: PipelineStore, rel: str, body: str) -> None:
    (repo / rel).write_text(body, encoding="utf-8")
    store.save_chunks(
        [
            ChunkRecord(
                id=0,
                file=rel,
                start_line=1,
                end_line=2,
                symbol="f",
                text=body[:40],
                enriched=body[:40],
            )
        ]
    )
    store.save_meta(
        {
            "dim": 8,
            "bits": 4,
            "chunks": 1,
            "fast": True,
            "collection": "test_col",
            "embed_model": "nomic-ai/CodeRankEmbed",
        }
    )
    store.save_merkle({rel: "oldhash"})


def test_incremental_uses_patch_not_full_extract(ce_home: Path, tmp_path: Path):
    from pipeline.incremental import incremental_sync

    repo = tmp_path / "code"
    repo.mkdir()
    ref = resolve_project(repo)
    store = PipelineStore(repo, base_dir=ref.store_dir, project_id=ref.project_id)
    _seed_store(repo, store, "a.py", "def a():\n    return 1\n")
    (store.base / "graph.json").write_text(
        json.dumps({"directed": False, "multigraph": False, "graph": {}, "nodes": [], "links": []}),
        encoding="utf-8",
    )
    (repo / "a.py").write_text("def a():\n    return 2\n", encoding="utf-8")

    extract_calls: list = []

    def fake_extract(paths, root=None, cache_root=None):
        extract_calls.append(list(paths))
        return {"nodes": [], "edges": [], "hyperedges": []}

    fake_patch = MagicMock()
    with patch("pipeline.incremental.extract", side_effect=fake_extract), patch(
        "pipeline.incremental.patch_and_save_graph", fake_patch
    ), patch("pipeline.incremental.build_and_save_graph") as fake_full, patch(
        "pipeline.incremental.chunk_file_from_ir", return_value=[]
    ), patch("pipeline.incremental.graphify_to_repo_ir", return_value=MagicMock()), patch.object(
        PipelineStore, "get_collection", return_value=None
    ), patch.object(PipelineStore, "upsert_vectors", return_value=MagicMock()), patch.object(
        PipelineStore, "save_chunks"
    ), patch.object(PipelineStore, "save_merkle"), patch.object(
        PipelineStore, "save_meta"
    ), patch("pipeline.capability.ensure_cards", return_value=0):
        incremental_sync(repo, force_files=["a.py"], base_dir=ref.store_dir)

    assert fake_patch.called
    assert not fake_full.called
    assert len(extract_calls) == 1
    assert all(Path(p).name == "a.py" for p in extract_calls[0])


def test_incremental_missing_graph_falls_back(ce_home: Path, tmp_path: Path):
    from pipeline.incremental import incremental_sync

    repo = tmp_path / "code2"
    repo.mkdir()
    ref = resolve_project(repo)
    store = PipelineStore(repo, base_dir=ref.store_dir, project_id=ref.project_id)
    _seed_store(repo, store, "b.py", "x=1\n")
    # deliberately no graph.json

    with patch(
        "pipeline.incremental.extract",
        return_value={"nodes": [], "edges": [], "hyperedges": []},
    ), patch("pipeline.incremental.build_and_save_graph") as fake_full, patch(
        "pipeline.incremental.patch_and_save_graph"
    ) as fake_patch, patch(
        "pipeline.incremental.chunk_file_from_ir", return_value=[]
    ), patch("pipeline.incremental.graphify_to_repo_ir", return_value=MagicMock()), patch(
        "pipeline.incremental.collect_index_paths",
        return_value=[repo / "b.py"],
    ), patch.object(PipelineStore, "get_collection", return_value=None), patch.object(
        PipelineStore, "upsert_vectors", return_value=MagicMock()
    ), patch.object(PipelineStore, "save_chunks"), patch.object(
        PipelineStore, "save_merkle"
    ), patch.object(PipelineStore, "save_meta"), patch(
        "pipeline.capability.ensure_cards", return_value=0
    ):
        incremental_sync(repo, force_files=["b.py"], base_dir=ref.store_dir)

    assert fake_full.called
    assert not fake_patch.called


def test_reinstall_recovers_id_from_usable_store(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    ref1 = resolve_project(repo)
    pid = ref1.project_id
    (ref1.store_dir / "chunks.jsonl").write_text('{"id":0}\n', encoding="utf-8")
    (ref1.store_dir / "graph.json").write_text("{}", encoding="utf-8")
    (ref1.store_dir / "meta.json").write_text(
        json.dumps({"root": str(repo.resolve()), "chunks": 1}),
        encoding="utf-8",
    )

    id_file_path(repo).unlink()
    assert read_id_file(repo) is None

    ref2 = resolve_project(repo)
    assert ref2.project_id == pid
    assert read_id_file(repo) == pid


def test_git_family_reconciles_existing_duplicate_id_files(
    ce_home: Path, tmp_path: Path,
) -> None:
    from pipeline.project_id import mint_project_id, projects_root, save_registry

    repo = tmp_path / "main"
    linked = tmp_path / "linked"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"], check=True
    )
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(linked), "-b", "linked"],
        check=True,
        capture_output=True,
    )

    main_id = mint_project_id(repo)
    duplicate_id = mint_project_id(linked)
    write_id_file(repo, main_id)
    write_id_file(linked, duplicate_id)
    common = git_common_dir(repo)
    assert common is not None
    save_registry(
        {
            "projects": {
                main_id: {
                    "paths": [str(repo.resolve())],
                    "managed": True,
                    "git_common_dir": str(common),
                    "last_access_at": 100.0,
                },
                duplicate_id: {
                    "paths": [str(linked.resolve())],
                    "managed": True,
                    "git_common_dir": str(common),
                    "last_access_at": 1.0,
                },
            }
        }
    )
    (projects_root() / main_id).mkdir(parents=True, exist_ok=True)
    (projects_root() / duplicate_id).mkdir(parents=True, exist_ok=True)

    reconciled = resolve_project(linked)
    assert reconciled.project_id == main_id
    assert read_id_file(linked) == main_id


def test_auto_index_gate(monkeypatch: pytest.MonkeyPatch):
    from pipeline.sync_loop import auto_index_enabled

    monkeypatch.setenv("CTX_AUTO_INDEX", "0")
    assert auto_index_enabled() is False
    monkeypatch.setenv("CTX_AUTO_INDEX", "1")
    assert auto_index_enabled() is True


def test_update_registry_promotes_enrolled_indexed_project_to_managed(
    ce_home: Path, tmp_path: Path,
) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    pid = mint_project_id(repo)
    write_id_file(repo, pid)
    save_registry(
        {
            "projects": {
                pid: {
                    "paths": [str(repo.resolve())],
                    "name": "proj",
                }
            }
        }
    )

    update_registry(pid, repo)

    entry = load_registry()["projects"][pid]
    assert entry["managed"] is True
    assert entry["lifecycle_state"] == "active"
