"""Minimal MCP stdio client for exercising a server the way Cursor spawns it.

Reads a Cursor ``mcp.json`` entry and speaks JSON-RPC over the child's stdio, so
tests go through the real process boundary instead of importing the tools.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


class McpError(RuntimeError):
    pass


class McpStdioClient:
    def __init__(self, command: str, args: list[str], env: dict[str, str] | None = None):
        self.command = command
        self.args = list(args)
        self.env = {**os.environ, **(env or {})}
        self._proc: subprocess.Popen | None = None
        self._id = 0

    @classmethod
    def from_config(cls, config: Path | str, server: str) -> "McpStdioClient":
        data = json.loads(Path(config).read_text(encoding="utf-8"))
        entry = (data.get("mcpServers") or {}).get(server)
        if not entry:
            raise McpError(f"server '{server}' not found in {config}")
        return cls(entry["command"], entry.get("args", []), entry.get("env"))

    def __enter__(self) -> "McpStdioClient":
        self._proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=self.env,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ctx-eval", "version": "0"},
            },
        )
        self._notify("notifications/initialized", {})
        return self

    def __exit__(self, *_exc) -> None:
        proc = self._proc
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        self._proc = None

    def _send(self, payload: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise McpError("server is not running")
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict) -> dict:
        self._id += 1
        mid = self._id
        self._send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
        if self._proc is None or self._proc.stdout is None:
            raise McpError("server is not running")
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise McpError(f"server closed stdout while waiting for {method}")
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # server logged to stdout; ignore non-JSON noise
            if obj.get("id") == mid:
                if obj.get("error"):
                    raise McpError(f"{method}: {obj['error']}")
                return obj.get("result") or {}

    def list_tools(self) -> list[str]:
        result = self._request("tools/list", {})
        return sorted(t["name"] for t in result.get("tools", []))

    def call_text(self, name: str, **arguments: Any) -> str:
        """Raw text of a tool result (what the agent's context actually pays for)."""
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        parts = [
            c.get("text") or ""
            for c in (result.get("content") or [])
            if isinstance(c, dict)
        ]
        return "\n".join(parts)

    def call(self, name: str, **arguments: Any) -> dict:
        text = self.call_text(name, **arguments)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return {"ok": False, "error": "non-json response", "text": text}
        return obj if isinstance(obj, dict) else {"ok": False, "value": obj}
