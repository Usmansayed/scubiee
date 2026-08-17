from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from pipeline import accel, ce_service, doctor, embedder as embedder_module
from pipeline.accel import AccelProfile
from pipeline.embedder import Embedder
from pipeline.runtime_profile import RuntimeProfileState


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    from pipeline import runtime_profile

    runtime_profile.set_runtime_profile_state(RuntimeProfileState("cpu", "cpu"))
    yield
    runtime_profile.set_runtime_profile_state(RuntimeProfileState("cpu", "cpu"))


def _accelerated_embedder(monkeypatch: pytest.MonkeyPatch) -> Embedder:
    profile = AccelProfile(
        profile="dml",
        provider="DmlExecutionProvider",
        batch_size=16,
        envelope={"tier": "standard", "batch_ceiling": 16},
    )
    monkeypatch.setattr(accel, "resolve_runtime", lambda: profile)
    monkeypatch.setattr(embedder_module, "_choose_backend", lambda *_args: "fastembed")
    instance = Embedder(backend="fastembed")
    failing_model = SimpleNamespace(
        embed=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("DML failed"))
    )
    monkeypatch.setattr(instance, "_ensure_fastembed", lambda: failing_model)
    return instance


def test_accelerated_embed_failure_uses_temporary_cpu_backup_once(monkeypatch):
    instance = _accelerated_embedder(monkeypatch)
    calls: list[tuple[list[str], int]] = []

    def cpu_backup(batch: list[str], *, batch_size: int) -> np.ndarray:
        calls.append((batch, batch_size))
        return np.zeros((len(batch), 768), dtype=np.float32)

    monkeypatch.setattr(instance, "_embed_cpu_backup", cpu_backup, raising=False)

    result = instance.embed_one("x")

    assert result.shape == (768,)
    assert calls == [(["x"], 8)]
    assert instance.runtime_state == RuntimeProfileState(
        preferred_profile="dml",
        active_profile="cpu",
        backup_reason="DML failed",
    )


def test_cpu_backup_keeps_saved_preferred_profile(monkeypatch, tmp_path):
    accel_path = tmp_path / "accel.json"
    monkeypatch.setattr(accel, "ACCEL_PATH", accel_path)
    from pipeline import runtime_profile

    monkeypatch.setattr(runtime_profile, "ACCEL_PATH", accel_path)
    accel.save_accel(
        AccelProfile(
            profile="dml",
            provider="DmlExecutionProvider",
            batch_size=16,
            envelope={"tier": "standard", "batch_ceiling": 16},
        ),
        accel_path,
    )
    instance = _accelerated_embedder(monkeypatch)
    monkeypatch.setattr(
        instance,
        "_embed_cpu_backup",
        lambda batch, *, batch_size: np.zeros((len(batch), 768), dtype=np.float32),
        raising=False,
    )
    monkeypatch.setattr(
        accel,
        "save_accel",
        lambda *_args, **_kwargs: pytest.fail("runtime must not persist fallback"),
    )

    instance.embed_one("x")

    assert json.loads(accel_path.read_text(encoding="utf-8"))["profile"] == "dml"
    assert runtime_profile.load_installed_profile().preferred.profile == "dml"


def test_failed_cpu_backup_restores_accelerator_and_preserves_primary_error(monkeypatch):
    from pipeline import runtime_profile

    instance = _accelerated_embedder(monkeypatch)
    backup_calls = 0

    def failed_backup(_batch: list[str], *, batch_size: int) -> np.ndarray:
        nonlocal backup_calls
        backup_calls += 1
        raise RuntimeError(f"CPU backup failed at batch {batch_size}")

    monkeypatch.setattr(instance, "_embed_cpu_backup", failed_backup)

    with pytest.raises(RuntimeError, match="DML failed") as caught:
        instance.embed_one("first")

    assert backup_calls == 1
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "CPU backup failed" in str(caught.value.__cause__)
    assert runtime_profile.get_runtime_profile_state() == RuntimeProfileState(
        "dml", "dml"
    )
    successful_model = SimpleNamespace(
        embed=lambda batch, **_kwargs: np.zeros((len(batch), 768), dtype=np.float32)
    )
    monkeypatch.setattr(instance, "_ensure_fastembed", lambda: successful_model)
    assert instance.embed_one("second").shape == (768,)


def test_successful_backup_is_shared_by_existing_and_new_embedders(monkeypatch):
    from pipeline import runtime_profile

    first = _accelerated_embedder(monkeypatch)
    second = Embedder(backend="fastembed")
    monkeypatch.setattr(
        first,
        "_embed_cpu_backup",
        lambda batch, *, batch_size: np.zeros((len(batch), 768), dtype=np.float32),
    )

    first.embed_one("first")

    cpu_calls: list[str] = []

    def shared_cpu(batch: list[str], *, batch_size: int) -> np.ndarray:
        cpu_calls.extend(batch)
        return np.zeros((len(batch), 768), dtype=np.float32)

    monkeypatch.setattr(second, "_embed_cpu_backup", shared_cpu)
    monkeypatch.setattr(
        second,
        "_ensure_fastembed",
        lambda: pytest.fail("existing embedder must observe shared CPU state"),
    )
    second.embed_one("second")

    third = Embedder(backend="fastembed")
    monkeypatch.setattr(third, "_embed_cpu_backup", shared_cpu)
    monkeypatch.setattr(
        third,
        "_ensure_fastembed",
        lambda: pytest.fail("new embedder must observe shared CPU state"),
    )
    third.embed_one("third")

    expected = RuntimeProfileState("dml", "cpu", "DML failed")
    assert first.runtime_state == expected
    assert second.runtime_state == expected
    assert third.runtime_state == expected
    assert runtime_profile.get_runtime_profile_state() == expected
    assert cpu_calls == ["second", "third"]


def test_status_and_doctor_report_preferred_active_backup(monkeypatch, tmp_path):
    from pipeline import repo_lifecycle, resources, runtime_profile

    state = RuntimeProfileState("dml", "cpu", "DML failed")
    runtime_profile.set_runtime_profile_state(state)
    envelope = {
        "tier": "low",
        "batch_ceiling": 4,
        "embed_workers": 1,
        "index_workers": 1,
        "aggressive_unload": True,
        "queue_limit": 1,
    }
    resource_status = {"envelope": envelope}
    monkeypatch.setattr(
        resources,
        "get_resource_manager",
        lambda: SimpleNamespace(status=lambda: resource_status),
    )
    monkeypatch.setattr(
        repo_lifecycle,
        "lifecycle_status",
        lambda _repo: {"state": repo_lifecycle.UNMANAGED, "project_id": None},
    )
    monkeypatch.setattr(ce_service, "is_registered", lambda _repo: False)
    monkeypatch.setattr(ce_service, "is_always_allowed", lambda _repo: False)
    monkeypatch.setattr(
        ce_service,
        "registration_prompt_payload",
        lambda _repo: {"required": True},
    )

    status = ce_service.RuntimeManager().status(tmp_path)
    report = doctor.doctor_report()

    for payload in (status, report["accel"]):
        assert payload["preferred_profile"] == "dml"
        assert payload["active_profile"] == "cpu"
        assert payload["backup_reason"] == "DML failed"
        assert payload["envelope"] == envelope
        assert payload["recommended_command"] == "python -m pipeline init --repair"
