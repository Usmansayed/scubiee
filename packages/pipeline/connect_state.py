"""Track which AI tools the user has connected (local-first install model).

Persisted at ``~/.scubiee/connected_tools.json``. Managed repo paths live in
``~/.scubiee/registry.json`` (see ``managed_repos.managed_repo_paths``).
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.project_id import context_engine_home


class MachineSetupRequiredError(RuntimeError):
    """Raised when connect/resume needs ``scubiee setup`` first."""


def require_machine_setup() -> None:
    """Connect/resume must not recreate a wiped machine — setup is explicit."""
    home = context_engine_home()
    if not (home / "accel.json").is_file():
        raise MachineSetupRequiredError(
            "Machine setup required — run `scubiee setup` before connect."
        )


def _state_path() -> Path:
    return context_engine_home() / "connected_tools.json"


def _backup_path() -> Path:
    return context_engine_home() / "connected_tools.json.bak"


def _dedup(slugs: "list") -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in slugs:
        slug = str(raw or "").strip()
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def _read_slugs(path: Path) -> list[str] | None:
    """Parse one state file. Returns the slug list, or None if unreadable/corrupt.

    None (not []) signals "could not read" so the caller can fall back to the
    backup instead of treating a torn write as "no tools connected" — the latter
    would silently break the connect-once promise.
    """
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return None
    slugs = data.get("slugs") if isinstance(data, dict) else None
    if not isinstance(slugs, list):
        return None
    return _dedup(slugs)


def load_connected_tools() -> list[str]:
    """Load the machine's connected tools, self-healing from a torn write.

    Primary file first; if it is missing or corrupt (e.g. an interrupted write),
    fall back to the ``.bak`` snapshot so a crash mid-save never silently resets
    the user's connections to empty. A genuinely-empty primary (``{"slugs": []}``)
    is honored as-is.
    """
    primary = _read_slugs(_state_path())
    if primary is not None:
        return primary
    # Primary missing or corrupt — try to recover from the backup.
    backup = _read_slugs(_backup_path())
    if backup is not None:
        # Heal the primary from the good backup so later reads are fast + clean.
        try:
            _atomic_write(_state_path(), backup)
        except OSError:
            pass
        return backup
    return []


def _atomic_write(path: Path, slugs: list[str]) -> None:
    """Write the state file atomically (temp + os.replace) so a crash never
    leaves a truncated/half-written connected_tools.json."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"slugs": slugs}, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(
        prefix=".connected_tools.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp, path)  # atomic on Windows + POSIX
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass


def save_connected_tools(slugs: list[str]) -> None:
    """Persist the connected-tools list atomically, keeping a .bak snapshot.

    Order matters: refresh the backup from the last-known-good primary BEFORE
    overwriting the primary, so there is always one intact copy on disk even if
    this process dies mid-write.
    """
    clean = _dedup(slugs)
    path = _state_path()
    # Snapshot the current good primary to .bak before we touch it.
    current = _read_slugs(path)
    if current is not None:
        try:
            _atomic_write(_backup_path(), current)
        except OSError:
            pass
    _atomic_write(path, clean)


def add_connected_tool(slug: str) -> list[str]:
    from pipeline.tool_registry import get_tool

    tool = get_tool(slug)
    canonical = tool.slug if tool else (slug or "").strip()
    if not canonical:
        return load_connected_tools()
    current = load_connected_tools()
    if canonical not in current:
        current.append(canonical)
        save_connected_tools(current)
    return current


def remove_connected_tool(slug: str) -> list[str]:
    from pipeline.tool_registry import get_tool

    tool = get_tool(slug)
    canonical = tool.slug if tool else (slug or "").strip()
    current = [s for s in load_connected_tools() if s != canonical]
    save_connected_tools(current)
    return current
