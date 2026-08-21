"""Data migration detection and execution for Context Engine version upgrades.

When the index schema, embedding model, or graph format changes between versions,
this module detects stale data and provides a guided path to bring it current.

Schema version history:
  1 — original (no version stamp; anything without schema_version is v1)
  2 — 0.2.18: added compress_mode, grep/glob honesty, schema_version stamp
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

# Bump this when the on-disk format changes in a way that requires re-indexing.
SCHEMA_VERSION = 2

# What changed in each version (for operator messages).
SCHEMA_CHANGELOG: dict[int, str] = {
    2: "Added compress_mode metadata, glob honesty fields, schema_version stamp.",
}


def detect_migration_needed(
    root: Path | None = None,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Check whether a project's index needs migration.

    Returns a result dict with:
      - needs_migration: bool
      - current_schema: int (stored version)
      - target_schema: int (this code's version)
      - reason: str (why migration is needed, if applicable)
      - actions: list of recommended actions
    """
    from pipeline.project_id import context_engine_home, load_registry, read_id_file
    from pipeline.store import PipelineStore

    if project_id is None:
        if root is None:
            return {"ok": False, "error": "root_or_project_id_required"}
        root = Path(root).resolve()
        project_id = read_id_file(root)
        if project_id is None:
            return {
                "ok": True,
                "needs_migration": False,
                "reason": "not_indexed",
                "root": str(root),
            }

    # Load meta from the project store
    store_dir = context_engine_home() / "projects" / project_id
    meta_path = store_dir / "meta.json"

    if not meta_path.exists():
        return {
            "ok": True,
            "needs_migration": False,
            "project_id": project_id,
            "reason": "no_index_data",
        }

    import json

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {
            "ok": False,
            "project_id": project_id,
            "error": "corrupt_metadata",
            "detail": str(exc),
            "meta_path": str(meta_path),
        }

    stored_version = meta.get("schema_version", 1)
    embed_model = meta.get("embed_model", "unknown")
    embed_backend = meta.get("embed_backend", "unknown")

    needs_migration = stored_version < SCHEMA_VERSION

    reasons: list[str] = []
    actions: list[str] = []

    if needs_migration:
        reasons.append(
            f"schema {stored_version} → {SCHEMA_VERSION}: "
            + "; ".join(
                SCHEMA_CHANGELOG[v]
                for v in range(stored_version + 1, SCHEMA_VERSION + 1)
                if v in SCHEMA_CHANGELOG
            )
        )
        actions.append("scubiee migrate --apply")

    return {
        "ok": True,
        "project_id": project_id,
        "root": meta.get("root"),
        "needs_migration": needs_migration,
        "current_schema": stored_version,
        "target_schema": SCHEMA_VERSION,
        "embed_model": embed_model,
        "embed_backend": embed_backend,
        "reasons": reasons,
        "actions": actions,
        "chunks": meta.get("chunks", 0),
        "indexed_at": meta.get("indexed_at"),
    }


def migrate_project(
    root: Path | None = None,
    *,
    project_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Perform migration for a single project.

    For schema changes that only need a metadata stamp update, this is cheap.
    For changes that require re-embedding or re-graphing, this triggers a rebuild.
    """
    from pipeline.project_id import read_id_file

    if root is None and project_id is None:
        return {"ok": False, "error": "root_or_project_id_required"}

    if root is not None:
        root = Path(root).resolve()
        if project_id is None:
            project_id = read_id_file(root)

    detection = detect_migration_needed(root, project_id=project_id)
    if not detection.get("ok"):
        return detection

    if not detection.get("needs_migration") and not force:
        return {
            "ok": True,
            "migrated": False,
            "reason": detection.get("reason", "already_current"),
            "schema_version": SCHEMA_VERSION,
            "project_id": project_id,
        }

    stored_version = detection.get("current_schema", 1)

    # Determine what kind of migration is needed
    if _requires_rebuild(stored_version, SCHEMA_VERSION):
        return _migrate_with_rebuild(root, project_id=project_id)
    else:
        return _migrate_metadata_only(root, project_id=project_id)


def _requires_rebuild(from_version: int, to_version: int) -> bool:
    """Determine if migration between versions requires a full rebuild.

    Schema version 1→2 is metadata-only (just stamp the version).
    Future versions that change embedding dimensions, model, or chunk strategy
    would return True here.
    """
    # v1 → v2: metadata stamp only, no rebuild needed
    # Future: if we change embed model or chunk strategy, add those ranges here
    return False


def _migrate_metadata_only(
    root: Path | None,
    *,
    project_id: str | None,
) -> dict[str, Any]:
    """Update meta.json with current schema version without re-indexing."""
    import json

    from pipeline.project_id import context_engine_home

    store_dir = context_engine_home() / "projects" / project_id
    meta_path = store_dir / "meta.json"

    if not meta_path.exists():
        return {"ok": False, "project_id": project_id, "error": "meta_not_found"}

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    old_version = meta.get("schema_version", 1)
    meta["schema_version"] = SCHEMA_VERSION
    meta["migrated_at"] = time.time()
    meta["migrated_from"] = old_version
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "migrated": True,
        "strategy": "metadata_only",
        "from_schema": old_version,
        "to_schema": SCHEMA_VERSION,
        "project_id": project_id,
        "root": str(root) if root else meta.get("root"),
    }


def _migrate_with_rebuild(
    root: Path | None,
    *,
    project_id: str | None,
) -> dict[str, Any]:
    """Trigger a full rebuild for schema changes that require re-embedding."""
    if root is None:
        return {
            "ok": False,
            "project_id": project_id,
            "error": "root_required_for_rebuild",
            "message": "Pass the repo path to rebuild: scubiee migrate --apply <path>",
        }

    from pipeline.repo_lifecycle import rebuild_repo

    rebuild_result = rebuild_repo(root)
    if not rebuild_result.get("ok"):
        return {
            "ok": False,
            "project_id": project_id,
            "error": "rebuild_failed",
            "detail": rebuild_result,
        }

    return {
        "ok": True,
        "migrated": True,
        "strategy": "rebuild",
        "to_schema": SCHEMA_VERSION,
        "project_id": project_id,
        "root": str(root),
        "rebuild": rebuild_result,
    }


def migrate_all() -> dict[str, Any]:
    """Check and migrate all managed projects."""
    from pipeline.project_id import load_registry

    registry = load_registry()
    projects = registry.get("projects", {})
    results: list[dict[str, Any]] = []
    migrated_count = 0
    skipped_count = 0
    error_count = 0

    for pid, entry in projects.items():
        if not isinstance(entry, dict) or not entry.get("managed"):
            continue
        paths = entry.get("paths", [])
        root = Path(paths[0]) if paths else None
        detection = detect_migration_needed(root, project_id=pid)

        if not detection.get("ok"):
            # Corrupt or unreadable — record the error and continue
            results.append(detection)
            error_count += 1
        elif detection.get("needs_migration"):
            result = migrate_project(root, project_id=pid)
            results.append(result)
            if result.get("migrated"):
                migrated_count += 1
        else:
            skipped_count += 1

    return {
        "ok": True,
        "migrated": migrated_count,
        "skipped": skipped_count,
        "errors": error_count,
        "current_schema": SCHEMA_VERSION,
        "results": results,
    }
