"""Cold ORT/index load must not hold process _LOCK across /health probes."""

from __future__ import annotations

import threading
import time

import pytest


def test_get_embedder_does_not_hold_lock_during_ensure(monkeypatch) -> None:
    from pipeline import engine as eng

    eng.clear_engines()
    eng.release_embedders()

    entered = threading.Event()
    release = threading.Event()
    health_ok = threading.Event()

    class FakeEmb:
        backend = "coderank"

        def _ensure_coderank(self) -> None:
            entered.set()
            assert release.wait(timeout=3.0), "ensure held too long"
            # After release, health path must have observed an unlocked check.
            assert health_ok.is_set()

        def _ensure_mlx(self) -> None:
            self._ensure_coderank()

    monkeypatch.setattr(eng, "Embedder", lambda **_kwargs: FakeEmb())

    def _health_watcher() -> None:
        assert entered.wait(timeout=3.0)
        # Must succeed while ensure is still in progress (lock not held).
        t0 = time.perf_counter()
        assert eng.embedder_is_loaded() is False
        assert (time.perf_counter() - t0) < 0.5
        health_ok.set()
        release.set()

    watcher = threading.Thread(target=_health_watcher, daemon=True)
    watcher.start()
    out = eng.get_embedder("fake-model", dim=8, cache_path=None, eager=True)
    watcher.join(timeout=3.0)
    assert isinstance(out, FakeEmb)
    assert eng.embedder_is_loaded() is True
    eng.release_embedders()


def test_is_running_true_when_pid_alive_even_if_health_down(monkeypatch) -> None:
    from pipeline import daemon as d

    monkeypatch.setattr(d, "_read_lock_pid", lambda: 4242)
    monkeypatch.setattr(d, "_pid_alive", lambda pid: pid == 4242)

    class Boom:
        def healthy(self) -> bool:
            raise AssertionError("healthy must not be required when pid is alive")

    monkeypatch.setattr(d, "EngineClient", Boom)
    assert d.is_running() is True
