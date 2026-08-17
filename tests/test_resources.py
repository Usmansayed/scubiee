"""Resource Manager unit tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.resources import (
    AdaptiveBudget,
    ResourceManager,
    SystemSample,
    get_resource_manager,
    reset_resource_manager_for_tests,
    resources_disabled,
)


@pytest.fixture(autouse=True)
def _reset_rm(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CTX_RM_DISABLE", raising=False)
    reset_resource_manager_for_tests()
    yield
    reset_resource_manager_for_tests()


def test_classify_ignores_cpu_spikes_and_ram_percent():
    rm = ResourceManager()
    assert (
        rm.classify(SystemSample(cpu_percent=10.0, ram_available_mb=8000, ram_percent=40))
        == "idle"
    )
    assert (
        rm.classify(SystemSample(cpu_percent=99.0, ram_available_mb=4000, ram_percent=50))
        == "normal"
    )
    assert (
        rm.classify(SystemSample(cpu_percent=80.0, ram_available_mb=4000, ram_percent=92))
        == "normal"
    )
    assert (
        rm.classify(SystemSample(cpu_percent=5.0, ram_available_mb=64, ram_percent=99))
        == "critical"
    )


def test_budget_allows_all_jobs_under_high_cpu_and_high_ram_percent():
    rm = ResourceManager()
    rm._base_batch = 16
    hot = SystemSample(
        cpu_percent=99.0,
        ram_available_mb=8_000,
        ram_percent=91.0,
        ram_total_mb=32_000,
    )
    with patch.object(rm, "sample", return_value=hot):
        for job in ("index", "sync", "graph", "embed"):
            budget = rm.budget(job)
            assert budget.allow is True
            assert budget.pressure != "critical"
            assert budget.pause_s == 0.0


def test_budget_refuses_only_when_free_ram_is_near_oom():
    rm = ResourceManager()
    rm.min_free_ram_mb = 256
    starving = SystemSample(
        cpu_percent=10.0,
        ram_available_mb=64,
        ram_percent=99.0,
        ram_total_mb=16_000,
    )
    with patch.object(rm, "sample", return_value=starving):
        for job in ("index", "sync", "graph", "embed"):
            assert rm.budget(job).allow is False


def test_disable_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CTX_RM_DISABLE", "1")
    assert resources_disabled() is True
    rm = get_resource_manager()
    b = rm.budget("sync")
    # classify returns idle when disabled; wait_for_capacity forces allow
    b2 = rm.wait_for_capacity("sync", timeout_s=1)
    assert b2.allow is True


def test_index_repo_raises_when_refused(monkeypatch, tmp_path):
    from pipeline.indexer import IndexDeferred, index_repo
    from pipeline.resources import AdaptiveBudget, reset_resource_manager_for_tests

    reset_resource_manager_for_tests()
    from pipeline.resources import get_resource_manager

    rm = get_resource_manager()
    refused = AdaptiveBudget(
        pressure="critical",
        allow=False,
        batch_size=1,
        workers=1,
        pause_s=0,
        reason="test refuse",
    )
    with patch.object(rm, "wait_for_capacity", return_value=refused):
        with pytest.raises(IndexDeferred):
            index_repo(tmp_path)

    rm = ResourceManager()
    called = {"n": 0}

    def work():
        called["n"] += 1
        return "ok"

    with patch.object(
        rm,
        "wait_for_capacity",
        return_value=AdaptiveBudget(
            pressure="critical",
            allow=False,
            batch_size=1,
            workers=1,
            pause_s=0,
            reason="test",
        ),
    ):
        assert rm.run_job("sync", work) is None
    assert called["n"] == 0


def test_hardware_detect_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline.hardware import detect_capabilities, ensure_hardware_snapshot, load_hardware

    snap = detect_capabilities()
    assert "os" in snap
    assert "cpu_count_logical" in snap or "cpu_count" in snap
    out = ensure_hardware_snapshot(force=True)
    assert out.get("os")
    assert load_hardware().get("os")
