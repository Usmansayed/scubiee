"""Persistent repository lifecycle built on the global project registry."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from pipeline.project_id import (
    find_id_by_path,
    index_is_usable,
    load_registry,
    projects_root,
    read_id_file,
    resolve_project,
    save_registry,
)
from pipeline.registration import mark_registered

ACTIVE = "active"
PAUSED = "paused"
NEVER_INDEX = "never_index"
UNMANAGED = "unmanaged"


def _root(root: Path | str) -> Path:
    return Path(root).resolve()


def _project(root: Path) -> tuple[str | None, dict[str, Any]]:
    project_id = read_id_file(root) or find_id_by_path(str(root))
    if not project_id:
        return None, {}
    entry = (load_registry().get("projects") or {}).get(project_id)
    return project_id, dict(entry) if isinstance(entry, dict) else {}


def _update(project_id: str, **values: Any) -> dict[str, Any]:
    registry = load_registry()
    projects = registry.setdefault("projects", {})
    current = projects.get(project_id)
    entry = dict(current) if isinstance(current, dict) else {}
    entry.update(values)
    entry["updated_at"] = time.time()
    projects[project_id] = entry
    save_registry(registry)
    return entry


def _result(project_id: str, entry: dict[str, Any], **extra: Any) -> dict[str, Any]:
    paths = entry.get("paths") if isinstance(entry.get("paths"), list) else []
    root = paths[0] if paths else ""
    result = {
        "ok": True,
        "project_id": project_id,
        "root": root,
        "store_dir": str((projects_root() / project_id).resolve()),
        "state": entry.get("lifecycle_state", ACTIVE),
        "git_common_dir": entry.get("git_common_dir"),
        "initialized_at": entry.get("initialized_at"),
        "last_activated_at": entry.get("last_activated_at"),
        "last_access_at": entry.get("last_access_at"),
    }
    result.update(extra)
    return result


def git_common_dir(root: Path) -> Path | None:
    """Return the shared Git administration directory for a checkout."""
    root = _root(root)
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def managed_state(root: Path) -> str:
    """Return active, paused, never_index, or unmanaged."""
    project_id, entry = _project(_root(root))
    if not project_id or not entry or not entry.get("managed"):
        return UNMANAGED
    state = entry.get("lifecycle_state", ACTIVE)
    return state if state in {ACTIVE, PAUSED, NEVER_INDEX} else ACTIVE


def lifecycle_status(root: Path | str) -> dict[str, Any]:
    """Return lifecycle metadata without creating project identity or state."""
    canonical = _root(root)
    project_id, entry = _project(canonical)
    state = managed_state(canonical)
    return {
        "project_id": project_id,
        "root": str(canonical),
        "state": state,
        "pause_reason": entry.get("pause_reason"),
        "timestamps": {
            key: entry.get(key)
            for key in (
                "initialized_at",
                "last_activated_at",
                "last_access_at",
                "paused_at",
                "last_sync_at",
                "updated_at",
            )
        },
    }


def initialize_repo(
    root: Path,
    *,
    index: bool = True,
    always_allow: bool = True,
) -> dict[str, Any]:
    """Admit a repository and reconcile an existing usable index."""
    root = _root(root)
    project_id, existing = _project(root)
    if project_id and existing.get("lifecycle_state") == NEVER_INDEX:
        entry = _update(project_id, last_access_at=time.time())
        return _result(
            project_id,
            entry,
            ok=False,
            indexed=False,
            reconciled=False,
            error=NEVER_INDEX,
        )

    ref = resolve_project(root)
    now = time.time()
    mark_registered(ref.project_id, root, always_allow=always_allow)
    current = (load_registry().get("projects") or {}).get(ref.project_id, {})
    initialized_at = (
        current.get("initialized_at") if isinstance(current, dict) else None
    ) or now
    common = git_common_dir(root)
    lifecycle_state = (
        PAUSED if existing.get("lifecycle_state") == PAUSED else ACTIVE
    )
    lifecycle_values: dict[str, Any] = {
        "managed": True,
        "lifecycle_state": lifecycle_state,
        "initialized_at": initialized_at,
        "last_access_at": now,
        "git_common_dir": str(common) if common else None,
    }
    if lifecycle_state == ACTIVE:
        lifecycle_values.update(last_activated_at=now, pause_reason=None)
    entry = _update(ref.project_id, **lifecycle_values)

    indexed = False
    reconciled = False
    chunks = 0
    if index:
        try:
            if index_is_usable(ref.store_dir):
                from pipeline.incremental import incremental_sync

                sync = incremental_sync(root, base_dir=ref.store_dir)
                sync_data = sync.to_dict()
                if sync_data.get("error"):
                    return _result(
                        ref.project_id,
                        entry,
                        ok=False,
                        indexed=False,
                        reconciled=True,
                        sync=sync_data,
                        error=sync_data["error"],
                    )
                reconciled = True
            else:
                from pipeline.indexer import index_repo

                stats = index_repo(root, force=False, fast=False)
                chunks = int(stats.chunks)
                indexed = True
        except Exception as exc:  # noqa: BLE001
            entry = _update(
                ref.project_id,
                last_access_at=time.time(),
                last_error=str(exc),
            )
            return _result(
                ref.project_id,
                entry,
                ok=False,
                indexed=False,
                reconciled=reconciled,
                error=str(exc),
            )

    entry = _update(ref.project_id, last_access_at=time.time())
    return _result(
        ref.project_id,
        entry,
        indexed=indexed,
        reconciled=reconciled,
        chunks=chunks,
    )


def activate_repo(root: Path) -> dict[str, Any]:
    root = _root(root)
    project_id, entry = _project(root)
    if not project_id or not entry.get("managed"):
        return {
            "ok": False,
            "root": str(root),
            "state": UNMANAGED,
            "status": "requires_initialize",
            "error": "requires_initialize",
        }
    if entry.get("lifecycle_state") == NEVER_INDEX:
        entry = _update(project_id, last_access_at=time.time())
        return _result(
            project_id,
            entry,
            ok=False,
            status=NEVER_INDEX,
            error=NEVER_INDEX,
        )
    if entry.get("lifecycle_state") == PAUSED:
        entry = _update(project_id, last_access_at=time.time())
        return _result(
            project_id,
            entry,
            ok=False,
            status=PAUSED,
            error=PAUSED,
            pause_reason=entry.get("pause_reason"),
        )
    now = time.time()
    entry = _update(
        project_id,
        lifecycle_state=ACTIVE,
        last_activated_at=now,
        last_access_at=now,
        pause_reason=None,
    )
    return _result(project_id, entry, status="activated")


def pause_repo(root: Path, *, reason: str | None = None) -> dict[str, Any]:
    root = _root(root)
    project_id, entry = _project(root)
    if not project_id or not entry.get("managed"):
        return {"ok": False, "root": str(root), "state": UNMANAGED, "error": "unmanaged"}
    if entry.get("lifecycle_state") == NEVER_INDEX:
        return _result(project_id, entry)
    entry = _update(
        project_id,
        lifecycle_state=PAUSED,
        pause_reason=reason,
        paused_at=time.time(),
        last_access_at=time.time(),
    )
    return _result(project_id, entry)


def resume_repo(root: Path) -> dict[str, Any]:
    root = _root(root)
    project_id, entry = _project(root)
    if not project_id or not entry.get("managed"):
        return {
            "ok": False,
            "root": str(root),
            "state": UNMANAGED,
            "status": "requires_initialize",
            "error": "requires_initialize",
        }
    if entry.get("lifecycle_state") == NEVER_INDEX:
        return _result(
            project_id,
            entry,
            ok=False,
            status=NEVER_INDEX,
            error=NEVER_INDEX,
        )
    _update(project_id, lifecycle_state=ACTIVE, pause_reason=None)
    return activate_repo(root)


def sync_now_repo(root: Path) -> dict[str, Any]:
    root = _root(root)
    project_id, entry = _project(root)
    state = managed_state(root)
    if not project_id or state == UNMANAGED:
        return {"ok": False, "root": str(root), "state": state, "error": "unmanaged"}
    if state == NEVER_INDEX:
        return _result(project_id, entry, ok=False, error="never_index")
    from pipeline.incremental import incremental_sync

    result = incremental_sync(root, base_dir=projects_root() / project_id)
    data = result.to_dict()
    entry = _update(project_id, last_access_at=time.time(), last_sync_at=time.time())
    return _result(
        project_id,
        entry,
        ok=data.get("error") is None,
        sync=data,
        error=data.get("error"),
    )


def rebuild_repo(root: Path) -> dict[str, Any]:
    root = _root(root)
    project_id, entry = _project(root)
    state = managed_state(root)
    if not project_id or state == UNMANAGED:
        return {"ok": False, "root": str(root), "state": state, "error": "unmanaged"}
    if state == NEVER_INDEX:
        return _result(project_id, entry, ok=False, error="never_index")
    from pipeline.indexer import index_repo

    try:
        stats = index_repo(root, force=True, fast=False)
    except Exception as exc:  # noqa: BLE001
        entry = _update(
            project_id,
            last_access_at=time.time(),
            last_error=str(exc),
        )
        return _result(project_id, entry, ok=False, rebuilt=False, error=str(exc))
    entry = _update(
        project_id,
        last_access_at=time.time(),
        last_rebuilt_at=time.time(),
    )
    return _result(project_id, entry, rebuilt=True, chunks=int(stats.chunks))


def never_index_repo(root: Path, *, reason: str | None = None) -> dict[str, Any]:
    root = _root(root)
    ref = resolve_project(root)
    now = time.time()
    current = (load_registry().get("projects") or {}).get(ref.project_id, {})
    initialized_at = (
        current.get("initialized_at") if isinstance(current, dict) else None
    ) or now
    common = git_common_dir(root)
    entry = _update(
        ref.project_id,
        managed=True,
        lifecycle_state=NEVER_INDEX,
        initialized_at=initialized_at,
        last_access_at=now,
        git_common_dir=str(common) if common else None,
        never_index_reason=reason,
        always_allow=False,
        registered=False,
    )
    return _result(ref.project_id, entry)


def remove_repo(root: Path, *, delete_store: bool = False) -> dict[str, Any]:
    root = _root(root)
    project_id, entry = _project(root)
    if not project_id or not entry.get("managed"):
        return {"ok": False, "root": str(root), "state": UNMANAGED, "error": "unmanaged"}
    store = (projects_root() / project_id).resolve()
    registry = load_registry()
    registry.setdefault("projects", {}).pop(project_id, None)
    save_registry(registry)
    deleted = False
    if delete_store and store.exists():
        shutil.rmtree(store)
        deleted = True
    return {
        "ok": True,
        "project_id": project_id,
        "root": str(root),
        "state": UNMANAGED,
        "store_dir": str(store),
        "store_deleted": deleted,
    }


def list_managed_repos() -> list[dict[str, Any]]:
    registry = load_registry()
    managed: list[dict[str, Any]] = []
    for project_id, raw in (registry.get("projects") or {}).items():
        if not isinstance(raw, dict) or not raw.get("managed"):
            continue
        managed.append(_result(str(project_id), raw))
    return sorted(managed, key=lambda item: (item["root"], item["project_id"]))
