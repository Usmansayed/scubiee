"""Shared pytest fixtures.

Unit tests must be deterministic regardless of how the process was launched. The
SDK trial harness runs the workspace's baseline pytest with ``CTX_MCP_SURFACE``
set in the environment (to A/B the ``read`` vs ``graph`` MCP surfaces), which
would otherwise leak into and flip surface-specific assertions. Neutralise it by
default; tests that want a specific surface opt in via ``monkeypatch.setenv``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Env keys written by ``apply_index_memory_budget`` / similar without always
# going through monkeypatch — clear between tests so ResourceManager ceilings
# and refuse logic stay deterministic in the full suite.
_LEAKY_CTX_KEYS = (
    "CTX_CE_MEMORY_MODE",
    "CTX_CE_RSS_CAP_MB",
    "CTX_CE_EMB_BATCH_CEILING",
    "CTX_CE_AGGRESSIVE_UNLOAD",
    "CTX_MLX_DTYPE",
    "CTX_MLX_FAST_ATTN",
    "CTX_MLX_FAST_LN",
    "CTX_MLX_EVAL",
    "CTX_MLX_CACHE_MB",
    "CTX_CPU_EMBED_THREADS",
    "CTX_EMBED_BATCH",
    "CTX_RM_DISABLE",
)


@pytest.fixture(autouse=True)
def _neutral_mcp_surface(monkeypatch):
    monkeypatch.delenv("CTX_MCP_SURFACE", raising=False)
    yield


@pytest.fixture(autouse=True)
def _clear_leaky_ctx_env():
    previous = {key: os.environ.get(key) for key in _LEAKY_CTX_KEYS}
    for key in _LEAKY_CTX_KEYS:
        os.environ.pop(key, None)
    yield
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def cpu_accel_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Persist a CPU accel.json under an isolated ``CTX_HOME`` for semantic tests."""
    home = tmp_path / "ce-home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("CTX_HOME", str(home))
    from pipeline import accel
    from pipeline.accel import AccelProfile, save_accel

    path = home / "accel.json"
    monkeypatch.setattr(accel, "ACCEL_PATH", path)
    save_accel(
        AccelProfile(
            profile="cpu",
            provider="CPUExecutionProvider",
            backend="fastembed",
            batch_size=16,
            texts_per_sec=2.0,
            reason="pytest fixture",
        ),
        path=path,
    )
    return path
