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
            "recommended_command": (
                "python -m pipeline init --repair"
                if state.backup_reason
                else recommended_server_command(
                    installed.preferred if installed else None
                )
            ),
        }
    }


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

    repairs: list[str] = []
    if not caps.get("ok"):
        repairs.append(
            "install missing deps: " + ", ".join(caps.get("missing_required") or [])
        )
    accel = {
        **(caps.get("accel") or {}),
        **doctor_report()["accel"],
    }
    if accel and not accel.get("ok"):
        repairs.append(str(accel.get("hint") or "run: python -m pipeline init"))
    if not usable:
        repairs.append("run: python -m pipeline register --force .")
    if manifest.get("ok") is False:
        repairs.append(f"corrupt publication ({manifest.get('reason')}) — rebuild index")
    if binding.get("ok") is False and binding.get("repair"):
        repairs.append(str(binding["repair"]))

    return {
        "ok": bool(caps.get("ok") and usable and not repairs),
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
        "meta": {
            k: meta.get(k)
            for k in ("chunks", "files_indexed", "collection", "embed_model", "project_id")
            if isinstance(meta, dict)
        },
        "repairs": repairs,
        "checked_at": time.time(),
    }
