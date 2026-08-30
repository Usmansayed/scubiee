"""Detect copied checkouts vs moves/worktrees; fork identity on first bind."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pipeline.project_id import (
    _norm_path,
    git_common_dir,
    load_registry,
    mint_project_id,
    mutate_registry,
    read_id_file,
    write_id_file,
)


def fs_ids_match(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    if left.get("os") != right.get("os"):
        return False
    if left.get("os") == "nt":
        return left.get("file_id") == right.get("file_id") and left.get(
            "vol_serial"
        ) == right.get("vol_serial")
    return left.get("dev") == right.get("dev") and left.get("ino") == right.get("ino")


def _registry_entry(project_id: str) -> dict[str, Any]:
    entry = (load_registry().get("projects") or {}).get(project_id)
    return dict(entry) if isinstance(entry, dict) else {}


def _current_fs_id(root: Path) -> dict[str, Any] | None:
    try:
        from pipeline.hw_track import get_filesystem_id

        return get_filesystem_id(root)
    except Exception:  # noqa: BLE001
        return None


def _shared_git_family(root: Path, entry: dict[str, Any]) -> bool:
    common = git_common_dir(root)
    if common is None:
        return False
    reg_common = entry.get("git_common_dir")
    if not isinstance(reg_common, str) or not reg_common.strip():
        return False
    try:
        return _norm_path(common) == _norm_path(reg_common)
    except OSError:
        return False


def _canonical_fs_id(entry: dict[str, Any]) -> dict[str, Any] | None:
    stored = entry.get("fs_id")
    if isinstance(stored, dict):
        return stored
    for raw in entry.get("paths") or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            path = Path(raw)
        except (TypeError, ValueError):
            continue
        if not path.is_dir():
            continue
        fs_id = _current_fs_id(path)
        if fs_id:
            return fs_id
    root_val = entry.get("root")
    if isinstance(root_val, str) and root_val.strip():
        try:
            path = Path(root_val)
            if path.is_dir():
                return _current_fs_id(path)
        except OSError:
            pass
    return None


def _is_copy_of_registry_checkout(root: Path, project_id: str) -> bool:
    """True when ``id.json`` matches registry but this folder is a filesystem copy."""
    entry = _registry_entry(project_id)
    if not entry:
        return False
    if _shared_git_family(root, entry):
        return False
    canonical_fs = _canonical_fs_id(entry)
    if not canonical_fs:
        return False
    current_fs = _current_fs_id(root)
    if not current_fs:
        return False
    if fs_ids_match(canonical_fs, current_fs):
        return False
    # Legacy registry entries may use a different schema (e.g. posix on Windows).
    if canonical_fs.get("os") != current_fs.get("os"):
        return False
    # Same inode via symlink/junction → alias, not a copy.
    root_key = _norm_path(root)
    for raw in entry.get("paths") or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            if _norm_path(raw) == root_key:
                continue
            other = Path(raw).resolve()
            if other.resolve() == root.resolve():
                return False
        except OSError:
            continue
    return True


def detach_registry_path(project_id: str, root: Path | str) -> bool:
    """Remove one checkout path from a registry row without deleting the project."""
    target = _norm_path(Path(root).resolve())

    def apply(registry: dict[str, Any]) -> bool:
        projects = registry.setdefault("projects", {})
        entry = projects.get(project_id)
        if not isinstance(entry, dict):
            return False
        paths = entry.get("paths")
        if not isinstance(paths, list):
            return False
        kept = [
            str(item)
            for item in paths
            if isinstance(item, str) and _norm_path(item) != target
        ]
        if kept == paths:
            return False
        updated = dict(entry)
        updated["paths"] = kept[:8]
        projects[project_id] = updated
        return True

    return mutate_registry(apply)


def fork_copied_checkout(root: Path, *, from_project_id: str) -> str:
    """Mint a new durable ID for an independent copied checkout."""
    from pipeline.project_id import update_registry

    root = root.resolve()
    new_pid = mint_project_id(root)
    write_id_file(root, new_pid)
    detach_registry_path(from_project_id, root)
    try:
        update_registry(new_pid, root)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[scubiee] Warning: forked {new_pid} but registry attach failed: {exc}",
            file=sys.stderr,
            flush=True,
        )
    print(
        f"[scubiee] Copied checkout detected at {root} — "
        f"forked new project {new_pid} (was {from_project_id}).",
        file=sys.stderr,
        flush=True,
    )
    return new_pid


def resolve_checkout_project_id(root: Path, project_id: str | None) -> tuple[str | None, dict[str, Any]]:
    """Adjust project_id before registry attach (fork copies on first bind)."""
    root = root.resolve()
    report: dict[str, Any] = {"root": str(root), "forked": False}
    if not project_id:
        report["kind"] = "none"
        return None, report

    if not _is_copy_of_registry_checkout(root, project_id):
        report["kind"] = "keep"
        report["project_id"] = project_id
        return project_id, report

    previous = project_id
    project_id = fork_copied_checkout(root, from_project_id=previous)
    report.update(
        {
            "kind": "forked",
            "project_id": project_id,
            "from_project_id": previous,
            "forked": True,
        }
    )
    return project_id, report


def _live_paths_for_project(project_id: str, *, exclude: Path | None = None) -> list[str]:
    entry = _registry_entry(project_id)
    paths = entry.get("paths") if isinstance(entry.get("paths"), list) else []
    exclude_key = _norm_path(exclude.resolve()) if exclude is not None else None
    live: list[str] = []
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            path = Path(raw).resolve()
        except OSError:
            continue
        if not path.is_dir():
            continue
        if exclude_key is not None and _norm_path(path) == exclude_key:
            continue
        if read_id_file(path) == project_id:
            live.append(str(path))
            continue
        entry_fs = entry.get("fs_id")
        path_fs = _current_fs_id(path)
        if isinstance(entry_fs, dict) and fs_ids_match(entry_fs, path_fs):
            live.append(str(path))
    return live


def remove_registry_checkout(
    root: Path | str,
    project_id: str,
    *,
    delete_store: bool = False,
) -> dict[str, Any]:
    """Drop one checkout path; delete store only when no siblings remain."""
    from pipeline.project_id import projects_root

    root_path = Path(root).resolve()
    target = _norm_path(root_path)
    store = (projects_root() / project_id).resolve()
    siblings = _live_paths_for_project(project_id, exclude=root_path)

    def apply(registry: dict[str, Any]) -> dict[str, Any]:
        projects = registry.setdefault("projects", {})
        entry = projects.get(project_id)
        if not isinstance(entry, dict):
            return {"removed_project": True, "siblings": len(siblings)}
        if siblings:
            paths = entry.get("paths") if isinstance(entry.get("paths"), list) else []
            kept = [
                str(item)
                for item in paths
                if isinstance(item, str) and _norm_path(item) != target
            ]
            updated = dict(entry)
            updated["paths"] = kept[:8]
            projects[project_id] = updated
            return {"removed_project": False, "siblings": len(siblings)}
        projects.pop(project_id, None)
        return {"removed_project": True, "siblings": 0}

    meta = mutate_registry(apply)
    store_deleted = False
    if delete_store and meta.get("removed_project") and store.exists():
        import shutil

        shutil.rmtree(store)
        store_deleted = True
    return {
        "project_id": project_id,
        "removed_project": bool(meta.get("removed_project")),
        "siblings_remaining": int(meta.get("siblings") or 0),
        "store_deleted": store_deleted,
    }


def reconcile_registry_copy_collisions() -> dict[str, Any]:
    """Daemon safety net: fork copied paths that still share one registry ID."""
    registry = load_registry()
    projects = registry.get("projects") or {}
    forked: list[dict[str, str]] = []
    detached: list[dict[str, str]] = []

    for project_id, raw in projects.items():
        if not isinstance(raw, dict) or raw.get("superseded_by"):
            continue
        paths = raw.get("paths") if isinstance(raw.get("paths"), list) else []
        for item in paths:
            if not isinstance(item, str) or not item.strip():
                continue
            try:
                path = Path(item).resolve()
            except OSError:
                continue
            if not path.is_dir():
                continue
            pid = read_id_file(path)
            if pid != str(project_id):
                continue
            if not _is_copy_of_registry_checkout(path, str(project_id)):
                continue
            new_pid = fork_copied_checkout(path, from_project_id=str(project_id))
            forked.append(
                {"path": str(path), "from": str(project_id), "to": new_pid}
            )

    return {"ok": True, "forked": forked, "detached": detached}


def detect_registry_copy_collisions() -> list[dict[str, str]]:
    """Paths that share a registry ID but look like independent filesystem copies."""
    registry = load_registry()
    projects = registry.get("projects") or {}
    collisions: list[dict[str, str]] = []

    for project_id, raw in projects.items():
        if not isinstance(raw, dict) or raw.get("superseded_by"):
            continue
        paths = raw.get("paths") if isinstance(raw.get("paths"), list) else []
        for item in paths:
            if not isinstance(item, str) or not item.strip():
                continue
            try:
                path = Path(item).resolve()
            except OSError:
                continue
            if not path.is_dir():
                continue
            if read_id_file(path) != str(project_id):
                continue
            if _is_copy_of_registry_checkout(path, str(project_id)):
                collisions.append({"project_id": str(project_id), "path": str(path)})
    return collisions
