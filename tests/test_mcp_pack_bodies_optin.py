"""MCP pack-body opt-in: flag / CTX_MCP_PACK_BODIES must reach run_pack_context."""
from __future__ import annotations

import inspect

import pytest


def test_resolve_pack_bodies_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_PACK_BODIES", raising=False)
    from pipeline.mcp_locate import _resolve_pack_bodies

    assert _resolve_pack_bodies(0) is False
    assert _resolve_pack_bodies(None) is False


def test_resolve_pack_bodies_env_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_PACK_BODIES", "1")
    from pipeline.mcp_locate import _resolve_pack_bodies

    assert _resolve_pack_bodies(0) is True
    assert _resolve_pack_bodies(None) is True


def test_resolve_pack_bodies_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_PACK_BODIES", raising=False)
    from pipeline.mcp_locate import _resolve_pack_bodies

    assert _resolve_pack_bodies(1) is True
    assert _resolve_pack_bodies(True) is True


def test_pack_impl_wires_want_bodies_not_hardcoded_false() -> None:
    """Regression: ship MCP pack must pass resolved want_bodies into run_pack_context."""
    from pipeline import mcp_locate as ml

    src = inspect.getsource(ml)
    assert "want_bodies = _resolve_pack_bodies(include_bodies)" in src
    assert "include_bodies=want_bodies" in src
    # The old bug: always False at the run_pack_context call site.
    assert "include_bodies=False,\n" not in src
