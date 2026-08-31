"""Post-upgrade MCP hot reload: version stamp + worker kill + engine nudge."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


ACTIVE_BUILD_NAME = "active_build.json"


def _home() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home()


def active_build_path() -> Path:
    return _home() / ACTIVE_BUILD_NAME


def make_build_id(version: str, *, epoch: float | None = None) -> str:
    ts = int(time.time() if epoch is None else epoch)
    return f"{version}-{ts}"


def write_active_build_stamp(version: str | None = None, *, epoch: float | None = None) -> dict[str, Any]:
    """Publish the active package build Cursor's MCP bridge should run."""
    from pipeline.artifact_guard import atomic_write_text
    from pipeline.upgrade import installed_version

    ver = (version or installed_version()).strip() or "unknown"
    now = time.time() if epoch is None else epoch
    stamp = {
        "version": ver,
        "epoch": now,
        "build_id": make_build_id(ver, epoch=now),
    }
    _home().mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        active_build_path(),
        json.dumps(stamp, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return stamp


def read_active_build_stamp() -> dict[str, Any] | None:
    path = active_build_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    build_id = str(data.get("build_id") or "").strip()
    if not build_id:
        ver = str(data.get("version") or "").strip()
        if not ver:
            return None
        epoch = data.get("epoch")
        try:
            epoch_f = float(epoch) if epoch is not None else time.time()
        except (TypeError, ValueError):
            epoch_f = time.time()
        data = {**data, "build_id": make_build_id(ver, epoch=epoch_f)}
    return data


def current_build_id() -> str | None:
    stamp = read_active_build_stamp()
    if not stamp:
        return None
    bid = str(stamp.get("build_id") or "").strip()
    return bid or None


def env_build_id(version: str | None = None) -> str:
    """Value for CTX_SCUBIEE_BUILD in mcp.json env (matches active stamp)."""
    stamp = write_active_build_stamp(version)
    return str(stamp["build_id"])


def nudge_mcp_hot_reload(version: str | None = None) -> dict[str, Any]:
    """After upgrade: stamp new build, kill MCP workers, keep bridge alive."""
    from pipeline.process_control import kill_mcp_worker_processes

    report: dict[str, Any] = {"ok": True}
    try:
        report["stamp"] = write_active_build_stamp(version)
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["stamp_error"] = str(exc)
        return report

    try:
        report["env_refresh"] = refresh_mcp_build_env()
    except Exception as exc:  # noqa: BLE001
        report["env_refresh"] = {"ok": False, "error": str(exc)}

    try:
        report["kill"] = kill_mcp_worker_processes(exclude_bridge=True)
        if not report["kill"].get("ok", True):
            report["warning"] = "some_mcp_workers_still_running"
    except Exception as exc:  # noqa: BLE001
        report["kill"] = {"ok": False, "error": str(exc)}

    return report


def _patch_build_env_in_json(path: Path, build_id: str) -> bool:
    """Update ``CTX_SCUBIEE_BUILD`` in a JSON MCP config if scubiee is present."""
    from pipeline.branding import MCP_SERVER_NAME, strip_legacy_mcp_keys

    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = data.get("servers")
    if not isinstance(servers, dict):
        return False
    strip_legacy_mcp_keys(servers)
    entry = servers.get(MCP_SERVER_NAME)
    if not isinstance(entry, dict):
        return False
    cmd = str(entry.get("command") or "")
    if "scubiee-mcp" not in cmd:
        return False
    env = entry.setdefault("env", {})
    if not isinstance(env, dict):
        env = {}
        entry["env"] = env
    if str(env.get("CTX_SCUBIEE_BUILD") or "") == build_id:
        return False
    env["CTX_SCUBIEE_BUILD"] = build_id
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


_TOML_BUILD_RE = re.compile(r'CTX_SCUBIEE_BUILD\s*=\s*"[^"]*"')


def _patch_build_env_in_toml(path: Path, build_id: str) -> bool:
    """Update ``CTX_SCUBIEE_BUILD`` in Codex-style TOML MCP config."""
    from pipeline.branding import MCP_SERVER_NAME

    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if "scubiee-mcp" not in text:
        return False
    section = f"[mcp_servers.{MCP_SERVER_NAME}]"
    if section not in text:
        return False
    lines = text.splitlines()
    in_section = False
    changed = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == section:
            in_section = True
            new_lines.append(line)
            continue
        if in_section and stripped.startswith("[") and not stripped.startswith("[mcp_servers"):
            in_section = False
        if in_section and stripped.startswith("env ="):
            if _TOML_BUILD_RE.search(line):
                replaced = _TOML_BUILD_RE.sub(f'CTX_SCUBIEE_BUILD = "{build_id}"', line)
                changed = changed or replaced != line
                new_lines.append(replaced)
                continue
            if "{" in line and "}" in line:
                inner = line.rstrip()
                if inner.endswith("}"):
                    body = inner[:-1].rstrip()
                    if body.endswith("{"):
                        patched = f'{body} CTX_SCUBIEE_BUILD = "{build_id}" }}'
                    else:
                        patched = f'{body}, CTX_SCUBIEE_BUILD = "{build_id}" }}'
                    changed = True
                    new_lines.append(patched)
                    continue
        new_lines.append(line)
    if not changed:
        return False
    path.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    try:
        from pipeline.rules_installer import _validate_toml_file

        _validate_toml_file(path)
    except Exception:  # noqa: BLE001
        return False
    return True


_YAML_BUILD_RE = re.compile(
    r'^(\s*CTX_SCUBIEE_BUILD:\s*)(["\'].*?["\']|\S+)',
    re.MULTILINE,
)


def _patch_build_env_in_yaml(path: Path, build_id: str) -> bool:
    """Update ``CTX_SCUBIEE_BUILD`` in Continue-style YAML MCP config."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if "scubiee-mcp" not in text:
        return False
    if _YAML_BUILD_RE.search(text):
        new_text = _YAML_BUILD_RE.sub(rf'\1"{build_id}"', text)
        if new_text == text:
            return False
        path.write_text(new_text, encoding="utf-8")
        return True
    lines = text.splitlines()
    new_lines: list[str] = []
    in_env = False
    inserted = False
    for line in lines:
        stripped = line.strip()
        if stripped == "env:":
            in_env = True
            new_lines.append(line)
            continue
        if in_env and stripped.startswith("CTX_SCUBIEE_BUILD:"):
            indent = line[: len(line) - len(line.lstrip())]
            new_lines.append(f'{indent}CTX_SCUBIEE_BUILD: "{build_id}"')
            inserted = True
            continue
        if in_env and stripped and not line.startswith((" ", "\t")):
            if not inserted:
                indent = "      "
                new_lines.append(f'{indent}CTX_SCUBIEE_BUILD: "{build_id}"')
                inserted = True
            in_env = False
        new_lines.append(line)
    if not inserted:
        return False
    path.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    return True


def _patch_build_env_in_mcp_file(path: Path, build_id: str) -> bool:
    """Update ``CTX_SCUBIEE_BUILD`` in JSON/TOML/YAML MCP configs."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _patch_build_env_in_json(path, build_id)
    if suffix == ".toml":
        return _patch_build_env_in_toml(path, build_id)
    if suffix in {".yaml", ".yml"}:
        return _patch_build_env_in_yaml(path, build_id)
    return False


def refresh_mcp_build_env() -> dict[str, Any]:
    """Refresh ``CTX_SCUBIEE_BUILD`` in connected-tool MCP configs (even if rebind skipped)."""
    build_id = current_build_id()
    if not build_id:
        return {"ok": False, "error": "no_active_build_stamp"}
    report: dict[str, Any] = {"ok": True, "build_id": build_id, "updated": [], "errors": []}
    try:
        from pipeline.connect_state import load_connected_tools
        from pipeline.managed_repos import managed_repo_paths
        from pipeline.tool_registry import get_tool, resolve_mcp_project_paths

        for repo in managed_repo_paths(enrolled_only=False):
            for slug in load_connected_tools():
                tool = get_tool(slug)
                if tool is None:
                    continue
                for path in resolve_mcp_project_paths(tool, repo):
                    try:
                        if _patch_build_env_in_mcp_file(path, build_id):
                            report["updated"].append(str(path))
                    except Exception as exc:  # noqa: BLE001
                        report["errors"].append(f"{path}: {exc}")
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["errors"].append(str(exc))
    if report["errors"]:
        report["ok"] = False
    return report
