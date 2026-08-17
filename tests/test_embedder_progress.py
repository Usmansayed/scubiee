"""Embedder progress wiring — quiet stderr when a bar drives updates."""

from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock

import numpy as np

from pipeline.embedder import Embedder


def test_embed_many_suppresses_stderr_when_progress_set(
    monkeypatch, capsys
) -> None:
    embedder = Embedder(model="nomic-ai/CodeRankEmbed", batch_size=2, quiet=True)
    embedder.backend = "fastembed"
    embedder.device = "cpu"
    embedder.cache = {}

    def fake_encode(batch: list[str]) -> np.ndarray:
        return np.ones((len(batch), 4), dtype=np.float32)

    monkeypatch.setattr(embedder, "_encode_batch", fake_encode)
    monkeypatch.setattr(
        "pipeline.resources.get_resource_manager",
        lambda: (_ for _ in ()).throw(ImportError()),
    )

    progress = MagicMock()
    texts = ["alpha", "beta", "gamma"]
    embedder.embed_many(texts, progress=progress)

    err = capsys.readouterr().err
    assert "[embed]" not in err
    assert progress.call_count >= 1


def test_embed_many_prints_without_progress(monkeypatch, capsys) -> None:
    embedder = Embedder(model="nomic-ai/CodeRankEmbed", batch_size=2)
    embedder.backend = "fastembed"
    embedder.device = "cpu"
    embedder.cache = {}

    monkeypatch.setattr(
        embedder,
        "_encode_batch",
        lambda batch: np.ones((len(batch), 4), dtype=np.float32),
    )
    monkeypatch.setattr(
        "pipeline.resources.get_resource_manager",
        lambda: (_ for _ in ()).throw(ImportError()),
    )

    embedder.embed_many(["one", "two"], progress=None)

    err = capsys.readouterr().err
    assert "[embed] done:" in err
