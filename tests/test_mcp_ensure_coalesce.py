"""MCP warm/ensure coalesce — avoid spawn storms on every tool call."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_warm_engine_skips_ensure_within_ttl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_MCP_ENSURE_TTL_S", "60")
    import pipeline.mcp_lifecycle as ml

    ml._ENSURE_READY_UNTIL = 0.0
    ml._ENSURE_TTL_S = 60.0
    calls: list[str] = []

    fake = MagicMock()
    fake.open_repo.return_value = {
        "ok": True,
        "status": "activated",
        "warm_state": "ready",
    }
    fake.post.return_value = {"ok": True}

    with patch("pipeline.daemon.is_running", return_value=True), patch(
        "pipeline.daemon.ensure_daemon",
        side_effect=lambda *a, **k: calls.append("ensure") or {"ok": True},
    ), patch("pipeline.client.EngineClient", return_value=fake):
        out1 = ml.warm_engine_for_mcp(tmp_path, client_id="mcp:test", blocking=False)
        out2 = ml.warm_engine_for_mcp(tmp_path, client_id="mcp:test", blocking=False)

    assert calls.count("ensure") == 1
    assert out2.get("ensure_skipped") == "ttl"
    assert out1.get("ok") is True
