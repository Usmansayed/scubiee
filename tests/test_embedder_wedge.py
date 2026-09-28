"""Live wedge (0.3.132 battery): after an idle demote the engine answered
``dense_embed_loading`` forever and the keeper deferred every save.

A ``_LazyEmbedder`` held by an engine outside ``_ENGINES`` kept its weights
through ``release_embedders()`` and served ``embed_one`` from them without
registering, so ``embedder_is_loaded()`` never became True again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import engine as eng


class _FakeInner:
    backend = "fake"

    def embed_one(self, *_a, **_k):
        return [0.0]


@pytest.fixture(autouse=True)
def _clean_embedders():
    with eng._LOCK:
        saved = dict(eng._EMBEDDERS)
        eng._EMBEDDERS.clear()
    yield
    with eng._LOCK:
        eng._EMBEDDERS.clear()
        eng._EMBEDDERS.update(saved)


def test_a_wrapper_that_kept_its_weights_registers_them_on_use() -> None:
    w = eng._LazyEmbedder("m", dim=4, cache_path=None)
    w._inner = _FakeInner()  # survived a release while outside _ENGINES
    assert eng.embedder_is_loaded() is False
    w._ensure()
    assert eng.embedder_is_loaded() is True


def test_release_unloads_wrappers_that_are_not_in_engines(monkeypatch) -> None:
    monkeypatch.setattr(eng, "stop_embed_keepalive_loop", lambda: None)
    w = eng._LazyEmbedder("m", dim=4, cache_path=None)
    w._inner = _FakeInner()
    eng.release_embedders()
    assert w._inner is None, "demote must drop the weights of every wrapper"


def test_keeper_stops_deferring_a_cold_embedder_after_the_cap(monkeypatch, tmp_path: Path) -> None:
    from conftest import enroll_test_repo

    from pipeline.sync_loop import BackgroundSyncLoop

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_coldcap1234567890abcdef0123")
    monkeypatch.setenv("CTX_SYNC_WAIT_FOR_EMBEDDER", "1")
    monkeypatch.setenv("CTX_SYNC_COLD_DEFER_MAX_S", "30")
    monkeypatch.setattr("pipeline.engine.embedder_is_loaded", lambda: False)
    monkeypatch.setattr("pipeline.engine.prewarm_embedder_async", lambda *_a, **_k: {"ok": True})
    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)

    assert loop._defer_cold_embedder(["a.py"], now=100.0) is True
    assert loop._defer_cold_embedder(["a.py"], now=120.0) is True
    assert loop._defer_cold_embedder(["a.py"], now=131.0) is False, "30s cap reached"
    assert loop._defer_cold_embedder(["a.py"], now=132.0) is True, "a new wait starts"
