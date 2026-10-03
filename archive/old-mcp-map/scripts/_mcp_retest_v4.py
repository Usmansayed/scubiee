#!/usr/bin/env python3
"""Quick retest of updated MCP features (glob alias, map confidence, cache, agent_ready)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))
os.environ.setdefault("CTX_MCP_SURFACE", "phase")
os.environ.setdefault("CTX_REPO", str(ROOT))
SESSION = "mcp-retest-v4"


def main() -> int:
    import pipeline.mcp_locate as ml

    ml._is_repo_managed = lambda: True  # type: ignore[method-assign]
    mcp = ml.create_mcp(name="retest")
    tools = {n: mcp._tool_manager._tools[n].fn for n in mcp._tool_manager._tools}

    def call(name: str, **kw) -> dict:
        kw.setdefault("session_id", SESSION)
        raw = tools[name](**kw)
        return json.loads(raw) if isinstance(raw, str) else raw

    from pipeline.session_store import clear_store

    clear_store(ROOT, session_id=SESSION)

    mock_status = {
        "ok": True,
        "healthy": True,
        "soft_search_ready": True,
        "warm_state": "ready",
        "project_id": "ce_test",
        "meta": {"chunks": 3931, "files_indexed": 472},
        "keeper": {
            "sync_status": "syncing",
            "overlay_ready": True,
            "publish_pending": True,
            "ready": False,
        },
    }
    mock_client = MagicMock()
    mock_client.healthy.return_value = True
    mock_client.status.return_value = mock_status

    results: list[dict] = []

    def record(name: str, ok: bool, **extra) -> None:
        results.append({"test": name, "ok": ok, **extra})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))

    noop = patch("pipeline.daemon.ensure_daemon", return_value={"ok": True})

    with noop:
        g1 = call("glob", pattern="**/*", glob="packages/pipeline/*.py", limit=5)
        record(
            "glob_alias_uses_glob_param",
            g1.get("pattern_source") == "glob_alias"
            and any("pipeline" in f for f in g1.get("files", [])),
            pattern=g1.get("pattern"),
            source=g1.get("pattern_source"),
        )

    with noop:
        g2 = call("glob", pattern="packages/pipeline/*.py", limit=5)
        record("glob_packages_pipeline", g2.get("count", 0) > 0, count=g2.get("count"))

    with noop:
        g3 = call("glob", pattern=".", limit=20)
        record(
            "glob_orient_dot",
            g3.get("mode") == "orient" or bool(g3.get("dirs") or g3.get("files")),
            mode=g3.get("mode"),
        )

    with noop:
        from pipeline.mcp_locate import _assess_map_confidence

        nonsense_cards = [
            {"file": f"f{i}.py", "score": 0.05 - i * 0.01} for i in range(8)
        ]
        conf = _assess_map_confidence("nonexistent_module_xyz_foo_bar baz qux handler", nonsense_cards)
        record(
            "map_low_confidence_assessment",
            conf.get("confidence") == "low" and conf.get("weak_match") is True,
            confidence=conf.get("confidence"),
        )

    with noop, patch("pipeline.locate._search_hits") as sh:
        sh.return_value = [{"file": "x.py", "score": 0.5, "why": "test", "start_line": 1, "end_line": 10}]
        call("map", query="daemon watchdog health restart unique_v4", k=8)
        second = call("map", query="daemon watchdog health restart unique_v4", k=8)
        record("map_duplicate_cached", second.get("cached") is True, cached=second.get("cached"))
        record("map_duplicate_skips_search", sh.call_count == 1, search_calls=sh.call_count)

    with noop, patch("pipeline.locate._search_hits") as sh:
        sh.side_effect = RuntimeError("Remote end closed connection without response")
        err = call("map", query="test retry query unique_abc123_v4", k=8)
        record(
            "map_transient_should_retry",
            err.get("should_retry") is True,
            should_retry=err.get("should_retry"),
            error=(err.get("error") or "")[:60],
        )

    with noop, patch("pipeline.mcp_locate._client_for", return_value=mock_client):
        st = call("status")
        record("status_has_agent_ready", "agent_ready" in st, agent_ready=st.get("agent_ready"))

    passed = sum(1 for r in results if r["ok"])
    print(f"\n=== {passed}/{len(results)} retest checks passed ===")
    out = ROOT / "docs" / "scubiee-mcp-retest-v4-results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
