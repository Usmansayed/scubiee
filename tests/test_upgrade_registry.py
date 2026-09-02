"""Tests for declarative upgrade release registry."""

from __future__ import annotations

import pytest

from pipeline import upgrade_releases as _load  # noqa: F401
from pipeline.upgrade_manifest import build_diff_plan
from pipeline.upgrade_registry import (
    compose_upgrade,
    disposition_to_action,
    list_releases,
    migrate_component,
    release,
    register_release,
    releases_between,
    update_component,
    ReleaseSpec,
    StepSpec,
)


def test_releases_registered():
    versions = [r.version for r in list_releases()]
    assert "0.2.18" in versions
    assert "0.3.7" in versions
    assert "0.3.10" in versions
    assert "0.3.13" in versions
    assert "0.3.14" in versions


def test_releases_between_range():
    path = releases_between("0.3.6", "0.3.10")
    assert [r.version for r in path] == ["0.3.7", "0.3.10"]


def test_compose_merges_strongest_disposition():
    register_release(
        ReleaseSpec(
            version="9.9.1",
            steps={
                "mcp_pins": update_component("mcp_pins", reason="soft update"),
            },
        )
    )
    register_release(
        ReleaseSpec(
            version="9.9.2",
            steps={
                "mcp_pins": migrate_component("mcp_pins", reason="should not win"),
            },
        )
    )
    composed = compose_upgrade("9.9.0", "9.9.2")
    assert composed.steps["mcp_pins"].disposition == "migrate"


def test_disposition_to_action_mapping():
    assert disposition_to_action(
        "mcp_pins", update_component("mcp_pins", reason="x")
    ).action == "rewrite"
    assert disposition_to_action(
        "embeddings", StepSpec("embeddings", "clear", "x", destructive=True)
    ).action == "rebuild"
    assert disposition_to_action(
        "index_schema", migrate_component("index_schema", reason="x")
    ).action == "migrate"


def test_plan_includes_release_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    plan = build_diff_plan(
        from_version="0.3.9",
        to_version="0.3.10",
        skip_package=False,
    )
    d = plan.to_dict()
    assert "0.3.10" in d.get("release_path", [])
    mcp = plan.action_for("mcp_pins")
    assert mcp is not None
    assert mcp.action == "rewrite"


def test_plan_preserves_when_no_release_and_current(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    plan = build_diff_plan(
        from_version="0.3.10",
        to_version="0.3.10",
        skip_package=True,
    )
    from pipeline.upgrade_manifest import MCP_PIN_FORMAT, record_component_applied

    record_component_applied("mcp_pins", version=f"0.3.10:v{MCP_PIN_FORMAT}", detail="test")
    record_component_applied("gate_rules", version="0.3.10:v1", detail="test")
    record_component_applied("home_layout", version="1", detail="test")
    plan = build_diff_plan(
        from_version="0.3.10",
        to_version="0.3.10",
        skip_package=True,
    )
    assert plan.action_for("mcp_pins").action == "skip"  # type: ignore[union-attr]
    assert plan.action_for("embeddings").action == "skip"  # type: ignore[union-attr]


@release("9.8.1", notes="decorator test")
class _DecoratedRelease:
    gate_rules = update_component("gate_rules", reason="decorator ok")


def test_release_decorator_registers():
    assert any(r.version == "9.8.1" for r in list_releases())
