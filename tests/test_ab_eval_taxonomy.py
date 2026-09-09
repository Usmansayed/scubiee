"""Unit tests for never-fail harness taxonomy (no live Kiro/MCP)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kiro_mcp_ab_dev_eval.py"


def _load():
    spec = importlib.util.spec_from_file_location("kiro_mcp_ab_dev_eval", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_mod = _load()
_heatmap_discipline = _mod._heatmap_discipline
_parse_cli_locate_from_shell = _mod._parse_cli_locate_from_shell


def test_uncallable_escape_not_scored_as_skip_pack():
    text = (
        '{"warm_state": "error", "should_retry_status": false}\n'
        "Running tool map ... (from mcp server: scubiee)\n"
        "proceed with native grep since MCP is fully uncallable\n"
        "Reading file: foo.py all lines\n"
        "Reading file: bar.py all lines\n"
    )
    tools = {"mcp_scubiee_tools": ["map"], "cli_locate_count": 0}
    r = _heatmap_discipline(text, tools)
    assert r["ladder_label"] == "uncallable_fallback"
    assert r["ok"] is True


def test_map_without_pack_with_healthy_engine_is_skip_pack_violation():
    text = "Running tool map ... (from mcp server: scubiee)\n"
    tools = {"mcp_scubiee_tools": ["map"], "cli_locate_count": 0}
    r = _heatmap_discipline(text, tools)
    assert r["ladder_label"] == "skip_pack_violation"
    assert r["ok"] is False


def test_findstr_search_for_scubiee_map_is_not_a_cli_leak():
    text = (
        "I will run the following command: findstr /s scubiee map "
        "(using tool: shell)\n"
    )
    assert _parse_cli_locate_from_shell(text) == []


def test_real_shell_scubiee_map_is_a_cli_leak():
    text = 'Executing command: scubiee map "foo" (using tool: shell)\n'
    assert _parse_cli_locate_from_shell(text) == ["map"]
