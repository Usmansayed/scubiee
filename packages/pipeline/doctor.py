"""Operator diagnostics: capabilities, liveness vs readiness, repair actions."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pipeline.artifact_guard import MANIFEST_NAME, validate_manifest
from pipeline.preflight import inspect_capabilities
from pipeline.project_id import ProjectNotBoundError, index_is_usable, resolve_project
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
    if not isinstance(paths, dict):
        return {"pending": False, "paths": []}
    # Published entries linger in the ledger until the next restore drops them;
    # they are done, and counting them failed doctor right after every sync.
    pending = sorted(
        path
        for path, entry in paths.items()
        if not (isinstance(entry, dict) and entry.get("state") == "published")
    )
    out: dict[str, Any] = {"pending": bool(pending), "paths": pending}
    try:
        out["age_s"] = round(max(0.0, time.time() - float(document.get("saved_at"))), 1)
    except (TypeError, ValueError):
        pass
    return out


# A bound engine drains its ledger within seconds; older pending entries are stuck.
JOURNAL_STUCK_AFTER_S = 300.0


def _journal_status(journal: dict[str, Any], binding: dict[str, Any]) -> str:
    """clear | syncing | replays_on_engine_start | stuck.

    Every keeper start restores the ledger from this journal, so pending paths
    with no engine bound are replayed automatically; only a bound engine that
    has not drained them for minutes needs a repair.
    """
    if not journal.get("pending"):
        return "clear"
    if binding.get("ok") is not True:
        return "replays_on_engine_start"
    age = journal.get("age_s")
    if isinstance(age, (int, float)) and age < JOURNAL_STUCK_AFTER_S:
        return "syncing"
    return "stuck"


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
    enrollment = report.get("enrollment") or {}
    if enrollment.get("enrolled") is False:
        actions.append(
            {
                "id": "initialize_repo",
                "kind": "manual",
                "detail": str(
                    enrollment.get("repair") or "run: scubiee init ."
                ),
            }
        )
    elif manifest.get("ok") is False:
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
    if journal.get("pending") and journal.get("status", "stuck") == "stuck":
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
    connect = report.get("connect_registry") or {}
    for warning in connect.get("warnings") or []:
        wid = str(warning.get("id") or "")
        detail = str(warning.get("detail") or wid)
        if wid == "unenrolled_managed_repo":
            actions.append({"id": "reenroll_repo", "kind": "manual", "detail": detail})
        elif wid == "stale_registry_path":
            # Safe to auto-prune: forget_repo enforces the missing-since retention
            # window, so a repo on a temporarily-unmounted drive is NOT removed
            # until it has been gone long enough (default 24h). Carry the
            # project_id/path so apply_safe_repairs doesn't parse the message.
            actions.append({
                "id": wid, "kind": "safe", "detail": detail,
                "project_id": str(warning.get("project_id") or ""),
                "path": str(warning.get("path") or ""),
            })
        elif wid == "connected_tools_no_managed_repos":
            actions.append({"id": wid, "kind": "manual", "detail": detail})
        elif wid == "shared_id_copy_collision":
            actions.append(
                {
                    "id": "fork_copy_collisions",
                    "kind": "safe",
                    "detail": detail,
                }
            )
    return actions


def doctor_repo(root: Path | str | None = None) -> dict[str, Any]:
    """Deep check for one repository — capabilities, readiness, repairs."""
    repo = Path(root).resolve() if root else Path.cwd()
    from pipeline.managed_repos import audit_connect_registry

    connect_registry = audit_connect_registry()
    caps = inspect_capabilities(require_semantic=True)
    from pipeline.project_id import detect_git_family_duplicates

    enrollment: dict[str, Any] = {"enrolled": True}
    try:
        ref = resolve_project(repo, migrate=False, bind=False)
    except ProjectNotBoundError as exc:
        ref = None
        enrollment = {
            "enrolled": False,
            "reason": str(exc),
            "repair": "scubiee init .",
        }
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        # The repo path no longer exists on disk (a stale registry entry or a
        # deleted/unmounted repo). A diagnostic must never crash on this —
        # report it as unenrolled with a path-missing reason so doctor_all /
        # --fix can still complete and surface/prune the stale entry.
        ref = None
        enrollment = {
            "enrolled": False,
            "reason": f"path missing on disk: {exc}",
            "repair": "scubiee init . (if moved) or `scubiee doctor --fix` to prune",
        }

    if ref is None:
        meta = {}
        usable = False
        manifest: dict[str, Any] = {"ok": None, "reason": "not_enrolled"}
        journal: dict[str, Any] = {"pending": False}
        project_id: str | None = None
    else:
        store = PipelineStore(
            repo, base_dir=ref.store_dir, project_id=ref.project_id, resolve=False
        )
        meta = {}
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
        journal = _journal_pending(ref.project_id)
        project_id = ref.project_id

    binding = {"ok": None, "reason": "daemon_unchecked"}
    try:
        from pipeline.daemon import validate_daemon_binding

        binding = validate_daemon_binding(repo)
    except Exception as exc:  # noqa: BLE001
        binding = {"ok": False, "error": str(exc)}
    journal["status"] = _journal_status(journal, binding)

    accel = {
        **(caps.get("accel") or {}),
        **doctor_report()["accel"],
    }
    from pipeline.env_guard import install_identity_report

    install = install_identity_report()
    try:
        from pipeline.upgrade_supervisor import interrupted_upgrade

        install["interrupted_upgrade"] = interrupted_upgrade(installed_version=install.get("version"))
    except Exception:  # noqa: BLE001
        pass
    git_family = detect_git_family_duplicates()
    report: dict[str, Any] = {
        "ok": False,
        "repo": str(repo),
        "project_id": project_id,
        "install": install,
        "enrollment": enrollment,
        "capabilities": caps,
        "accel": accel,
        "connect_registry": connect_registry,
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
    # These repairs are operational guidance about OTHER/removed repos or an
    # unbound daemon — none indicate the current repo's index is unhealthy, so
    # they must not force ok=False:
    #   bind_daemon         — daemon just needs reopening for this workspace
    #   stale_registry_path — a different, deleted/moved repo's leftover entry
    #                         (advisory; `doctor --fix` prunes it, retention-safe)
    _non_blocking = {"bind_daemon", "stale_registry_path"}
    blocking = [item for item in planned if item.get("id") not in _non_blocking]
    report["ok"] = bool(
        caps.get("ok")
        and usable
        and manifest.get("ok") is not False
        and not git_family.get("needs_reconcile")
        and connect_registry.get("ok", True)
        and not blocking
    )
    return report


def doctor_all() -> dict[str, Any]:
    """Doctor every managed repository."""
    from pipeline.managed_repos import audit_connect_registry
    from pipeline.repo_lifecycle import list_managed_repos

    connect_registry = audit_connect_registry()
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
    for warning in connect_registry.get("warnings") or []:
        wid = str(warning.get("id") or "")
        detail = str(warning.get("detail") or wid)
        kind = "manual" if wid != "unenrolled_managed_repo" else "manual"
        planned.append({"id": wid, "kind": kind, "detail": detail, "repo": None})
    return {
        "ok": (
            all(item.get("ok") for item in repositories) if repositories else True
        )
        and connect_registry.get("ok", True),
        "repositories": repositories,
        "connect_registry": connect_registry,
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
        # Repairs that operate on the live checkout need the dir to exist. When
        # the repo is gone from disk (stale/unmounted), running them crashes
        # (ensure_daemon -> client ValueError, initialize/sync -> FileNotFound).
        # Skip those to manual; only registry-level repairs (stale prune) run.
        _path_dependent = {
            "bind_daemon", "initialize_index", "replay_dirty_journal",
            "reconcile_git_family",
        }
        try:
            _repo_live = repo.is_dir()
        except OSError:
            _repo_live = False
        if action_id in _path_dependent and not _repo_live:
            manual.append({**action, "kind": "manual",
                           "detail": str(action.get("detail", "")) + " (repo not on disk; skipped)"})
            continue
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
        elif action_id == "fork_copy_collisions":
            from pipeline.checkout_identity import reconcile_registry_copy_collisions

            result = reconcile_registry_copy_collisions()
        elif action_id == "stale_registry_path":
            # Prune a registry entry whose repo is gone from disk — but only
            # through forget_repo, which refuses unless the path has been missing
            # past the retention window (protects an unmounted-drive repo). If
            # retention hasn't elapsed, surface it as a still-manual note rather
            # than forcing a removal.
            from pipeline.repo_lifecycle import forget_repo

            pid = str(action.get("project_id") or "")
            if not pid:
                manual.append({**action, "kind": "manual"})
                continue
            result = forget_repo(pid, confirm=pid)
            if not result.get("ok"):
                manual.append({
                    **action, "kind": "manual",
                    "detail": action.get("detail", "")
                    + f" (not pruned yet: {result.get('error')})",
                })
                continue
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
