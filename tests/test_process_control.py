from __future__ import annotations

import os
from pathlib import Path

from pipeline import process_control


def test_cmdline_matches_mcp_locate_module() -> None:
    from pipeline.process_control import _cmdline_matches_ce

    assert _cmdline_matches_ce(["python", "-m", "pipeline.mcp_locate"])
    assert _cmdline_matches_ce(["scubiee-mcp"])
    assert not _cmdline_matches_ce(["python", "-m", "pip", "install", "requests"])


def test_uv_tool_root_from_scripts_python() -> None:
    py = Path("C:/Users/me/AppData/Roaming/uv/tools/scubiee/Scripts/python.exe")
    root = process_control.uv_tool_root(py)
    assert root == Path("C:/Users/me/AppData/Roaming/uv/tools/scubiee")


def test_uv_tool_root_none_for_conda() -> None:
    py = Path("C:/Users/me/Miniconda3/python.exe")
    assert process_control.uv_tool_root(py) is None


def test_is_uv_tool_install_checks_receipt(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "uv" / "tools" / "scubiee"
    scripts = root / "Scripts"
    scripts.mkdir(parents=True)
    py = scripts / "python.exe"
    py.write_bytes(b"")
    (root / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    monkeypatch.setattr(process_control, "uv_tool_root", lambda _p=None: root)
    assert process_control.is_uv_tool_install(py) is True


def test_rmtree_with_retries_rename_first_on_windows(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "scubiee"
    root.mkdir()
    (root / "locked.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(process_control, "stop_all_context_engine_processes", lambda: {"ok": True})
    monkeypatch.setattr(process_control.time, "sleep", lambda _s: None)
    monkeypatch.setattr(process_control.os, "name", "nt")
    monkeypatch.setattr(process_control, "_schedule_delete_after_exit", lambda *_a, **_k: {"ok": True})
    result = process_control._rmtree_with_retries(root, attempts=3, delay_s=0)
    assert result["ok"] is True
    assert not root.exists()
    assert any(a.get("action") == "rename" for a in result["attempts"])


def test_prepare_uv_tool_disables_mcp_before_stop(tmp_path: Path, monkeypatch) -> None:
    order: list[str] = []

    def fake_disable(*, project=None):  # noqa: ANN001
        order.append("mcp")
        return {"ok": True, "disabled": ["~/.cursor/mcp.json"]}

    def fake_stop(*, ctx_home=None):  # noqa: ANN001
        order.append("stop")
        return {"ok": True, "remaining": [], "extra_killed": []}

    monkeypatch.setattr(process_control, "disable_mcp_to_prevent_respawn", fake_disable)
    monkeypatch.setattr(process_control, "stop_all_context_engine_processes", fake_stop)
    report = process_control.prepare_uv_tool_directory_for_swap(remove_dir=False)
    assert order == ["mcp", "stop"]
    assert report["ok"] is True
    assert report["mcp"]["disabled"] == ["~/.cursor/mcp.json"]


def test_disable_mcp_marks_project_cursor(tmp_path: Path, monkeypatch) -> None:
    proj = tmp_path / "repo"
    mcp_dir = proj / ".cursor"
    mcp_dir.mkdir(parents=True)
    mcp = mcp_dir / "mcp.json"
    mcp.write_text(
        '{"mcpServers":{"scubiee":{"command":"scubiee-mcp"}}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pipeline.pause_resume._disable_mcp_for_tool",
        lambda _tool: [],
    )
    report = process_control.disable_mcp_to_prevent_respawn(project=proj)
    data = __import__("json").loads(mcp.read_text(encoding="utf-8"))
    assert data["mcpServers"]["scubiee"]["disabled"] is True
    assert any(str(mcp) == p or p.endswith("mcp.json") for p in report["disabled"])


def test_stop_processes_under_skips_self_and_ancestors(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "uv" / "tools" / "scubiee"
    root.mkdir(parents=True)
    self_pid = os.getpid()
    killed: list[int] = []

    def fake_term(pid: int) -> None:
        killed.append(pid)

    calls = {"n": 0}

    def processes_side_effect(_r):
        calls["n"] += 1
        if calls["n"] == 1:
            return [self_pid, 424242]
        return [self_pid]

    monkeypatch.setattr(process_control, "_terminate_pid_no_tree", fake_term)
    monkeypatch.setattr(process_control, "_pid_in_our_ancestry", lambda pid, self_pid=None: pid == os.getpid())
    monkeypatch.setattr(process_control.time, "sleep", lambda _s: None)
    monkeypatch.setattr(process_control, "processes_under", processes_side_effect)
    report = process_control.stop_processes_under(root, grace_s=0)
    assert self_pid in report["skipped"]
    assert self_pid not in killed
    assert 424242 in killed


def test_running_from_uv_tool_uses_sys_executable(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "uv" / "tools" / "scubiee"
    scripts = root / "Scripts"
    scripts.mkdir(parents=True)
    tool_py = scripts / "python.exe"
    tool_py.write_bytes(b"")
    other = tmp_path / "other" / "python.exe"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"")
    monkeypatch.setattr(process_control.sys, "executable", str(tool_py))
    assert process_control._running_from_uv_tool(root, other) is True
    monkeypatch.setattr(process_control.sys, "executable", str(other))
    assert process_control._running_from_uv_tool(root, tool_py) is False
