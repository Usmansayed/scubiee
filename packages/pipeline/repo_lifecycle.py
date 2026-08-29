"""Persistent repository lifecycle built on the global project registry."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from pipeline.project_id import (
    RegistryConflictError,
    find_id_by_path,
    git_common_dir,
    index_is_usable,
    load_registry,
    mutate_registry,
    projects_root,
    read_id_file,
    registry_lock,
    resolve_project,
    update_registry,
)
from pipeline.registration import mark_registered
from pipeline.repo_presence import PresenceReport, assess_presence

ACTIVE = "active"
PAUSED = "paused"
NEVER_INDEX = "never_index"
UNMANAGED = "unmanaged"


def _root(root: Path | str) -> Path:
    return Path(root).resolve()


def _is_too_broad(root: Path) -> bool:
    """Refuse home directories, filesystem roots, and common system paths."""
    resolved = root.resolve()
    home = Path.home().resolve()

    # Exact home directory
    if resolved == home:
        return True

    # Filesystem root or near-root
    if len(resolved.parts) <= 2:
        return True

    # Common system/user-level directories that should never be indexed
    _BROAD = {
        str(home / "Desktop"),
        str(home / "Documents"),
        str(home / "Downloads"),
        "/tmp",
        "/var",
        "/usr",
        "/etc",
        "/opt",
    }

    # Windows-specific broad paths
    import platform

    if platform.system() == "Windows":
        win_root = os.environ.get("SystemDrive", "C:")
        _BROAD.update({
            f"{win_root}\\",
            f"{win_root}\\Users",
            f"{win_root}\\Windows",
            f"{win_root}\\Program Files",
            f"{win_root}\\Program Files (x86)",
            str(home / "AppData"),
            str(home / "OneDrive"),
        })

    if str(resolved) in _BROAD:
        return True

    return False


def _project(root: Path) -> tuple[str | None, dict[str, Any]]:
    project_id = read_id_file(root) or find_id_by_path(str(root))
    if not project_id:
        return None, {}
    entry = (load_registry().get("projects") or {}).get(project_id)
    return project_id, dict(entry) if isinstance(entry, dict) else {}


def _update(project_id: str, **values: Any) -> dict[str, Any]:
    def apply(registry: dict[str, Any]) -> dict[str, Any]:
        projects = registry.setdefault("projects", {})
        current = projects.get(project_id)
        entry = dict(current) if isinstance(current, dict) else {}
        if entry.get("forget_pending"):
            raise RegistryConflictError("project forget is pending")
        entry.update(values)
        entry["updated_at"] = time.time()
        projects[project_id] = entry
        return entry

    return mutate_registry(apply)


def _result(project_id: str, entry: dict[str, Any], **extra: Any) -> dict[str, Any]:
    paths = entry.get("paths") if isinstance(entry.get("paths"), list) else []
    root = str(paths[0]) if paths else ""
    state = entry.get("lifecycle_state", ACTIVE)
    result = {
        "ok": True,
        "project_id": project_id,
        "root": root,
        "primary_path": root,
        "path": root,
        "paths": [str(item) for item in paths],
        "store_dir": str((projects_root() / project_id).resolve()),
        "state": state,
        "paused": state == PAUSED,
        "pinned": bool(entry.get("pinned")),
        "git_common_dir": entry.get("git_common_dir"),
        "initialized_at": entry.get("initialized_at"),
        "last_activated_at": entry.get("last_activated_at"),
        "last_access_at": entry.get("last_access_at"),
    }
    result.update(extra)
    return result


def _entry_by_id(project_id: str) -> dict[str, Any]:
    entry = (load_registry().get("projects") or {}).get(project_id)
    return dict(entry) if isinstance(entry, dict) else {}


def _store_dir(project_id: str) -> Path:
    root = projects_root().resolve()
    store = (root / project_id).resolve()
    if store.parent != root:
        raise ValueError("invalid_project_id")
    return store


def _presence(project_id: str, entry: dict[str, Any], **kwargs: Any) -> PresenceReport:
    paths = entry.get("paths") if isinstance(entry.get("paths"), list) else []
    return assess_presence(
        project_id,
        [str(path) for path in paths],
        missing_since=entry.get("missing_since"),
        **kwargs,
    )


def _missing_retention_seconds() -> float:
    from pipeline.settings import load_prefs

    try:
        return max(0.0, float(load_prefs().get("missing_retention_seconds", 86400)))
    except (TypeError, ValueError):
        return 86400.0


def _observed_presence(
    project_id: str, entry: dict[str, Any], *, retention_s: float
) -> tuple[dict[str, Any], PresenceReport]:
    presence = _presence(project_id, entry, retention_s=retention_s)
    if presence.state == "missing" and entry.get("missing_since") is None:
        entry = _update(project_id, missing_since=time.time())
        presence = _presence(project_id, entry, retention_s=retention_s)
    elif presence.state in {"active", "replaced", "conflict"} and entry.get(
        "missing_since"
    ) is not None:
        entry = _update(project_id, missing_since=None)
        presence = _presence(project_id, entry, retention_s=retention_s)
    return entry, presence


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
    progress: Any = None,
    fast: bool = False,
    fast_roots: list[str] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Admit a repository and reconcile an existing usable index."""
    root = _root(root)

    # Guard: refuse to index CE's own storage directory
    from pipeline.project_id import context_engine_home

    ce_home = context_engine_home()
    try:
        if root.resolve().is_relative_to(ce_home.resolve()):
            return {
                "ok": False,
                "root": str(root),
                "error": "inside_ce_home",
                "message": "Cannot manage a folder inside Scubiee's storage directory.",
            }
    except (ValueError, OSError):
        pass  # is_relative_to raises ValueError on unrelated paths on older Python

    # Guard: refuse overly broad directories (home, root, system paths)
    if _is_too_broad(root):
        return {
            "ok": False,
            "root": str(root),
            "error": "path_too_broad",
            "message": (
                f"Refusing to manage '{root}' — too broad. "
                "This would index personal files, secrets, or system data. "
                "Use scubiee init on a specific project directory."
            ),
        }

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

    # Serialize init so concurrent calls on the same folder wait instead of racing.
    with registry_lock():
        # Re-check after acquiring lock — another thread may have completed init.
        project_id, existing = _project(root)
        if project_id and existing.get("managed"):
            # Already initialized — reconcile git families first (using existing
            # scores), then refresh timestamps and paths.
            store_dir = (projects_root() / project_id).resolve()
            from pipeline.git_family import reconcile_git_families as _rgf

            family = _rgf(prefer_root=None, prefer_project_id=None)
            # Reconciliation may have synced id files to a canonical winner
            ref_pid = read_id_file(root) or project_id
            if ref_pid != project_id:
                store_dir = (projects_root() / ref_pid).resolve()
            # Now update timestamps and path aliases on the canonical entry
            entry = _update(ref_pid, last_access_at=time.time())
            from pipeline.project_id import update_registry as _upreg
            try:
                _upreg(ref_pid, root)
            except (ValueError, RegistryConflictError):
                pass
            entry = _entry_by_id(ref_pid) or entry
        else:
            ref = resolve_project(root)
            now = time.time()
            # resolve_project may have walked up to a parent — use ref's root for registration
            try:
                mark_registered(ref.project_id, root, always_allow=always_allow)
            except (ValueError, RegistryConflictError):
                # Subfolder resolved to parent's project — that's fine, just activate parent
                entry = _update(ref.project_id, last_access_at=time.time())
                return _result(ref.project_id, entry, indexed=False, reconciled=False)
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
            from pipeline.git_family import reconcile_git_families

            family = reconcile_git_families(prefer_root=root, prefer_project_id=ref.project_id)
            if family.canonical_project_ids:
                ref_pid = read_id_file(root) or ref.project_id
                if ref_pid != ref.project_id:
                    ref = resolve_project(root, migrate=False)
                else:
                    ref_pid = ref.project_id
            else:
                ref_pid = ref.project_id
            entry = _entry_by_id(ref_pid) or entry
            store_dir = (projects_root() / ref_pid).resolve()
            ref = resolve_project(root, migrate=False)

    # --- Lock released: indexing can proceed without holding the registry ---
    indexed = False
    reconciled = False
    chunks = 0
    if index:
        try:
            from pipeline.store_lock import quiesce_background_indexing

            quiesce_background_indexing(store_dir=store_dir)
        except Exception:  # noqa: BLE001
            pass
        try:
            from pipeline.incremental import preflight_index_scope

            preflight_index_scope(
                root,
                fast=fast,
                fast_roots=fast_roots,
                confirm=confirm,
            )
            if index_is_usable(store_dir):
                from pipeline.incremental import incremental_sync

                sync = incremental_sync(
                    root, base_dir=store_dir, confirm=confirm
                )
                sync_data = sync.to_dict()
                if sync_data.get("error"):
                    return _result(
                        ref_pid,
                        entry,
                        ok=False,
                        indexed=False,
                        reconciled=True,
                        sync=sync_data,
                        confirmation_required=bool(sync_data.get("confirmation_required")),
                        error=sync_data["error"],
                    )
                reconciled = True
            else:
                from pipeline.indexer import index_repo

                stats = index_repo(
                    root,
                    force=False,
                    fast=fast,
                    fast_roots=fast_roots,
                    progress=progress,
                    confirm=confirm,
                )
                chunks = int(stats.chunks)
                indexed = True
        except Exception as exc:  # noqa: BLE001
            entry = _update(
                ref_pid,
                last_access_at=time.time(),
                last_error=str(exc),
            )
            return _result(
                ref_pid,
                entry,
                ok=False,
                indexed=False,
                reconciled=reconciled,
                error=str(exc),
            )

    entry = _update(ref_pid, last_access_at=time.time())
    return _result(
        ref_pid,
        entry,
        indexed=indexed,
        reconciled=reconciled,
        chunks=chunks,
        git_family=family.to_dict(),
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


def sync_now_repo(root: Path, *, confirm: bool = False) -> dict[str, Any]:
    root = _root(root)
    project_id, entry = _project(root)
    state = managed_state(root)
    if not project_id or state == UNMANAGED:
        return {"ok": False, "root": str(root), "state": state, "error": "unmanaged"}
    if state == NEVER_INDEX:
        return _result(project_id, entry, ok=False, error="never_index")
    from pipeline.incremental import incremental_sync

    result = incremental_sync(
        root, base_dir=projects_root() / project_id, confirm=confirm
    )
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

    def remove(registry: dict[str, Any]) -> None:
        registry.setdefault("projects", {}).pop(project_id, None)

    mutate_registry(remove)
    deleted = False
    if delete_store and store.exists():
        shutil.rmtree(store)
        deleted = True
    try:
        id_f = id_file_path(root)
        if id_f.is_file():
            id_f.unlink(missing_ok=True)
        id_d = id_dir_path(root)
        if id_d.is_dir() and not any(id_d.iterdir()):
            shutil.rmtree(id_d, ignore_errors=True)
    except Exception:
        pass
    return {
        "ok": True,
        "project_id": project_id,
        "root": str(root),
        "state": UNMANAGED,
        "store_dir": str(store),
        "store_deleted": deleted,
    }


def clear_index_repo(
    root: Path | str | None = None,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Delete only a known project's index store, preserving durable identity."""
    if project_id is None:
        if root is None:
            return {"ok": False, "error": "project_required"}
        canonical = _root(root)
        project_id = read_id_file(canonical)
        if project_id is None:
            return {
                "ok": False,
                "root": str(canonical),
                "error": "unknown_project",
            }

    entry = _entry_by_id(project_id)
    if not entry:
        return {"ok": False, "project_id": project_id, "error": "unknown_project"}
    try:
        store = _store_dir(project_id)
    except ValueError as exc:
        return {"ok": False, "project_id": project_id, "error": str(exc)}

    deleted = store.exists()
    if deleted:
        shutil.rmtree(store)
    return _result(project_id, entry, store_deleted=deleted, index_cleared=True)


def locate_repo(project_id: str, new_path: Path | str) -> dict[str, Any]:
    """Reattach a registry row only to a live path carrying the same ID."""
    entry = _entry_by_id(project_id)
    if not entry:
        return {"ok": False, "project_id": project_id, "error": "unknown_project"}

    path = _root(new_path)
    if not path.exists():
        return {
            "ok": False,
            "project_id": project_id,
            "root": str(path),
            "error": "path_missing",
        }

    actual_project_id = read_id_file(path)
    if actual_project_id != project_id:
        return {
            "ok": False,
            "project_id": project_id,
            "actual_project_id": actual_project_id,
            "root": str(path),
            "error": "project_id_mismatch",
        }

    with registry_lock():
        attached_path = str(path)
        current_entry = _entry_by_id(project_id)
        current_paths = (
            current_entry.get("paths")
            if isinstance(current_entry.get("paths"), list)
            else []
        )
        alias_existed = any(
            str(Path(item).resolve()) == attached_path for item in current_paths
        )
        try:
            update_registry(project_id, path)
        except ValueError:
            return {
                "ok": False,
                "project_id": project_id,
                "actual_project_id": read_id_file(path),
                "root": str(path),
                "error": "project_id_mismatch",
            }
        except RegistryConflictError as exc:
            return {
                "ok": False,
                "project_id": project_id,
                "root": str(path),
                "error": "registry_conflict",
                "detail": str(exc),
            }

        actual_project_id = read_id_file(path)
        if actual_project_id != project_id:
            def rollback(registry: dict[str, Any]) -> None:
                current = registry.setdefault("projects", {}).get(project_id)
                if alias_existed or not isinstance(current, dict):
                    return
                paths = current.get("paths")
                if isinstance(paths, list):
                    current["paths"] = [
                        item
                        for item in paths
                        if str(Path(item).resolve()) != attached_path
                    ]

            mutate_registry(rollback)
            return {
                "ok": False,
                "project_id": project_id,
                "actual_project_id": actual_project_id,
                "root": attached_path,
                "error": "project_id_mismatch",
            }
        updated = _entry_by_id(project_id)
        return _result(project_id, updated, located=True)


def forget_repo(
    project_id: str,
    *,
    confirm: str,
    force: bool = False,
    operator: bool = False,
    now: float | None = None,
    retention_s: float = 86400,
) -> dict[str, Any]:
    """Permanently remove CE-owned state after exact confirmation and validation.

    Automated forget still requires presence eligibility. An operator console
    that already collected an exact project-id confirmation may pass
    ``operator=True`` to remove a live repository from Scubiee.
    """
    del force
    if confirm != project_id:
        return {
            "ok": False,
            "project_id": project_id,
            "error": "confirmation_mismatch",
        }

    store: Path

    def mark_pending(registry: dict[str, Any]) -> dict[str, Any]:
        projects = registry.setdefault("projects", {})
        raw_entry = projects.get(project_id)
        entry = dict(raw_entry) if isinstance(raw_entry, dict) else {}
        if not entry:
            raise KeyError(project_id)
        presence = _presence(
            project_id,
            entry,
            now=now,
            retention_s=retention_s,
        )
        if not presence.forget_allowed and not operator:
            raise PermissionError(presence.state, presence.reasons)
        entry["forget_pending"] = True
        entry["forget_pending_at"] = time.time()
        projects[project_id] = entry
        return entry

    try:
        store = _store_dir(project_id)
        mark_pending_result = mutate_registry(mark_pending)
    except KeyError:
        return {"ok": False, "project_id": project_id, "error": "unknown_project"}
    except PermissionError as exc:
        return {
            "ok": False,
            "project_id": project_id,
            "error": "forget_not_allowed",
            "presence": exc.args[0],
            "reasons": exc.args[1],
        }
    except ValueError as exc:
        return {"ok": False, "project_id": project_id, "error": str(exc)}
    except OSError as exc:
        return {
            "ok": False,
            "project_id": project_id,
            "error": "registry_write_failed",
            "detail": str(exc),
            "store_dir": str(store),
            "store_deleted": False,
        }

    deleted = store.exists()
    try:
        if deleted:
            shutil.rmtree(store)
    except OSError as exc:
        return {
            "ok": False,
            "project_id": project_id,
            "error": "store_delete_failed",
            "detail": str(exc),
            "store_dir": str(store),
            "store_deleted": False,
            "forget_pending": bool(mark_pending_result.get("forget_pending")),
        }

    def finish(registry: dict[str, Any]) -> None:
        current = registry.setdefault("projects", {}).get(project_id)
        if isinstance(current, dict) and current.get("forget_pending"):
            registry["projects"].pop(project_id, None)

    try:
        mutate_registry(finish)
    except OSError as exc:
        return {
            "ok": False,
            "project_id": project_id,
            "error": "registry_cleanup_pending",
            "detail": str(exc),
            "store_dir": str(store),
            "store_deleted": deleted,
            "forget_pending": True,
        }
    return {
        "ok": True,
        "project_id": project_id,
        "state": UNMANAGED,
        "store_dir": str(store),
        "store_deleted": deleted,
        "forgotten": True,
    }


def list_managed_repos() -> list[dict[str, Any]]:
    registry = load_registry()
    managed: list[dict[str, Any]] = []
    retention_s = _missing_retention_seconds()
    for project_id, raw in (registry.get("projects") or {}).items():
        if not isinstance(raw, dict) or not raw.get("managed"):
            continue
        if raw.get("superseded_by"):
            continue
        project_id = str(project_id)
        entry, presence = _observed_presence(
            project_id, raw, retention_s=retention_s
        )
        paths = entry.get("paths") if isinstance(entry.get("paths"), list) else []
        primary = Path(paths[0]) if paths else None
        indexed = False
        try:
            indexed = index_is_usable(_store_dir(project_id))
        except ValueError:
            indexed = False
        managed.append(
            _result(
                project_id,
                entry,
                presence=presence.state,
                forget_allowed=presence.forget_allowed,
                root_exists=bool(primary and primary.exists()),
                presence_reasons=presence.reasons,
                indexed=indexed,
                index_exists=indexed,
                has_index=indexed,
                index_state="ready" if indexed else "empty",
                name=primary.name if primary else project_id,
            )
        )
    return sorted(managed, key=lambda item: (item["root"], item["project_id"]))
