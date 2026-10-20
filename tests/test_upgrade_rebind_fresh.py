"""Upgrade must always refresh MCP + rules with the *installed* version's code."""

from __future__ import annotations

import subprocess

import pytest


def test_write_text_if_changed_skips_identical(tmp_path):
    from pipeline.rules_installer import _write_text_if_changed

    p = tmp_path / "mcp.json"
    assert _write_text_if_changed(p, "a\n") is True
    mtime = p.stat().st_mtime_ns
    assert _write_text_if_changed(p, "a\n") is False
    assert p.stat().st_mtime_ns == mtime
    assert _write_text_if_changed(p, "b\n") is True
    assert p.read_text(encoding="utf-8") == "b\n"


def test_write_json_leaves_identical_mcp_untouched(tmp_path):
    from pipeline.rules_installer import _write_json

    p = tmp_path / ".cursor" / "mcp.json"
    data = {"mcpServers": {"scubiee": {"command": "x"}}}
    _write_json(p, data)
    mtime = p.stat().st_mtime_ns
    _write_json(p, dict(data))
    assert p.stat().st_mtime_ns == mtime


def test_rebind_fresh_process_runs_real_interpreter(tmp_path, monkeypatch):
    import pipeline.upgrade_supervisor as sup

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    result = sup.rebind_in_fresh_process(timeout_s=120)
    assert result["fresh_process"] is True, result
    assert result["ok"] is True
    assert result.get("skipped") is True  # empty CTX_HOME → no connected tools


def test_fresh_rebind_writes_current_templates_not_stale_in_memory(
    tmp_path, _isolate_scubiee_home, monkeypatch
):
    """Old process holds stale template code; the rebind must still write the
    on-disk (new) GATE rules + MCP entry for every connected tool."""
    import json

    from conftest import enroll_test_repo
    import pipeline.rules_installer as ri
    import pipeline.upgrade_supervisor as sup
    from pipeline.connect_state import save_connected_tools

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    enroll_test_repo(repo, home=_isolate_scubiee_home)
    save_connected_tools(["cursor"])

    mdc = repo / ".cursor" / "rules" / "scubiee.mdc"
    mdc.parent.mkdir(parents=True)
    mdc.write_text("OLD GATE BODY\n", encoding="utf-8")
    monkeypatch.setattr(ri, "_rule_content_mdc", lambda gate_line=None: "STALE IN-MEMORY\n")

    result = sup.rebind_in_fresh_process(timeout_s=120)
    assert result["fresh_process"] is True, result
    assert result["ok"] is True, result

    body = mdc.read_text(encoding="utf-8")
    assert "OLD GATE BODY" not in body and "STALE IN-MEMORY" not in body
    assert "GATE 1:" in body
    mcp = json.loads((repo / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "scubiee" in mcp["mcpServers"]

    mtimes = (mdc.stat().st_mtime_ns, (repo / ".cursor" / "mcp.json").stat().st_mtime_ns)
    again = sup.rebind_in_fresh_process(timeout_s=120)
    assert again["ok"] is True
    assert (mdc.stat().st_mtime_ns, (repo / ".cursor" / "mcp.json").stat().st_mtime_ns) == mtimes


def test_rebind_fresh_process_falls_back_in_process(monkeypatch):
    import pipeline.upgrade_supervisor as sup

    def boom(*a, **k):
        raise OSError("spawn failed")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(sup, "rebind_mcp_and_rules", lambda: {"ok": True, "repos": []})
    result = sup.rebind_in_fresh_process()
    assert result["fresh_process"] is False
    assert "spawn failed" in result["fresh_process_error"]
    assert result["ok"] is True


def _mock_upgrade(monkeypatch, tmp_path, *, swap: bool):
    from pipeline import upgrade
    import pipeline.upgrade_supervisor as sup
    from pipeline.upgrade_manifest import ComponentAction, DiffPlan

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setattr(upgrade, "installed_version", lambda: "0.3.6")
    monkeypatch.setattr(
        upgrade,
        "check_pypi_version",
        lambda force=False, timeout=5.0: {
            "current": "0.3.6",
            "latest": "0.3.6",
            "update_available": False,
        },
    )
    # Format stamps current: only the package (maybe) changes.
    monkeypatch.setattr(
        sup,
        "build_diff_plan",
        lambda **kwargs: DiffPlan(
            from_version=kwargs["from_version"],
            to_version=kwargs["to_version"],
            actions=[
                ComponentAction("package", "swap" if swap else "skip", "x"),
                ComponentAction("daemon", "restart", "ensure"),
            ],
        ),
    )
    monkeypatch.setattr(sup, "quiesce_for_upgrade", lambda project=None: {"ok": True})
    monkeypatch.setattr(
        sup, "swap_package", lambda pre_release=False, target_version=None: {"ok": True}
    )
    monkeypatch.setattr(
        sup, "ensure_daemon_after_upgrade", lambda repo=None: {"ok": True, "action": "x"}
    )
    monkeypatch.setattr(
        sup,
        "health_check",
        lambda timeout=5.0: {"ok": True, "installed_version": "0.3.6", "daemon_version": "0.3.6"},
    )
    monkeypatch.setattr(sup, "maybe_setup_repair", lambda: {"ok": True, "skipped": True})
    monkeypatch.setattr(sup, "rebuild_embeddings_if_needed", lambda plan: {"ok": True, "skipped": True})
    monkeypatch.setattr(sup, "migrate_indexes", lambda: {"ok": True, "skipped": True})
    monkeypatch.setattr(
        sup,
        "snapshot_for_rollback",
        lambda revision_id, old_version: {"ok": True, "revision_id": revision_id},
    )
    monkeypatch.setattr(
        "pipeline.mcp_hot_reload.nudge_mcp_hot_reload", lambda version=None: {"ok": True}
    )
    monkeypatch.setattr("pipeline.install_lean.apply_lean", lambda: {"ok": True})
    calls: list[str] = []
    monkeypatch.setattr(
        sup, "rebind_mcp_and_rules", lambda: calls.append("in_process") or {"ok": True, "repos": []}
    )
    monkeypatch.setattr(
        sup,
        "rebind_in_fresh_process",
        lambda **k: calls.append("fresh") or {"ok": True, "repos": [], "fresh_process": True},
    )
    return sup, calls


@pytest.mark.parametrize("swap,expected", [(True, ["fresh"]), (False, ["in_process"])])
def test_upgrade_always_rebinds_without_format_bump(tmp_path, monkeypatch, swap, expected):
    sup, calls = _mock_upgrade(monkeypatch, tmp_path, swap=swap)
    report = sup.run_upgrade(connect=True, skip_package=not swap)
    assert report["ok"] is True, report
    assert calls == expected
    assert not report["rebind"].get("skipped")


def test_upgrade_fails_when_the_swap_leaves_the_old_version(tmp_path, monkeypatch):
    from pipeline import upgrade

    sup, calls = _mock_upgrade(monkeypatch, tmp_path, swap=True)
    monkeypatch.setattr(
        upgrade,
        "check_pypi_version",
        lambda force=False, timeout=5.0: {"current": "0.3.6", "latest": "0.3.7", "update_available": True},
    )
    report = sup.run_upgrade(connect=True)
    assert report["ok"] is False, report
    assert report["error"] == "package_not_updated"
    assert "upgrade" in report["hint"]
    assert "fresh" not in calls


def test_swap_command_pins_target_and_refreshes_index():
    from pipeline.upgrade_platform import package_swap_commands

    (cmd,) = package_swap_commands(target_version="0.3.170")
    assert "scubiee==0.3.170" in cmd
    assert cmd[cmd.index("--refresh-package") + 1] == "scubiee"
    (bare,) = package_swap_commands()
    assert "scubiee" in bare and not any(a.startswith("scubiee==") for a in bare)


def test_upgrade_no_connect_skips_rebind(tmp_path, monkeypatch):
    sup, calls = _mock_upgrade(monkeypatch, tmp_path, swap=False)
    report = sup.run_upgrade(connect=False, skip_package=True)
    assert calls == []
    assert report["rebind"]["reason"] == "connect disabled"
