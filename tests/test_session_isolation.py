"""Per-session store isolation for multi-chat / multi-host MCP."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def _clear_session_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from pipeline.session_isolation import (
        _ENV_SCAN_PREFIXES,
        _ENV_SCAN_SKIP,
        _HOST_CHAT_SESSION_ENV_KEYS,
        _HOST_CHAT_SESSION_ENV_KEYS_BEST_EFFORT,
        _SESSION_KEY_MARKERS,
    )

    for key in (*_HOST_CHAT_SESSION_ENV_KEYS, *_HOST_CHAT_SESSION_ENV_KEYS_BEST_EFFORT):
        monkeypatch.delenv(key, raising=False)
    for key in list(os.environ):
        if key in _ENV_SCAN_SKIP:
            continue
        upper = key.upper()
        if not any(marker in upper for marker in _SESSION_KEY_MARKERS):
            continue
        if not any(upper.startswith(prefix) for prefix in _ENV_SCAN_PREFIXES):
            continue
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    ce = root / ".scubiee"
    ce.mkdir()
    (ce / "id.json").write_text(
        json.dumps({"project_id": "ce_iso_test1234567890abcdef"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return root


def test_session_stores_are_isolated(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_SESSION_ISOLATE", "1")
    from pipeline.session_store import load_store, put_span, recall
    from pipeline.session_isolation import session_data_dir

    put_span(
        repo,
        path="a.py",
        start_line=1,
        end_line=2,
        text="alpha",
        session_id="chat-a",
    )
    put_span(
        repo,
        path="b.py",
        start_line=1,
        end_line=2,
        text="beta",
        session_id="chat-b",
    )

    a = recall(repo, session_id="chat-a")
    b = recall(repo, session_id="chat-b")
    assert len(a.get("spans") or []) == 1
    assert len(b.get("spans") or []) == 1
    assert a["spans"][0]["path"] == "a.py"
    assert b["spans"][0]["path"] == "b.py"
    assert session_data_dir(repo, "chat-a").is_dir()
    assert session_data_dir(repo, "chat-b").is_dir()
    assert load_store(repo, session_id="chat-a") is not load_store(repo, session_id="chat-b")


def test_mcp_default_session_is_per_process(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_SESSION_ISOLATE", "1")
    monkeypatch.setenv("CTX_MCP_CLIENT", "codex")
    from pipeline.session_isolation import (
        _HOST_CHAT_SESSION_ENV_KEYS,
        _HOST_CHAT_SESSION_ENV_KEYS_BEST_EFFORT,
        default_process_session_id,
        effective_session_id,
    )
    from pipeline.work_session import pin

    for key in (*_HOST_CHAT_SESSION_ENV_KEYS, *_HOST_CHAT_SESSION_ENV_KEYS_BEST_EFFORT):
        monkeypatch.delenv(key, raising=False)
    _clear_session_env(monkeypatch)

    sid = effective_session_id(None)
    assert sid == default_process_session_id()
    assert sid.startswith("codex@proc-")
    pin(repo, "pkg/mod.py", session_id=sid)
    other = f"codex@proc-{os.getpid() + 9999}"
    assert load_pins(repo, other) == []


def test_host_chat_env_isolates_sessions(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_SESSION_ISOLATE", "1")
    monkeypatch.setenv("CTX_MCP_CLIENT", "claude-code")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "thread-abc")
    from pipeline.session_isolation import effective_session_id
    from pipeline.session_store import put_span, recall

    sid = effective_session_id(None)
    assert sid == "claude-code@chat-thread-abc"
    put_span(repo, path="x.py", start_line=1, end_line=1, text="one", session_id=sid)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "thread-xyz")
    sid2 = effective_session_id(None)
    assert sid2 == "claude-code@chat-thread-xyz"
    assert len(recall(repo, session_id=sid).get("spans") or []) == 1
    assert len(recall(repo, session_id=sid2).get("spans") or []) == 0


@pytest.mark.parametrize(
    ("env_key", "env_val", "expected_host"),
    [
        ("CURSOR_PROJECT_DIR", "/tmp/p", "cursor"),
        ("CLAUDE_PROJECT_DIR", "/tmp/p", "claude-code"),
        ("CODEX_WORKSPACE_ROOT", "/tmp/p", "codex"),
        ("COPILOT_WORKSPACE_FOLDER", "/tmp/p", "copilot"),
        ("CLINE_PROJECT_DIR", "/tmp/p", "cline"),
        ("OPENCODE_DEFAULT_PROJECT", "/tmp/p", "opencode"),
        ("WINDSURF_WORKSPACE", "/tmp/p", "windsurf"),
        ("CONTINUE_PROJECT_DIR", "/tmp/p", "continue"),
        ("ZED_PROJECT_DIR", "/tmp/p", "zed"),
        ("AMP_PROJECT_DIR", "/tmp/p", "amp"),
        ("PI_PROJECT_DIR", "/tmp/p", "pi"),
    ],
)
def test_detect_mcp_host_all_tools(
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    env_val: str,
    expected_host: str,
) -> None:
    from pipeline.host_workspace import host_env_signals

    monkeypatch.delenv("CTX_MCP_CLIENT", raising=False)
    for _slug, keys in host_env_signals():
        for key in keys:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(env_key, env_val)
    from pipeline.session_isolation import detect_mcp_host

    assert detect_mcp_host() == expected_host


def test_resolve_session_explicit_and_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_SESSION_ISOLATE", "1")
    monkeypatch.setenv("CTX_MCP_CLIENT", "cursor")
    from pipeline.session_isolation import (
        _HOST_CHAT_SESSION_ENV_KEYS,
        _HOST_CHAT_SESSION_ENV_KEYS_BEST_EFFORT,
        resolve_session,
    )

    for key in (*_HOST_CHAT_SESSION_ENV_KEYS, *_HOST_CHAT_SESSION_ENV_KEYS_BEST_EFFORT):
        monkeypatch.delenv(key, raising=False)
    _clear_session_env(monkeypatch)

    explicit = resolve_session("my-task")
    assert explicit["session_id"] == "my-task"
    assert explicit["source"] == "explicit"
    assert explicit["shared_process_risk"] is False

    proc = resolve_session(None)
    assert proc["source"] == "process"
    assert proc["session_id"].startswith("cursor@proc-")
    assert proc["shared_process_risk"] is True


def test_dynamic_env_scan_finds_cursor_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_CLIENT", "cursor")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("CURSOR_CHAT_ID", "abc-123")
    from pipeline.session_isolation import resolve_session

    info = resolve_session(None)
    assert info["source"] in {"host_env_scan", "host_env"}
    assert info["session_id"] == "cursor@chat-abc-123"


def test_claude_code_session_is_verified_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_CLIENT", "claude-code")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-xyz")
    from pipeline.session_isolation import resolve_session

    info = resolve_session(None)
    assert info["source"] == "host_env"
    assert info["env_key"] == "CLAUDE_CODE_SESSION_ID"
    assert info["shared_process_risk"] is False


def load_pins(root: Path, session_id: str) -> list[str]:
    from pipeline.work_session import load_session

    return load_session(root, session_id=session_id).get("pins") or []


def test_concurrent_session_writes(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_SESSION_ISOLATE", "1")
    from pipeline.session_store import put_span, recall

    def write(session: str, path: str) -> None:
        put_span(
            repo,
            path=path,
            start_line=1,
            end_line=1,
            text=f"body-{session}-{path}",
            session_id=session,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = []
        for i in range(8):
            sid = f"worker-{i % 2}"
            futs.append(pool.submit(write, sid, f"f{i}.py"))
        for f in futs:
            f.result()

    r0 = recall(repo, session_id="worker-0")
    r1 = recall(repo, session_id="worker-1")
    assert len(r0.get("spans") or []) == 4
    assert len(r1.get("spans") or []) == 4


def test_ctx_mcp_client_overrides_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CURSOR_PROJECT_DIR", "/tmp/p")
    monkeypatch.setenv("CTX_MCP_CLIENT", "continue")
    from pipeline.session_isolation import detect_mcp_host

    assert detect_mcp_host() == "continue"


def test_attach_gate_includes_session_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_SESSION_ISOLATE", "1")
    monkeypatch.setenv("CTX_MCP_CLIENT", "copilot")
    from pipeline.mcp_locate import _attach_gate
    from pipeline.session_isolation import bind_resolved_session, reset_resolved_session, resolve_session

    info = resolve_session("parallel-task-a")
    tok = bind_resolved_session(info)
    try:
        out = _attach_gate({"ok": True, "tool": "map"})
    finally:
        reset_resolved_session(tok)
    assert out["session_id"] == "parallel-task-a"
    assert out["session_source"] == "explicit"
