"""wipe --all requires --yes; repo wipe removes id + store."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.wipe import wipe, wipe_all, wipe_repo


def test_wipe_all_requires_yes(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    out = wipe_all(yes=False)
    assert out["ok"] is False
    assert out["error"] == "confirm_required"
    assert "--yes" in out["hint"]
    assert "--confirm" in out["hint"]
    assert home.is_dir()


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
        json.dumps({"mcpServers": {"context-engine": {"command": "x"}, "other": {}}}),
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
    assert "context-engine" not in (mcp.get("mcpServers") or {})
    assert "other" in (mcp.get("mcpServers") or {})


def test_wipe_repo_removes_id_and_rule(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    id_dir = repo / ".context-engine"
    id_dir.mkdir()
    (id_dir / "id.json").write_text(
        json.dumps({"project_id": "ce_test"}), encoding="utf-8"
    )
    rule = repo / ".cursor" / "rules" / "context-agent.mdc"
    rule.parent.mkdir(parents=True)
    rule.write_text("x", encoding="utf-8")
    mcp = repo / ".cursor" / "mcp.json"
    mcp.write_text(
        json.dumps({"mcpServers": {"context-engine": {"command": "x"}}}),
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
    data = json.loads(mcp.read_text(encoding="utf-8"))
    assert "context-engine" not in (data.get("mcpServers") or {})


def test_wipe_repo_hint_mentions_all(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    (home / "accel.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    out = wipe_repo(repo)
    assert "wipe --all --yes" in out["hint"]
    assert out["still_on_machine"]["accel_json"] is True


def test_wipe_dispatch_all_flag(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    out = wipe(all=True, yes=False)
    assert out["error"] == "confirm_required"
