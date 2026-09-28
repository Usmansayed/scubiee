"""Issue 3: the near-OOM guard must not stall small hot-save embeds."""

from __future__ import annotations

import time

import numpy as np

from pipeline.resources import AdaptiveBudget, ResourceManager, SystemSample


def _critical_rm() -> ResourceManager:
    rm = ResourceManager()
    rm._prefs_enabled = True
    rm.sample = lambda: SystemSample(  # type: ignore[method-assign]
        cpu_percent=10.0, ram_percent=99.0, ram_available_mb=150.0, ram_total_mb=16000.0
    )
    return rm


def test_min_free_ram_default_is_one_value(monkeypatch):
    from pipeline.settings import DEFAULT_MIN_FREE_RAM_MB, DEFAULT_PREFS

    monkeypatch.delenv("CTX_RM_MIN_FREE_RAM_MB", raising=False)
    rm = ResourceManager()
    assert rm.min_free_ram_mb == DEFAULT_MIN_FREE_RAM_MB
    assert DEFAULT_PREFS["resource_management"]["min_free_ram_mb"] == DEFAULT_MIN_FREE_RAM_MB


def test_env_threshold_beats_prefs_default(monkeypatch):
    monkeypatch.setenv("CTX_RM_MIN_FREE_RAM_MB", "200")
    assert ResourceManager().min_free_ram_mb == 200.0


def test_wait_for_capacity_does_not_oversleep_short_deadline(monkeypatch):
    rm = _critical_rm()
    monkeypatch.setattr("pipeline.resources.resources_disabled", lambda: False)
    t0 = time.perf_counter()
    b = rm.wait_for_capacity("embed", timeout_s=1.0)
    took = time.perf_counter() - t0
    assert b.allow is False and b.pressure == "critical"
    assert took < 1.4, took


def _embedder(monkeypatch, cpu_accel_profile, rm):
    del cpu_accel_profile
    from pipeline.embedder import Embedder

    emb = Embedder(model="nomic-ai/CodeRankEmbed", batch_size=16, quiet=True)
    emb.backend = "fastembed"
    emb.device = "cpu"
    emb.cache = {}
    emb.cache_path = None  # no disk flush per batch
    monkeypatch.setattr(emb, "_queue_cache", lambda *_a, **_k: None, raising=False)
    batches: list[int] = []

    def _encode(batch):
        batches.append(len(batch))
        return np.ones((len(batch), 4), dtype=np.float32)

    monkeypatch.setattr(emb, "_encode_batch", _encode)
    monkeypatch.setattr("pipeline.resources.get_resource_manager", lambda: rm)
    monkeypatch.setattr("pipeline.resources.resources_disabled", lambda: False)
    monkeypatch.setattr(rm, "refresh_base_from_accel", lambda: None, raising=False)
    return emb, batches


def test_hot_save_embed_waits_about_a_second_then_runs_full_batches(monkeypatch, capsys, cpu_accel_profile):
    rm = _critical_rm()
    emb, batches = _embedder(monkeypatch, cpu_accel_profile, rm)
    t0 = time.perf_counter()
    emb.embed_many([f"def f{i}(): pass" for i in range(44)])
    took = time.perf_counter() - t0
    err = capsys.readouterr().err
    assert took < 2.0, took  # was: up to 180s of "embed waiting" per batch
    assert "embed waiting" not in err
    assert err.count("hot save embed 44 chunk(s) under low RAM") == 1
    assert max(batches) > 1  # not one forward pass per chunk


def test_bulk_embed_keeps_the_guard(monkeypatch, capsys, cpu_accel_profile):
    rm = _critical_rm()
    emb, batches = _embedder(monkeypatch, cpu_accel_profile, rm)
    waits: list[float] = []

    def _wait(job, *, timeout_s=120.0, on_wait=None):
        waits.append(timeout_s)
        return AdaptiveBudget(
            pressure="critical", allow=False, batch_size=1, workers=1, pause_s=0.0,
            reason="almost no free RAM — pause to avoid OOM", sample={},
        )

    monkeypatch.setattr(rm, "wait_for_capacity", _wait)
    monkeypatch.setattr(rm, "apply_pause", lambda _b: None)  # bulk still pauses 0.5s/batch
    emb.embed_many([f"def g{i}(): pass" for i in range(80)])
    assert waits and all(w == 180.0 for w in waits)
    assert set(batches) == {1}
