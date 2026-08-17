"""ctx init enrolls a repository; machine install lives on ctx setup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline import __main__ as cli


def test_init_refuses_when_machine_setup_is_missing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr("pipeline.accel.load_accel", lambda: None)
    repo = tmp_path / "app"
    repo.mkdir()
    rc = cli.cmd_init(
        argparse.Namespace(path=str(repo), no_index=False, allow_once=False)
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "machine_not_setup"
    assert "setup" in payload["repair"]


def test_init_enrolls_indexes_and_binds_daemon(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    (repo / "a.py").write_text("a=1\n", encoding="utf-8")
    called: dict[str, object] = {}

    monkeypatch.setattr(
        "pipeline.accel.load_accel",
        lambda: object(),
    )

    def fake_initialize(root, *, index=True, always_allow=True, **_kwargs):
        called["root"] = Path(root).resolve()
        called["index"] = index
        called["always_allow"] = always_allow
        return {"ok": True, "project_id": "ce_test", "indexed": index}

    def fake_ensure(root, **_kwargs):
        called["bound"] = Path(root).resolve()
        return {"ok": True, "already_running": True, "repo": str(Path(root).resolve())}

    monkeypatch.setattr("pipeline.repo_lifecycle.initialize_repo", fake_initialize)
    monkeypatch.setattr("pipeline.daemon.ensure_daemon", fake_ensure)

    rc = cli.cmd_init(
        argparse.Namespace(path=str(repo), no_index=False, allow_once=False)
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert called["root"] == repo.resolve()
    assert called["index"] is True
    assert called["bound"] == repo.resolve()
    assert payload["daemon"]["ok"] is True


def test_init_skips_json_on_tty(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    monkeypatch.setattr("pipeline.accel.load_accel", lambda: object())
    monkeypatch.setattr(
        "pipeline.repo_lifecycle.initialize_repo",
        lambda *_a, **_k: {"ok": True, "project_id": "ce_test"},
    )
    monkeypatch.setattr(
        "pipeline.daemon.ensure_daemon",
        lambda *_a, **_k: {"ok": True},
    )
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    rc = cli.cmd_init(
        argparse.Namespace(path=str(repo), no_index=False, allow_once=False)
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() == ""


def test_pyproject_ships_dashboard_ui_assets() -> None:
    import tomllib

    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    packaged = data["tool"]["setuptools"]["package-data"]["pipeline"]
    assert any("dashboard_ui" in item for item in packaged)
