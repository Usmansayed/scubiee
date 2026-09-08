"""Tests for embed query vs intent query split (seed code anchors)."""

from __future__ import annotations

from types import SimpleNamespace

from trace_lab.system_trace import _embed_query, _user_query


def test_user_query_strips_seed_anchors() -> None:
    case = SimpleNamespace(
        query=(
            "authenticate jwt verify user resolve — ignore log\n\n"
            "## Seed code anchors\n"
            "### Seed 1: app/a.py::authenticate\n"
            "```\ndef authenticate():\n    log('ok')\n```\n"
        )
    )
    uq = _user_query(case)  # type: ignore[arg-type]
    assert "Seed code anchors" not in uq
    assert "authenticate jwt verify" in uq
    assert "log('ok')" not in uq


def test_embed_query_keeps_seed_anchors() -> None:
    case = SimpleNamespace(
        query=(
            "authenticate jwt verify\n\n"
            "## Seed code anchors\n"
            "### Seed 1: a.py::authenticate\n"
            "```\ndef authenticate():\n    return 1\n```\n"
        )
    )
    eq = _embed_query(case)  # type: ignore[arg-type]
    assert "## Seed code anchors" in eq
    assert "def authenticate" in eq
