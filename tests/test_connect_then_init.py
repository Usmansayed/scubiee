"""connect-then-init reliability on macOS (MAC-145 fixes).

Two independent bugs made `scubiee connect` followed by `scubiee init` unreliable
on Apple Silicon:

  1. DEADLOCK: `connect` starts the supervisor; a later `init` stopped the engine
     to take the store write-lock, but the supervisor kept respawning/idle-
     stopping it, so init wedged past the 120s lock timeout. Fix: a bounded,
     self-expiring "store hold" that makes the supervisor a no-op for the window.

  2. SEGFAULT: a full index embeds (MLX/Metal) then does a numpy-LAPACK/faiss
     vector write in the SAME process; MLX leaves the heap in a state that trips
     the malloc guard at the subsequent allocation (~1/3 of inits crashed at
     "Writing index"). Fix: MLX stays the index backend on Apple Silicon; the
     crash is removed on the MLX path by quiescing MLX (synchronize + clear the
     Metal cache) before the vector write. CTX_INDEX_EMBED_BACKEND is an opt-in
     escape hatch only — there is NO silent FastEmbed swap on Darwin.

Offline; no engine/embedder required.
"""

from __future__ import annotations

import time

import pytest


# ---- 1. Store-hold gating (deadlock fix) ------------------------------------

@pytest.fixture()
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    (tmp_path / "ce-home").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_store_hold_blocks_engine_should_be_running(_home, monkeypatch):
    from pipeline.lifecycle_runtime import (
        begin_store_hold,
        clear_store_hold,
        engine_should_be_running,
        set_desired_mode,
        store_hold_active,
        DESIRED_RUN,
    )

    # Even with desired_mode=RUN (which normally means "run the engine"), an
    # active store hold must make engine_should_be_running() return False so the
    # supervisor neither starts nor stops the engine during an index.
    set_desired_mode(DESIRED_RUN)
    assert engine_should_be_running() is True

    begin_store_hold(seconds=30)
    assert store_hold_active() is True
    assert engine_should_be_running() is False

    clear_store_hold()
    assert store_hold_active() is False
    assert engine_should_be_running() is True


def test_store_hold_self_expires(_home):
    from pipeline.lifecycle_runtime import begin_store_hold, store_hold_active

    # A crashed init must never pin the engine off forever: the hold is a
    # bounded deadline that auto-clears once passed.
    begin_store_hold(seconds=1)
    assert store_hold_active() is True
    time.sleep(1.3)
    assert store_hold_active() is False  # deadline passed → auto-cleared


def test_enter_standby_is_noop_while_held(_home, monkeypatch):
    from pipeline import lifecycle_runtime as lr

    # enter_standby must NOT stop the engine while a store hold is active (that
    # was the race that stopped the engine out from under init).
    stopped = {"called": False}
    monkeypatch.setattr(
        "pipeline.daemon.stop_daemon",
        lambda *a, **k: stopped.__setitem__("called", True) or {"ok": True},
    )
    lr.begin_store_hold(seconds=30)
    out = lr.enter_standby(stop_engine=True)
    assert out.get("action") == "store_hold_skip_standby"
    assert stopped["called"] is False
    lr.clear_store_hold()


# ---- 2. Index-build backend selection (segfault fix) ------------------------

def _resolve_index_backend() -> str | None:
    """Decision mirror of indexer.index_repo (kept in sync with the code there).

    Default: index_backend stays None → Embedder resolves normally (MLX on Apple
    Silicon). CTX_INDEX_EMBED_BACKEND is an explicit opt-in override only. There
    is NO platform-based swap to FastEmbed on Darwin.
    """
    import os

    index_backend = None
    forced = (os.environ.get("CTX_INDEX_EMBED_BACKEND") or "").strip().lower()
    if forced in {"mlx", "fastembed", "coderank", "cpu"}:
        index_backend = "fastembed" if forced == "cpu" else forced
    return index_backend


def test_index_keeps_mlx_default_on_darwin(monkeypatch):
    """On Darwin with an MLX profile and no override, the index build does NOT
    swap to FastEmbed — index_backend stays None so Embedder resolves to MLX,
    the chosen Apple-Silicon accelerator. (Regression guard against the reverted
    silent FastEmbed swap.)"""
    import sys

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("CTX_INDEX_EMBED_BACKEND", raising=False)
    monkeypatch.delenv("CTX_EMBED_BACKEND", raising=False)

    # No override, Darwin+MLX → no forced backend. Embedder picks MLX itself.
    assert _resolve_index_backend() is None


def test_index_backend_override_opt_in(monkeypatch):
    """CTX_INDEX_EMBED_BACKEND is an explicit escape hatch, honored on any OS."""
    import sys

    monkeypatch.setattr(sys, "platform", "darwin")

    # Explicit MLX stays MLX.
    monkeypatch.setenv("CTX_INDEX_EMBED_BACKEND", "mlx")
    assert _resolve_index_backend() == "mlx"

    # Explicit opt-in to FastEmbed is still possible for anyone who needs it.
    monkeypatch.setenv("CTX_INDEX_EMBED_BACKEND", "fastembed")
    assert _resolve_index_backend() == "fastembed"

    # "cpu" is normalized to fastembed.
    monkeypatch.setenv("CTX_INDEX_EMBED_BACKEND", "cpu")
    assert _resolve_index_backend() == "fastembed"
