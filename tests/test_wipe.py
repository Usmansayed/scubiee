"""wipe --all requires --yes; repo wipe removes id + store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.wipe import audit_scubiee_artifacts, wipe, wipe_all, wipe_repo


@pytest.fixture(autouse=True)
def _fast_wipe_process_kill(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Avoid scanning/killing real OS processes in wipe integration tests."""
    if request.node.name in {
        "test_wipe_all_runs_final_kill_after_cleanup",
        "test_wipe_repo_halts_before_removal",
    }:
        return

    monkeypatch.setattr(
        "pipeline.process_control.kill_all_scubiee_processes",
        lambda **kw: {"ok": True, "remaining": [], "remaining_pids": []},
    )
    monkeypatch.setattr(
        "pipeline.process_control.release_scubiee_process_locks",
        lambda **kw: {"ok": True, "mcp": {"disabled": []}, "kill": {"ok": True, "remaining": []}},
    )
    monkeypatch.setattr(
        "pipeline.process_control.unlock_uv_tool_env",
        lambda **kw: {"ok": True},
    )
    monkeypatch.setattr(
        "pipeline.daemon.stop_daemon",
        lambda: {"ok": True},
    )
    monkeypatch.setattr(
        "pipeline.watchdog.stop_watchdog",
        lambda: {"ok": True},
    )
    monkeypatch.setattr(
        "pipeline.daemon.ensure_daemon",
        lambda repo=None, **kw: {"ok": True, "started": True},
    )
    monkeypatch.setattr(
        "pipeline.pause_resume.pause",
        lambda: {"ok": True, "already_paused": False},
    )
    monkeypatch.setattr(
        "pipeline.process_control.stop_all_context_engine_processes",
        lambda **kw: {"ok": True, "remaining": [], "remaining_pids": []},
    )


def test_wipe_repo_halts_before_removal(tmp_path: Path, monkeypatch) -> None:
    """Repo wipe must stop MCP/processes before deleting files."""
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    order: list[str] = []

    def _halt(**kwargs: object) -> dict:
        order.append("halt")
        return {"ok": True, "scope": "repo", "actions": {"stop_all": {"ok": True}}}

    def _remove_repo(*_a, **_k) -> dict:
        order.append("remove")
        return {"ok": True, "error": "unmanaged"}

    monkeypatch.setattr("pipeline.wipe._halt_scubiee_before_wipe", _halt)
    monkeypatch.setattr("pipeline.repo_lifecycle.remove_repo", _remove_repo)

    wipe_repo(repo)
    assert order == ["halt", "remove"]


def test_wipe_repo_does_not_global_pause(tmp_path: Path, monkeypatch) -> None:
    """Repo wipe stops engine only — no global pause or MCP disable."""
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()

    pause_called = False
    release_called = False

    def _fake_pause() -> dict:
        nonlocal pause_called
        pause_called = True
        return {"ok": True}

    def _fake_release(**kw: object) -> dict:
        nonlocal release_called
        release_called = True
        return {"ok": True}

    monkeypatch.setattr("pipeline.pause_resume.pause", _fake_pause)
    monkeypatch.setattr(
        "pipeline.process_control.release_scubiee_process_locks",
        _fake_release,
    )
    monkeypatch.setattr("pipeline.daemon.stop_daemon", lambda: {"ok": True})
    monkeypatch.setattr("pipeline.watchdog.stop_watchdog", lambda: {"ok": True})
    monkeypatch.setattr(
        "pipeline.repo_lifecycle.remove_repo",
        lambda *_a, **_k: {"ok": True},
    )

    halt = __import__("pipeline.wipe", fromlist=["_halt_scubiee_before_wipe"])._halt_scubiee_before_wipe(
        scope="repo", repo=repo
    )

    assert pause_called is False
    assert release_called is False
    assert "pause" not in (halt.get("actions") or {})
    assert "process_release" not in (halt.get("actions") or {})
    assert "engine_stop" in (halt.get("actions") or {})


def test_wipe_repo_restarts_engine(tmp_path: Path, monkeypatch) -> None:
    """Repo wipe: stop → wipe → restart engine."""
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()

    order: list[str] = []

    monkeypatch.setattr(
        "pipeline.wipe._halt_scubiee_before_wipe",
        lambda **kw: order.append("halt") or {"ok": True, "actions": {}},
    )
    monkeypatch.setattr(
        "pipeline.repo_lifecycle.remove_repo",
        lambda *_a, **_k: order.append("wipe") or {"ok": True, "error": "unmanaged"},
    )
    monkeypatch.setattr(
        "pipeline.wipe._restart_engine_after_repo_wipe",
        lambda r: order.append("restart") or {"ok": True},
    )

    wipe_repo(repo)
    assert order == ["halt", "wipe", "restart"]


def test_wipe_all_does_not_global_pause(tmp_path: Path, monkeypatch) -> None:
    """Full wipe hard-stops processes — must not call pause() backup."""
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()

    pause_called = False

    def _fake_pause() -> dict:
        nonlocal pause_called
        pause_called = True
        return {"ok": True}

    monkeypatch.setattr("pipeline.pause_resume.pause", _fake_pause)
    monkeypatch.setattr(
        "pipeline.process_control.release_scubiee_process_locks",
        lambda **kw: {"ok": True, "kill": {"ok": True, "remaining": []}},
    )
    monkeypatch.setattr(
        "pipeline.process_control.kill_all_scubiee_processes",
        lambda **kw: {"ok": True, "remaining": []},
    )
    monkeypatch.setattr(
        "pipeline.process_control.unlock_uv_tool_env",
        lambda **kw: {"ok": True},
    )
    monkeypatch.setattr(
        "pipeline.process_control.is_uv_tool_install",
        lambda **kw: False,
    )
    monkeypatch.setattr(
        "pipeline.process_control.uv_tool_root",
        lambda **kw: None,
    )
    monkeypatch.setattr(
        "pipeline.rules_installer.uninstall_tools",
        lambda *a, **k: {"ok": True},
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.unregister_logon_autostart",
        lambda: {"ok": True},
    )

    halt = __import__("pipeline.wipe", fromlist=["_halt_scubiee_before_wipe"])._halt_scubiee_before_wipe(
        scope="all", repo=repo
    )

    assert pause_called is False
    assert "pause" not in (halt.get("actions") or {})
    assert "process_release" in (halt.get("actions") or {})
    assert "kill_all" in (halt.get("actions") or {})


def test_wipe_all_runs_final_kill_after_cleanup(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    fake_user = tmp_path / "fake-user"
    fake_user.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_user)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    calls: list[str] = []

    def _halt(**kwargs: object) -> dict:
        calls.append("halt")
        return {"ok": True, "scope": "all", "actions": {}, "remaining_processes": []}

    def _final_kill(**kwargs: object) -> dict:
        calls.append("final_kill")
        return {"ok": True, "remaining": [], "remaining_pids": []}

    monkeypatch.setattr("pipeline.wipe._halt_scubiee_before_wipe", _halt)
    monkeypatch.setattr(
        "pipeline.process_control.kill_all_scubiee_processes", _final_kill
    )
    monkeypatch.setattr(
        "pipeline.wipe.audit_scubiee_artifacts",
        lambda **kw: {"clean": True, "remaining": []},
    )
    monkeypatch.setattr(
        "pipeline.wipe.wipe_repo",
        lambda *a, **k: {"ok": True, "scope": "repo", "root": str(repo), "actions": []},
    )

    out = wipe_all(yes=True, models=False, package=False, repo=repo)
    assert out["ok"] is True
    assert calls == ["halt", "final_kill"]


def test_wipe_all_requires_yes(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    out = wipe_all(yes=False)
    assert out["ok"] is False
    assert out["error"] == "confirm_required"
    assert "--confirm" in out["hint"]
    assert home.is_dir()


def test_wipe_repo_requires_yes(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    from pipeline.wipe import wipe

    out = wipe(all=False, yes=False, path=repo)
    assert out["ok"] is False
    assert out["scope"] == "repo"
    assert out["error"] == "confirm_required"
    assert "--confirm" in out["hint"]


def test_wipe_all_confirm_alias_via_dispatch(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    from pipeline.wipe import wipe

    out = wipe(all=True, yes=True, models=False, package=False)
    assert out["scope"] == "all"
    assert not home.exists()


def test_wipe_all_yes_removes_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    (home / "projects" / "ce_x").mkdir(parents=True)
    (home / "prefs.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CTX_HOME", str(home))

    fake_user = tmp_path / "fake-user"
    (fake_user / ".cursor").mkdir(parents=True)
    (fake_user / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"scubiee": {"command": "x"}, "other": {}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: fake_user)

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    out = wipe_all(yes=True, models=False, package=False, repo=repo)
    assert out["ok"] is True
    assert out["scope"] == "all"
    assert not home.exists()
    mcp = json.loads((fake_user / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "scubiee" not in (mcp.get("mcpServers") or {})
    assert "other" in (mcp.get("mcpServers") or {})


def test_wipe_repo_removes_id_and_rule(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    id_dir = repo / ".scubiee"
    id_dir.mkdir()
    (id_dir / "id.json").write_text(
        json.dumps({"project_id": "ce_test"}), encoding="utf-8"
    )
    rule = repo / ".cursor" / "rules" / "scubiee.mdc"
    rule.parent.mkdir(parents=True)
    rule.write_text("x", encoding="utf-8")
    mcp = repo / ".cursor" / "mcp.json"
    mcp.write_text(
        json.dumps({"mcpServers": {"scubiee": {"command": "x"}}}),
        encoding="utf-8",
    )

    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_test": {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "lifecycle_state": "active",
                }
            }
        }
    )

    out = wipe_repo(repo)
    assert out["scope"] == "repo"
    assert not id_dir.exists()
    assert not rule.exists()
    if mcp.is_file():
        data = json.loads(mcp.read_text(encoding="utf-8"))
        assert "scubiee" not in (data.get("mcpServers") or {})
    else:
        assert not mcp.exists()


def test_wipe_repo_removes_nested_scubiee_dirs(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "mono"
    nested = repo / "packages" / "web"
    nested.mkdir(parents=True)
    root_id = repo / ".scubiee"
    root_id.mkdir()
    (root_id / "id.json").write_text(
        json.dumps({"project_id": "ce_root1234567890abcdef"}), encoding="utf-8"
    )
    nested_id = nested / ".scubiee"
    nested_id.mkdir()
    (nested_id / "id.json").write_text(
        json.dumps({"project_id": "ce_web1234567890abcdef"}), encoding="utf-8"
    )

    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_root1234567890abcdef": {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "lifecycle_state": "active",
                }
            }
        }
    )

    out = wipe_repo(repo)
    assert out["ok"] is True
    assert not root_id.exists()
    assert not nested_id.exists()


def test_wipe_repo_hint_mentions_all(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    (home / "accel.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    out = wipe_repo(repo)
    assert "wipe --all --confirm" in out["hint"]
    assert out["still_on_machine"]["accel_json"] is True


def test_audit_reports_ctx_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    out = audit_scubiee_artifacts(include_package=False)
    assert out["clean"] is False
    kinds = {item["kind"] for item in out["remaining"]}
    assert "ctx_home" in kinds


def test_wipe_repo_removes_workspace_local_mcp_files(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    files = [
        repo / ".kiro" / "settings" / "mcp.json",
        repo / ".vscode" / "mcp.json",
        repo / ".mcp.json",
        repo / ".cline" / "mcp.json",
        repo / ".roo" / "mcp.json",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = "servers" if ".vscode" in path.parts else "mcpServers"
        path.write_text(
            json.dumps({key: {"scubiee": {"command": "x"}}}),
            encoding="utf-8",
        )

    out = wipe_repo(repo)
    assert out["ok"] is True
    for path in files:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers") or data.get("servers") or {}
            assert "scubiee" not in servers
        else:
            assert not path.exists()


def test_wipe_all_removes_all_connect_tool_mcp(tmp_path: Path, monkeypatch) -> None:
    """wipe --all must clear every tool connect can write, not only Cursor/Kiro."""
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))

    fake_user = tmp_path / "fake-user"
    fake_user.mkdir()
    monkeypatch.setenv("HOME", str(fake_user))
    monkeypatch.setenv("USERPROFILE", str(fake_user))
    monkeypatch.setenv("APPDATA", str(fake_user / "AppData" / "Roaming"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_user))

    # Cursor (already covered elsewhere) + Claude Code + Windsurf user MCP.
    cursor_mcp = fake_user / ".cursor" / "mcp.json"
    cursor_mcp.parent.mkdir(parents=True)
    cursor_mcp.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "scubiee": {"command": "x"},
                    "keep-me": {"command": "y"},
                }
            }
        ),
        encoding="utf-8",
    )
    claude_mcp = fake_user / ".claude.json"
    claude_mcp.write_text(
        json.dumps({"mcpServers": {"scubiee": {"command": "x"}, "other": {}}}),
        encoding="utf-8",
    )
    windsurf_mcp = fake_user / ".codeium" / "windsurf" / "mcp_config.json"
    windsurf_mcp.parent.mkdir(parents=True)
    windsurf_mcp.write_text(
        json.dumps({"mcpServers": {"scubiee": {"command": "x"}}}),
        encoding="utf-8",
    )
    # Codex TOML
    codex_cfg = fake_user / ".codex" / "config.toml"
    codex_cfg.parent.mkdir(parents=True)
    codex_cfg.write_text(
        '[mcp_servers.other]\ncommand = "y"\n\n[mcp_servers.scubiee]\ncommand = "x"\n',
        encoding="utf-8",
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    out = wipe_all(yes=True, models=False, package=False, repo=repo)
    assert out["ok"] is True
    assert any("disconnect_all_tools" in a for a in out.get("actions", []))

    cursor = json.loads(cursor_mcp.read_text(encoding="utf-8"))
    assert "scubiee" not in (cursor.get("mcpServers") or {})
    assert "keep-me" in (cursor.get("mcpServers") or {})

    claude = json.loads(claude_mcp.read_text(encoding="utf-8"))
    assert "scubiee" not in (claude.get("mcpServers") or {})
    assert "other" in (claude.get("mcpServers") or {})

    if windsurf_mcp.is_file():
        wind = json.loads(windsurf_mcp.read_text(encoding="utf-8"))
        assert "scubiee" not in (wind.get("mcpServers") or {})
    # Empty-only files may be deleted entirely.

    if codex_cfg.is_file():
        text = codex_cfg.read_text(encoding="utf-8")
        assert "scubiee" not in text
        assert "other" in text

    audit = audit_scubiee_artifacts(include_package=False, include_models=False)
    tool_leftovers = [r for r in audit["remaining"] if str(r["kind"]).startswith("tool_mcp:")]
    assert tool_leftovers == [], tool_leftovers


def test_disconnect_all_workspaces_removes_other_repo_local_mcp(
    tmp_path: Path, monkeypatch
) -> None:
    from pipeline.rules_installer import uninstall_tool
    from pipeline.tool_registry import TOOL_MAP

    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path / "user-home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user-home"))
    (tmp_path / "user-home").mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "user-home"))

    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    for repo in (repo_a, repo_b):
        repo.mkdir()
        (repo / ".git").mkdir()
        ce = repo / ".scubiee"
        ce.mkdir(parents=True)
        mcp = repo / ".kiro" / "settings" / "mcp.json"
        mcp.parent.mkdir(parents=True)
        mcp.write_text(
            json.dumps({"mcpServers": {"scubiee": {"command": "x", "env": {}}}}),
            encoding="utf-8",
        )
        pid = "ce_aaaaa" if repo == repo_a else "ce_bbbbb"
        (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")

    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_aaaaa": {
                    "managed": True,
                    "root": str(repo_a.resolve()),
                    "paths": [str(repo_a.resolve())],
                },
                "ce_bbbbb": {
                    "managed": True,
                    "root": str(repo_b.resolve()),
                    "paths": [str(repo_b.resolve())],
                },
            }
        }
    )

    monkeypatch.chdir(repo_a)
    report = uninstall_tool(TOOL_MAP["kiro"], repo=repo_a, all_workspaces=True)
    assert report["ok"] is True
    assert report.get("all_workspaces") is True
    assert not (repo_a / ".kiro" / "settings" / "mcp.json").is_file()
    assert not (repo_b / ".kiro" / "settings" / "mcp.json").is_file()


def test_wipe_all_removes_mlx_and_fastembed_model_caches(
    tmp_path: Path, monkeypatch
) -> None:
    """--all must delete MLX weights under CTX_HOME and FastEmbed CodeRank caches."""
    from pipeline.wipe import _coderank_model_dirs

    home = tmp_path / "ce-home"
    mlx = home / "mlx" / "CodeRankEmbed"
    mlx.mkdir(parents=True)
    (mlx / "weights.fp16.npz").write_bytes(b"fake-mlx")
    (home / "accel.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CTX_HOME", str(home))

    fe_cache = tmp_path / "fastembed_cache"
    model = fe_cache / "models--jamie8johnson--CodeRankEmbed-onnx"
    model.mkdir(parents=True)
    (model / "model_fp16.onnx").write_bytes(b"fake-onnx")
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(fe_cache))
    monkeypatch.setenv("FASTEMBED_CACHE", str(fe_cache))

    fake_user = tmp_path / "user"
    fake_user.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_user))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    targets = {p.resolve() for p in _coderank_model_dirs()}
    assert mlx.resolve() in targets
    assert fe_cache.resolve() in targets or model.resolve() in targets

    out = wipe_all(yes=True, models=True, package=False)
    assert out["scope"] == "all"
    assert not home.exists(), "CTX_HOME (incl. MLX weights) must be gone"
    model_actions = next(
        (a["models"] for a in out.get("actions", []) if isinstance(a.get("models"), list)),
        [],
    )
    removed_paths = {item["path"] for item in model_actions if item.get("removed")}
    assert str(fe_cache.resolve()) in removed_paths or str(model.resolve()) in removed_paths
    assert not model.exists(), "CodeRank model files must be gone"
    remaining_models = [
        item for item in (out.get("remaining") or []) if item.get("kind") == "model_cache"
    ]
    assert remaining_models == []


def test_wipe_cli_accepts_yes_as_confirm_alias(tmp_path: Path, monkeypatch, capsys) -> None:
    from pipeline.__main__ import main

    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    fake_user = tmp_path / "user"
    fake_user.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_user))
    monkeypatch.chdir(tmp_path)
    # Non-TTY → JSON path
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    monkeypatch.setattr("sys.stderr.isatty", lambda: False)

    rc = main(["wipe", "--all", "--yes", "--keep-package"])
    assert rc in {0, 1}  # 1 if audit finds unrelated leftovers
    assert not home.exists()
    err = capsys.readouterr()
    assert "unrecognized arguments" not in err.err


def test_wipe_all_keep_package_preserves_tool_shims(tmp_path: Path, monkeypatch) -> None:
    """--keep-package must not remove ~/.local/bin/scubiee (W5 / G16b matrix)."""
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))

    fake_user = tmp_path / "user"
    shim = fake_user / ".local" / "bin" / "scubiee"
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/bin/sh\necho scubiee\n", encoding="utf-8")
    mcp = fake_user / ".cursor" / "mcp.json"
    mcp.parent.mkdir(parents=True)
    mcp.write_text(
        json.dumps({"mcpServers": {"scubiee": {"command": "x"}, "neighbor": {}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_user))

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    out = wipe_all(yes=True, models=False, package=False, repo=repo)
    assert out["ok"] is True
    assert shim.is_file(), "keep-package must not unlink uv tool shims"
    assert not any("tool_shims" in a for a in out.get("actions", []))
    cursor = json.loads(mcp.read_text(encoding="utf-8"))
    assert "scubiee" not in (cursor.get("mcpServers") or {})
    assert "neighbor" in (cursor.get("mcpServers") or {})
    audit = audit_scubiee_artifacts(include_package=False, include_models=False)
    shim_left = [r for r in audit["remaining"] if r.get("kind") == "tool_shim"]
    assert shim_left == [], shim_left
