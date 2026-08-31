"""Unit tests for upgrade DiffPlan + supervisor check-only path."""

from __future__ import annotations

from pipeline.upgrade_manifest import ComponentAction, DiffPlan, build_diff_plan
from pipeline.upgrade_platform import platform_name


def test_platform_name_known():
    assert platform_name() in {"windows", "macos", "linux"}


def test_diff_plan_skip_package_when_same_version(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    plan = build_diff_plan(
        from_version="0.3.6",
        to_version="0.3.6",
        skip_package=True,
    )
    assert isinstance(plan, DiffPlan)
    pkg = plan.action_for("package")
    assert pkg is not None
    assert pkg.action == "skip"
    daemon = plan.action_for("daemon")
    assert daemon is not None
    assert daemon.action == "restart"


def test_diff_plan_swap_when_versions_differ(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    plan = build_diff_plan(
        from_version="0.3.5",
        to_version="0.3.6",
        skip_package=False,
    )
    pkg = plan.action_for("package")
    assert pkg is not None
    assert pkg.action == "swap"
    emb = plan.action_for("embeddings")
    assert emb is not None
    assert emb.action == "skip"


def test_diff_plan_force_reindex(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    plan = build_diff_plan(
        from_version="0.3.7",
        to_version="0.3.7",
        skip_package=True,
        force_reindex=True,
    )
    emb = plan.action_for("embeddings")
    assert emb is not None
    assert emb.action == "rebuild"
    assert emb.destructive is True
    assert plan.to_dict()["warnings"]


def test_diff_plan_rewrites_mcp_when_pin_format_stale(tmp_path, monkeypatch):
    """v1 pins must rewrite when MCP_PIN_FORMAT bumps to v2 (bridge migration)."""
    from pipeline.upgrade_manifest import MCP_PIN_FORMAT, record_component_applied

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    stale_fmt = max(1, MCP_PIN_FORMAT - 1)
    record_component_applied("mcp_pins", version=f"0.3.7:v{stale_fmt}", detail="legacy")
    plan = build_diff_plan(
        from_version="0.3.7",
        to_version="0.3.7",
        skip_package=True,
    )
    mcp = plan.action_for("mcp_pins")
    assert mcp is not None
    assert mcp.action == "rewrite"


def test_do_upgrade_check_only(tmp_path, monkeypatch):
    from pipeline import upgrade
    import pipeline.upgrade_supervisor as sup

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

    def fake_plan(**kwargs):
        return DiffPlan(
            from_version=kwargs["from_version"],
            to_version=kwargs["to_version"],
            actions=[
                ComponentAction("package", "skip", "same"),
                ComponentAction("daemon", "restart", "ensure"),
            ],
        )

    monkeypatch.setattr(sup, "build_diff_plan", fake_plan)

    report = upgrade.do_upgrade(check_only=True, skip_package=True)
    assert report["ok"] is True
    assert report.get("check_only") is True
    assert "plan" in report
    assert "quiesce" not in report["phases"]
