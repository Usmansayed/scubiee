"""MCP repo resolution — must not default to user home when daemon has a bind."""

from __future__ import annotations

from pathlib import Path

from pipeline import mcp_locate


def test_default_repo_uses_ctx_repo_env(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    monkeypatch.setenv("CTX_REPO", str(repo))
    monkeypatch.delenv("CONTEXT_ENGINE_REPO", raising=False)
    assert mcp_locate._default_repo() == repo.resolve()


def test_default_repo_falls_back_to_daemon_bound_repo(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("CTX_REPO", raising=False)
    monkeypatch.delenv("CONTEXT_ENGINE_REPO", raising=False)
    monkeypatch.chdir(tmp_path)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, path: str):
            assert path == "/health"
            return {"ok": True, "repo": str(tmp_path / "bound")}

    monkeypatch.setattr("pipeline.client.EngineClient", FakeClient)
    assert mcp_locate._default_repo() == (tmp_path / "bound").resolve()


def test_write_cursor_mcp_drops_user_duplicate(tmp_path: Path, monkeypatch) -> None:
    from pipeline.mcp_install import write_cursor_mcp

    project_root = tmp_path / "proj"
    project_root.mkdir()
    user_home = tmp_path / "home"
    user_home.mkdir()
    user_mcp = user_home / ".cursor" / "mcp.json"
    user_mcp.parent.mkdir(parents=True)
    user_mcp.write_text(
        '{"mcpServers": {"context-engine": {"command": "python", "args": []}}}\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(project_root)
    monkeypatch.setattr("pipeline.mcp_install.Path.home", lambda: user_home)

    write_cursor_mcp(project_root)

    data = __import__("json").loads(user_mcp.read_text(encoding="utf-8"))
    assert "context-engine" not in (data.get("mcpServers") or {})
    project_mcp = project_root / ".cursor" / "mcp.json"
    project = __import__("json").loads(project_mcp.read_text(encoding="utf-8"))
    env = project["mcpServers"]["context-engine"]["env"]
    assert "CTX_REPO" in env
