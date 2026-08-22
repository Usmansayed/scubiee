"""Operator diagnostics: capabilities, liveness vs readiness, repair actions."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pipeline.artifact_guard import MANIFEST_NAME, validate_manifest
from pipeline.preflight import inspect_capabilities
from pipeline.project_id import index_is_usable, resolve_project
from pipeline.store import PipelineStore


def doctor_report() -> dict[str, Any]:
    """Return read-only process acceleration health for operator tooling."""

    from pipeline.preflight import recommended_server_command
    from pipeline.runtime_profile import get_runtime_profile_state, load_installed_profile

    state = get_runtime_profile_state()
    installed = load_installed_profile()
    try:
        from pipeline.resources import get_resource_manager

        resources = get_resource_manager().status()
    except Exception:  # noqa: BLE001
        resources = None
    envelope = resources.get("envelope") if isinstance(resources, dict) else None
    return {
        "accel": {
            "preferred_profile": state.preferred_profile,
            "active_profile": state.active_profile,
            "backup_reason": state.backup_reason,
            "envelope": envelope,
            "onnx_file": getattr(installed.preferred, "onnx_file", None)
            if installed and installed.preferred
            else None,
            "recommended_command": (
                "python -m pipeline setup --repair"
                if state.backup_reason
                else recommended_server_command(
                    installed.preferred if installed else None
                )
            ),
        }
    }


def _journal_pending(project_id: str) -> dict[str, Any]:
    try:
        from pipeline.dirty_journal import load_dirty_journal

        document = load_dirty_journal(project_id)
    except Exception as exc:  # noqa: BLE001
        return {"pending": False, "error": str(exc)}
    if not isinstance(document, dict) or document.get("ok") is False:
        return {"pending": False, "document": document}
    snapshot = document.get("snapshot") or {}
    paths = snapshot.get("paths") if isinstance(snapshot, dict) else {}
    return {"pending": bool(paths), "paths": sorted(paths) if isinstance(paths, dict) else []}


def _managed_root(entry: dict[str, Any]) -> Path | None:
    value = entry.get("root") or entry.get("primary_path") or entry.get("path")
    if not value:
        paths = entry.get("paths")
        value = paths[0] if isinstance(paths, list) and paths else None
    if not value:
        return None
    return Path(str(value)).resolve()


def plan_repairs(
    root: Path | str | None = None,
    report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Classify repairs as safe (auto-applicable) or manual."""
    if report is None:
        report = doctor_repo(root)
    actions: list[dict[str, Any]] = []
    caps = report.get("capabilities") or {}
    missing = [str(item) for item in (caps.get("missing_required") or [])]
    if missing:
        actions.append(
            {
                "id": "install_deps",
                "kind": "manual",
                "detail": "install missing deps: " + ", ".join(missing),
            }
        )
    accel = report.get("accel") or {}
    if accel and accel.get("ok") is False:
        actions.append(
            {
                "id": "init_repair",
                "kind": "manual",
                "detail": str(
                    accel.get("hint") or "run: python -m pipeline setup --repair"
                ),
            }
        )
    binding = report.get("binding") or {}
    if binding.get("ok") is False:
        actions.append(
            {
                "id": "bind_daemon",
                "kind": "safe",
                "detail": str(
                    binding.get("repair")
                    or "scubiee engine ensure .  # reopen so soft search binds this workspace"
                ),
            }
        )
    readiness = report.get("readiness") or {}
    manifest = readiness.get("manifest") if isinstance(readiness.get("manifest"), dict) else {}
    if manifest.get("ok") is False:
        actions.append(
            {
                "id": "rebuild_index",
                "kind": "manual",
                "detail": (
                    f"corrupt publication ({manifest.get('reason')}) — rebuild index"
                ),
            }
        )
    elif not readiness.get("index_usable"):
        actions.append(
            {
                "id": "initialize_index",
                "kind": "safe",
                "detail": "run: python -m pipeline init .",
            }
        )
    journal = report.get("journal") or {}
    if journal.get("pending"):
        actions.append(
            {
                "id": "replay_dirty_journal",
                "kind": "safe",
                "detail": "replay dirty journal then sync-now",
            }
        )
    duplicates = report.get("git_family") or {}
    if duplicates.get("needs_reconcile"):
        actions.append(
            {
                "id": "reconcile_git_family",
                "kind": "safe",
                "detail": "merge duplicate git worktree indexes into one project store",
            }
        )
    return actions


def doctor_repo(root: Path | str | None = None) -> dict[str, Any]:
    """Deep check for one repository — capabilities, readiness, repairs."""
    repo = Path(root).resolve() if root else Path.cwd()
    caps = inspect_capabilities(require_semantic=True)
    ref = resolve_project(repo, migrate=False)
    store = PipelineStore(repo)
    meta: dict[str, Any] = {}
    try:
        meta = store.load_meta()
    except Exception as exc:  # noqa: BLE001
        meta = {"_error": str(exc)}

    collection = meta.get("collection") if isinstance(meta, dict) else None
    usable = index_is_usable(store.base, collection_name=collection)
    manifest = (
        validate_manifest(store.base)
        if (store.base / MANIFEST_NAME).is_file()
        else {"ok": None, "reason": "manifest_absent_legacy"}
    )

    binding = {"ok": None, "reason": "daemon_unchecked"}
    try:
        from pipeline.daemon import validate_daemon_binding

        binding = validate_daemon_binding(repo)
    except Exception as exc:  # noqa: BLE001
        binding = {"ok": False, "error": str(exc)}

    accel = {
        **(caps.get("accel") or {}),
        **doctor_report()["accel"],
    }
    journal = _journal_pending(ref.project_id)
    from pipeline.project_id import detect_git_family_duplicates

    git_family = detect_git_family_duplicates()
    report: dict[str, Any] = {
        "ok": False,
        "repo": str(repo),
        "project_id": ref.project_id,
        "capabilities": caps,
        "accel": accel,
        "readiness": {
            "index_usable": usable,
            "manifest": manifest,
            "soft_search_ready": bool(usable and caps.get("ok")),
            "embed_profile": accel.get("profile"),
            "embed_batch": accel.get("batch_size"),
            "embed_tps": accel.get("texts_per_sec"),
        },
        "binding": binding,
        "journal": journal,
        "git_family": git_family,
        "meta": {
            k: meta.get(k)
            for k in ("chunks", "files_indexed", "collection", "embed_model", "project_id")
            if isinstance(meta, dict)
        },
        "checked_at": time.time(),
    }
    planned = plan_repairs(report=report)
    report["repair_plan"] = planned
    report["repairs"] = [item["detail"] for item in planned]
    # An unbound daemon is operational guidance, not index corruption.
    blocking = [item for item in planned if item.get("id") != "bind_daemon"]
    report["ok"] = bool(
        caps.get("ok")
        and usable
        and manifest.get("ok") is not False
        and not git_family.get("needs_reconcile")
        and not blocking
    )
    return report


def doctor_all() -> dict[str, Any]:
    """Doctor every managed repository."""
    from pipeline.repo_lifecycle import list_managed_repos

    repositories: list[dict[str, Any]] = []
    for entry in list_managed_repos():
        root = _managed_root(entry)
        if root is None:
            continue
        report = doctor_repo(root)
        report["presence"] = entry.get("presence")
        repositories.append(report)
    planned = [
        {**action, "repo": item["repo"], "project_id": item.get("project_id")}
        for item in repositories
        for action in (item.get("repair_plan") or [])
    ]
    return {
        "ok": all(item.get("ok") for item in repositories) if repositories else True,
        "repositories": repositories,
        "repair_plan": planned,
        "repairs": planned,
        "checked_at": time.time(),
    }


def apply_safe_repairs(root: Path | str | None = None) -> dict[str, Any]:
    """Apply only safe repairs for one repository, then re-doctor."""
    repo = Path(root).resolve() if root else Path.cwd()
    before = doctor_repo(repo)
    applied: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    for action in plan_repairs(report=before):
        if action.get("kind") != "safe":
            manual.append(action)
            continue
        action_id = action.get("id")
        if action_id == "bind_daemon":
            from pipeline.daemon import ensure_daemon

            result = ensure_daemon(repo)
        elif action_id == "initialize_index":
            from pipeline.repo_lifecycle import initialize_repo

            result = initialize_repo(repo, index=True)
        elif action_id == "replay_dirty_journal":
            from pipeline.dirty_journal import restore_ledger_from_journal
            from pipeline.dirty_ledger import DirtyLedger
            from pipeline.repo_lifecycle import sync_now_repo

            ledger = DirtyLedger(debounce_ms=0)
            restore = restore_ledger_from_journal(ledger, str(before.get("project_id") or ""))
            result = {"restore": restore, "sync": sync_now_repo(repo)}
        elif action_id == "reconcile_git_family":
            from pipeline.git_family import reconcile_git_families

            result = reconcile_git_families(prefer_root=repo).to_dict()
        else:
            manual.append({**action, "kind": "manual"})
            continue
        applied.append({**action, "result": result})
    after = doctor_repo(repo)
    remaining_manual = [
        item for item in plan_repairs(report=after) if item.get("kind") == "manual"
    ]
    return {
        "ok": bool(after.get("ok")),
        "repo": str(repo),
        "project_id": after.get("project_id"),
        "applied": applied,
        "manual": remaining_manual or manual,
        "before": before,
        "after": after,
    }


def apply_safe_repairs_all() -> dict[str, Any]:
    """Apply safe repairs across every managed repository."""
    from pipeline.repo_lifecycle import list_managed_repos

    results: list[dict[str, Any]] = []
    for entry in list_managed_repos():
        root = _managed_root(entry)
        if root is None:
            continue
        results.append(apply_safe_repairs(root))
    applied = [item for result in results for item in result.get("applied") or []]
    manual = [item for result in results for item in result.get("manual") or []]
    return {
        "ok": all(result.get("ok") for result in results) if results else True,
        "repositories": results,
        "applied": applied,
        "manual": manual,
        "checked_at": time.time(),
    }
