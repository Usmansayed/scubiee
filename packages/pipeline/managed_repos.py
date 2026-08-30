"""Managed checkout paths from ``~/.scubiee/registry.json``.

Connect/disconnect fan-out uses every registry path (even when repo-local
``.scubiee/id.json`` was deleted). Init-time rule writes still require enrollment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _path_key(path: Path | str) -> str:
    return str(path).replace("\\", "/").lower()


def iter_registry_checkout_paths() -> list[dict[str, Any]]:
    """Every checkout path recorded for managed projects (may be missing on disk)."""
    from pipeline.project_id import load_registry
    from pipeline.repo_lifecycle import _entry_managed

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(pid: str, raw: str | Path, source: str) -> None:
        text = str(raw).strip()
        if not text:
            return
        try:
            path = Path(text)
        except (TypeError, ValueError):
            return
        dedupe = f"{pid}:{_path_key(path)}"
        if dedupe in seen:
            return
        seen.add(dedupe)
        rows.append(
            {
                "project_id": pid,
                "path": str(path),
                "source": source,
                "exists": path.is_dir(),
            }
        )

    for pid, meta in (load_registry().get("projects") or {}).items():
        if not isinstance(meta, dict) or not _entry_managed(meta):
            continue
        if meta.get("superseded_by"):
            continue
        project_id = str(pid)
        root = meta.get("root")
        if isinstance(root, str) and root.strip():
            add(project_id, root, "root")
        paths = meta.get("paths")
        if isinstance(paths, list):
            for raw in paths:
                if isinstance(raw, str) and raw.strip():
                    add(project_id, raw, "paths")
        try:
            from pipeline.hw_track import resolve_moved_path

            fs_id = meta.get("fs_id")
            if isinstance(fs_id, dict):
                moved = resolve_moved_path(fs_id)
                if moved is not None:
                    add(project_id, moved, "fs_id")
        except Exception:  # noqa: BLE001
            pass

    return rows


def find_managed_project_by_path(root: Path | str) -> str | None:
    """Resolve a managed registry project from checkout path without ``id.json``."""
    from pipeline.project_id import _norm_path, load_registry
    from pipeline.repo_lifecycle import _entry_managed

    try:
        target = _norm_path(Path(root).resolve())
    except OSError:
        return None

    for pid, meta in (load_registry().get("projects") or {}).items():
        if not isinstance(meta, dict) or not _entry_managed(meta):
            continue
        if meta.get("superseded_by"):
            continue
        candidates: list[str] = []
        root_val = meta.get("root")
        if isinstance(root_val, str) and root_val.strip():
            candidates.append(root_val)
        paths = meta.get("paths")
        if isinstance(paths, list):
            candidates.extend(str(p) for p in paths if isinstance(p, str) and p.strip())
        for raw in candidates:
            try:
                if _norm_path(raw) != target:
                    continue
                if not Path(raw).is_dir():
                    continue
                # Do not resolve a copied checkout to the canonical project_id
                # until enrollment has forked identity (prevents silent cross-wipe).
                try:
                    from pipeline.checkout_identity import _is_copy_of_registry_checkout
                    from pipeline.mcp_locate import _is_enrolled

                    if _is_enrolled(Path(raw)) and _is_copy_of_registry_checkout(
                        Path(raw), str(pid)
                    ):
                        continue
                except Exception:  # noqa: BLE001
                    pass
                return str(pid)
            except OSError:
                continue
    return None


def audit_connect_registry() -> dict[str, Any]:
    """Doctor checks for connected tools + managed registry consistency."""
    from pipeline.connect_state import load_connected_tools
    from pipeline.mcp_locate import _is_enrolled

    connected = load_connected_tools()
    registry_rows = iter_registry_checkout_paths()
    stale = [row for row in registry_rows if not row.get("exists")]
    managed_existing = managed_repo_paths(enrolled_only=False)
    enrolled_existing = managed_repo_paths(enrolled_only=True)

    path_to_pid: dict[str, str] = {}
    for row in registry_rows:
        if row.get("exists"):
            path_to_pid[_path_key(row["path"])] = str(row["project_id"])

    unenrolled: list[dict[str, str]] = []
    for path in managed_existing:
        if _is_enrolled(path):
            continue
        pid = path_to_pid.get(_path_key(path), "")
        unenrolled.append({"project_id": pid, "path": str(path)})

    warnings: list[dict[str, str]] = []
    if connected and not managed_existing:
        joined = ", ".join(connected)
        warnings.append(
            {
                "id": "connected_tools_no_managed_repos",
                "detail": (
                    f"Tools connected ({joined}) but no managed repos on disk — "
                    "run `scubiee init .` in a project folder"
                ),
            }
        )
    for row in stale:
        warnings.append(
            {
                "id": "stale_registry_path",
                "detail": (
                    f"Registry path missing: {row['path']} "
                    f"(project {row['project_id']}) — move repo and re-run "
                    "`scubiee init`, or remove stale registry entry"
                ),
            }
        )
    for row in unenrolled:
        suffix = f" (project {row['project_id']})" if row.get("project_id") else ""
        warnings.append(
            {
                "id": "unenrolled_managed_repo",
                "detail": (
                    f"Managed repo missing `.scubiee/id.json`: {row['path']}{suffix} — "
                    "run `scubiee init .` to restore GATE rules"
                ),
            }
        )

    try:
        from pipeline.checkout_identity import detect_registry_copy_collisions

        for row in detect_registry_copy_collisions():
            warnings.append(
                {
                    "id": "shared_id_copy_collision",
                    "detail": (
                        f"Copied checkout still shares project {row['project_id']} "
                        f"at {row['path']} — open folder in IDE or run "
                        "`scubiee init .` to fork a new identity"
                    ),
                }
            )
    except Exception:  # noqa: BLE001
        pass

    blocking = {
        "connected_tools_no_managed_repos",
        "stale_registry_path",
        "shared_id_copy_collision",
    }
    ok = not any(item.get("id") in blocking for item in warnings)

    return {
        "ok": ok,
        "connected_tools": connected,
        "managed_repos": len(managed_existing),
        "enrolled_repos": len(enrolled_existing),
        "stale_registry_paths": stale,
        "unenrolled_managed_repos": unenrolled,
        "warnings": warnings,
    }


def managed_repo_paths(*, enrolled_only: bool = False) -> list[Path]:
    """Existing checkout directories for managed registry projects.

    Parameters
    ----------
    enrolled_only:
        When True, keep only paths that still have ``.scubiee/id.json`` (or legacy
        id dir). Use for operations that require a live project_id on disk.
        When False (default for connect/disconnect fan-out), trust the global
        registry even if the user deleted the repo-local ``.scubiee/`` folder.
    """
    from pipeline.mcp_locate import _is_enrolled
    from pipeline.project_id import load_registry
    from pipeline.repo_lifecycle import _entry_managed, list_managed_repos

    roots: list[Path] = []
    seen: set[str] = set()

    def add(raw: str | Path | None) -> None:
        if raw is None:
            return
        text = str(raw).strip()
        if not text:
            return
        try:
            path = Path(text).resolve()
        except OSError:
            return
        if not path.is_dir():
            return
        key = _path_key(path)
        if key in seen:
            return
        if enrolled_only and not _is_enrolled(path):
            return
        seen.add(key)
        roots.append(path)

    for item in list_managed_repos():
        add(item.get("root"))
        paths = item.get("paths")
        if isinstance(paths, list):
            for raw in paths:
                add(raw)

    # Hardware-moved paths (same as wipe) for registry rows list_managed skips.
    try:
        from pipeline.hw_track import resolve_moved_path

        for _pid, meta in (load_registry().get("projects") or {}).items():
            if not isinstance(meta, dict) or not _entry_managed(meta):
                continue
            if meta.get("superseded_by"):
                continue
            fs_id = meta.get("fs_id")
            if isinstance(fs_id, dict):
                moved = resolve_moved_path(fs_id)
                if moved is not None:
                    add(moved)
    except Exception:  # noqa: BLE001
        pass

    return roots
