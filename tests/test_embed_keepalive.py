"""Embed keepalive + keeper defer while MCP clients are connected (0.3.81+)."""

from __future__ import annotations

from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from unittest.mock import MagicMock


def test_run_embed_infer_reentrant_no_deadlock() -> None:
    """Nested run_embed_infer on the single-worker pool must not hang."""
    from pipeline import engine as eng

    seen: list[str] = []

    def _outer():
        seen.append("outer")

        def _inner():
            seen.append("inner")
            return 42

        return eng.run_embed_infer(_inner, timeout_s=2.0)

    assert eng.run_embed_infer(_outer, timeout_s=5.0) == 42
    assert seen == ["outer", "inner"]


def test_ensure_keepalive_already_running_no_deadlock(monkeypatch) -> None:
    """already_running path must not deadlock on non-reentrant keepalive lock."""
    import time

    from pipeline import engine as eng

    monkeypatch.setenv("CTX_EMBED_KEEPALIVE", "1")
    monkeypatch.setenv("CTX_EMBED_KEEPALIVE_S", "60")
    eng.stop_embed_keepalive_loop()
    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)
    monkeypatch.setattr(
        eng,
        "embed_keepalive",
        lambda *_a, **_k: {"ok": True, "ms": 1.0},
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.active_client_count",
        lambda: 1,
    )
    first = eng.ensure_embed_keepalive_loop(".")
    assert first.get("started") or first.get("already_running")
    t0 = time.time()
    second = eng.ensure_embed_keepalive_loop(".")
    assert (time.time() - t0) < 2.0, "already_running must not hang on Lock re-entry"
    assert second.get("already_running") is True
    eng.stop_embed_keepalive_loop()


def test_embed_keepalive_skips_when_not_loaded(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: False)
    out = eng.embed_keepalive()
    assert out.get("ok") is True
    assert out.get("skipped") is True
    assert out.get("reason") == "embedder_not_loaded"


def test_embed_keepalive_encodes_when_loaded(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)
    inner = MagicMock()
    fake_emb = MagicMock()
    fake_emb._ensure = MagicMock(return_value=inner)
    fake_eng = MagicMock()
    fake_eng.embedder = fake_emb
    monkeypatch.setattr(eng, "load_engine", lambda _root: fake_eng)
    monkeypatch.setattr(eng, "run_embed_infer", lambda fn, timeout_s=None: fn())
    out = eng.embed_keepalive(".")
    assert out.get("ok") is True
    assert out.get("ms") is not None
    inner.embed_one.assert_called_once()
    assert "keepalive" in str(inner.embed_one.call_args[0][0])


def test_embed_keepalive_skips_on_timeout(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)

    def _boom(_fn, timeout_s=None):
        raise FuturesTimeoutError()

    monkeypatch.setattr(eng, "run_embed_infer", _boom)
    out = eng.embed_keepalive(".")
    assert out.get("ok") is True
    assert out.get("skipped") is True
    assert out.get("reason") == "timeout"


def test_embed_keepalive_interval_default_is_15s(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.delenv("CTX_EMBED_KEEPALIVE_S", raising=False)
    assert eng.embed_keepalive_interval_s() == 15.0
    monkeypatch.setenv("CTX_EMBED_KEEPALIVE_S", "20")
    assert eng.embed_keepalive_interval_s() == 20.0


def test_embed_keepalive_disabled(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.setenv("CTX_EMBED_KEEPALIVE", "0")
    out = eng.ensure_embed_keepalive_loop(".")
    assert out.get("skipped") is True


def test_keepalive_loop_ticks_immediately(monkeypatch) -> None:
    """First encode must not wait a full interval (map after attach stays hot)."""
    import time

    from pipeline import engine as eng

    monkeypatch.setenv("CTX_EMBED_KEEPALIVE", "1")
    monkeypatch.setenv("CTX_EMBED_KEEPALIVE_S", "60")
    eng.stop_embed_keepalive_loop()
    ticks: list[float] = []

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)
    monkeypatch.setattr(
        eng,
        "embed_keepalive",
        lambda *_a, **_k: ticks.append(time.time()) or {"ok": True, "ms": 1.0},
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.active_client_count",
        lambda: 1,
    )

    t0 = time.time()
    out = eng.ensure_embed_keepalive_loop(".")
    assert out.get("started") or out.get("already_running")
    deadline = time.time() + 2.0
    while time.time() < deadline and not ticks:
        time.sleep(0.05)
    eng.stop_embed_keepalive_loop()
    assert ticks, "expected near-immediate keepalive tick"
    assert (ticks[0] - t0) < 1.5


def test_keepalive_loop_prewarm_polls_fast_when_soft_cold(monkeypatch) -> None:
    """While soft-ready but embedder cold, loop must re-kick prewarm ~2s (not 15s)."""
    import time

    from pipeline import engine as eng

    monkeypatch.setenv("CTX_EMBED_KEEPALIVE", "1")
    monkeypatch.setenv("CTX_EMBED_KEEPALIVE_S", "60")
    eng.stop_embed_keepalive_loop()
    kicks: list[float] = []

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: False)
    monkeypatch.setattr(
        eng,
        "prewarm_status",
        lambda: {"running": False},
    )
    monkeypatch.setattr(
        eng,
        "prewarm_embedder_async",
        lambda *_a, **_k: kicks.append(time.time()) or {"ok": True, "started": True},
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.active_client_count",
        lambda: 1,
    )

    class _Eng:
        texts = ["chunk"]

    class _CE:
        engine = _Eng()

        def health(self):
            raise AssertionError("keepalive must not call health() for soft_seen")

    monkeypatch.setattr(
        "pipeline.ce_service.get_context_engine",
        lambda: _CE(),
    )

    t0 = time.time()
    out = eng.ensure_embed_keepalive_loop(".")
    assert out.get("started") or out.get("already_running")
    deadline = time.time() + 5.0
    while time.time() < deadline and len(kicks) < 2:
        time.sleep(0.05)
    eng.stop_embed_keepalive_loop()
    assert len(kicks) >= 2, f"expected ≥2 prewarm kicks within 5s, got {len(kicks)}"
    assert (kicks[1] - kicks[0]) < 3.5, f"gap={kicks[1] - kicks[0]:.2f}s (want ~2s)"
    assert (kicks[0] - t0) < 1.5


def test_keeper_tick_skips_when_clients_active(tmp_path: Path, monkeypatch) -> None:
    from conftest import enroll_test_repo
    from pipeline.sync_loop import BackgroundSyncLoop

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setenv("CTX_KEEPER_DEFER_WHILE_CLIENTS", "1")
    enroll_test_repo(tmp_path, home=home, project_id="ce_clients_defer_tick001")
    loop = BackgroundSyncLoop(tmp_path, locate_streak_ms=60_000)
    monkeypatch.setattr(loop, "_locate_streak_active", lambda now=None: False)
    monkeypatch.setattr(loop, "_clients_active", lambda: True)
    out = loop.keeper_tick(reason="interval")
    assert out.get("strategy") == "deferred_clients_active"
    assert out.get("reason") == "clients_active"
    assert out.get("clients_active") is True


def test_keeper_tick_clients_defer_can_disable(tmp_path: Path, monkeypatch) -> None:
    from conftest import enroll_test_repo
    from pipeline.sync_loop import BackgroundSyncLoop

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setenv("CTX_KEEPER_DEFER_WHILE_CLIENTS", "0")
    enroll_test_repo(tmp_path, home=home, project_id="ce_clients_defer_off001")
    loop = BackgroundSyncLoop(tmp_path, locate_streak_ms=60_000)
    monkeypatch.setattr(loop, "_locate_streak_active", lambda now=None: False)
    monkeypatch.setattr(loop, "_clients_active", lambda: True)

    class _Probe:
        clean = True
        ms = 1.0
        files_checked = 1
        changed_count = 0
        added: list = []
        modified: list = []
        removed: list = []

        def to_dict(self):
            return {"clean": True, "ms": 1.0}

    monkeypatch.setattr(
        "pipeline.root_probe.root_probe",
        lambda _repo: _Probe(),
    )
    out = loop.keeper_tick(reason="interval")
    assert out.get("strategy") == "root_clean"


def test_keeper_trigger_still_runs_with_clients(tmp_path: Path, monkeypatch) -> None:
    """Disk/trigger reasons must not be swallowed by clients_active defer."""
    from conftest import enroll_test_repo
    from pipeline.sync_loop import BackgroundSyncLoop

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setenv("CTX_KEEPER_DEFER_WHILE_CLIENTS", "1")
    enroll_test_repo(tmp_path, home=home, project_id="ce_clients_defer_trig001")
    loop = BackgroundSyncLoop(tmp_path, locate_streak_ms=60_000)
    monkeypatch.setattr(loop, "_locate_streak_active", lambda now=None: False)
    monkeypatch.setattr(loop, "_clients_active", lambda: True)

    class _Probe:
        clean = True
        ms = 1.0
        files_checked = 1
        changed_count = 0
        added: list = []
        modified: list = []
        removed: list = []

        def to_dict(self):
            return {"clean": True, "ms": 1.0}

    monkeypatch.setattr(
        "pipeline.root_probe.root_probe",
        lambda _repo: _Probe(),
    )
    out = loop.keeper_tick(reason="trigger")
    assert out.get("strategy") == "root_clean"
