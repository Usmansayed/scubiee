"""Per-session isolation for MCP spans, recall, and workspace state.

Each MCP host connection (or explicit ``session_id``) gets its own store under
``.scubiee/sessions/<id>/``. See ``docs/mcp-multi-session-all-hosts-research.md``.
"""

from __future__ import annotations

import os
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator, Literal

_REQUEST_SESSION_ID: ContextVar[str | None] = ContextVar("scubiee_request_session_id", default=None)
_MCP_TRANSPORT_SESSION_ID: ContextVar[str | None] = ContextVar("scubiee_mcp_transport_session_id", default=None)
_RESOLVED_SESSION: ContextVar[dict[str, Any] | None] = ContextVar("scubiee_resolved_session", default=None)

SessionSource = Literal[
    "explicit",
    "request",
    "transport_client",
    "transport_conn",
    "host_env",
    "host_env_scan",
    "process",
    "legacy",
]

# Hosts that typically share one stdio MCP process across parallel chats (research 2026-08).
_SHARED_PROCESS_HOSTS: frozenset[str] = frozenset(
    {
        "cursor",
        "copilot",
        "codex",
        "vscode",
        "kiro",
        "windsurf",
        "cline",
        "roo-code",
        "continue",
        "zed",
        "opencode",
        "amp",
        "mcp",
    }
)

_HOST_ENV_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = ()

def _load_host_env_signals() -> tuple[tuple[str, tuple[str, ...]], ...]:
    from pipeline.host_workspace import host_env_signals

    return host_env_signals()


def _host_env_signals() -> tuple[tuple[str, tuple[str, ...]], ...]:
    global _HOST_ENV_SIGNALS
    if not _HOST_ENV_SIGNALS:
        _HOST_ENV_SIGNALS = _load_host_env_signals()
    return _HOST_ENV_SIGNALS

_HOST_CHAT_SESSION_ENV_KEYS: tuple[str, ...] = (
    "CTX_MCP_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "MCP_SESSION_ID",
)

_HOST_CHAT_SESSION_ENV_KEYS_BEST_EFFORT: tuple[str, ...] = (
    "CONVERSATION_ID",
    "CHAT_ID",
    "THREAD_ID",
)

_SESSION_KEY_MARKERS: tuple[str, ...] = ("SESSION", "CHAT", "CONVERSATION", "THREAD", "TASK")
_ENV_SCAN_PREFIXES: tuple[str, ...] = (
    "CTX_",
    "MCP_",
    "CLAUDE_",
    "CURSOR_",
    "CODEX_",
    "COPILOT_",
    "VSCODE_",
    "CLINE_",
    "ROO_",
    "CONTINUE_",
    "KIRO_",
    "WINDSURF_",
    "OPENCODE_",
    "AMP_",
    "PI_",
)
_ENV_SCAN_SKIP: frozenset[str] = frozenset(
    {
        "CTX_MCP_CLIENT",
        "CTX_MCP_SESSION_ISOLATE",
        "CTX_MCP_SURFACE",
        "CTX_REPO",
        "CTX_PROJECT_ID",
        "CTX_HOME",
        "CTX_ENGINE_URL",
        "CLAUDECODE",
        "CLAUDE_CODE_CHILD_SESSION",
    }
)

_SESSION_FILE_LOCKS: dict[str, threading.RLock] = {}
_SESSION_FILE_LOCKS_GUARD = threading.Lock()
_SAFE_SESSION_RE = re.compile(r"[^\w\-.:@+]+")


def bind_request_session(session_id: str | None) -> Any | None:
    raw = (session_id or "").strip()
    if not raw:
        return None
    return _REQUEST_SESSION_ID.set(sanitize_session_id(raw))


def reset_request_session(token: Any | None) -> None:
    if token is not None:
        _REQUEST_SESSION_ID.reset(token)


def bind_transport_session(session_id: str | None) -> Any | None:
    raw = (session_id or "").strip()
    if not raw:
        return None
    return _MCP_TRANSPORT_SESSION_ID.set(sanitize_session_id(raw))


def reset_transport_session(token: Any | None) -> None:
    if token is not None:
        _MCP_TRANSPORT_SESSION_ID.reset(token)


def bind_resolved_session(info: dict[str, Any]) -> Any | None:
    return _RESOLVED_SESSION.set(info)


def reset_resolved_session(token: Any | None) -> None:
    if token is not None:
        _RESOLVED_SESSION.reset(token)


def bind_transport_session_from_mcp(fastmcp: Any) -> Any | None:
    """Derive session id from MCP protocol context (connection or client meta)."""
    try:
        ctx = fastmcp.get_context()
    except Exception:  # noqa: BLE001
        return None
    host = detect_mcp_host()
    client_id = None
    try:
        client_id = ctx.client_id
    except (ValueError, AttributeError):
        client_id = None
    if client_id and str(client_id).strip():
        return bind_transport_session(f"{host}@chat-{client_id}")
    session = None
    try:
        session = ctx.session
    except (ValueError, AttributeError):
        session = None
    if session is not None:
        conn = f"{id(session) & 0xFFFFFF:06x}"
        return bind_transport_session(f"{host}@conn-{conn}")
    return None


def sanitize_session_id(raw: str) -> str:
    s = (raw or "").strip().replace(":", "@")
    s = _SAFE_SESSION_RE.sub("_", s)[:128]
    return s or "default"


def detect_mcp_host() -> str:
    explicit = (os.environ.get("CTX_MCP_CLIENT") or "").strip()
    if explicit:
        return explicit
    for slug, keys in _host_env_signals():
        for key in keys:
            if (os.environ.get(key) or "").strip():
                return slug
    return "mcp"


def _session_hint_echo(session_id: str) -> str:
    return (
        f"Pass session_id={session_id!r} on later Scubiee calls in this chat "
        "(recall, expand, workspace). For a parallel task, use a different session_id."
    )


def _session_hint_shared_process(host: str, session_id: str) -> str:
    return (
        f"Session {session_id!r} may be shared across parallel chats on {host} "
        "(one MCP process). For isolation: pass a distinct session_id per chat/task, "
        "or set CTX_MCP_SESSION_ID in the host MCP env block."
    )


def _make_session_info(
    session_id: str,
    source: SessionSource,
    *,
    env_key: str = "",
) -> dict[str, Any]:
    host = detect_mcp_host()
    shared = source in {"process", "transport_conn"} and host in _SHARED_PROCESS_HOSTS
    hint = _session_hint_echo(session_id)
    if shared:
        hint = _session_hint_shared_process(host, session_id)
    info: dict[str, Any] = {
        "session_id": session_id,
        "source": source,
        "host": host,
        "shared_process_risk": shared,
        "env_key": env_key or None,
        "hint": hint,
    }
    return info


def detect_host_chat_session_from_env() -> dict[str, Any] | None:
    """Chat/thread id from host env (re-scanned every call — some hosts may update)."""
    host = detect_mcp_host()
    for key in _HOST_CHAT_SESSION_ENV_KEYS:
        val = (os.environ.get(key) or "").strip()
        if not val:
            continue
        if key == "CTX_MCP_SESSION_ID" and "@" in val:
            sid = sanitize_session_id(val)
        else:
            sid = sanitize_session_id(f"{host}@chat-{val}")
        return _make_session_info(sid, "host_env", env_key=key)
    for key in _HOST_CHAT_SESSION_ENV_KEYS_BEST_EFFORT:
        val = (os.environ.get(key) or "").strip()
        if val:
            sid = sanitize_session_id(f"{host}@chat-{val}")
            return _make_session_info(sid, "host_env", env_key=key)
    scanned = _scan_env_for_session_id(host)
    if scanned:
        key, sid = scanned
        return _make_session_info(sid, "host_env_scan", env_key=key)
    return None


def _scan_env_for_session_id(host: str) -> tuple[str, str] | None:
    """Best-effort: host-prefixed env vars containing SESSION/CHAT/THREAD/etc."""
    skip = set(_HOST_CHAT_SESSION_ENV_KEYS) | set(_HOST_CHAT_SESSION_ENV_KEYS_BEST_EFFORT) | _ENV_SCAN_SKIP
    candidates: list[tuple[int, str, str]] = []
    for key, val in os.environ.items():
        if key in skip or not str(val or "").strip():
            continue
        upper = key.upper()
        if not any(marker in upper for marker in _SESSION_KEY_MARKERS):
            continue
        if not any(upper.startswith(prefix) for prefix in _ENV_SCAN_PREFIXES):
            continue
        if upper == "SESSION_ID":
            priority = 2
        elif "CODE_SESSION" in upper:
            priority = 0
        else:
            priority = 1
        candidates.append((priority, key, str(val).strip()))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    key, raw = candidates[0][1], candidates[0][2]
    if "@" in raw and key == "CTX_MCP_SESSION_ID":
        return key, sanitize_session_id(raw)
    return key, sanitize_session_id(f"{host}@chat-{raw}")


def default_process_session_id() -> str:
    transport = _MCP_TRANSPORT_SESSION_ID.get()
    if transport:
        return transport
    host = detect_mcp_host()
    return sanitize_session_id(f"{host}@proc-{os.getpid()}")


def resolve_session(explicit: str | None = None) -> dict[str, Any]:
    """Full session resolution with source metadata for tools and status()."""
    if explicit and str(explicit).strip():
        sid = sanitize_session_id(str(explicit).strip())
        return _make_session_info(sid, "explicit")

    req = _REQUEST_SESSION_ID.get()
    if req:
        return _make_session_info(req, "request")

    transport = _MCP_TRANSPORT_SESSION_ID.get()
    if transport:
        source: SessionSource = "transport_conn"
        if "@chat-" in transport:
            source = "transport_client"
        return _make_session_info(transport, source)

    from_env = detect_host_chat_session_from_env()
    if from_env:
        return from_env

    if _session_isolate_enabled():
        return _make_session_info(default_process_session_id(), "process")

    return _make_session_info("default", "legacy")


def session_context_for_response() -> dict[str, Any]:
    cached = _RESOLVED_SESSION.get()
    if cached:
        return cached
    return resolve_session(None)


def effective_session_id(explicit: str | None = None) -> str | None:
    info = resolve_session(explicit)
    sid = str(info.get("session_id") or "").strip()
    if sid and sid != "default":
        return sid
    if _session_isolate_enabled():
        return default_process_session_id()
    return None if sid == "default" else sid


def mcp_client_name() -> str:
    return detect_mcp_host()


def _session_isolate_enabled() -> bool:
    return (os.environ.get("CTX_MCP_SESSION_ISOLATE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def session_data_dir(repo: Path | str, session_id: str) -> Path:
    from pipeline.project_id import id_dir_path

    sid = sanitize_session_id(session_id)
    path = id_dir_path(Path(repo).resolve()) / "sessions" / sid
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_session_ids(repo: Path | str) -> list[str]:
    from pipeline.project_id import id_dir_path

    root = id_dir_path(Path(repo).resolve()) / "sessions"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def _lock_key(path: Path) -> str:
    return str(path.resolve())


def _file_lock_for(path: Path) -> threading.RLock:
    key = _lock_key(path)
    with _SESSION_FILE_LOCKS_GUARD:
        lock = _SESSION_FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _SESSION_FILE_LOCKS[key] = lock
        return lock


@contextmanager
def session_json_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    sidecar = path.with_suffix(path.suffix + ".lock")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock_for(path):
        handle = sidecar.open("a+b")
        try:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            _lock_file(handle)
            try:
                yield
            finally:
                _unlock_file(handle)
        finally:
            handle.close()


def _lock_file(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                time.sleep(0.02)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
