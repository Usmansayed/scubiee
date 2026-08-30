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


def load_connected_tools() -> list[str]:
    path = _state_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    slugs = data.get("slugs") if isinstance(data, dict) else None
    if not isinstance(slugs, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in slugs:
        slug = str(raw or "").strip()
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def save_connected_tools(slugs: list[str]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean: list[str] = []
    seen: set[str] = set()
    for raw in slugs:
        slug = str(raw or "").strip()
        if slug and slug not in seen:
            seen.add(slug)
            clean.append(slug)
    path.write_text(json.dumps({"slugs": clean}, indent=2) + "\n", encoding="utf-8")


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
