"""CLI UX hardening — regression tests for the command-combination findings.

Covers:
- #1 systemic: main() dispatch never dumps a raw traceback; a raising command
  becomes a clean error + exit 1 (and CTX_DEBUG re-raises for debugging).
- #2/#3: `map` with the engine down prints a friendly message and exits 1
  (no raw RuntimeError/WinError leak, no exit-0-on-failure, no hang).
- #4: the `map` CLI docstring reflects the shipped two-config surface.
"""

from __future__ import annotations

import argparse

import pytest

from pipeline import __main__ as cli


# ---------------------------------------------------------------------------
# #1 — top-level safety net: no raw tracebacks
# ---------------------------------------------------------------------------

def test_dispatch_catches_raising_command(monkeypatch, capsys):
    """A cmd_* that raises must become a clean error + exit 1, never a raw
    Python traceback leaking to the user (non-TTY → structured JSON)."""
    def boom(_args):
        raise FileNotFoundError("not a directory: C:/nope/deep/xyz")

    monkeypatch.setattr(cli, "cmd_gate", boom)
    # non-interactive so the JSON branch runs
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)

    rc = cli.main(["gate", "C:/nope/deep/xyz"])
    out = capsys.readouterr()
    assert rc == 1
    # friendly one-liner on stderr, no "Traceback (most recent call last)"
    assert "Traceback (most recent call last)" not in (out.out + out.err)
    assert "gate failed" in out.err
    import json

    payload = json.loads(out.out)
    assert payload["ok"] is False
    assert "not a directory" in payload["error"]


def test_dispatch_ctx_debug_reraises(monkeypatch):
    """CTX_DEBUG=1 opts into the full traceback (re-raise) for debugging."""
    def boom(_args):
        raise RuntimeError("boom-for-debug")

    monkeypatch.setattr(cli, "cmd_gate", boom)
    monkeypatch.setenv("CTX_DEBUG", "1")
    with pytest.raises(RuntimeError, match="boom-for-debug"):
        cli.main(["gate", "."])


def test_dispatch_keyboardinterrupt_is_clean(monkeypatch, capsys):
    def interrupt(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_gate", interrupt)
    rc = cli.main(["gate", "."])
    assert rc == 130
    assert "Cancelled" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# #2 / #3 — map CLI when the engine is down
# ---------------------------------------------------------------------------

def _map_args(**over):
    base = dict(config="find", query="where is auth", names=None, anchor=None,
                targets=None, k=None, path=".", cmd="map", func=cli.cmd_map)
    base.update(over)
    return argparse.Namespace(**base)


def test_map_engine_down_friendly_message_and_exit1(monkeypatch, capsys):
    """Engine down → friendly 'engine not running' message + exit 1, NOT a raw
    RuntimeError/URLError/WinError leak, NOT exit 0, and no engine call (no hang)."""
    monkeypatch.setattr("pipeline.client.EngineClient.healthy", lambda self: False)

    called = {"tool_map": False}

    def _should_not_run(_call):
        called["tool_map"] = True
        return "unexpected"

    monkeypatch.setattr("pipeline.map_v3_server.tool_map", _should_not_run)

    rc = cli.cmd_map(_map_args())
    out = capsys.readouterr()
    assert rc == 1
    assert "engine not running" in out.err.lower()
    assert "scubiee engine start" in out.err
    # no raw internals leaked
    for leak in ("RuntimeError", "URLError", "WinError", "Traceback"):
        assert leak not in (out.out + out.err)
    # must NOT have called the engine path (prevents the hang)
    assert called["tool_map"] is False


def test_map_exit_code_failure_vs_empty(monkeypatch):
    """Exit non-zero on an operational failure; exit 0 on a valid empty result."""
    monkeypatch.setattr("pipeline.client.EngineClient.healthy", lambda self: True)

    cases = {
        "error: find needs query": 1,
        "map find failed: RuntimeError: engine /v1/search failed": 1,
        "focus: could not resolve foo": 1,
        "find: no confident match in scope=code": 0,   # valid empty, not a failure
        "find: 3 results  confidence: high": 0,
        "focus some_symbol  (lines 1-9)": 0,
    }
    for text, expected_rc in cases.items():
        monkeypatch.setattr("pipeline.map_v3_server.tool_map", lambda _c, _t=text: _t)
        rc = cli.cmd_map(_map_args())
        assert rc == expected_rc, f"{text!r} -> rc={rc}, expected {expected_rc}"


# ---------------------------------------------------------------------------
# #4 — docstring reflects the two-config surface
# ---------------------------------------------------------------------------

def test_map_docstring_is_two_configs():
    doc = cli.cmd_map.__doc__ or ""
    assert "find | focus" in doc
    assert "related" not in doc and "graph" not in doc
