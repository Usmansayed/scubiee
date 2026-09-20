"""Cursor MCP entry for an installed Scubiee package (no source tree)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _pipeline_site_installed() -> bool:
    """True when ``pipeline`` comes from site/dist-packages (not source sys.path)."""
    try:
        import pipeline

        parts = {p.lower() for p in Path(pipeline.__file__).resolve().parts}
        return "site-packages" in parts or "dist-packages" in parts
    except Exception:  # noqa: BLE001
        return False


def _uv_tool_scubiee_python(*, prefer_pythonw: bool = False) -> str | None:
    """Locate the ``uv tool install scubiee`` interpreter when present."""
    home = Path.home()
    appdata = os.environ.get("APPDATA") or ""
    candidates: list[Path] = []
    if os.name == "nt":
        if appdata:
            base = Path(appdata) / "uv" / "tools" / "scubiee" / "Scripts"
            if prefer_pythonw:
                candidates.append(base / "pythonw.exe")
            candidates.append(base / "python.exe")
            if not prefer_pythonw:
                candidates.append(base / "pythonw.exe")
        local = home / ".local" / "bin"
        # uv shims are not usable as -m parents; skip.
        _ = local
    else:
        base = home / ".local" / "share" / "uv" / "tools" / "scubiee" / "bin"
        candidates.append(base / "python")
    for c in candidates:
        if c.is_file():
            return str(c).replace("\\", "/")
    return None


def interpreter() -> str:
    """Python that can ``import pipeline`` for Cursor MCP.

    Do **not** ``Path.resolve()`` the executable: on macOS a venv's
    ``bin/python`` is a symlink into Homebrew's Cellar, and resolving it
    drops the venv ``site-packages`` → ``ModuleNotFoundError: pipeline``.
    Prefer ``CTX_PYTHON``, then an installed scubiee tool env when the host
    only imports ``pipeline`` via source-tree ``sys.path`` (host-sim / pytest),
    then ``sys.prefix``'s python, then ``sys.executable`` as written.
    """
    override = (os.environ.get("CTX_PYTHON") or "").strip()
    if override:
        return override.replace("\\", "/")
    # Dev host (miniconda + packages/ on sys.path) must not spawn its own
    # pythonw for MCP — children do not inherit that path and crash with
    # ModuleNotFoundError: pipeline. Do **not** steal the uv-tool interpreter
    # when the caller already pointed sys.executable at a venv Scripts/bin shim
    # (unit tests + intentional venvs).
    if not _pipeline_site_installed() and _host_needs_uv_tool_python():
        tool_py = _uv_tool_scubiee_python(prefer_pythonw=(os.name == "nt"))
        if tool_py:
            return tool_py
    if os.name == "nt":
        pyw = Path(sys.prefix) / "Scripts" / "pythonw.exe"
        if pyw.is_file():
            return str(pyw).replace("\\", "/")
        candidate = Path(sys.prefix) / "Scripts" / "python.exe"
    else:
        candidate = Path(sys.prefix) / "bin" / "python"
    if candidate.is_file():
        return str(candidate).replace("\\", "/")
    return str(Path(sys.executable)).replace("\\", "/")


def _host_needs_uv_tool_python() -> bool:
    """True for naked host interpreters (conda/system), false for venv shims."""
    exe = Path(sys.executable)
    prefix = Path(sys.prefix)
    for sub in ("bin", "Scripts"):
        if exe.parent == prefix / sub:
            return False
    return True


def server_entry(
    repo: Path | str | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> dict[str, Any]:
    """MCP server block that works after `pip install scubiee`.

    Prefers ``scubiee-mcp-bridge`` (stable stdio proxy; hot-respawns workers after
    upgrade). Falls back to ``scubiee-mcp``, then ``python -m pipeline.mcp_locate``.
    """
    import shutil

    from pipeline.mcp_hot_reload import ensure_active_build_stamp

    engine_url = os.environ.get("CTX_ENGINE_URL") or f"http://{host}:{port}"
    from pipeline.settings import get_registration_mode

    reg_mode = get_registration_mode()
    env: dict[str, str] = {
        "CTX_ENGINE_URL": engine_url,
        "CTX_TOKEN_MODE": "savings",
        "CTX_BACKGROUND_SYNC": "1",
        "CTX_ALLOW_BG_FULL": "0",
        "CTX_AUTO_INDEX": "1",
        "CTX_SYNC_INTERVAL_MS": "300000",
        "CTX_REGISTRATION_MODE": reg_mode,
        "CTX_MCP_SURFACE": "phase",
        "CTX_MCP_EXPERIMENT": "ship",
        "CTX_TRACE_GRAPHIFY": "1",
        "CTX_MCP_SESSION_ISOLATE": "1",
        "CTX_MCP_BRIDGE_MODE": "shared",
        "CTX_ENGINE_IDLE_S": "10",
        "CTX_DISCONNECT_DEBOUNCE_S": "10",
        "CTX_ENGINE_TRANSITION_DEBOUNCE_S": "5",
        "CTX_EMBED_IDLE_DEMOTE_S": "10",
        "CTX_EMBED_PREWARM": "1",
        "CTX_TRACE_PARALLEL": "1",
        "CTX_ENGINE_SPAWN_OWNER": "supervisor",
        "CTX_LOCATE_STREAK_MS": "60000",
        "CTX_EMBED_KEEPALIVE": "1",
        # 15s keeps DirectML hot so map after idle stays <1s (was 45s).
        "CTX_EMBED_KEEPALIVE_S": "15",
        # Polite cap: 25% starved ORT; 0 was uncapped. 35% ≈ old wait-then-ms
        # politeness without collapsing to one core on typical desktops.
        "CTX_ENGINE_CPU_CAP_PCT": "35",
        # 1.5 GB tree — 800 MB squeezed the embedder out; 4096 was uncapped.
        "CTX_CE_RSS_CAP_MB": "1536",
        "CTX_SCUBIEE_TOTAL_RSS_MB": "1536",
        "CTX_KEEPER_DEFER_WHILE_CLIENTS": "1",
        # Low-end DirectML/ORT cold load often exceeds 30s under the CPU cap.
        "CTX_WARM_DEADLINE_MS": "90000",
        "PYTHONUTF8": "1",
    }
    # Always refresh stamp to installed version so connect/mcp.json don't lag (R9).
    env["CTX_SCUBIEE_BUILD"] = str(ensure_active_build_stamp()["build_id"])
    # Per-chat isolation: host-native keys (CLAUDE_CODE_SESSION_ID, MCP_SESSION_ID, …)
    # or explicit CTX_MCP_SESSION_ID — see session_isolation.detect_host_chat_session_from_env
    for session_key in (
        "CTX_MCP_SESSION_ID",
        "MCP_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
    ):
        session_val = (os.environ.get(session_key) or "").strip()
        if session_val:
            env[session_key] = session_val
            break
    if repo is not None:
        resolved = Path(repo).resolve()
        env["CTX_REPO"] = str(resolved).replace("\\", "/")
        try:
            from pipeline.project_id import read_id_file

            project_id = read_id_file(resolved)
            if project_id:
                env["CTX_PROJECT_ID"] = project_id
        except Exception:  # noqa: BLE001
            pass

    # Prefer the bridge — stable entry for hot reload after upgrade.
    # Windows: NEVER point Cursor at the uv *.EXE console shims — those are
    # subsystem=CONSOLE and every MCP reconnect allocates conhost (visible blink /
    # DWM window trails). Launch via pythonw -m instead; stdio still works when
    # the IDE owns the pipes.
    if os.name == "nt":
        try:
            from pipeline.process_job import background_python

            # Prefer MCP interpreter() when host is source-tree (dev sim) so we
            # do not spawn miniconda pythonw without site-packages pipeline.
            if not _pipeline_site_installed():
                pyw = interpreter()
            else:
                pyw = background_python()
        except Exception:  # noqa: BLE001
            pyw = interpreter()
        pyw_s = str(Path(pyw)).replace("\\", "/")
        # Worker children also use pythonw (bridge CREATE_NO_WINDOW alone is not enough
        # if the shim itself is a console EXE).
        env["CTX_MCP_BRIDGE_SPAWN_JSON"] = json.dumps(
            [pyw_s, "-u", "-m", "pipeline.mcp_locate"]
        )
        return {
            "command": pyw_s,
            "args": ["-u", "-m", "pipeline.mcp_bridge"],
            "env": env,
            # Claude Code (and other Node hosts) honor this → CREATE_NO_WINDOW.
            # Cursor may ignore unknown keys; crash-loop prevention still matters more.
            "windowsHide": True,
        }

    bridge_exe = shutil.which("scubiee-mcp-bridge")
    if bridge_exe:
        return {
            "command": bridge_exe.replace("\\", "/"),
            "args": [],
            "env": env,
        }
    # Fallback: direct scubiee-mcp executable.
    mcp_exe = shutil.which("scubiee-mcp")
    if mcp_exe:
        return {
            "command": mcp_exe.replace("\\", "/"),
            "args": [],
            "env": env,
        }
    # Fallback: raw Python interpreter + module
    return {
        "command": interpreter(),
        "args": ["-u", "-m", "pipeline.mcp_locate"],
        "env": env,
    }


def _merge_idle_env_max(dst_env: dict[str, str], prior_env: dict[str, Any] | None) -> None:
    """Keep a higher *transition* debounce on reconnect; disconnect unload stays at install defaults.

    ``CTX_DISCONNECT_DEBOUNCE_S`` / ``CTX_ENGINE_IDLE_S`` are disconnect-unload
    knobs (default 10s) and must not be sticky-raised from old 300s installs.
    ``CTX_EMBED_IDLE_DEMOTE_S`` stays a short GPU demote (default 10s).
    """
    if not isinstance(prior_env, dict):
        return
    key = "CTX_ENGINE_TRANSITION_DEBOUNCE_S"
    try:
        old = float(str(prior_env.get(key) or "").strip() or "0")
    except ValueError:
        old = 0.0
    try:
        new = float(str(dst_env.get(key) or "").strip() or "0")
    except ValueError:
        new = 0.0
    if old > new:
        dst_env[key] = str(int(old) if old == int(old) else old)


def merge_mcp_json(
    path: Path,
    *,
    name: str | None = None,
    repo: Path | str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    from pipeline.branding import MCP_SERVER_NAME, strip_legacy_mcp_keys

    server_name = name or MCP_SERVER_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"mcpServers": {}}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    strip_legacy_mcp_keys(servers)
    prior = servers.get(server_name) if isinstance(servers.get(server_name), dict) else {}
    prior_env = prior.get("env") if isinstance(prior, dict) else None
    entry = server_entry(repo, host=host, port=port)
    env = entry.get("env")
    if isinstance(env, dict):
        _merge_idle_env_max(env, prior_env if isinstance(prior_env, dict) else None)
    servers[server_name] = entry
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _find_mcp_server_entry(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = data.get("servers")
    if isinstance(servers, dict):
        entry = servers.get(name)
        if isinstance(entry, dict):
            return entry
    amp_servers = data.get("amp.mcpServers")
    if isinstance(amp_servers, dict):
        entry = amp_servers.get(name)
        if isinstance(entry, dict):
            return entry
    context = data.get("context_servers")
    if isinstance(context, dict):
        entry = context.get(name)
        if isinstance(entry, dict):
            return entry
    mcp = data.get("mcp")
    if isinstance(mcp, dict):
        nested = mcp.get("servers")
        if isinstance(nested, dict):
            entry = nested.get(name)
            if isinstance(entry, dict):
                return entry
        entry = mcp.get(name)
        if isinstance(entry, dict):
            return entry
    return None


def _entry_command_text(entry: dict[str, Any]) -> str:
    """Full launcher blob: command + args (Windows pins put the module in args)."""
    cmd = entry.get("command")
    if isinstance(cmd, list):
        text = " ".join(str(x) for x in cmd)
    else:
        text = str(cmd or "")
    args = entry.get("args") or []
    if isinstance(args, list) and args:
        text = f"{text} {' '.join(str(a) for a in args)}"
    return text


def verify_mcp_json(path: Path, *, server_name: str | None = None) -> dict[str, Any]:
    """Post-write check: scubiee entry exists and points at bridge/worker with build env."""
    from pipeline.branding import MCP_SERVER_NAME

    name = server_name or MCP_SERVER_NAME
    report: dict[str, Any] = {"ok": False, "path": str(path)}
    if not path.is_file():
        report["error"] = "missing_file"
        return report
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report["error"] = f"invalid_json: {exc}"
        return report
    if not isinstance(data, dict):
        report["error"] = "invalid_root"
        return report
    entry = _find_mcp_server_entry(data, name)
    if entry is None:
        report["error"] = "server_missing"
        return report
    from pipeline.mcp_restore import is_live_scubiee_mcp_launcher

    cmd = _entry_command_text(entry)
    live = is_live_scubiee_mcp_launcher(entry)
    cmd_l = cmd.lower()
    uses_bridge = "mcp_bridge" in cmd_l or "scubiee-mcp-bridge" in cmd_l
    uses_worker = ("scubiee-mcp" in cmd_l and "bridge" not in cmd_l) or (
        "pipeline.mcp_locate" in cmd_l
    )
    env_raw = entry.get("env")
    if not isinstance(env_raw, dict):
        env_raw = entry.get("environment")
    env = env_raw if isinstance(env_raw, dict) else {}
    has_build = bool(str(env.get("CTX_SCUBIEE_BUILD") or "").strip())
    report.update(
        {
            "uses_bridge": uses_bridge,
            "uses_worker": uses_worker,
            "live_launcher": live,
            "has_build_env": has_build,
        }
    )
    if not live:
        report["error"] = "bad_command"
        return report
    if not has_build:
        report["error"] = "missing_build_env"
        return report
    report["ok"] = True
    return report


def write_kiro_mcp(
    repo: Path | str | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> dict[str, str]:
    """Write repo-aware and repo-neutral Kiro MCP configuration.

    Kiro loads user-level settings for every workspace, so that entry must not
    contain ``CTX_REPO``.  The workspace-level entry is the one that pins the
    server to the repository being configured.
    """
    target_repo = Path(repo or Path.cwd()).resolve()
    project = target_repo / ".kiro" / "settings" / "mcp.json"
    user = Path.home() / ".kiro" / "settings" / "mcp.json"

    # Keep the global entry usable from any workspace, then let the closer
    # workspace scope provide the repository-specific environment.
    merge_mcp_json(user, repo=None, host=host, port=port)
    merge_mcp_json(project, repo=target_repo, host=host, port=port)
    return {"project": str(project), "user": str(user)}


def _context_agent_rule_template() -> Path:
    import pipeline

    return Path(pipeline.__file__).resolve().parent / "templates" / "scubiee.mdc"


def write_cursor_rule(repo: Path | str | None = None) -> str | None:
    """Write repo rule with real ``GATE 1:ce_…`` (included every chat by Cursor)."""
    from pipeline.rules_installer import _rule_content_mdc, gate_line_for_repo

    target = Path(repo or Path.cwd()).resolve()
    dest = target / ".cursor" / "rules" / "scubiee.mdc"
    dest.parent.mkdir(parents=True, exist_ok=True)
    gate = gate_line_for_repo(target)
    dest.write_text(_rule_content_mdc(gate_line=gate), encoding="utf-8")
    return str(dest)


def write_cursor_mcp(
    repo: Path | str | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> dict[str, str]:
    """Write project mcp.json with CTX_REPO; avoid a user-level CE block that overrides it."""
    project = Path.cwd() / ".cursor" / "mcp.json"
    user = Path.home() / ".cursor" / "mcp.json"
    target_repo = repo or Path.cwd()
    merge_mcp_json(project, repo=target_repo, host=host, port=port)
    _drop_user_context_engine_when_project_configured(project, user)
    out = {"project": str(project), "user": str(user)}
    rule = write_cursor_rule()
    if rule:
        out["rule"] = rule
    return out


def _drop_user_context_engine_when_project_configured(
    project: Path,
    user: Path,
    *,
    name: str | None = None,
) -> None:
    """Cursor merges user + project MCP; a user Scubiee block without CTX_REPO breaks locate."""
    from pipeline.branding import MCP_SERVER_NAMES

    if not project.is_file() or not user.is_file():
        return
    try:
        data = json.loads(user.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return
    names = (name,) if name else MCP_SERVER_NAMES
    changed = False
    for n in names:
        if n in servers:
            servers.pop(n, None)
            changed = True
    if not changed:
        return
    user.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
