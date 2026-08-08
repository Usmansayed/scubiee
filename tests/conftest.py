"""Shared pytest fixtures.

Unit tests must be deterministic regardless of how the process was launched. The
SDK trial harness runs the workspace's baseline pytest with ``CTX_MCP_SURFACE``
set in the environment (to A/B the ``read`` vs ``graph`` MCP surfaces), which
would otherwise leak into and flip surface-specific assertions. Neutralise it by
default; tests that want a specific surface opt in via ``monkeypatch.setenv``.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _neutral_mcp_surface(monkeypatch):
    monkeypatch.delenv("CTX_MCP_SURFACE", raising=False)
    yield
