"""warm_phase=dense is published once a live model session exists, however it loaded."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import engine, warm_autoload


class _Emb:
    def __init__(self, backend: str, loaded: bool) -> None:
        self.backend = backend
        self._fe_model = object() if (loaded and backend == "fastembed") else None
        self._mlx_model = object() if (loaded and backend == "mlx") else None


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(engine, "_mark_prewarm_busy", lambda busy: None)
    warm_autoload.set_phase(warm_autoload.PHASE_SOFT)
    saved = dict(engine._EMBEDDERS)
    engine._EMBEDDERS.clear()
    yield
    engine._EMBEDDERS.clear()
    engine._EMBEDDERS.update(saved)


def test_lazy_shell_does_not_publish_dense() -> None:
    engine._EMBEDDERS["k"] = _Emb("fastembed", loaded=False)
    engine.publish_dense_phase()
    assert warm_autoload.read_phase()["phase"] == warm_autoload.PHASE_SOFT


def test_loaded_fastembed_publishes_dense_to_disk() -> None:
    engine._EMBEDDERS["k"] = _Emb("fastembed", loaded=True)
    engine.publish_dense_phase()
    assert warm_autoload.read_phase()["phase"] == warm_autoload.PHASE_DENSE
    assert '"dense"' in warm_autoload.phase_path().read_text(encoding="utf-8")


def test_no_embedder_does_not_publish() -> None:
    engine.publish_dense_phase()
    assert warm_autoload.read_phase()["phase"] == warm_autoload.PHASE_SOFT


def test_already_dense_is_not_rewritten(monkeypatch: pytest.MonkeyPatch) -> None:
    engine._EMBEDDERS["k"] = _Emb("fastembed", loaded=True)
    warm_autoload.set_phase(warm_autoload.PHASE_DENSE)
    calls: list[bool] = []
    monkeypatch.setattr(warm_autoload, "end_prewarm", lambda **k: calls.append(True))
    engine.publish_dense_phase()
    assert calls == []
