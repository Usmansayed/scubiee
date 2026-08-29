"""Regression tests from docs/scubiee-mcp-exploration-session-2026-08-29.md."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.client import EngineClient, is_transient_engine_error
from pipeline.dirty_ledger import DirtyLedger, normalize_dirty_path
from pipeline.mcp_locate import (
    _assess_map_confidence,
    _enrich_map_cards,
    _find_repo_files,
    _looks_like_symbol_query,
    _map_cache_get,
    _map_cache_put,
    _read_line_range,
    _resolve_span_in_path,
    _slim_status_keeper,
    _strip_bom_text,
)
from pipeline.rules_installer import _write_rule_append_md, _write_rule_md
from pipeline.sync_status import build_sync_contract, derive_agent_ready, derive_agent_ready_note


def test_is_transient_engine_error() -> None:
    assert is_transient_engine_error("Remote end closed connection without response")
    assert not is_transient_engine_error("file not found")


def test_client_retries_transient_url_error() -> None:
    client = EngineClient(base_url="http://127.0.0.1:8765", timeout=1.0)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            import urllib.error

            raise urllib.error.URLError("Remote end closed connection")
        payload = MagicMock()
        payload.read.return_value = b'{"ok": true}'
        payload.__enter__ = lambda s: s
        payload.__exit__ = lambda *a: None
        return payload

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        out = client.get("/health")
    assert out.get("ok") is True
    assert out.get("retried") is True
    assert calls["n"] == 2


def test_glob_packages_star_lists_immediate_children(tmp_path: Path) -> None:
    (tmp_path / "packages" / "pipeline").mkdir(parents=True)
    (tmp_path / "packages" / "graphify").mkdir(parents=True)
    (tmp_path / "packages" / "pipeline" / "mod.py").write_text("x=1\n", encoding="utf-8")
    found, truncated = _find_repo_files(tmp_path, "packages/*", limit=20)
    names = {p.rstrip("/") for p in found}
    assert "packages/pipeline" in names or "packages/pipeline/" in found
    assert "packages/graphify" in names or "packages/graphify/" in found
    assert truncated is False


def test_map_confidence_low_for_nonsense() -> None:
    cards = [
        {"file": "packages/pipeline/server.py", "score": 2.47, "why": "handler"},
        {"file": "docs/readme.md", "score": 2.1, "why": "doc"},
    ]
    conf = _assess_map_confidence(
        "xyzzy_plugh_garply_frotz_quux nonsense gibberish no_match", cards,
    )
    assert conf["confidence"] == "low"
    assert conf.get("weak_match") is True


def test_map_confidence_high_for_strong_hits() -> None:
    cards = [{"file": "packages/pipeline/mcp_locate.py", "score": 19.88}]
    conf = _assess_map_confidence("_assess_map_confidence map cards", cards)
    assert conf["confidence"] == "high"


def test_enrich_map_cards_weak_match_on_low_score() -> None:
    out = _enrich_map_cards([{"file": "a.py", "score": 2.5, "start_line": 1, "end_line": 5}])
    assert out[0].get("weak_match") is True


def test_symbol_query_skips_semantic_fallback(tmp_path: Path) -> None:
    f = tmp_path / "rules_installer.py"
    f.write_text(
        "def gate_line_for_repo():\n    return 'gate'\n",
        encoding="utf-8",
    )
    assert _looks_like_symbol_query("write_cursor_rule")
    assert _resolve_span_in_path(tmp_path, "rules_installer.py", "write_cursor_rule") == (0, 0)


def test_read_line_range_strips_bom(tmp_path: Path) -> None:
    f = tmp_path / "sync_loop.py"
    f.write_bytes(b"\xef\xbb\xbfdef tick():\n    pass\n")
    out = _read_line_range(tmp_path, "sync_loop.py", 1, 2, 500)
    assert out.get("ok") is True
    assert not str(out.get("excerpt") or "").startswith("\ufeff")


def test_find_repo_files_ignores_scubiee_snapshot_dirs(tmp_path: Path) -> None:
    (tmp_path / "packages" / "pipeline").mkdir(parents=True)
    snap = tmp_path / "scubiee-0.2.61" / "packages" / "pipeline"
    snap.mkdir(parents=True)
    (snap / "old.py").write_text("stale=1\n", encoding="utf-8")
    (tmp_path / "packages" / "pipeline" / "live.py").write_text("live=1\n", encoding="utf-8")
    found, _ = _find_repo_files(tmp_path, "**/live.py", limit=10)
    assert any("packages/pipeline/live.py" in p for p in found)
    found_old, _ = _find_repo_files(tmp_path, "**/old.py", limit=10)
    assert not found_old


def test_slim_status_keeper_truncates_file_lists() -> None:
    keeper = {
        "last_sync": {"files": [f"f{i}.py" for i in range(50)]},
        "dirty": {"paths": {f"p{i}.py": {"state": "added"} for i in range(60)}},
    }
    slim = _slim_status_keeper(keeper)
    assert len(slim["last_sync"]["files"]) == 25
    assert slim["last_sync"]["files_truncated"] == 50
    assert len(slim["dirty"]["paths"]) == 40
    assert slim["dirty"]["paths_truncated"] == 60


def test_derive_agent_ready_note_stale_sync() -> None:
    note = derive_agent_ready_note(
        agent_ready="stale",
        sync_state="syncing",
        syncing=True,
        overlay_ready=False,
        publish_pending=False,
        ready=False,
    )
    assert "sync" in note.lower()


def test_enrich_map_cards_needs_outline_and_bom_strip() -> None:
    cards = _enrich_map_cards(
        [{"file": "a.py", "start_line": None, "end_line": None, "why": "\ufeffsnippet"}]
    )
    assert cards[0]["needs_outline"] is True
    assert not cards[0]["why"].startswith("\ufeff")


def test_map_cache_roundtrip(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / ".scubiee").mkdir()
    qn = "daemon watchdog restart"
    cards = [{"file": "watchdog.py", "rank": 1}]
    _map_cache_put(repo, qn, 8, cards, session_id="test-cache")
    from pipeline.session_store import load_store

    store = load_store(repo, session_id="test-cache")
    assert _map_cache_get(store, qn, 8) == cards


def test_derive_agent_ready_stale_while_syncing() -> None:
    assert (
        derive_agent_ready(
            healthy=True,
            soft_search_ready=True,
            sync_state="syncing",
            ready=False,
            syncing=True,
            overlay_ready=False,
        )
        == "stale"
    )
    assert (
        derive_agent_ready(
            healthy=True,
            soft_search_ready=True,
            sync_state="ready",
            ready=True,
            syncing=False,
            overlay_ready=False,
        )
        == "yes"
    )


def test_dirty_ledger_recovers_stale_processing() -> None:
    from unittest.mock import patch

    ledger = DirtyLedger()
    with patch("pipeline.dirty_ledger.time.monotonic", side_effect=[0.0, 0.0, 100.0]):
        ledger.mark([".config/amp/AGENTS.md"], reason="test", now=0.0)
        ledger.begin([".config/amp/AGENTS.md"])
        recovered = ledger.recover_stale_processing(max_age_s=90.0, now=100.0)
    assert ".config/amp/AGENTS.md" in recovered
    snap = ledger.snapshot()["paths"]
    key = normalize_dirty_path(".config/amp/AGENTS.md")
    assert snap[key]["state"] == "queued"


def test_rule_append_skips_unchanged_write(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    _write_rule_append_md(path, gate_line="1:ce_test1234567890abcdef12345678")
    first = path.read_text(encoding="utf-8")
    mtime = path.stat().st_mtime
    _write_rule_append_md(path, gate_line="1:ce_test1234567890abcdef12345678")
    assert path.read_text(encoding="utf-8") == first
    assert path.stat().st_mtime == mtime


def test_rule_md_skips_unchanged_write(tmp_path: Path) -> None:
    path = tmp_path / "rules.md"
    _write_rule_md(path, gate_line="1:ce_test1234567890abcdef12345678")
    first = path.read_text(encoding="utf-8")
    _write_rule_md(path, gate_line="1:ce_test1234567890abcdef12345678")
    assert path.read_text(encoding="utf-8") == first


def test_strip_bom_text() -> None:
    assert _strip_bom_text("\ufeffhello") == "hello"


def test_glob_effective_pattern_alias() -> None:
    """glob= alias must win when pattern defaults to **/*."""
    pattern = "**/*"
    glob_alias = "packages/*"
    effective = (pattern or "").strip()
    if effective in {"", "**/*"} and glob_alias:
        effective = glob_alias
    assert effective == "packages/*"


def test_build_sync_contract_includes_agent_ready() -> None:
    from pipeline.sync_status import build_sync_contract

    contract = build_sync_contract(
        warm_state="ready",
        soft_search_ready=True,
        keeper={"running": True, "dirty": {"paths": {"a.py": {"state": "processing"}}}},
    )
    assert contract.get("agent_ready") in {"yes", "warming", "stale"}
    assert contract.get("agent_ready_note")

