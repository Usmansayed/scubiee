"""Post-update / post-unlock heal: free locks, rebind daemon, restore MCP.

Research (uv Access-denied + Cursor MCP orphan locks on Windows):
- Disable/stub MCP *before* killing so the host cannot respawn lockers.
- Kill by real cmdline (``pipeline engine run``) + LISTEN port, not only lock pid.
- Rename-aside for tool dir swaps; retry with backoff.
- Rebind the *current* repo and restore live MCP pins so agents work again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def heal_runtime(
    repo: Path | str | None = None,
    *,
    connect: bool = True,
    unlock_tool_dir: bool = False,
) -> dict[str, Any]:
    """One-shot recovery after upgrade / Access denied / dead pytest bind.

    Default path: sweep engine port/lock → restore pins → ensure daemon →
    optional connect.

    ``unlock_tool_dir`` uses the nuclear ``release_scubiee_process_locks`` path
    (wipe-grade). Default heal avoids it — that path can hang for minutes on
    IDE-respawned MCP / uv-tool PIDs.
    """
    import sys
    import time
    from urllib.parse import urlparse

    root = Path(repo or Path.cwd()).resolve()
    out: dict[str, Any] = {"ok": True, "repo": str(root), "steps": {}}
    t0 = time.time()

    def _progress(step: str) -> None:
        elapsed = round(time.time() - t0, 1)
        print(f"[scubiee heal] {step} (+{elapsed}s)", file=sys.stderr, flush=True)

    from pipeline.client import engine_url
    from pipeline.process_control import (
        kill_all_engine_daemons,
        release_scubiee_process_locks,
        unlock_uv_tool_env,
    )

    try:
        port = int(urlparse(engine_url()).port or 8765)
    except Exception:  # noqa: BLE001
        port = 8765

    if unlock_tool_dir:
        _progress("releasing process locks (unlock mode)")
        out["steps"]["release"] = release_scubiee_process_locks(
            project=root,
            strip_mcp=False,
            settle_s=2.0,
            rounds=2,
        )
        _progress("unlocking uv tool dir")
        out["steps"]["unlock_tool"] = unlock_uv_tool_env(project=root)
    else:
        # Prefer a single hard sweep — stop_daemon + worker kill both soft-POST
        # /v1/shutdown and can stall on a half-dead listener (Windows).
        _progress("sweeping engine daemons")
        out["steps"]["engine_sweep"] = kill_all_engine_daemons(port=port, wait_s=3.0)
        try:
            from pipeline.daemon import release_lock

            release_lock()
        except Exception:  # noqa: BLE001
            pass
        # Skip MCP worker kill on the default path — enumerate_scubiee_processes
        # is slow on Windows and workers respawn from the bridge on next tool call.

    try:
        from pipeline.mcp_restore import heal_mcp_pins_if_stubbed

        _progress("restoring MCP pins")
        out["steps"]["mcp_restore"] = heal_mcp_pins_if_stubbed()
    except Exception as exc:  # noqa: BLE001
        out["steps"]["mcp_restore"] = {"ok": False, "error": str(exc)}

    try:
        from pipeline.client import EngineClient
        from pipeline.daemon import ensure_daemon

        _progress("ensuring daemon")
        ensured = ensure_daemon(root, force_if_hung=True)
        out["steps"]["ensure"] = ensured
        if not ensured.get("ok"):
            from pipeline.daemon import force_restart_daemon

            _progress("force-restarting daemon")
            out["steps"]["force_restart"] = force_restart_daemon(root)
        client = EngineClient(workspace_path=str(root), timeout=45.0)
        _progress("opening repo")
        opened = client.open_repo(str(root), wait=True)
        out["steps"]["open_repo"] = opened
        if not opened.get("ok"):
            out["ok"] = False
    except Exception as exc:  # noqa: BLE001
        out["steps"]["ensure"] = {"ok": False, "error": str(exc)}
        out["ok"] = False

    if connect:
        try:
            from pipeline.rules_installer import install_tools

            _progress("reconnecting MCP tools")
            connected = install_tools(["cursor"], dry_run=False, repo=root)
            out["steps"]["connect"] = connected
            if isinstance(connected, list):
                if any(not (r or {}).get("ok", True) for r in connected if isinstance(r, dict)):
                    out["ok"] = False
            elif isinstance(connected, dict) and connected.get("ok") is False:
                out["ok"] = False
        except Exception as exc:  # noqa: BLE001
            out["steps"]["connect"] = {"ok": False, "error": str(exc)}
            out["ok"] = False

    try:
        from pipeline.client import EngineClient

        _progress("health check")
        healthy = EngineClient(workspace_path=str(root), timeout=5.0).healthy()
        out["healthy"] = healthy
        if not healthy:
            out["ok"] = False
    except Exception as exc:  # noqa: BLE001
        out["healthy"] = False
        out["ok"] = False
        out["health_error"] = str(exc)

    out["elapsed_s"] = round(time.time() - t0, 1)
    out["hint"] = (
        "Reload Scubiee MCP in Cursor after heal. "
        "If uv tool install still Access-denied: scubiee heal --unlock"
    )
    _progress(f"done ok={out.get('ok')} healthy={out.get('healthy')}")
    return out
