"""Shared project registration pipeline.

All triggers (automatic IDE open, MCP consent, CLI) call ``register_project``.
Only the *trigger* differs by ``registration_mode`` in prefs.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pipeline.project_id import (
    index_is_usable,
    load_registry,
    resolve_project,
    save_registry,
    update_registry,
)
from pipeline.settings import get_registration_mode, load_prefs


@dataclass
class RegistrationResult:
    ok: bool
    project_id: str
    root: str
    store_dir: str
    already_registered: bool
    indexed: bool
    chunks: int = 0
    always_allow: bool = False
    error: str | None = None
    mode: str = "automatic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _project_entry(project_id: str) -> dict[str, Any]:
    reg = load_registry()
    entry = (reg.get("projects") or {}).get(project_id)
    return entry if isinstance(entry, dict) else {}


def is_registered(root: Path) -> bool:
    """True if this checkout is intentionally registered (not just id minted)."""
    root = root.resolve()
    # Prefer explicit flag on registry after resolve would mint — peek id file first
    from pipeline.project_id import find_id_by_path, read_id_file

    pid = read_id_file(root) or find_id_by_path(str(root))
    if not pid:
        return False
    entry = _project_entry(pid)
    if entry.get("registered"):
        return True
    # Legacy: usable index implies registered
    from pipeline.project_id import projects_root

    store = projects_root() / pid
    return index_is_usable(store)


def is_always_allowed(root: Path) -> bool:
    from pipeline.project_id import find_id_by_path, read_id_file

    root = root.resolve()
    pid = read_id_file(root) or find_id_by_path(str(root))
    if not pid:
        return False
    return bool(_project_entry(pid).get("always_allow"))


def needs_registration_consent(root: Path) -> bool:
    """MCP/CLI mode: ask before first register unless always_allow or already registered."""
    if get_registration_mode() == "automatic":
        return False
    if is_registered(root):
        return False
    if is_always_allowed(root):
        return False
    return True


def registration_prompt_payload(root: Path) -> dict[str, Any]:
    root = root.resolve()
    return {
        "status": "needs_registration",
        "registration_mode": get_registration_mode(),
        "repo": str(root),
        "message": (
            "This project is not registered with Context Engine. "
            "Call register_project(path, always_allow=true|false) to index it, "
            "or run: ctx register <path>"
        ),
        "actions": [
            {
                "tool": "register_project",
                "always_allow": True,
                "label": "Register and always allow for this project",
            },
            {
                "tool": "register_project",
                "always_allow": False,
                "label": "Register once",
            },
        ],
        "hint": (
            "Ask the user whether to register this repo. "
            "If they choose always-allow, pass always_allow=true."
        ),
    }


def mark_registered(
    project_id: str,
    root: Path,
    *,
    always_allow: bool = False,
) -> None:
    update_registry(project_id, root)
    reg = load_registry()
    projects = reg.setdefault("projects", {})
    entry = projects.get(project_id) if isinstance(projects.get(project_id), dict) else {}
    entry = dict(entry)
    entry["registered"] = True
    entry.setdefault("registered_at", time.time())
    if always_allow:
        entry["always_allow"] = True
    elif "always_allow" not in entry:
        entry["always_allow"] = False
    # keep paths from update_registry
    paths = list(entry.get("paths") or [])
    abs_root = str(root.resolve())
    if abs_root not in paths:
        paths = [abs_root] + paths
    entry["paths"] = paths[:8]
    entry["name"] = Path(abs_root).name
    entry["updated_at"] = time.time()
    projects[project_id] = entry
    save_registry(reg)


def register_project(
    root: Path,
    *,
    always_allow: bool = False,
    index: bool | None = None,
    fast: bool = False,
    force_reindex: bool = False,
) -> RegistrationResult:
    """Single registration pipeline used by automatic, MCP, and CLI triggers.

    1. resolve_project (id file + registry + store dir)
    2. mark registered (+ optional always_allow)
    3. index if missing / force

    ``fast`` defaults False so small/root-level repos are not skipped by
    fast-root filters (src/, packages/, …).
    """
    root = root.resolve()
    mode = get_registration_mode()
    prefs = load_prefs()
    do_index = prefs.get("incremental_indexing", True) if index is None else index

    try:
        already = is_registered(root)
        ref = resolve_project(root)
        mark_registered(ref.project_id, root, always_allow=always_allow)

        indexed = False
        chunks = 0
        if do_index and (force_reindex or not index_is_usable(ref.store_dir)):
            from pipeline.indexer import index_repo

            stats = index_repo(root, force=force_reindex, fast=fast)
            indexed = True
            chunks = int(stats.chunks)
        elif index_is_usable(ref.store_dir):
            from pipeline.store import PipelineStore

            store = PipelineStore(
                root, base_dir=ref.store_dir, project_id=ref.project_id
            )
            chunks = len(store.load_chunks())

        return RegistrationResult(
            ok=True,
            project_id=ref.project_id,
            root=str(root),
            store_dir=str(ref.store_dir),
            already_registered=already,
            indexed=indexed,
            chunks=chunks,
            always_allow=bool(
                always_allow or _project_entry(ref.project_id).get("always_allow")
            ),
            mode=mode,
        )
    except Exception as exc:  # noqa: BLE001
        return RegistrationResult(
            ok=False,
            project_id="",
            root=str(root),
            store_dir="",
            already_registered=False,
            indexed=False,
            error=str(exc),
            mode=mode,
        )
