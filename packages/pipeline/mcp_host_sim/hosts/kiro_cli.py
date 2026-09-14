"""Lane B: real Kiro CLI host (best-effort)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


class KiroHost:
    """Drive a real Kiro session when ``kiro`` is on PATH.

    v1: detect availability and document skip; full agent tool driving can
    deepen once Lane A SLAs are green. Prefer ``BridgeHost`` for CI.
    """

    def __init__(self, *, repo: Path, project_id: str, engine_url: str) -> None:
        self.repo = Path(repo).resolve()
        self.project_id = project_id
        self.engine_url = engine_url
        self._available = bool(shutil.which("kiro") or shutil.which("kiro-cli"))

    @property
    def available(self) -> bool:
        return self._available

    def start(self) -> dict[str, Any]:
        if not self.available:
            return {
                "ok": False,
                "code": "HOST_SETUP",
                "error": "kiro CLI not found on PATH — use --lane a or install Kiro",
            }
        # Ensure project MCP pins exist for this repo.
        try:
            from pipeline.mcp_install import merge_mcp_json
            from urllib.parse import urlparse

            port = urlparse(self.engine_url).port or 8765
            mcp = self.repo / ".kiro" / "settings" / "mcp.json"
            merge_mcp_json(mcp, repo=self.repo, port=int(port))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "code": "HOST_SETUP", "error": str(exc)}
        return {
            "ok": True,
            "deferred": True,
            "hint": (
                "Kiro MCP pins written. Lane B full auto-session is best-effort in v1; "
                "run BridgeHost (--lane a) for SLA gates, then open Kiro against this repo."
            ),
        }

    def stop(self) -> dict[str, Any]:
        return {"ok": True, "skipped": True}
