"""Lane A: real mcp_bridge over stdio (same binary/env Kiro uses)."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


class McpStdioClient:
    def __init__(self, proc: subprocess.Popen[str]):
        self.proc = proc
        self._id = 0

    def _next(self) -> int:
        self._id += 1
        return self._id

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 90.0,
    ) -> dict[str, Any]:
        assert self.proc.stdin and self.proc.stdout
        msg_id = self._next()
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            payload["params"] = params
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.proc.stdout.readline()
            if not raw:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"bridge exited early code={self.proc.returncode}")
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("id") != msg_id:
                continue
            if "error" in msg:
                raise RuntimeError(f"{method} error: {msg['error']}")
            return msg.get("result") or {}
        raise TimeoutError(f"{method} timed out after {timeout}s")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.proc.stdin
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        return self.request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            timeout=timeout,
        )


def content_text(result: dict[str, Any]) -> str:
    parts = result.get("content") or []
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            texts.append(str(p.get("text") or ""))
    return "\n".join(texts)


def parse_tool_json(result: dict[str, Any]) -> dict[str, Any]:
    text = content_text(result).strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"raw": text}
    except json.JSONDecodeError:
        return {"raw": text[:800]}


class BridgeHost:
    """Spawn scubiee-mcp-bridge like an IDE MCP host."""

    def __init__(
        self,
        *,
        repo: Path,
        project_id: str,
        engine_url: str,
        env_extra: dict[str, str] | None = None,
    ) -> None:
        self.repo = Path(repo).resolve()
        self.project_id = project_id
        self.engine_url = engine_url.rstrip("/")
        self.env_extra = dict(env_extra or {})
        self.proc: subprocess.Popen[str] | None = None
        self.client: McpStdioClient | None = None
        self.started_at: float | None = None

    def _entry(self) -> dict[str, Any]:
        from pipeline.mcp_install import server_entry

        return server_entry(self.repo, host="127.0.0.1", port=_port_from_url(self.engine_url))

    def start(self) -> dict[str, Any]:
        entry = self._entry()
        cmd = [str(entry["command"]), *[str(a) for a in (entry.get("args") or [])]]
        env = os.environ.copy()
        for k, v in (entry.get("env") or {}).items():
            env[str(k)] = str(v)
        env["CTX_ENGINE_URL"] = self.engine_url
        env["CTX_REPO"] = str(self.repo).replace("\\", "/")
        env["CTX_PROJECT_ID"] = self.project_id
        env["CTX_MCP_CLIENT"] = "kiro"
        env["CTX_MCP_EXPERIMENT"] = "ship"
        env["CTX_MCP_SURFACE"] = "phase"
        # Stable session so map_cache survives worker respawn; disable hot-reload
        # mid-run (uv install / file mtime) which wiped in-process map cache.
        env["CTX_MCP_SESSION_ID"] = env.get("CTX_MCP_SESSION_ID") or "mcp-host-sim-lane-a"
        env["CTX_MCP_HOT_RELOAD"] = env.get("CTX_MCP_HOT_RELOAD") or "0"
        # Force shared: auto mode was spawning tools/list on kiro@chat-* and
        # tools/call map on a second cold worker (SETTLE_MAP_SLOW 5–6s).
        env["CTX_MCP_BRIDGE_MODE"] = "shared"
        env["CTX_MAP_RESULT_CACHE_TTL_S"] = env.get("CTX_MAP_RESULT_CACHE_TTL_S") or "300"
        env["CTX_DISCONNECT_DEBOUNCE_S"] = env.get("CTX_DISCONNECT_DEBOUNCE_S") or "10"
        env.update(self.env_extra)
        # env_extra must not accidentally flip bridge back to auto mid-sim.
        if (env.get("CTX_MCP_BRIDGE_MODE") or "").strip().lower() == "auto":
            env["CTX_MCP_BRIDGE_MODE"] = "shared"
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        err_path = self.repo / "docs" / "superpowers" / "plans" / "_mcp_host_sim_bridge_stderr.txt"
        try:
            err_path.parent.mkdir(parents=True, exist_ok=True)
            self._stderr_file = open(err_path, "w", encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            self._stderr_file = subprocess.DEVNULL
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr_file,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=creationflags,
        )
        print(f"[mcp_host_sim] bridge cmd={cmd[0]!r} args={cmd[1:]!r} pid={self.proc.pid}", flush=True)
        self.client = McpStdioClient(self.proc)
        self.started_at = time.time()
        try:
            init = self.client.request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-host-sim", "version": "0.1"},
                },
                timeout=60,
            )
        except Exception:
            # Surface bridge crash reason for CONN_CLOSED debugging.
            try:
                if hasattr(self, "_stderr_file") and hasattr(self._stderr_file, "flush"):
                    self._stderr_file.flush()
                print(f"[mcp_host_sim] bridge stderr → {err_path}", flush=True)
                if err_path.is_file():
                    tail = err_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                    if tail.strip():
                        print(f"[mcp_host_sim] bridge stderr tail:\n{tail}", flush=True)
            except Exception:  # noqa: BLE001
                pass
            raise
        self.client.notify("notifications/initialized")
        return {"ok": True, "pid": self.proc.pid, "server": (init.get("serverInfo") or {})}

    def gate(self) -> dict[str, Any]:
        assert self.client
        raw = self.client.call_tool(
            "gate",
            {"project_id": self.project_id, "root": str(self.repo)},
            timeout=60,
        )
        return {"ok": True, "text": content_text(raw), "raw": raw}

    def status(self) -> dict[str, Any]:
        assert self.client
        raw = self.client.call_tool(
            "status",
            {
                "project_id": self.project_id,
                "root": str(self.repo),
                "detail": "summary",
                "session_id": "mcp-host-sim-lane-a",
            },
            timeout=12,
        )
        return parse_tool_json(raw)

    def map(self, query: str, *, k: int = 12) -> dict[str, Any]:
        assert self.client
        t0 = time.perf_counter()
        raw = self.client.call_tool(
            "map",
            {
                "query": query,
                "k": k,
                "project_id": self.project_id,
                "root": str(self.repo),
                "session_id": "mcp-host-sim-lane-a",
            },
            timeout=180,
        )
        data = parse_tool_json(raw)
        data["_elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return data

    def pack(
        self,
        query: str,
        *,
        seed_file: str,
        seed_symbol: str = "",
        seed2_file: str = "",
        seed2_symbol: str = "",
        seed3_file: str = "",
        seed3_symbol: str = "",
    ) -> dict[str, Any]:
        assert self.client
        args: dict[str, Any] = {
            "query": query,
            "seed_file": seed_file,
            "seed_symbol": seed_symbol,
            "mode": "lean",
            "project_id": self.project_id,
            "root": str(self.repo),
            "session_id": "mcp-host-sim-lane-a",
        }
        if seed2_file:
            args["seed2_file"] = seed2_file
            args["seed2_symbol"] = seed2_symbol
        if seed3_file:
            args["seed3_file"] = seed3_file
            args["seed3_symbol"] = seed3_symbol
        t0 = time.perf_counter()
        raw = self.client.call_tool("pack_context", args, timeout=180)
        data = parse_tool_json(raw)
        data["_elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return data

    def expand_context(
        self,
        *,
        node: str = "",
        seed_file: str = "",
        seed_symbol: str = "",
        direction: str = "broad",
        query: str = "",
    ) -> dict[str, Any]:
        assert self.client
        args: dict[str, Any] = {
            "direction": direction,
            "project_id": self.project_id,
            "root": str(self.repo),
            "session_id": "mcp-host-sim-lane-a",
        }
        if node:
            args["node"] = node
        if seed_file:
            args["seed_file"] = seed_file
            args["seed_symbol"] = seed_symbol
        if query:
            args["query"] = query
        t0 = time.perf_counter()
        raw = self.client.call_tool("expand_context", args, timeout=120)
        data = parse_tool_json(raw)
        data["_elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return data

    def stop(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": True}
        if self.proc is None:
            return out
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=8)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass
        out["returncode"] = self.proc.returncode
        self.proc = None
        self.client = None
        try:
            sf = getattr(self, "_stderr_file", None)
            if sf is not None and sf is not subprocess.DEVNULL:
                sf.close()
        except Exception:  # noqa: BLE001
            pass
        self._stderr_file = None
        return out


def _port_from_url(url: str) -> int:
    try:
        from urllib.parse import urlparse

        p = urlparse(url)
        if p.port:
            return int(p.port)
    except Exception:  # noqa: BLE001
        pass
    return 8765
