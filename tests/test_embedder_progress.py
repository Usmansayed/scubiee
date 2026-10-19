"""Embedder progress wiring — quiet stderr when a bar drives updates."""

from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock

import numpy as np

from pipeline.embedder import Embedder


def test_embed_many_suppresses_stderr_when_progress_set(
    monkeypatch, capsys, cpu_accel_profile
) -> None:
    del cpu_accel_profile
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


def test_embed_many_prints_without_progress(monkeypatch, capsys, cpu_accel_profile) -> None:
    del cpu_accel_profile
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


def test_cli_front_end_silences_embed_diagnostics(monkeypatch, capsys, cpu_accel_profile) -> None:
    del cpu_accel_profile
    monkeypatch.setenv("CTX_EMBED_LOG", "0")
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

    assert "[embed]" not in capsys.readouterr().err


def test_engine_spawned_from_a_quiet_cli_still_logs_embed_diagnostics(
    monkeypatch, tmp_path
) -> None:
    import socket

    import pytest

    import pipeline.__main__ as cli
    from pipeline import daemon as d

    assert {"init", "sync", "index", "setup"} <= cli._QUIET_EMBED_COMMANDS
    assert not {"engine", "mcp", "serve", "doctor"} & cli._QUIET_EMBED_COMMANDS

    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        monkeypatch.setenv("CTX_ENGINE_URL", f"http://127.0.0.1:{s.getsockname()[1]}")
    monkeypatch.setenv("CTX_EMBED_LOG", "0")
    seen: dict[str, str] = {}

    class Spawned(Exception):
        pass

    def fake_spawn(cmd, env):
        seen.update(env)
        raise Spawned()

    monkeypatch.setattr("pipeline.install_guard.check_install_conflict", lambda: None)
    monkeypatch.setattr("pipeline.install_guard.write_install_marker", lambda *a, **k: None)
    monkeypatch.setattr(d, "_engine_orphan_spawn_enabled", lambda: False)
    monkeypatch.setattr(d, "_spawn_engine_child", fake_spawn)
    with pytest.raises(Spawned):
        d.start_daemon(None, wait_s=1.0)
    assert seen["CTX_EMBED_LOG"] == "1"
