"""Hybrid project identity: in-repo id file + global registry + projects/<id>/.

Resolve order:
  1. ``<repo>/.scubiee/id.json`` → project_id
  2. Registry lookup by absolute path (requires live id.json trust)
  3. Recover from a usable store whose ``meta.json`` root matches this path
  4. Reuse an existing git-family project (shared ``git_common_dir``)
  5. Mint new id, write both

Path moves: id file wins; registry paths updated.
Id deleted but store proves ownership: recover durable id (reinstall-safe).
Git worktrees share one project_id / index store (deduped by ``git_common_dir``).
Both gone: mint (caller reindexes into empty store).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

from pipeline.branding import (
    DATA_DIR_NAME,
    LOG_PREFIX,
    migrate_home_dir,
    resolve_repo_data_dir,
)

ID_DIR_NAME = DATA_DIR_NAME
ID_FILE_NAME = "id.json"
REGISTRY_NAME = "registry.json"
_REGISTRY_LOCK = threading.RLock()
_REGISTRY_LOCK_STATE = threading.local()
_REGISTRY_REVISION = "_registry_revision"
_T = TypeVar("_T")


class RegistryConflictError(RuntimeError):
    """A stale registry snapshot attempted to overwrite newer state."""


def _lock_registry_file(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.05)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_registry_file(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def registry_lock() -> Iterator[None]:
    """Serialize registry transactions across threads and processes."""
    with _REGISTRY_LOCK:
        depth = int(getattr(_REGISTRY_LOCK_STATE, "depth", 0))
        if depth:
            _REGISTRY_LOCK_STATE.depth = depth + 1
            try:
                yield
            finally:
                _REGISTRY_LOCK_STATE.depth -= 1
            return

        lock_path = context_engine_home() / "registry.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            _lock_registry_file(handle)
            _REGISTRY_LOCK_STATE.depth = 1
            try:
                yield
            finally:
                _REGISTRY_LOCK_STATE.depth = 0
                _unlock_registry_file(handle)


def context_engine_home() -> Path:
    """Scubiee machine home (``~/.scubiee``)."""
    override = os.environ.get("CTX_HOME", "").strip()
    if override:
        return Path(override).resolve()
    return migrate_home_dir(Path.home())


def id_dir_path(root: Path) -> Path:
    """Repo-local data directory (``.scubiee``, with legacy migration)."""
    return resolve_repo_data_dir(root)


def id_file_path(root: Path) -> Path:
    return id_dir_path(root) / ID_FILE_NAME


def registry_path() -> Path:
    return context_engine_home() / REGISTRY_NAME


def projects_root() -> Path:
    return context_engine_home() / "projects"


def legacy_indexes_root() -> Path:
    return context_engine_home() / "indexes"


def mint_project_id(root: Path) -> str:
    """One-shot unique id (persist; do not recompute)."""
    payload = f"{root.resolve()}|{time.time_ns()}|{secrets.token_hex(8)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"ce_{digest}"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        import sys

        print(
            f"{LOG_PREFIX} WARNING: corrupt JSON at {path}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically replace a JSON document in its destination directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_id_file(root: Path) -> str | None:
    data = _read_json(id_file_path(root))
    pid = data.get("project_id")
    if isinstance(pid, str) and pid.startswith("ce_") and len(pid) > 5:
        return pid
    return None


def write_id_file(root: Path, project_id: str) -> Path:
    root = Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"cannot write project id: not a directory: {root}")
    path = id_file_path(root)
    _write_json(
        path,
        {
            "version": 1,
            "project_id": project_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
    return path


def load_registry() -> dict[str, Any]:
    data = _read_json(registry_path())
    if "projects" not in data or not isinstance(data["projects"], dict):
        data["projects"] = {}
    revision = data.get(_REGISTRY_REVISION, 0)
    data[_REGISTRY_REVISION] = revision if isinstance(revision, int) else 0
    return data


def save_registry(data: dict[str, Any]) -> None:
    with registry_lock():
        current = _read_json(registry_path())
        current_revision = current.get(_REGISTRY_REVISION, 0)
        if not isinstance(current_revision, int):
            current_revision = 0
        expected_revision = data.get(_REGISTRY_REVISION)
        if (
            isinstance(expected_revision, int)
            and expected_revision != current_revision
        ):
            raise RegistryConflictError(
                f"stale registry revision {expected_revision}; current is {current_revision}"
            )
        next_revision = current_revision + 1
        data[_REGISTRY_REVISION] = next_revision
        _write_json(registry_path(), data)


def mutate_registry(mutator: Callable[[dict[str, Any]], _T]) -> _T:
    """Apply one load-modify-save operation under the shared registry lock."""
    with registry_lock():
        registry = load_registry()
        result = mutator(registry)
        save_registry(registry)
        return result


def _norm_path(p: Path | str) -> str:
    resolved = str(Path(p).resolve())
    if os.name == "nt":
        return os.path.normcase(resolved)
    return resolved


def _id_file_trusted(root: Path, project_id: str) -> bool:
    """True when on-disk id.json matches registry/store for this root."""
    abs_root = _norm_path(root)
    reg = load_registry()
    entry = (reg.get("projects") or {}).get(project_id)
    if isinstance(entry, dict):
        roots = entry.get("paths") or []
        primary = entry.get("root")
        if isinstance(primary, str) and primary.strip():
            roots = list(roots) + [primary]
        for raw in roots:
            if isinstance(raw, str) and raw.strip():
                try:
                    if _norm_path(raw) == abs_root:
                        return True
                except OSError:
                    continue
        if entry.get("managed") or entry.get("registered"):
            return True
    store = (projects_root() / project_id).resolve()
    if index_is_usable(store):
        store_meta = _read_json(store / "meta.json")
        store_root = store_meta.get("root")
        if isinstance(store_root, str) and store_root.strip():
            try:
                return _norm_path(store_root) == abs_root
            except OSError:
                return False
    return False


def _registry_path_identity_trusted(project_id: str, path: Path) -> bool:
    """Trust a registry path alias only when live ``id.json`` exactly matches.

    Missing or malformed identity files are treated as stale/untrusted so a
    vacated path (even with an empty ``.scubiee/`` directory) cannot
    inherit a moved repository's durable ID.
    """
    return read_id_file(path) == project_id


def git_common_dir(root: Path) -> Path | None:
    """Return the shared Git administration directory for a checkout."""
    root = root.resolve()
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
            # git never needs stdin here. Without this, subprocess inherits
            # the parent's stdin handle on Windows — fatal inside the MCP
            # stdio server, whose stdin is an open pipe to the client that
            # is never written to or closed. git.exe can then block during
            # process creation on that inherited handle, and since the hang
            # happens before Popen.wait() is reached, subprocess.run's
            # ``timeout=`` never gets a chance to fire (#3182).
            stdin=subprocess.DEVNULL,
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


def find_recoverable_by_store(
    root: Path, registry: dict[str, Any] | None = None
) -> str | None:
    """Recover durable id when id.json is gone but the index store proves this path."""
    abs_root = _norm_path(root)
    reg = registry if registry is not None else load_registry()
    for pid, meta in (reg.get("projects") or {}).items():
        if not isinstance(meta, dict):
            continue
        store = (projects_root() / str(pid)).resolve()
        if not index_is_usable(store):
            continue
        store_meta = _read_json(store / "meta.json")
        store_root = store_meta.get("root")
        if not isinstance(store_root, str) or not store_root.strip():
            continue
        try:
            if _norm_path(store_root) != abs_root:
                continue
        except OSError:
            continue
        return str(pid)
    return None


def find_id_by_git_common_dir(
    common_dir: Path | str, registry: dict[str, Any] | None = None
) -> str | None:
    """Return the best existing project_id for a git worktree family."""
    common = _norm_path(common_dir)
    reg = registry if registry is not None else load_registry()
    best: tuple[tuple[int, float], str] | None = None
    for pid, meta in (reg.get("projects") or {}).items():
        if not isinstance(meta, dict):
            continue
        raw = meta.get("git_common_dir")
        if not raw:
            continue
        try:
            if _norm_path(raw) != common:
                continue
        except OSError:
            continue
        store = (projects_root() / str(pid)).resolve()
        score = 0
        if meta.get("managed"):
            score += 4
        if index_is_usable(store):
            score += 2
        if meta.get("registered"):
            score += 1
        last = float(meta.get("last_access_at") or meta.get("updated_at") or 0.0)
        key = (score, last)
        if best is None or key > best[0]:
            best = (key, str(pid))
    return best[1] if best else None


def detect_git_family_duplicates() -> dict[str, Any]:
    """Return duplicate git-family groups that still need reconciliation."""
    registry = load_registry()
    projects = registry.get("projects")
    if not isinstance(projects, dict):
        return {"needs_reconcile": False, "groups": []}

    groups: dict[str, list[str]] = {}
    for project_id, raw in projects.items():
        if not isinstance(raw, dict) or raw.get("superseded_by"):
            continue
        common = raw.get("git_common_dir")
        if not common:
            paths = raw.get("paths")
            if isinstance(paths, list):
                for item in paths:
                    try:
                        common = git_common_dir(Path(str(item)))
                    except OSError:
                        common = None
                    if common is not None:
                        break
        if not common:
            continue
        try:
            key = _norm_path(common)
        except OSError:
            continue
        groups.setdefault(key, []).append(str(project_id))

    duplicate_groups = [
        {"git_common_dir": key, "project_ids": ids}
        for key, ids in groups.items()
        if len(ids) > 1
    ]
    return {
        "needs_reconcile": bool(duplicate_groups),
        "groups": duplicate_groups,
        "duplicate_count": sum(len(item["project_ids"]) - 1 for item in duplicate_groups),
    }


def find_id_by_path(abs_path: str, registry: dict[str, Any] | None = None) -> str | None:
    reg = registry if registry is not None else load_registry()
    target = _norm_path(abs_path)
    for pid, meta in (reg.get("projects") or {}).items():
        if not isinstance(meta, dict):
            continue
        paths = meta.get("paths") or []
        if not isinstance(paths, list):
            continue
        for p in paths:
            try:
                if _norm_path(p) != target:
                    continue
                if _registry_path_identity_trusted(str(pid), Path(p)):
                    return str(pid)
            except OSError:
                continue
    return None


def update_registry(project_id: str, root: Path) -> None:
    def attach(reg: dict[str, Any]) -> None:
        if read_id_file(root) != project_id:
            raise ValueError("project_id_mismatch")
        projects = reg.setdefault("projects", {})
        entry = (
            projects.get(project_id)
            if isinstance(projects.get(project_id), dict)
            else {}
        )
        entry = dict(entry)
        if entry.get("forget_pending"):
            raise RegistryConflictError("project forget is pending")
        paths = (
            list(entry.get("paths") or [])
            if isinstance(entry.get("paths"), list)
            else []
        )
        abs_root = _norm_path(root)
        # Keep aliases that still carry this durable identity. A moved repository's
        # vacated path must not remain an alias that can identify a new checkout.
        live_aliases: list[str] = []
        for path in paths:
            normalized = _norm_path(path)
            if normalized == abs_root:
                continue
            if read_id_file(Path(path)) == project_id:
                live_aliases.append(normalized)
        paths = [abs_root] + [path for path in live_aliases if path != abs_root]
        entry.update(
            {
                "paths": paths[:8],
                "updated_at": time.time(),
                "name": Path(abs_root).name,
            }
        )
        try:
            from pipeline.hw_track import get_filesystem_id
            fs_id = get_filesystem_id(root)
            if fs_id:
                entry["fs_id"] = fs_id
        except Exception:
            pass
        if read_id_file(root) != project_id:
            raise ValueError("project_id_mismatch")
        projects[project_id] = entry

    mutate_registry(attach)


def legacy_repo_key(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]


def _dir_has_index_data(path: Path) -> bool:
    return (path / "chunks.jsonl").is_file() or (path / "meta.json").is_file()


def migrate_legacy_index(project_id: str, root: Path, dest: Path) -> bool:
    """Move path-hash index into projects/<id>/ if dest empty and legacy exists."""
    legacy = legacy_indexes_root() / legacy_repo_key(root)
    if not legacy.is_dir() or not _dir_has_index_data(legacy):
        return False
    if _dir_has_index_data(dest):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not any(dest.iterdir()):
        dest.rmdir()
    if dest.exists():
        return False
    shutil.move(str(legacy), str(dest))
    return True


@dataclass(frozen=True)
class ProjectRef:
    root: Path
    project_id: str
    store_dir: Path
    id_file: Path
    migrated_legacy: bool = False


def resolve_project(root: Path, *, migrate: bool = True) -> ProjectRef:
    """Ensure id file + registry + projects/<id>/ exist; migrate legacy indexes."""
    root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"not a directory: {root}")
    # Nested folders (accidental CLI args, dump dirs) inherit the enclosing
    # project's id.json instead of minting a sibling identity + polluting disk.
    # BUT: if the folder has a real .git (contains HEAD), it's an independent repo.
    has_own_git = (root / ".git").exists() and (
        (root / ".git" / "HEAD").exists()  # real git repo
        or (root / ".git").is_file()  # git worktree pointer file
    )
    if not read_id_file(root) and not has_own_git:
        for parent in root.parents:
            parent_pid = read_id_file(parent)
            if parent_pid:
                root = parent
                break
    abs_root = _norm_path(root)
    migrated = False
    common = git_common_dir(root)

    # If this folder has its own .git directory (not a worktree pointer file)
    # but git_common_dir resolves outside the root, this is a nested independent
    # repo — don't inherit the parent's identity.  Worktrees have a .git *file*
    # pointing to the main repo's .git, so their common_dir is intentionally
    # outside the worktree root and must be preserved for family reconciliation.
    is_worktree_pointer = (root / ".git").is_file()
    if has_own_git and common and not is_worktree_pointer:
        try:
            if not common.resolve().is_relative_to(root.resolve()):
                common = None  # Ignore parent's git — this repo is independent
        except (ValueError, OSError):
            pass

    pid = read_id_file(root)
    if pid and not _id_file_trusted(root, pid):
        import sys

        print(
            f"[scubiee] Warning: {id_file_path(root)} project_id {pid} "
            f"does not match registry/store for {root}. "
            "Ignoring id file (set CTX_TRUST_ID_FILE=1 to force-trust).",
            file=sys.stderr,
            flush=True,
        )
        if os.environ.get("CTX_TRUST_ID_FILE", "").strip().lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            pid = None
    if not pid:
        pid = find_id_by_path(abs_root)
        if pid:
            write_id_file(root, pid)

    if not pid:
        pid = find_recoverable_by_store(root)
        if pid:
            write_id_file(root, pid)

    if not pid and common:
        pid = find_id_by_git_common_dir(common)
        if pid:
            write_id_file(root, pid)

    if pid and common:
        canonical = find_id_by_git_common_dir(common)
        if canonical and canonical != pid:
            entry = (load_registry().get("projects") or {}).get(pid)
            if isinstance(entry, dict) and entry.get("git_common_dir"):
                try:
                    if _norm_path(entry["git_common_dir"]) == _norm_path(common):
                        pid = canonical
                        write_id_file(root, pid)
                except OSError:
                    pass

    if not pid:
        pid = mint_project_id(root)
        write_id_file(root, pid)

    update_registry(pid, root)
    from pipeline.git_family import reconcile_git_families

    reconcile_git_families(prefer_root=root, prefer_project_id=pid)
    pid = read_id_file(root) or pid

    store_dir = (projects_root() / pid).resolve()
    store_dir.mkdir(parents=True, exist_ok=True)

    if migrate:
        migrated = migrate_legacy_index(pid, root, store_dir)

    return ProjectRef(
        root=root,
        project_id=pid,
        store_dir=store_dir,
        id_file=id_file_path(root),
        migrated_legacy=migrated,
    )


def collection_name_for_project(root: Path, project_id: str) -> str:
    """Stable FAISS collection name keyed by project_id (survives path moves)."""
    import re

    base = Path(root).name
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", base).strip("_").lower() or "repo"
    # project_id is ce_<32 hex>; use 16 chars after prefix for compactness
    digest = project_id.replace("ce_", "")[:16]
    return f"{safe}_{digest}"


def index_is_usable(store_dir: Path, *, collection_name: str | None = None) -> bool:
    """True when chunks + graph.json exist and any publication manifest is valid."""
    if not (store_dir / "chunks.jsonl").is_file():
        return False
    if not (store_dir / "graph.json").is_file():
        return False
    meta = _read_json(store_dir / "meta.json")
    if meta.get("chunks", 0) == 0 and not (store_dir / "chunks.jsonl").stat().st_size:
        return False
    # Prefer collection name from meta when present
    _ = collection_name or meta.get("collection")
    # Fail closed when a manifest exists but is corrupt/mismatched.
    from pipeline.artifact_guard import MANIFEST_NAME, validate_manifest

    if (store_dir / MANIFEST_NAME).is_file():
        report = validate_manifest(store_dir)
        if not report.get("ok"):
            return False
    return True
