"""Deterministic production fault / recovery scenarios for CE certification."""

from __future__ import annotations

from pathlib import Path


def test_scenario_checks_cover_core_faults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline.certify import scenario_checks

    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("x=1\n", encoding="utf-8")
    checks = {c["name"]: c for c in scenario_checks(root)}
    required = {
        "repo_lifecycle",
        "disk_denial_unusable_store",
        "dirty_restart_journal_replay",
        "two_repo_runtime_isolation",
        "provider_warmup_fail_closed",
        "watcher_overflow_recovery",
        "publication_coherence",
        "doctor_safe_repair_classification",
    }
    assert required <= checks.keys()
    failed = {name: checks[name] for name in required if checks[name]["status"] != "passed"}
    assert not failed, failed
    assert checks["permission_denial"]["status"] in {"passed", "skipped"}
    if checks["permission_denial"]["status"] == "skipped":
        assert checks["permission_denial"]["ok"] is False
    assert checks["external_client_matrix"]["status"] == "skipped"
    assert not (root / ".ce-scenario-store").exists()


def test_certify_required_gate_passes_without_daemon(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline.certify import certify

    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("x=1\n", encoding="utf-8")
    out = certify(root, skip_daemon=True, skip_canary=True)
    assert out["ok"] is True
    assert out["failed_required"] == 0
    names = {c["name"] for c in out["checks"]}
    assert "import_preflight" in names
    assert "install_mcp_phase_env" in names
    assert "dirty_restart_journal_replay" in names
    assert out["passed"] == sum(
        check["status"] == "passed" for check in out["checks"]
    )
    assert out["skipped"] == sum(
        check["status"] == "skipped" for check in out["checks"]
    )


def test_skipped_checks_are_neutral_and_never_counted_as_passed(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline import certify as certification

    original = certification.scenario_checks
    monkeypatch.setattr(
        certification,
        "scenario_checks",
        lambda _root: [
            certification._check(
                "unsupported_permission_probe",
                False,
                required=True,
                status="skipped",
                detail="unsupported",
            )
        ],
    )
    try:
        out = certification.certify(
            tmp_path, skip_daemon=True, skip_canary=True
        )
    finally:
        monkeypatch.setattr(certification, "scenario_checks", original)

    assert out["ok"] is True
    assert out["failed_required"] == 0
    assert out["skipped"] >= 2
    skipped = [c for c in out["checks"] if c["name"] == "unsupported_permission_probe"]
    assert skipped and skipped[0]["status"] == "skipped" and skipped[0]["required"] is False
    assert out["passed"] == sum(
        check["status"] == "passed" for check in out["checks"]
    )


def test_core_test_plan_contains_required_certification_suites(tmp_path: Path) -> None:
    from pipeline.test_runner import build_test_plan

    targets = set(build_test_plan("core", root=tmp_path).pytest_targets)
    assert {
        "tests/test_repo_lifecycle.py",
        "tests/test_multi_repo_runtime.py",
        "tests/test_sync_status_canaries.py",
        "tests/test_storage_policy.py",
        "tests/test_watcher_recovery.py",
        "tests/test_artifact_guard.py",
        "tests/test_production_scenarios.py",
    } <= targets


def test_index_unusable_when_manifest_checksum_mismatches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline.artifact_guard import publish_manifest
    from pipeline.project_id import index_is_usable

    store = tmp_path / "store"
    store.mkdir()
    chunks = store / "chunks.jsonl"
    graph = store / "graph.json"
    meta = store / "meta.json"
    chunks.write_text('{"id":1,"file":"a.py","start_line":1,"end_line":1,"symbol":null,"text":"x","enriched":"x"}\n', encoding="utf-8")
    graph.write_text("{}\n", encoding="utf-8")
    meta.write_text('{"chunks": 1}\n', encoding="utf-8")
    publish_manifest(store, [chunks, graph, meta])
    assert index_is_usable(store) is True
    chunks.write_text("tampered\n", encoding="utf-8")
    assert index_is_usable(store) is False
