"""One durable project + index store per git repository (worktree deduplication)."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.project_id import (
    _norm_path,
    find_id_by_path,
    git_common_dir,
    index_is_usable,
    load_registry,
    mutate_registry,
    projects_root,
    read_id_file,
    update_registry,
    write_id_file,
)


@dataclass
class GitFamilyReconcileResult:
    ok: bool = True
    groups_reconciled: int = 0
    canonical_project_ids: list[str] = field(default_factory=list)
    superseded_project_ids: list[str] = field(default_factory=list)
    stores_promoted: list[str] = field(default_factory=list)
    id_files_synced: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "groups_reconciled": self.groups_reconciled,
            "canonical_project_ids": self.canonical_project_ids,
            "superseded_project_ids": self.superseded_project_ids,
            "stores_promoted": self.stores_promoted,
            "id_files_synced": self.id_files_synced,
            "errors": self.errors,
        }


def _entry_paths(entry: dict[str, Any]) -> list[Path]:
    raw = entry.get("paths")
    if not isinstance(raw, list):
        return []
    paths: list[Path] = []
    for item in raw:
        try:
            path = Path(str(item)).resolve()
        except OSError:
            continue
        if path.is_dir():
            paths.append(path)
    return paths


def _entry_score(project_id: str, entry: dict[str, Any]) -> tuple[int, float]:
    store = (projects_root() / project_id).resolve()
    score = 0
    if not entry.get("superseded_by"):
        score += 32
    if entry.get("managed"):
        score += 8
    if entry.get("registered"):
        score += 4
    if index_is_usable(store):
        score += 16
    last = float(entry.get("last_access_at") or entry.get("updated_at") or 0.0)
    return score, last


def _ensure_git_common_dir(entry: dict[str, Any], *, paths: list[Path]) -> str | None:
    raw = entry.get("git_common_dir")
    if isinstance(raw, str) and raw.strip():
        try:
            return _norm_path(raw)
        except OSError:
            pass
    for path in paths:
        common = git_common_dir(path)
        if common is not None:
            return _norm_path(common)
    return None


def _promote_store(canonical_id: str, duplicate_id: str) -> bool:
    """Move a usable duplicate store onto the canonical slot when canonical is empty."""
    canonical_store = (projects_root() / canonical_id).resolve()
    duplicate_store = (projects_root() / duplicate_id).resolve()
    if index_is_usable(canonical_store):
        return False
    if not index_is_usable(duplicate_store):
        return False
    if duplicate_store == canonical_store:
        return False
    if canonical_store.exists() and any(canonical_store.iterdir()):
        backup = canonical_store.with_name(
            f"{canonical_id}.superseded.{int(time.time())}"
        )
        if backup.exists():
            shutil.rmtree(backup)
        shutil.move(str(canonical_store), str(backup))
    elif canonical_store.exists():
        canonical_store.rmdir()
    duplicate_store.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(duplicate_store), str(canonical_store))
    return True


def _pick_canonical(
    members: list[tuple[str, dict[str, Any]]],
    *,
    prefer_project_id: str | None,
    prefer_root: Path | None,
) -> str:
    preferred = prefer_project_id
    if prefer_root is not None and not preferred:
        preferred = read_id_file(prefer_root) or find_id_by_path(
            str(prefer_root.resolve())
        )
    if preferred and any(pid == preferred for pid, _ in members):
        return preferred
    return max(members, key=lambda item: _entry_score(item[0], item[1]))[0]


def reconcile_git_families(
    *,
    prefer_root: Path | str | None = None,
    prefer_project_id: str | None = None,
) -> GitFamilyReconcileResult:
    """Collapse duplicate managed git worktrees to one canonical project + store."""
    result = GitFamilyReconcileResult()
    prefer_path = (
        Path(prefer_root).resolve() if prefer_root is not None else None
    )

    registry = load_registry()
    projects = registry.get("projects")
    if not isinstance(projects, dict):
        return result

    enriched: dict[str, dict[str, Any]] = {}
    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}

    for project_id, raw in projects.items():
        if not isinstance(raw, dict):
            continue
        entry = dict(raw)
        paths = _entry_paths(entry)
        common_key = _ensure_git_common_dir(entry, paths=paths)
        if common_key:
            entry["git_common_dir"] = common_key
        enriched[str(project_id)] = entry
        if common_key:
            groups.setdefault(common_key, []).append((str(project_id), entry))

    def apply(reg: dict[str, Any]) -> None:
        nonlocal result
        reg_projects = reg.setdefault("projects", {})

        for common_key, members in groups.items():
            active = [
                (pid, dict(reg_projects.get(pid) or entry))
                for pid, entry in members
                if not (reg_projects.get(pid) or entry).get("superseded_by")
            ]
            if len(active) >= 2:
                canonical_id = _pick_canonical(
                    active,
                    prefer_project_id=prefer_project_id,
                    prefer_root=prefer_path,
                )
                canonical = dict(reg_projects.get(canonical_id) or {})
                for pid, duplicate in active:
                    if pid == canonical_id:
                        continue
                    try:
                        if _promote_store(canonical_id, pid):
                            result.stores_promoted.append(pid)
                    except OSError as exc:
                        result.errors.append(f"store promote {pid}->{canonical_id}: {exc}")

                    merged_paths = list(canonical.get("paths") or [])
                    for path in _entry_paths(duplicate):
                        normalized = str(path)
                        if normalized not in merged_paths:
                            merged_paths.append(normalized)
                    canonical.update(
                        {
                            "paths": merged_paths[:8],
                            "git_common_dir": common_key,
                            "managed": bool(
                                canonical.get("managed") or duplicate.get("managed")
                            ),
                            "registered": bool(
                                canonical.get("registered")
                                or duplicate.get("registered")
                            ),
                            "updated_at": time.time(),
                        }
                    )
                    duplicate.update(
                        {
                            "lifecycle_state": "paused",
                            "pause_reason": "git_family_duplicate",
                            "superseded_by": canonical_id,
                            "updated_at": time.time(),
                        }
                    )
                    reg_projects[pid] = duplicate
                    result.superseded_project_ids.append(pid)
                    result.groups_reconciled += 1

                reg_projects[canonical_id] = canonical
                if canonical_id not in result.canonical_project_ids:
                    result.canonical_project_ids.append(canonical_id)
            else:
                canonical_id = active[0][0] if active else None
                if canonical_id is None:
                    continue

            for pid, entry in members:
                merged = dict(reg_projects.get(pid) or entry)
                if merged.get("git_common_dir") != common_key:
                    merged["git_common_dir"] = common_key
                    reg_projects[pid] = merged
                for path in _entry_paths(merged):
                    current = read_id_file(path)
                    if current == canonical_id:
                        continue
                    try:
                        write_id_file(path, str(canonical_id))
                        canonical_entry = dict(
                            reg_projects.get(str(canonical_id)) or {}
                        )
                        paths = list(canonical_entry.get("paths") or [])
                        normalized = str(path)
                        if normalized not in paths:
                            paths = [normalized] + paths
                        canonical_entry["paths"] = paths[:8]
                        canonical_entry["updated_at"] = time.time()
                        reg_projects[str(canonical_id)] = canonical_entry
                        result.id_files_synced.append(normalized)
                    except OSError as exc:
                        result.errors.append(f"id sync {path}: {exc}")

    try:
        mutate_registry(apply)
    except Exception as exc:  # noqa: BLE001
        result.ok = False
        result.errors.append(str(exc))

    result.ok = result.ok and not result.errors
    return result
