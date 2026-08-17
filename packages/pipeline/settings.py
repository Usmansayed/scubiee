"""User preferences for Context Engine (dashboard + CLI + MCP).

Stored at ``~/.context-engine/prefs.json`` (or ``$CTX_HOME/prefs.json``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

RegistrationMode = Literal["automatic", "mcp_cli"]

DEFAULT_PREFS: dict[str, Any] = {
    "version": 1,
    "registration_mode": "automatic",
    # After register: start 5-min keeper / incremental (MCP session)
    "incremental_indexing": True,
    "file_watching": True,  # keeper + sync-trigger; not OS fs.watch yet
    "auto_admission": {
        "max_repositories": 8,
        "large_repo_files": 10_000,
    },
    "resource_management": {
        "enabled": True,
        "max_cpu_busy": 70,
        "max_cpu_critical": 90,
        "min_free_ram_mb": 512,
    },
}


def _home() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home()


def prefs_path() -> Path:
    return _home() / "prefs.json"


def load_prefs() -> dict[str, Any]:
    path = prefs_path()
    data = dict(DEFAULT_PREFS)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
        except (OSError, json.JSONDecodeError):
            pass
    # Env override wins for mode (install / CI)
    env_mode = os.environ.get("CTX_REGISTRATION_MODE", "").strip().lower()
    if env_mode in {"automatic", "auto"}:
        data["registration_mode"] = "automatic"
    elif env_mode in {"mcp_cli", "mcp", "cli", "manual"}:
        data["registration_mode"] = "mcp_cli"
    return data


def save_prefs(prefs: dict[str, Any]) -> Path:
    path = prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(DEFAULT_PREFS)
    merged.update(prefs)
    # normalize mode
    mode = str(merged.get("registration_mode") or "automatic").lower()
    if mode in {"auto", "automatic"}:
        merged["registration_mode"] = "automatic"
    else:
        merged["registration_mode"] = "mcp_cli"
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return path


def get_registration_mode() -> RegistrationMode:
    mode = str(load_prefs().get("registration_mode") or "automatic").lower()
    if mode in {"mcp_cli", "mcp", "cli", "manual"}:
        return "mcp_cli"
    return "automatic"


def set_registration_mode(mode: str) -> dict[str, Any]:
    prefs = load_prefs()
    prefs["registration_mode"] = mode
    save_prefs(prefs)
    return load_prefs()
