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


def test_embed_keepalive_skips_when_search_in_flight(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)
    eng._SEARCH_IN_FLIGHT.set()
    try:
        out = eng.embed_keepalive(".")
        assert out.get("ok") is True
        assert out.get("skipped") is True
        assert out.get("reason") == "search_in_flight"
    finally:
        eng._SEARCH_IN_FLIGHT.clear()


def test_embed_keepalive_skips_when_embed_busy(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)
    eng._EMBED_BUSY.set()
    try:
        out = eng.embed_keepalive(".")
        assert out.get("ok") is True
        assert out.get("skipped") is True
        assert out.get("reason") == "embed_busy"
    finally:
        eng._EMBED_BUSY.clear()


def test_embed_keepalive_skips_after_recent_search(monkeypatch) -> None:
    import time

    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)
    eng._LAST_SEARCH_DONE_AT = time.time()
    out = eng.embed_keepalive(".")
    assert out.get("ok") is True
    assert out.get("skipped") is True
    assert out.get("reason") == "recent_search"
    eng._LAST_SEARCH_DONE_AT = 0.0


def test_keepalive_index_touch_dense_bm25_capped_graph() -> None:
    import numpy as np
    from pipeline import engine as eng

    fake_eng = MagicMock()
    fake_eng.conductor._n = 64
    fake_eng.conductor.dense.score_all = MagicMock(return_value=[])
    fake_eng.conductor.bm25.score_all = MagicMock(return_value=[])
    fake_eng.conductor.graph.affinity_scores = MagicMock(return_value=(None, [], 0.0))
    qvec = np.ones(8, dtype=np.float32)
    eng._keepalive_index_touch(fake_eng, "warmup", qvec)
    fake_eng.conductor.dense.score_all.assert_called_once()
    fake_eng.conductor.bm25.score_all.assert_called_once_with("warmup")
    fake_eng.conductor.graph.affinity_scores.assert_called_once()
    kwargs = fake_eng.conductor.graph.affinity_scores.call_args.kwargs
    assert kwargs.get("max_visit") == 64


def test_embed_keepalive_skips_when_not_loaded(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: False)
    out = eng.embed_keepalive()
    assert out.get("ok") is True
    assert out.get("skipped") is True
    assert out.get("reason") == "embedder_not_loaded"


def test_embed_keepalive_encodes_and_retrieves_when_loaded(monkeypatch) -> None:
    import numpy as np
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)
    monkeypatch.setattr(eng, "prime_dense_ready", lambda: True)
    inner = MagicMock()
    inner.format_query = lambda s: s
    inner._encode_batch = MagicMock(return_value=np.ones((1, 8), dtype=np.float32))
    fake_emb = MagicMock()
    fake_emb._ensure = MagicMock(return_value=inner)
    fake_eng = MagicMock()
    fake_eng.embedder = fake_emb
    fake_eng.conductor.dense.score_all = MagicMock(return_value=[])
    monkeypatch.setattr(eng, "load_engine", lambda _root: fake_eng)
    monkeypatch.setattr(eng, "run_embed_infer", lambda fn, timeout_s=None, **_k: fn())
    out = eng.embed_keepalive(".")
    assert out.get("ok") is True
    assert out.get("ms") is not None
    inner._encode_batch.assert_called_once()
    assert "keepalive" in str(inner._encode_batch.call_args[0][0][0])
    fake_eng.conductor.dense.score_all.assert_called_once()
    fake_eng.conductor.bm25.score_all.assert_called()
    fake_eng.conductor.graph.affinity_scores.assert_called()
    assert out.get("retrieve_ok") is True


def test_embed_keepalive_retrieve_off_embed_worker(monkeypatch) -> None:
    """Retrieve must not run inside run_embed_infer (would block map encode)."""
    import numpy as np
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)
    monkeypatch.setattr(eng, "prime_dense_ready", lambda: True)
    inner = MagicMock()
    inner.format_query = lambda s: s
    inner._encode_batch = MagicMock(return_value=np.ones((1, 8), dtype=np.float32))
    fake_emb = MagicMock()
    fake_emb._ensure = MagicMock(return_value=inner)
    fake_eng = MagicMock()
    fake_eng.embedder = fake_emb
    order: list[str] = []

    def _retrieve(*_a, **_k):
        order.append("retrieve")
        return []

    fake_eng.conductor.dense.score_all = _retrieve
    monkeypatch.setattr(eng, "load_engine", lambda _root: fake_eng)

    def _run(fn, timeout_s=None, **_k):
        order.append("enter")
        try:
            return fn()
        finally:
            order.append("exit")

    monkeypatch.setattr(eng, "run_embed_infer", _run)
    out = eng.embed_keepalive(".")
    assert out.get("retrieve_ok") is True
    assert order == ["enter", "exit", "retrieve"]


def test_embed_keepalive_encode_ok_if_retrieve_fails(monkeypatch) -> None:
    import numpy as np
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)
    monkeypatch.setattr(eng, "prime_dense_ready", lambda: True)
    inner = MagicMock()
    inner.format_query = lambda s: s
    inner._encode_batch = MagicMock(return_value=np.ones((1, 8), dtype=np.float32))
    fake_emb = MagicMock()
    fake_emb._ensure = MagicMock(return_value=inner)
    fake_eng = MagicMock()
    fake_eng.embedder = fake_emb
    fake_eng.conductor.dense.score_all = MagicMock(side_effect=RuntimeError("cold graph"))
    monkeypatch.setattr(eng, "load_engine", lambda _root: fake_eng)
    monkeypatch.setattr(eng, "run_embed_infer", lambda fn, timeout_s=None, **_k: fn())
    out = eng.embed_keepalive(".")
    assert out.get("ok") is True
    assert out.get("retrieve_ok") is False


def test_embed_keepalive_skips_on_timeout(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)

    def _boom(_fn, timeout_s=None, **_k):
        raise FuturesTimeoutError()

    monkeypatch.setattr(eng, "run_embed_infer", _boom)
    out = eng.embed_keepalive(".")
    assert out.get("ok") is True
    assert out.get("skipped") is True
    assert out.get("reason") == "timeout"


def test_embed_keepalive_interval_default_is_8s(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.delenv("CTX_EMBED_KEEPALIVE_S", raising=False)
    assert eng.embed_keepalive_interval_s() == 8.0
    monkeypatch.setenv("CTX_EMBED_KEEPALIVE_S", "20")
    assert eng.embed_keepalive_interval_s() == 20.0
    monkeypatch.setenv("CTX_EMBED_KEEPALIVE_S", "3")
    assert eng.embed_keepalive_interval_s() == 5.0


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


def test_keepalive_loop_does_not_kick_prewarm_when_embedder_cold(monkeypatch) -> None:
    """Attach kicks prewarm once; keepalive must not re-enter ORT while load holds GIL."""
    import time

    from pipeline import engine as eng

    monkeypatch.setenv("CTX_EMBED_KEEPALIVE", "1")
    monkeypatch.setenv("CTX_EMBED_KEEPALIVE_S", "60")
    eng.stop_embed_keepalive_loop()
    kicks: list[float] = []
    ticks: list[float] = []

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: False)
    monkeypatch.setattr(
        eng,
        "prewarm_embedder_async",
        lambda *_a, **_k: kicks.append(time.time()) or {"ok": True, "started": True},
    )
    monkeypatch.setattr(
        eng,
        "embed_keepalive",
        lambda *_a, **_k: ticks.append(time.time()) or {"ok": True, "ms": 1.0},
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.active_client_count",
        lambda: 1,
    )

    out = eng.ensure_embed_keepalive_loop(".")
    assert out.get("started") or out.get("already_running")
    time.sleep(0.4)
    eng.stop_embed_keepalive_loop()
    assert kicks == [], f"keepalive must not kick prewarm, got {len(kicks)}"
    assert ticks == [], "keepalive encode must wait until embedder is loaded"


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
