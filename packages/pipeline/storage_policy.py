"""Disk accounting, FAISS compaction, and managed-repository eviction policy."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from pipeline.project_id import (
    collection_name_for_project,
    load_registry,
    projects_root,
    save_registry,
)
from pipeline.vectordb import VectorDatabase, default_vectordb_root

DEFAULT_COMPACT_DEAD_RATIO = 0.25
_PROJECT_ID = re.compile(r"^ce_[A-Za-z0-9_-]+$")


def _store_dir(project_id: str) -> Path:
    if not _PROJECT_ID.fullmatch(project_id):
        raise ValueError(f"invalid project_id: {project_id!r}")
    return (projects_root() / project_id).resolve()


def _tree_bytes(path: Path) -> int:
    if not path.is_dir():
        return path.stat().st_size if path.is_file() else 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _project_entry(project_id: str) -> dict[str, Any]:
    raw = (load_registry().get("projects") or {}).get(project_id)
    return dict(raw) if isinstance(raw, dict) else {}


def _collection_location(
    project_id: str, store_dir: Path, entry: dict[str, Any]
) -> tuple[Path, str | None]:
    meta = _read_json(store_dir / "meta.json")
    root = Path(meta.get("vectordb_root") or default_vectordb_root()).resolve()
    name = meta.get("collection")
    if not isinstance(name, str) or not name:
        paths = entry.get("paths")
        if isinstance(paths, list) and paths:
            name = collection_name_for_project(Path(paths[0]), project_id)
        else:
            name = None
    return root, name


def _vector_counts(collection_dir: Path) -> tuple[int | None, int | None]:
    if not (collection_dir / "meta.json").is_file():
        return None, None
    meta = _read_json(collection_dir / "meta.json")
    dead_ids = meta.get("dead_ids")
    dead = len(dead_ids) if isinstance(dead_ids, list) else 0
    # ``ids.npy`` keeps every vector id (including tombstones). ``meta.ntotal`` is
    # rewritten from FAISS ``index.ntotal`` on save — which is live-only when
    # ``remove_ids`` succeeded, or still full when it failed. Prefer ids length.
    ids_path = collection_dir / "ids.npy"
    if ids_path.is_file():
        try:
            import numpy as np

            n_ids = int(np.load(ids_path).shape[0])
            return max(0, n_ids - dead), dead
        except Exception:  # noqa: BLE001
            pass
    ntotal = meta.get("ntotal")
    if isinstance(ntotal, (int, float)):
        # Fall back: assume ntotal is live when remove_ids worked.
        return int(ntotal), dead
    return None, dead


def repo_storage_status(project_id: str) -> dict[str, Any]:
    """Return project-store and vector-collection disk usage."""
    store_dir = _store_dir(project_id)
    entry = _project_entry(project_id)
    vector_root, collection_name = _collection_location(project_id, store_dir, entry)
    collection_dir = (
        vector_root / "collections" / collection_name
        if collection_name
        else vector_root / "collections" / "__missing__"
    )
    store_bytes = _tree_bytes(store_dir)
    vector_bytes = _tree_bytes(collection_dir) if collection_name else 0
    live, dead = _vector_counts(collection_dir) if collection_name else (None, None)
    total_vectors = (live or 0) + (dead or 0)
    reclaimable = (
        int(vector_bytes * (dead or 0) / total_vectors) if total_vectors else 0
    )
    last_access = entry.get("last_access_at")
    if last_access is None:
        last_access = entry.get("updated_at")
    return {
        "project_id": project_id,
        "store_dir": str(store_dir),
        "collection": collection_name,
        "collection_dir": str(collection_dir) if collection_name else None,
        "store_bytes": store_bytes,
        "vector_bytes": vector_bytes,
        "bytes_used": store_bytes + vector_bytes,
        "reclaimable_bytes": reclaimable,
        "live_vectors": live,
        "dead_vectors": dead,
        "last_access": last_access,
        "pinned": bool(entry.get("pinned", False)),
        "managed": bool(entry.get("managed", False)),
    }


def compact_collection(project_id: str, *, force: bool = False) -> dict[str, Any]:
    """Rebuild and serialize a project's collection when tombstones justify it."""
    before = repo_storage_status(project_id)
    collection_name = before.get("collection")
    collection_dir_value = before.get("collection_dir")
    if not collection_name or not collection_dir_value:
        return {
            "project_id": project_id,
            "compacted": False,
            "reason": "collection_not_found",
            "before": before,
            "after": before,
            "bytes_reclaimed": 0,
        }
    collection_dir = Path(collection_dir_value)
    if not (collection_dir / "meta.json").is_file():
        return {
            "project_id": project_id,
            "compacted": False,
            "reason": "collection_not_found",
            "before": before,
            "after": before,
            "bytes_reclaimed": 0,
        }

    live = int(before.get("live_vectors") or 0)
    dead = int(before.get("dead_vectors") or 0)
    ratio = dead / max(live + dead, 1)
    threshold = float(
        os.environ.get("CTX_FAISS_COMPACT_DEAD_RATIO", DEFAULT_COMPACT_DEAD_RATIO)
    )
    if not force and (dead == 0 or ratio < threshold):
        return {
            "project_id": project_id,
            "compacted": False,
            "reason": "below_dead_ratio_threshold",
            "dead_ratio": ratio,
            "threshold": threshold,
            "before": before,
            "after": before,
            "bytes_reclaimed": 0,
        }

    vector_root = collection_dir.parent.parent
    database = VectorDatabase(vector_root)
    collection = database.get_collection(str(collection_name))
    removed_tombstones = collection.compact()
    database.save_collection(collection.name)
    after = repo_storage_status(project_id)
    return {
        "project_id": project_id,
        "compacted": True,
        "dead_ratio": ratio,
        "threshold": threshold,
        "tombstones_removed": removed_tombstones,
        "before": before,
        "after": after,
        "bytes_reclaimed": max(0, before["bytes_used"] - after["bytes_used"]),
    }


def collect_unused_repos(
    *,
    max_bytes: int | None = None,
    inactive_days: float | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Select LRU managed stores and optionally delete their stored artifacts."""
    if max_bytes is not None and max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if inactive_days is not None and inactive_days < 0:
        raise ValueError("inactive_days must be non-negative")

    registry = load_registry()
    projects = registry.get("projects") or {}
    statuses: list[dict[str, Any]] = []
    for project_id, raw in projects.items():
        if (
            not isinstance(raw, dict)
            or not raw.get("managed")
            or raw.get("pinned")
        ):
            continue
        status = repo_storage_status(str(project_id))
        if status["last_access"] is not None:
            statuses.append(status)
    statuses.sort(key=lambda item: (float(item["last_access"]), item["project_id"]))

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    if inactive_days is not None:
        cutoff = time.time() - inactive_days * 86400
        for status in statuses:
            if float(status["last_access"]) <= cutoff:
                selected.append(status)
                selected_ids.add(status["project_id"])

    total_bytes = sum(
        repo_storage_status(str(project_id))["bytes_used"]
        for project_id, raw in projects.items()
        if isinstance(raw, dict) and raw.get("managed")
    )
    if max_bytes is not None and total_bytes > max_bytes:
        needed = total_bytes - max_bytes
        planned = sum(item["bytes_used"] for item in selected)
        for status in statuses:
            if planned >= needed:
                break
            if status["project_id"] in selected_ids:
                continue
            selected.append(status)
            selected_ids.add(status["project_id"])
            planned += status["bytes_used"]

    candidates = [
        {
            "project_id": item["project_id"],
            "last_access": item["last_access"],
            "bytes_used": item["bytes_used"],
            "reclaimable_bytes": item["bytes_used"],
            "store_dir": item["store_dir"],
            "collection": item["collection"],
        }
        for item in sorted(
            selected, key=lambda item: (float(item["last_access"]), item["project_id"])
        )
    ]
    deleted: list[str] = []
    bytes_reclaimed = 0
    if not dry_run:
        for item in selected:
            before = int(item["bytes_used"])
            collection_dir = item.get("collection_dir")
            collection_name = item.get("collection")
            if collection_dir and collection_name:
                collection_path = Path(collection_dir)
                try:
                    VectorDatabase(collection_path.parent.parent).drop_collection(
                        str(collection_name)
                    )
                except (OSError, ValueError, json.JSONDecodeError):
                    shutil.rmtree(collection_path, ignore_errors=True)
            shutil.rmtree(Path(item["store_dir"]), ignore_errors=True)
            bytes_reclaimed += before
            deleted.append(item["project_id"])
            raw = projects.get(item["project_id"])
            if isinstance(raw, dict):
                raw["evicted_at"] = time.time()
                raw["store_evicted"] = True
        save_registry(registry)

    return {
        "dry_run": dry_run,
        "max_bytes": max_bytes,
        "inactive_days": inactive_days,
        "total_bytes": total_bytes,
        "candidates": candidates,
        "planned_reclaim_bytes": sum(item["bytes_used"] for item in candidates),
        "deleted": deleted,
        "bytes_reclaimed": bytes_reclaimed,
    }
