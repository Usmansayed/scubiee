"""Minimal pyright language-server client (stdio JSON-RPC) for experiments.

Spawns: npx --yes -p pyright pyright-langserver --stdio
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import pathname2url


@dataclass
class LspLocation:
    path: str  # absolute or workspace-relative
    line: int  # 1-based
    character: int = 0


def _path_to_uri(path: Path) -> str:
    resolved = path.resolve()
    # file:///C:/... on Windows
    return "file:///" + pathname2url(str(resolved)).lstrip("/")


def _uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    p = unquote(parsed.path)
    if os.name == "nt" and p.startswith("/") and len(p) > 2 and p[2] == ":":
        p = p[1:]
    return Path(p)


class PyrightLsp:
    """Context-managed pyright LSP. Soft-fails: available=False on spawn/init error."""

    def __init__(self, root: Path, *, timeout_s: float = 30.0) -> None:
        self.root = root.resolve()
        self.timeout_s = timeout_s
        self.available = False
        self.error: str | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._id = 0
        self._pending: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._opened: set[str] = set()
        self._stderr_tail: list[str] = []

    def __enter__(self) -> PyrightLsp:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.shutdown()

    def start(self) -> bool:
        cmd = [
            "npx",
            "--yes",
            "-p",
            "pyright",
            "pyright-langserver",
            "--stdio",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.root),
                shell=(os.name == "nt"),
            )
        except OSError as exc:
            self.error = f"spawn failed: {exc}"
            self.available = False
            return False

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

        try:
            init = self._request(
                "initialize",
                {
                    "processId": os.getpid(),
                    "rootUri": _path_to_uri(self.root),
                    "capabilities": {
                        "textDocument": {
                            "definition": {"linkSupport": True},
                            "references": {},
                        }
                    },
                    "workspaceFolders": [
                        {"uri": _path_to_uri(self.root), "name": self.root.name}
                    ],
                },
                timeout=self.timeout_s,
            )
            if init is None:
                self.error = "initialize timeout/failed"
                self.available = False
                return False
            self._notify("initialized", {})
            self.available = True
            return True
        except Exception as exc:  # noqa: BLE001
            self.error = f"initialize error: {exc}"
            self.available = False
            return False

    def shutdown(self) -> None:
        if self._proc is None:
            return
        try:
            if self.available:
                self._request("shutdown", None, timeout=5.0)
                self._notify("exit", None)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001
                pass
        self._proc = None
        self.available = False

    def did_open(self, abs_path: Path, text: str | None = None) -> None:
        if not self.available:
            return
        uri = _path_to_uri(abs_path)
        if uri in self._opened:
            return
        if text is None:
            try:
                text = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return
        self._notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "python",
                    "version": 1,
                    "text": text,
                }
            },
        )
        self._opened.add(uri)
        # Give pyright a moment to analyze
        time.sleep(0.05)

    def definition(self, abs_path: Path, line: int, character: int = 0) -> list[LspLocation]:
        """line is 1-based (converted to 0-based for LSP)."""
        return self._locations(
            "textDocument/definition",
            abs_path,
            line,
            character,
        )

    def references(
        self,
        abs_path: Path,
        line: int,
        character: int = 0,
        *,
        include_declaration: bool = True,
    ) -> list[LspLocation]:
        if not self.available:
            return []
        self.did_open(abs_path)
        result = self._request(
            "textDocument/references",
            {
                "textDocument": {"uri": _path_to_uri(abs_path)},
                "position": {"line": max(0, line - 1), "character": max(0, character)},
                "context": {"includeDeclaration": include_declaration},
            },
            timeout=self.timeout_s,
        )
        return self._parse_locations(result)

    def _locations(
        self, method: str, abs_path: Path, line: int, character: int
    ) -> list[LspLocation]:
        if not self.available:
            return []
        self.did_open(abs_path)
        result = self._request(
            method,
            {
                "textDocument": {"uri": _path_to_uri(abs_path)},
                "position": {"line": max(0, line - 1), "character": max(0, character)},
            },
            timeout=self.timeout_s,
        )
        return self._parse_locations(result)

    def _parse_locations(self, result: Any) -> list[LspLocation]:
        if result is None:
            return []
        items: list[Any]
        if isinstance(result, list):
            items = result
        elif isinstance(result, dict):
            items = [result]
        else:
            return []
        out: list[LspLocation] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            # LocationLink
            target = it.get("targetUri") or (it.get("uri"))
            rng = it.get("targetSelectionRange") or it.get("targetRange") or it.get("range")
            if not target or not isinstance(rng, dict):
                continue
            start = rng.get("start") or {}
            out.append(
                LspLocation(
                    path=str(_uri_to_path(str(target))),
                    line=int(start.get("line", 0)) + 1,
                    character=int(start.get("character", 0)),
                )
            )
        return out

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _write(self, msg: dict[str, Any]) -> None:
        assert self._proc and self._proc.stdin
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        with self._lock:
            self._proc.stdin.write(header + body)
            self._proc.stdin.flush()

    def _notify(self, method: str, params: Any) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)

    def _request(self, method: str, params: Any, *, timeout: float) -> Any:
        rid = self._next_id()
        event = threading.Event()
        slot: dict[str, Any] = {"event": event, "result": None, "error": None}
        self._pending[rid] = slot
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)
        if not event.wait(timeout):
            self._pending.pop(rid, None)
            return None
        self._pending.pop(rid, None)
        if slot["error"]:
            return None
        return slot["result"]

    def _drain_stderr(self) -> None:
        if not self._proc or not self._proc.stderr:
            return
        for raw in self._proc.stderr:
            try:
                line = raw.decode("utf-8", errors="replace").rstrip()
            except Exception:  # noqa: BLE001
                break
            if line:
                self._stderr_tail.append(line)
                if len(self._stderr_tail) > 50:
                    self._stderr_tail = self._stderr_tail[-50:]

    def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        buf = b""
        while self._proc.poll() is None or buf:
            chunk = self._proc.stdout.read(1)
            if not chunk:
                if self._proc.poll() is not None:
                    break
                time.sleep(0.01)
                continue
            buf += chunk
            while True:
                sep = buf.find(b"\r\n\r\n")
                if sep < 0:
                    break
                header = buf[:sep].decode("ascii", errors="replace")
                length = 0
                for line in header.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        length = int(line.split(":", 1)[1].strip())
                body = buf[sep + 4 : sep + 4 + length]
                if len(body) < length:
                    break
                buf = buf[sep + 4 + length :]
                try:
                    msg = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                if "id" in msg and ("result" in msg or "error" in msg):
                    slot = self._pending.get(int(msg["id"]))
                    if slot:
                        slot["result"] = msg.get("result")
                        slot["error"] = msg.get("error")
                        slot["event"].set()
                # ignore server notifications/requests
