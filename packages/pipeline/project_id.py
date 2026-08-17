"""Hybrid project identity: in-repo id file + global registry + projects/<id>/.

Resolve order:
  1. ``<repo>/.context-engine/id.json`` → project_id
  2. Registry lookup by absolute path
  3. Mint new id, write both

Path moves: id file wins; registry paths updated.
Id deleted but path known: recover from registry and rewrite id file.
Both gone: mint (caller reindexes into empty store).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ID_DIR_NAME = ".context-engine"
ID_FILE_NAME = "id.json"
REGISTRY_NAME = "registry.json"


def context_engine_home() -> Path:
    import os

    override = os.environ.get("CTX_HOME", "").strip()
    if override:
        return Path(override).resolve()
    return Path.home() / ".context-engine"


def id_file_path(root: Path) -> Path:
    return root.resolve() / ID_DIR_NAME / ID_FILE_NAME


def registry_path() -> Path:
    return context_engine_home() / REGISTRY_NAME


def projects_root() -> Path:
    return context_engine_home() / "projects"


def legacy_indexes_root() -> Path:
    return context_engine_home() / "indexes"


def mint_project_id(root: Path) -> str:
    """One-shot unique id (persist; do not recompute)."""
    payload = f"{root.resolve()}|{time.time_ns()}|{secrets.token_hex(8)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"ce_{digest}"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically replace a JSON document in its destination directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_id_file(root: Path) -> str | None:
    data = _read_json(id_file_path(root))
    pid = data.get("project_id")
    if isinstance(pid, str) and pid.startswith("ce_") and len(pid) > 5:
        return pid
    return None


def write_id_file(root: Path, project_id: str) -> Path:
    path = id_file_path(root)
    _write_json(
        path,
        {
            "version": 1,
            "project_id": project_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
    return path


def load_registry() -> dict[str, Any]:
    data = _read_json(registry_path())
    if "projects" not in data or not isinstance(data["projects"], dict):
        data["projects"] = {}
    return data


def save_registry(data: dict[str, Any]) -> None:
    _write_json(registry_path(), data)


def _norm_path(p: Path | str) -> str:
    return str(Path(p).resolve())


def _registry_path_identity_trusted(project_id: str, path: Path) -> bool:
    """Trust a registry path alias only when live ``id.json`` exactly matches.

    Missing or malformed identity files are treated as stale/untrusted so a
    vacated path (even with an empty ``.context-engine/`` directory) cannot
    inherit a moved repository's durable ID.
    """
    return read_id_file(path) == project_id


def find_id_by_path(abs_path: str, registry: dict[str, Any] | None = None) -> str | None:
    reg = registry if registry is not None else load_registry()
    target = _norm_path(abs_path)
    for pid, meta in (reg.get("projects") or {}).items():
        if not isinstance(meta, dict):
            continue
        paths = meta.get("paths") or []
        if not isinstance(paths, list):
            continue
        for p in paths:
            try:
                if _norm_path(p) != target:
                    continue
                if _registry_path_identity_trusted(str(pid), Path(p)):
                    return str(pid)
            except OSError:
                continue
    return None


def update_registry(project_id: str, root: Path) -> None:
    reg = load_registry()
    projects = reg.setdefault("projects", {})
    entry = projects.get(project_id) if isinstance(projects.get(project_id), dict) else {}
    entry = dict(entry)
    paths = list(entry.get("paths") or []) if isinstance(entry.get("paths"), list) else []
    abs_root = _norm_path(root)
    # Keep aliases that still carry this durable identity. A moved repository's
    # vacated path must not remain an alias that can identify a new checkout.
    live_aliases: list[str] = []
    for path in paths:
        normalized = _norm_path(path)
        if normalized == abs_root:
            continue
        if read_id_file(Path(path)) == project_id:
            live_aliases.append(normalized)
    paths = [abs_root] + [path for path in live_aliases if path != abs_root]
    entry.update(
        {
            "paths": paths[:8],
            "updated_at": time.time(),
            "name": Path(abs_root).name,
        }
    )
    projects[project_id] = entry
    save_registry(reg)


def legacy_repo_key(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]


def _dir_has_index_data(path: Path) -> bool:
    return (path / "chunks.jsonl").is_file() or (path / "meta.json").is_file()


def migrate_legacy_index(project_id: str, root: Path, dest: Path) -> bool:
    """Move path-hash index into projects/<id>/ if dest empty and legacy exists."""
    legacy = legacy_indexes_root() / legacy_repo_key(root)
    if not legacy.is_dir() or not _dir_has_index_data(legacy):
        return False
    if _dir_has_index_data(dest):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not any(dest.iterdir()):
        dest.rmdir()
    if dest.exists():
        return False
    shutil.move(str(legacy), str(dest))
    return True


@dataclass(frozen=True)
class ProjectRef:
    root: Path
    project_id: str
    store_dir: Path
    id_file: Path
    migrated_legacy: bool = False


def resolve_project(root: Path, *, migrate: bool = True) -> ProjectRef:
    """Ensure id file + registry + projects/<id>/ exist; migrate legacy indexes."""
    root = root.resolve()
    abs_root = _norm_path(root)
    migrated = False

    pid = read_id_file(root)
    if not pid:
        pid = find_id_by_path(abs_root)
        if pid:
            write_id_file(root, pid)
        else:
            pid = mint_project_id(root)
            write_id_file(root, pid)

    update_registry(pid, root)
    store_dir = (projects_root() / pid).resolve()
    store_dir.mkdir(parents=True, exist_ok=True)

    if migrate:
        migrated = migrate_legacy_index(pid, root, store_dir)

    return ProjectRef(
        root=root,
        project_id=pid,
        store_dir=store_dir,
        id_file=id_file_path(root),
        migrated_legacy=migrated,
    )


def collection_name_for_project(root: Path, project_id: str) -> str:
    """Stable FAISS collection name keyed by project_id (survives path moves)."""
    import re

    base = Path(root).name
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", base).strip("_").lower() or "repo"
    # project_id is ce_<32 hex>; use 16 chars after prefix for compactness
    digest = project_id.replace("ce_", "")[:16]
    return f"{safe}_{digest}"


def index_is_usable(store_dir: Path, *, collection_name: str | None = None) -> bool:
    """True when chunks + graph.json exist and any publication manifest is valid."""
    if not (store_dir / "chunks.jsonl").is_file():
        return False
    if not (store_dir / "graph.json").is_file():
        return False
    meta = _read_json(store_dir / "meta.json")
    if meta.get("chunks", 0) == 0 and not (store_dir / "chunks.jsonl").stat().st_size:
        return False
    # Prefer collection name from meta when present
    _ = collection_name or meta.get("collection")
    # Fail closed when a manifest exists but is corrupt/mismatched.
    from pipeline.artifact_guard import MANIFEST_NAME, validate_manifest

    if (store_dir / MANIFEST_NAME).is_file():
        report = validate_manifest(store_dir)
        if not report.get("ok"):
            return False
    return True
