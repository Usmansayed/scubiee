"""CBM binary discovery + CLI proxy for graph tools."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Protocol


ALLOWLISTED_TOOLS = frozenset(
    {
        "search_graph",
        "trace_path",
        "get_code_snippet",
        "list_projects",
        "index_repository",
        "get_architecture",
    }
)


class CbmProxy(Protocol):
    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        ...

    def available(self) -> bool:
        ...

    def binary_path(self) -> str | None:
        ...


def resolve_cbm_bin(explicit: str | None = None) -> str | None:
    """Resolve CBM executable: arg → CTX_CBM_BIN / CBM_BIN → PATH."""
    for candidate in (
        explicit,
        (os.environ.get("CTX_CBM_BIN") or "").strip() or None,
        (os.environ.get("CBM_BIN") or "").strip() or None,
        shutil.which("codebase-memory-mcp"),
    ):
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return str(path.resolve())
        # shutil.which already returned an executable path string
        if candidate == shutil.which("codebase-memory-mcp"):
            return candidate
    return None


def project_name_from_repo(repo: Path) -> str:
    """Best-effort CBM project name from an absolute repo path.

    CBM indexes use a sanitized absolute path (e.g. ``C-Users-…-fixture``). Prefer
    resolving via ``list_projects`` when possible; this is the fallback sanitizer.
    """
    text = str(repo.resolve()).replace("\\", "/")
    out: list[str] = []
    for ch in text:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("-")
    name = "".join(out).strip("-")
    while "--" in name:
        name = name.replace("--", "-")
    return name


def parse_cli_payload(stdout: str) -> dict[str, Any]:
    """Unwrap CBM CLI MCP-style ``{content:[{text}]}`` into a JSON object."""
    raw = (stdout or "").strip()
    if not raw:
        return {"ok": False, "error": "empty CBM CLI stdout"}
    try:
        outer = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": "non-JSON CBM stdout", "raw": raw[:2000]}

    if isinstance(outer, dict) and outer.get("isError"):
        text = _content_text(outer)
        try:
            inner = json.loads(text) if text.startswith("{") else {"error": text}
        except json.JSONDecodeError:
            inner = {"error": text}
        if not isinstance(inner, dict):
            inner = {"error": text}
        return {"ok": False, **inner}

    if isinstance(outer, dict) and "content" in outer:
        text = _content_text(outer)
        if not text:
            return {"ok": True, "raw": outer}
        try:
            inner = json.loads(text)
        except json.JSONDecodeError:
            return {"ok": True, "text": text}
        if isinstance(inner, dict):
            if "error" in inner and "results" not in inner and "projects" not in inner:
                return {"ok": False, **inner}
            return {"ok": True, **inner}
        return {"ok": True, "data": inner}

    if isinstance(outer, dict):
        return {"ok": True, **outer}
    return {"ok": True, "data": outer}


def _content_text(outer: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in outer.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts).strip()


class NullProxy:
    """Proxy used when the CBM binary is missing."""

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": False,
            "error": "CBM binary not found",
            "hint": "Install codebase-memory-mcp or set CTX_CBM_BIN / CBM_BIN",
            "tool": tool,
            "arguments": arguments or {},
        }

    def available(self) -> bool:
        return False

    def binary_path(self) -> str | None:
        return None


class CliProxy:
    """Invoke stock CBM via ``codebase-memory-mcp cli <tool> '<json>'``."""

    def __init__(self, binary: str, *, timeout_s: float = 120.0) -> None:
        self._binary = binary
        self._timeout_s = timeout_s

    def available(self) -> bool:
        return bool(self._binary)

    def binary_path(self) -> str | None:
        return self._binary

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if tool not in ALLOWLISTED_TOOLS:
            return {
                "ok": False,
                "error": f"tool not allowlisted for hybrid proxy: {tool}",
                "allowlist": sorted(ALLOWLISTED_TOOLS),
            }
        cmd = [self._binary, "cli", tool]
        args = dict(arguments or {})
        if args:
            cmd.append(json.dumps(args, ensure_ascii=False))
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
                check=False,
            )
        except FileNotFoundError:
            return {
                "ok": False,
                "error": f"CBM binary missing at runtime: {self._binary}",
                "tool": tool,
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"CBM CLI timed out after {self._timeout_s:g}s",
                "tool": tool,
            }
        payload = parse_cli_payload(completed.stdout or "")
        payload.setdefault("tool", tool)
        if completed.returncode not in (0, None) and payload.get("ok") is not False:
            payload["ok"] = False
            payload.setdefault("error", f"CBM exit {completed.returncode}")
            if completed.stderr:
                payload["stderr_tail"] = completed.stderr[-500:]
        return payload


def make_proxy(explicit_bin: str | None = None) -> CbmProxy:
    path = resolve_cbm_bin(explicit_bin)
    if not path:
        return NullProxy()
    return CliProxy(path)


def resolve_project_name(proxy: CbmProxy, repo: Path) -> str:
    """Match indexed CBM project by root_path; else sanitized path name."""
    wanted = str(repo.resolve()).replace("\\", "/").rstrip("/").lower()
    listed = proxy.call("list_projects", {})
    projects = listed.get("projects") if isinstance(listed, dict) else None
    if isinstance(projects, list):
        for proj in projects:
            if not isinstance(proj, dict):
                continue
            root = str(proj.get("root_path") or "").replace("\\", "/").rstrip("/").lower()
            if root == wanted:
                name = str(proj.get("name") or "").strip()
                if name:
                    return name
    return project_name_from_repo(repo)


def ensure_indexed(proxy: CbmProxy, repo: Path) -> dict[str, Any]:
    """Index ``repo`` via CBM CLI (idempotent enough for trials)."""
    repo_path = str(repo.resolve()).replace("\\", "/")
    return proxy.call("index_repository", {"repo_path": repo_path})
