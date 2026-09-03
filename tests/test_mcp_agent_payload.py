"""Host-agnostic MCP payload contracts: skinny status, dedup, bind copy."""

from __future__ import annotations

import json

import pytest

from pipeline.mcp_locate import (
    _BIND_ROOT_DESC,
    _BIND_SESSION_DESC,
    _annotate_locate_dedup,
    _summarize_status_payload,
)


def test_bind_copy_is_host_agnostic() -> None:
    assert "Cursor Workspace Path" not in _BIND_ROOT_DESC
    assert "workspace" in _BIND_ROOT_DESC.lower()
    assert "CTX_MCP_SESSION_ID" in _BIND_SESSION_DESC
    assert "Cursor/Copilot" not in _BIND_SESSION_DESC


def test_summarize_status_drops_keeper_keeps_action_fields() -> None:
    full = {
        "ok": True,
        "tool": "status",
        "server": "scubiee",
        "managed": True,
        "should_use_mcp": True,
        "should_retry_status": False,
        "warming": False,
        "agent_ready": "stale",
        "agent_ready_note": "Background sync active — recent file edits may be stale.",
        "sync_state": "syncing",
        "ready": False,
        "syncing": True,
        "next_action": None,
        "hint": "Do not poll status() in a loop.",
        "repo": "/tmp/proj",
        "index_available": True,
        "engine": {
            "healthy": True,
            "soft_search_ready": True,
            "warm_state": "ready",
            "warm_error": None,
            "project_id": "ce_abc",
            "meta": {"chunks": 4781, "files_indexed": 555},
        },
        "keeper": {"running": True, "dirty": {"paths": {"a.py": {"state": "processing"}}}},
        "session": {
            "session_id": "copilot@conn-1",
            "shared_process_risk": True,
            "n_spans": 3,
            "ledger": {"served_handles": ["sp_1"], "approx_prompt_tokens": 900},
            "hint": "long isolation prose " * 20,
        },
        "lifecycle": {"state": "ready", "steps": [{"action": "none", "why": "Ready"}]},
        "tools": ["gate", "map", "focus", "status"],
    }
    out = _summarize_status_payload(full)
    assert "keeper" not in out
    assert "meta" not in (out.get("engine") or {})
    assert "ledger" not in out
    assert out["agent_ready"] == "stale"
    assert out["agent_ready_note"]
    assert out["managed"] is True
    assert out["repo"] == "/tmp/proj"
    assert out["engine"]["project_id"] == "ce_abc"
    assert out["session_id"] == "copilot@conn-1"
    assert out["session_shared_risk"] is True
    assert out["n_spans"] == 3
    assert out["lifecycle_state"] == "ready"
    assert out["tools"] == ["gate", "map", "focus", "status"]
    assert "session_hint" not in out


def test_annotate_locate_dedup_sets_stop_locate_keeps_expand() -> None:
    card = {
        "ok": True,
        "status": "already_in_session",
        "unchanged": True,
        "handle": "sp_0001",
        "code": "",
        "next": "edit | expand(handle='sp_0001')",
        "usage_hint": "Advisory: unchanged/already_in_session. Edit now, or expand(handle).",
    }
    out = _annotate_locate_dedup(card)
    assert out["stop_locate"] is True
    assert out["locate_action"] == "edit_now"
    assert "expand" in out["next"]
    assert out["handle"] == "sp_0001"


def test_overlap_cap_block_is_success_stub_not_retry(tmp_path) -> None:
    from pipeline import mcp_locate as ml
    from pipeline.session_store import clear_store, save_store

    repo = tmp_path / "proj"
    repo.mkdir()
    clear_store(repo)
    save_store(
        repo,
        {
            "focus_seen": {
                "span:pkg/mod.py": {
                    "file": "pkg/mod.py",
                    "mode": "span",
                    "start_line": 1,
                    "end_line": 200,
                    "handle": "h1",
                }
            }
        },
    )
    overlap = ml._check_focus_overlap(repo, "pkg/mod.py", 100, 250, budget="cap")
    assert overlap is not None
    assert overlap["ok"] is True
    assert overlap["error"] == "overlapping_span"
    assert overlap["status"] == "already_in_session"
    assert overlap["stop_locate"] is True
    assert overlap["locate_action"] == "edit_now"
    assert overlap["handle"] == "h1"
    next_s = str(overlap.get("next") or "")
    assert "expand" in next_s
    assert "budget=full" not in next_s
    assert "budget=wide" not in next_s
    hint = str(overlap.get("hint") or "")
    assert "budget=" not in hint
    assert overlap["should_retry"] is False


def test_annotate_locate_dedup_noop_when_fresh() -> None:
    card = {"ok": True, "status": "stored", "unchanged": False, "code": "x"}
    out = _annotate_locate_dedup(card)
    assert "stop_locate" not in out
    assert out["code"] == "x"


def test_status_default_is_summary(monkeypatch, tmp_path) -> None:
    pytest.importorskip("mcp")
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / ".scubiee").mkdir()
    (repo / ".scubiee" / "id.json").write_text(
        json.dumps({"project_id": "ce_summ"}), encoding="utf-8"
    )
    monkeypatch.setenv("CTX_MCP_SURFACE", "phase")
    monkeypatch.setenv("CTX_REPO", str(repo))
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    (tmp_path / "ce-home").mkdir()
    monkeypatch.chdir(repo)
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_summ": {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )

    class FakeEng:
        base = "http://127.0.0.1:8765"

        def healthy(self) -> bool:
            return True

        def status(self, _root: str) -> dict:
            return {
                "ok": True,
                "warm_state": "ready",
                "soft_search_ready": True,
                "project_id": "ce_summ",
                "meta": {"chunks": 12},
                "keeper": {
                    "running": True,
                    "dirty": {"paths": {"a.py": {"state": "published"}}},
                    "last_sync": {"files": ["a.py"] * 30, "strategy": "incremental"},
                },
            }

    monkeypatch.setattr("pipeline.daemon.ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr("pipeline.client.EngineClient", lambda *a, **k: FakeEng())
    monkeypatch.setattr(
        "pipeline.session_store.load_store",
        lambda _r, **_: {"topic": None, "spans": {}, "focus_seen": {}, "ledger": {}},
    )
    from pipeline.mcp_locate import create_mcp

    fn = create_mcp()._tool_manager._tools["status"].fn
    default = json.loads(fn())
    assert "keeper" not in default
    assert default["agent_ready"] in {"yes", "stale", "warming"}
    assert default["managed"] is True
    full = json.loads(fn(detail="full"))
    assert "keeper" in full
    assert full["engine"]["meta"]["chunks"] == 12
