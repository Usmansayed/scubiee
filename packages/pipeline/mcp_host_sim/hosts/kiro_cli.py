"""Lane B: Kiro MCP pins + optional real kiro-cli chat."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

KNOWN_KIRO = Path(r"C:\Users\usman\AppData\Local\Kiro-Cli\kiro-cli.exe")


def kiro_cli_path() -> Path | None:
    for name in ("kiro-cli", "kiro"):
        found = shutil.which(name)
        if found:
            return Path(found)
    if KNOWN_KIRO.is_file():
        return KNOWN_KIRO
    return None


def _kiro_key(repo: Path) -> str:
    env = os.environ.get("KIRO_API_KEY", "").strip()
    if env:
        return env
    dotenv = repo / ".env"
    if not dotenv.is_file():
        return ""
    for line in dotenv.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("KIRO_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


class KiroHost:
    """Write production Kiro MCP pins; optionally drive ``kiro-cli chat``."""

    def __init__(self, *, repo: Path, project_id: str, engine_url: str) -> None:
        self.repo = Path(repo).resolve()
        self.project_id = project_id
        self.engine_url = engine_url
        self.bin = kiro_cli_path()
        self._available = self.bin is not None

    @property
    def available(self) -> bool:
        return self._available

    def start(self) -> dict[str, Any]:
        try:
            from pipeline.mcp_install import merge_mcp_json

            port = urlparse(self.engine_url).port or 8765
            mcp = self.repo / ".kiro" / "settings" / "mcp.json"
            merge_mcp_json(mcp, repo=self.repo, port=int(port))
            self._pin_kiro_client(mcp)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "code": "HOST_SETUP", "error": str(exc)}
        return {
            "ok": True,
            "pins": True,
            "kiro_cli": str(self.bin) if self.bin else None,
            "hint": (
                "Kiro MCP pins written. SLA is BridgeHost with CTX_MCP_CLIENT=kiro "
                "(same stdio binary as .kiro/settings/mcp.json)."
            ),
        }

    def _pin_kiro_client(self, mcp: Path) -> None:
        try:
            data = json.loads(mcp.read_text(encoding="utf-8"))
            servers = data.get("mcpServers") or {}
            for entry in servers.values():
                if isinstance(entry, dict):
                    env = entry.setdefault("env", {})
                    if isinstance(env, dict):
                        env["CTX_MCP_CLIENT"] = "kiro"
            mcp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def drive_map(self, *, query: str) -> dict[str, Any]:
        """Best-effort live kiro-cli chat that must start MCP and call map."""
        if self.bin is None or not self.bin.is_file():
            return {"ok": True, "skipped": True, "reason": "kiro_cli_missing"}
        key = _kiro_key(self.repo)
        if not key:
            return {"ok": True, "skipped": True, "reason": "KIRO_API_KEY missing"}
        prompt = (
            "Call Scubiee MCP map once with this query (do not skip tools): "
            f"{query[:400]}. Then reply MAP_OK or MAP_FAIL only."
        )
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("CURSOR_") and not k.startswith("__CURSOR")
        }
        env["KIRO_API_KEY"] = key
        env["PATH"] = str(Path.home() / ".local" / "bin") + os.pathsep + env.get("PATH", "")
        cmd = [
            str(self.bin),
            "chat",
            "--no-interactive",
            "--trust-all-tools",
            "--require-mcp-startup",
            "--agent-engine",
            "v1",
            "--legacy-ui",
            "--effort",
            "low",
            "--wrap",
            "never",
            prompt,
        ]
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.repo),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "code": "KIRO_CHAT_TIMEOUT", "elapsed_ms": 180000.0}
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        ms = round((time.perf_counter() - t0) * 1000, 1)
        clean = out.replace("\x1b", "")
        startup_fail = "Not all mcp servers loaded" in clean
        ok = (not startup_fail) and proc.returncode == 0 and ("MAP_FAIL" not in clean)
        return {
            "ok": ok,
            "code": "KIRO_MCP_STARTUP" if startup_fail else (None if ok else "KIRO_CHAT"),
            "elapsed_ms": ms,
            "rc": proc.returncode,
            "tail": [ln for ln in clean.splitlines() if ln.strip()][-20:],
        }

    def stop(self) -> dict[str, Any]:
        return {"ok": True}
