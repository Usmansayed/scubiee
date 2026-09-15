"""Release 0.3.72 — first MCP call returns warming+retry; no console-shim spawn."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.72",
    notes=(
        "First gate/status/map returns warming+should_retry instead of blocking "
        "on open_repo/index/FastEmbed (Cursor ~60s timeout). Background thread "
        "finishes embedder. MCP locate never force_restart_daemon. Windows MCP "
        "workers always pythonw -m (never uv scubiee-mcp.exe console shims). "
        "Disconnect unload unchanged."
    ),
)
class Release_0_3_72:
    pass
