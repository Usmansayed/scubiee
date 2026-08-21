"""Doctor / certify CLI contract tests."""

from __future__ import annotations

from pathlib import Path


def test_doctor_reports_capability_gaps(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline.doctor import doctor_repo
    from pipeline.preflight import inspect_capabilities

    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "a.py").write_text("a=1\n", encoding="utf-8")
    report = doctor_repo(repo)
    caps = inspect_capabilities(require_semantic=True)
    assert "capabilities" in report
    assert "repairs" in report
    # If deps missing, doctor must not claim ok
    if not caps["ok"]:
        assert report["ok"] is False
        assert report["repairs"]


def test_apply_safe_repairs_rebinds_daemon_and_leaves_manual_actions(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline.doctor import apply_safe_repairs, plan_repairs

    repo = tmp_path / "app"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    called: dict[str, object] = {}

    def fake_binding(root):
        target = Path(root).resolve()
        if called.get("ensured"):
            return {
                "ok": True,
                "healthy": True,
                "matched": True,
                "bound_repo": str(target),
                "repo": str(target),
                "lock_pid": 1,
                "repair": None,
            }
        return {
            "ok": False,
            "healthy": True,
            "matched": False,
            "bound_repo": str(other),
            "repo": str(target),
            "lock_pid": 1,
            "repair": f"scubiee engine ensure {target}",
        }

    def fake_ensure(root, **_kwargs):
        called["ensured"] = Path(root).resolve()
        return {"ok": True, "already_running": True, "repo": str(Path(root).resolve())}

    def fake_initialize(*_args, **_kwargs):
        called["initialized"] = True
        return {"ok": True}

    monkeypatch.setattr("pipeline.daemon.validate_daemon_binding", fake_binding)
    monkeypatch.setattr("pipeline.daemon.ensure_daemon", fake_ensure)
    monkeypatch.setattr("pipeline.repo_lifecycle.initialize_repo", fake_initialize)
    monkeypatch.setattr("pipeline.doctor.index_is_usable", lambda *_args, **_kwargs: True)

    planned = plan_repairs(repo)
    kinds = {item["id"]: item["kind"] for item in planned}
    assert kinds["bind_daemon"] == "safe"
    assert "install_deps" not in kinds or kinds["install_deps"] == "manual"

    result = apply_safe_repairs(repo)
    assert called.get("ensured") == repo.resolve()
    assert "initialized" not in called
    applied_ids = [item["id"] for item in result["applied"]]
    assert "bind_daemon" in applied_ids
    assert all(item["kind"] == "manual" for item in result["manual"])
    assert result["after"]["binding"]["matched"] is True


def test_doctor_all_reports_each_managed_repository(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline.doctor import doctor_all
    from pipeline.repo_lifecycle import initialize_repo

    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    (first / "a.py").write_text("a=1\n", encoding="utf-8")
    (second / "b.py").write_text("b=1\n", encoding="utf-8")
    initialize_repo(first, index=False)
    initialize_repo(second, index=False)

    fleet = doctor_all()
    roots = {Path(item["repo"]).resolve() for item in fleet["repositories"]}
    assert first.resolve() in roots
    assert second.resolve() in roots
    assert "ok" in fleet
