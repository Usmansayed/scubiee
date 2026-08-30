"""scubiee init enrolls a repository; machine install lives on scubiee setup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

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


def test_search_cli_treats_dot_then_query_as_repo_then_query(tmp_path: Path):
    from pipeline.__main__ import interpret_search_cli

    root, query = interpret_search_cli(".", "unique beacon phrase")
    assert query == "unique beacon phrase"
    assert root == Path(".").resolve()


def test_search_cli_query_only(tmp_path: Path):
    from pipeline.__main__ import interpret_search_cli

    root, query = interpret_search_cli("symbol_name", None)
    assert query == "symbol_name"
    assert root == Path(".").resolve()


def test_client_ignores_non_directory_path(tmp_path: Path):
    from pipeline.client import EngineClient

    repo = tmp_path / "app"
    repo.mkdir()
    client = EngineClient("http://example.invalid", workspace_path=str(repo))
    assert client._coerce_workspace("not a real folder") == str(repo.resolve())
    with pytest.raises(ValueError, match="not a directory"):
        EngineClient("http://example.invalid")._coerce_workspace("ghost path")


def test_search_cli_fails_when_daemon_unreachable(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "app"
    repo.mkdir()
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        "pipeline.searcher._search_via_server",
        lambda *args, **kwargs: None,
    )
    rc = cli.cmd_search(
        argparse.Namespace(
            query="beacon",
            path=".",
            top_k=8,
            local=False,
            url="http://127.0.0.1:8765",
        )
    )
    err = json.loads(capsys.readouterr().err)
    assert rc == 1
    assert err["ok"] is False
    assert "unreachable" in err["error"].lower()


def test_init_skips_preflight_prompt_for_repeat_init(tmp_path: Path, monkeypatch):
    repo = tmp_path / "app"
    repo.mkdir()
    monkeypatch.setattr("pipeline.accel.load_accel", lambda: object())
    monkeypatch.setattr(
        "pipeline.repo_lifecycle.describe_init_state",
        lambda _root: {"repeat_init": True, "managed": True, "index_usable": True},
    )

    preflight_calls: list[dict[str, object]] = []

    def fake_preflight(*_args, **kwargs):
        preflight_calls.append(kwargs)
        return 99999

    captured: dict[str, object] = {}

    def fake_initialize(root, **kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "project_id": "ce_test",
            "already_initialized": True,
            "chunks": 42,
            "store_dir": str(tmp_path / "store"),
        }

    monkeypatch.setattr("pipeline.incremental.preflight_index_scope", fake_preflight)
    monkeypatch.setattr("pipeline.repo_lifecycle.initialize_repo", fake_initialize)
    monkeypatch.setattr("pipeline.daemon.ensure_daemon", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    rc = cli.cmd_init(
        argparse.Namespace(
            path=str(repo),
            no_index=False,
            allow_once=False,
            fast=False,
            roots=None,
            confirm=False,
        )
    )
    assert rc == 0
    assert preflight_calls == []
    assert captured.get("confirm") is True


def test_init_accepts_fast_roots(tmp_path: Path, monkeypatch):
    repo = tmp_path / "app"
    repo.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr("pipeline.accel.load_accel", lambda: object())
    monkeypatch.setattr(
        "pipeline.repo_lifecycle.describe_init_state",
        lambda _root: {"repeat_init": False},
    )

    def fake_initialize(root, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "project_id": "ce_test"}

    monkeypatch.setattr("pipeline.repo_lifecycle.initialize_repo", fake_initialize)
    monkeypatch.setattr("pipeline.daemon.ensure_daemon", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)

    rc = cli.cmd_init(
        argparse.Namespace(
            path=str(repo),
            no_index=False,
            allow_once=False,
            fast=False,
            roots="src,packages",
            confirm=True,
        )
    )
    assert rc == 0
    assert captured.get("fast") is True
    assert captured.get("fast_roots") == ["src", "packages"]
