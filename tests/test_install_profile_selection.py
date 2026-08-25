from __future__ import annotations

import argparse
import json

import pytest

from pipeline import __main__ as cli
from pipeline import accel, hardware
from pipeline.accel import AccelProfile


def _profile(*, batch_size: int = 16) -> AccelProfile:
    return AccelProfile(
        profile="dml",
        provider="DmlExecutionProvider",
        batch_size=batch_size,
        batch_calibration={"winner": batch_size},
        detected={
            "os": "Windows",
            "nvidia": True,
            "gpus": [
                {"name": "NVIDIA GeForce RTX 3060", "adapter_ram": 12_000_000_000},
            ],
            "windows_discrete_amd_nvidia": True,
            "suggested_dml_device_id": 0,
        },
        envelope={
            "tier": "standard",
            "batch_ceiling": batch_size,
            "embed_workers": 1,
            "index_workers": 2,
            "aggressive_unload": False,
            "queue_limit": 2,
        },
        hardware_fingerprint="windows-test-host",
    )


def _setup_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "status": False,
        "repair": False,
        "profile": None,
        "skip_install": True,
        "skip_model": True,
        "skip_bench": True,
        "skip_accel": False,
        "index_path": None,
        "repo": ".",
        "register": False,
        "host": "127.0.0.1",
        "port": 8765,
        "wait": 1.0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_resolve_runtime_returns_saved_profile_without_detect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = _profile()
    monkeypatch.setattr(accel, "load_accel", lambda: saved)
    monkeypatch.delenv("CTX_EMBED_BACKEND", raising=False)
    monkeypatch.delenv("CTX_MLX", raising=False)
    monkeypatch.setattr(
        accel,
        "recommend_profile",
        lambda *args, **kwargs: pytest.fail("runtime must not choose"),
    )
    monkeypatch.setattr(
        accel,
        "detect_hardware",
        lambda: pytest.fail("runtime must not detect"),
    )
    monkeypatch.setenv("CTX_ACCEL", "cpu")

    assert accel.resolve_runtime() is saved


def test_resolve_runtime_requires_init_when_profile_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(accel, "load_accel", lambda: None)
    monkeypatch.setattr(
        accel,
        "recommend_profile",
        lambda *args, **kwargs: pytest.fail("runtime must not choose"),
    )

    with pytest.raises(RuntimeError, match=r"scubiee setup"):
        accel.resolve_runtime()


def test_init_calibration_persists_preferred_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    accel_path = tmp_path / "accel.json"
    mib = 1024 * 1024
    detected = {
        "os": "Windows",
        "machine": "AMD64",
        "python": "3.13.0",
        "nvidia": False,
        "gpus": [{"name": "Test GPU", "adapter_ram": 8_000_000_000}],
        "cpu_count": 16,
        "suggested_dml_device_id": 0,
    }
    snapshot = {
        **detected,
        "cpu_model": "Test CPU",
        "cpu_count_logical": 16,
        "ram_total_bytes": 32_768 * mib,
        "ram_available_bytes": 20_000 * mib,
    }
    saved_snapshot: dict[str, object] = {}
    monkeypatch.setattr(accel, "ACCEL_PATH", accel_path)
    monkeypatch.setattr(accel, "detect_hardware", lambda: detected)
    monkeypatch.setattr(
        hardware,
        "ensure_hardware_snapshot",
        lambda **kwargs: snapshot,
    )
    monkeypatch.setattr(
        hardware,
        "save_hardware",
        lambda value: saved_snapshot.update(value) or tmp_path / "hardware.json",
    )
    monkeypatch.setattr(
        accel,
        "calibrate_batch",
        lambda profile: {
            "ok": True,
            "winner": 20,
            "texts_per_sec": 40.0,
            "candidates": {"8": 25.0, "16": 30.0, "20": 40.0},
            "reason": "20 clears ROI",
        },
    )

    profile = accel.configure(
        install_pkgs=False,
        download_model=False,
        bench=True,
    )
    persisted = accel.load_accel(accel_path)

    assert profile.batch_calibration["winner"] == 20
    assert profile.envelope["batch_ceiling"] == 20
    assert profile.hardware_fingerprint
    assert persisted is not None
    assert persisted.batch_calibration == profile.batch_calibration
    assert persisted.envelope == profile.envelope
    assert saved_snapshot["recommended_accel"]["batch_size"] == 20


def test_init_status_is_read_only_and_prints_preferred_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    saved = _profile()
    monkeypatch.setattr(accel, "load_accel", lambda: saved)
    monkeypatch.setattr(
        accel,
        "detect_hardware",
        lambda: pytest.fail("status must not detect"),
    )
    monkeypatch.setattr(
        accel,
        "configure",
        lambda **kwargs: pytest.fail("status must not configure"),
    )

    assert cli.cmd_setup(_setup_args(status=True)) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["preferred_profile"]["profile"] == "dml"
    assert payload["envelope"]["batch_ceiling"] == 16
    assert "detected_now" not in payload


def test_existing_init_profile_is_reused_unless_repair_requested(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    saved = _profile()
    monkeypatch.setattr(accel, "load_accel", lambda: saved)
    monkeypatch.setattr(
        accel,
        "configure",
        lambda **kwargs: pytest.fail("existing init must not reconfigure"),
    )

    assert cli._configure_machine(_setup_args()) == 0
    assert json.loads(capsys.readouterr().out)["profile"] == "dml"


def test_init_repair_explicitly_reconfigures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repaired = _profile(batch_size=20)
    monkeypatch.setattr(accel, "load_accel", lambda: _profile())
    monkeypatch.setattr(accel, "configure", lambda **kwargs: repaired)

    assert cli._configure_machine(_setup_args(repair=True)) == 0
    assert json.loads(capsys.readouterr().out)["batch_size"] == 20


def test_hardware_snapshot_uses_saved_preference_without_recommendation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = _profile()
    monkeypatch.setattr(accel, "load_accel", lambda: saved)
    monkeypatch.setattr(
        accel,
        "recommend_profile",
        lambda *args, **kwargs: pytest.fail("hardware snapshot must not choose"),
    )
    monkeypatch.setattr(
        accel,
        "detect_hardware",
        lambda: {
            "os": "Windows",
            "machine": "AMD64",
            "python": "3.13.0",
            "nvidia": False,
            "gpus": [],
            "cpu_count": 8,
            "suggested_dml_device_id": 0,
        },
    )
    monkeypatch.setattr(hardware, "_cpu_model", lambda: "Test CPU")
    monkeypatch.setattr(hardware, "_ram_bytes", lambda: {"total": 1, "available": 1})
    monkeypatch.setattr(hardware, "_accel_libs", lambda: {})

    snapshot = hardware.detect_capabilities()

    assert snapshot["recommended_accel"]["profile"] == "dml"


def test_setup_parser_accepts_repair_and_init_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_setup(args: argparse.Namespace) -> int:
        seen["repair"] = args.repair
        return 0

    monkeypatch.setattr(cli, "cmd_setup", fake_setup)

    assert cli.main(["setup", "--repair", "--skip-install", "--skip-model", "--skip-bench"]) == 0
    assert seen["repair"] is True
    with pytest.raises(SystemExit):
        cli.main(["init", "--repair"])
