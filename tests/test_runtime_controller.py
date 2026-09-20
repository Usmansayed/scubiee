"""RuntimeController unit tests (host/OS agnostic)."""

from __future__ import annotations

import time
from pathlib import Path


def test_attach_warm_alias_from_legacy_auto_warm(monkeypatch):
    from pipeline.runtime_controller import attach_warm_enabled

    monkeypatch.delenv("CTX_MCP_ATTACH_WARM", raising=False)
    monkeypatch.setenv("CTX_MCP_AUTO_WARM", "1")
    assert attach_warm_enabled() is True
    monkeypatch.setenv("CTX_MCP_AUTO_WARM", "0")
    monkeypatch.setenv("CTX_MCP_ATTACH_WARM", "0")
    assert attach_warm_enabled() is False
    monkeypatch.delenv("CTX_MCP_AUTO_WARM", raising=False)
    monkeypatch.delenv("CTX_MCP_ATTACH_WARM", raising=False)
    assert attach_warm_enabled() is True


def test_ensure_attach_is_singleflight(monkeypatch, tmp_path: Path):
    from pipeline.runtime_controller import RuntimeController

    RuntimeController.reset_for_tests()
    rt = RuntimeController.get()
    calls: list[str] = []

    def _worker(root: Path) -> None:
        calls.append("worker")
        rt._mark_ready()

    monkeypatch.setattr(rt, "_attach_worker", _worker)
    monkeypatch.setenv("CTX_MCP_ATTACH_WARM", "1")
    rt.ensure(tmp_path, "attach")
    rt.ensure(tmp_path, "attach")
    # Attach is async singleflight: second ensure must not start another worker.
    deadline = time.time() + 1.0
    while time.time() < deadline and not calls:
        time.sleep(0.01)
    assert calls == ["worker"]


def test_snapshot_warm_ready_soft_or_embedder(monkeypatch, tmp_path: Path):
    """Soft binder alone is map-ready; dense embed is optional for warm_ready."""
    from pipeline.runtime_controller import RuntimeController

    RuntimeController.reset_for_tests()
    rt = RuntimeController.get()
    monkeypatch.setattr(
        rt,
        "_probe_health",
        lambda repo=None: {
            "ok": True,
            "service": True,
            "embedder_loaded": False,
            "soft_search_ready": False,
        },
    )
    snap = rt.snapshot(repo=tmp_path)
    assert snap.engine_ok is True
    assert snap.warm_ready is False
    monkeypatch.setattr(
        rt,
        "_probe_health",
        lambda repo=None: {
            "ok": True,
            "service": True,
            "embedder_loaded": False,
            "soft_search_ready": True,
        },
    )
    snap_soft = rt.snapshot(repo=tmp_path)
    assert snap_soft.warm_ready is True
    assert snap_soft.soft_search_ready is True
    monkeypatch.setattr(
        rt,
        "_probe_health",
        lambda repo=None: {
            "ok": True,
            "service": True,
            "embedder_loaded": True,
            "soft_search_ready": False,
        },
    )
    snap2 = rt.snapshot(repo=tmp_path)
    assert snap2.warm_ready is True
    fields = snap2.as_status_fields()
    assert fields["warm_ready"] is True
    assert fields["embedder_loaded"] is True
