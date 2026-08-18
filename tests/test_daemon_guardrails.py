"""Daemon lock / binding / install surface guardrails."""

from __future__ import annotations

import json
from pathlib import Path


def test_acquire_lock_writes_atomic_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline.daemon import acquire_lock, lock_path

    out = acquire_lock(12345, url="http://127.0.0.1:8765", repo=str(tmp_path / "repo"))
    assert out["ok"] is True
    data = json.loads(lock_path().read_text(encoding="utf-8"))
    assert data["pid"] == 12345
    assert not list((tmp_path / "ce-home").glob("*.tmp"))


def test_validate_daemon_binding_reports_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline import daemon as d

    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    repo_a.mkdir()
    repo_b.mkdir()
    d.acquire_lock(1, url="http://127.0.0.1:8765", repo=str(repo_a))
    monkeypatch.setattr(d, "is_running", lambda: True)

    class FakeClient:
        def get(self, path: str):
            assert path == "/health"
            return {"ok": True, "repo": str(repo_a)}

    monkeypatch.setattr("pipeline.client.EngineClient", FakeClient)
    report = d.validate_daemon_binding(repo_b)
    assert report["ok"] is False
    assert report["matched"] is False
    assert "ensure" in (report.get("repair") or "")


def test_install_mcp_defaults_to_phase_surface() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "install_mcp.py"
    spec = importlib.util.spec_from_file_location("install_mcp_guard", path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    entry = mod.server_entry()
    assert entry["env"]["CTX_MCP_SURFACE"] == "phase"
