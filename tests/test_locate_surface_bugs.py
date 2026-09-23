"""Regressions for four defects found by the with/without-Scubiee retrieval A/B.

Each test pins a failure that was observed in a real agent transcript, not a
hypothetical: the agent either got an error mid-ladder or got a worse answer
from the CLI than the MCP surface gave for the same question.
"""

from __future__ import annotations

import json

import pytest

from pipeline.context_agent import tools as ca_tools
from pipeline.context_trace import rank_soft_map_cards
from pipeline.locate_cli import emit_cli_json


class _FakeClient:
    """Engine client that refuses the first N calls, as a retiring daemon does."""

    def __init__(self, refusals: int) -> None:
        self.refusals = refusals
        self.calls = 0

    def _maybe_refuse(self) -> dict | None:
        self.calls += 1
        if self.calls <= self.refusals:
            return {
                "ok": False,
                "error": (
                    "Scubiee unreachable at http://127.0.0.1:8765: [WinError 10061] "
                    "No connection could be made because the target machine actively refused it"
                ),
                "should_retry": True,
            }
        return None

    def search(self, query, top_k=6, path=None):  # noqa: ANN001, ARG002
        refused = self._maybe_refuse()
        if refused:
            return refused
        return {"ok": True, "hits": [{"file": "packages/pipeline/embedder.py", "score": 1.0}]}

    def grep(self, pattern, glob="**/*", max_hits=200, path=None):  # noqa: ANN001, ARG002
        refused = self._maybe_refuse()
        if refused:
            return refused
        return {"ok": True, "hits": [{"file": "packages/pipeline/embedder.py", "line": 3}]}


@pytest.fixture
def fake_engine(monkeypatch):
    """Install a fake client and count how often the daemon is (re-)ensured."""
    state = {"ensured": 0, "client": None}

    def _install(refusals: int) -> _FakeClient:
        client = _FakeClient(refusals)
        state["client"] = client

        def _client(repo=None):  # noqa: ANN001, ARG001
            state["ensured"] += 1
            return client

        monkeypatch.setattr(ca_tools, "_client", _client)
        return client

    state["install"] = _install
    return state


def test_search_recovers_when_daemon_retires_mid_flight(fake_engine, tmp_path):
    """ensure_daemon proves liveness, then the idle sweeper retires the engine.

    The agent used to receive "Scubiee unreachable" and fall back to native
    grep on a perfectly healthy install.
    """
    fake_engine["install"](refusals=1)

    out = ca_tools.tool_search_code(tmp_path, "embedding cache model fingerprint", top_k=5)

    assert out["ok"] is True, out
    assert out["hits"], "recovered call must still return hits"
    assert out.get("engine_restarted") is True
    assert fake_engine["ensured"] == 2, "second attempt must rebuild the client to restart the daemon"


def test_grep_recovers_when_daemon_retires_mid_flight(fake_engine, tmp_path):
    fake_engine["install"](refusals=1)

    out = ca_tools.tool_grep_code(tmp_path, "save_cache_npz")

    assert out["ok"] is True, out
    assert fake_engine["ensured"] == 2


def test_unreachable_engine_still_reports_failure(fake_engine, tmp_path):
    """A genuinely down engine must surface the error, not retry forever."""
    fake_engine["install"](refusals=99)

    out = ca_tools.tool_search_code(tmp_path, "anything", top_k=5)

    assert out["ok"] is False
    assert "unreachable" in str(out.get("error", "")).lower()
    assert fake_engine["ensured"] == 2, "bounded retries"


def test_healthy_engine_is_not_restarted(fake_engine, tmp_path):
    fake_engine["install"](refusals=0)

    out = ca_tools.tool_search_code(tmp_path, "anything", top_k=5)

    assert out["ok"] is True
    assert "engine_restarted" not in out
    assert fake_engine["ensured"] == 1, "no extra daemon churn on the happy path"


# --- expand_context accepting pack_context's seed vocabulary -----------------


def _resolve(**kwargs):
    from pipeline.mcp_locate import _resolve_expand_node

    return _resolve_expand_node(
        kwargs.get("node", ""),
        kwargs.get("seed_file", ""),
        kwargs.get("seed_symbol", ""),
        kwargs.get("prior"),
    )


def test_expand_node_accepts_explicit_node():
    assert _resolve(node="packages/pipeline/embedder.py::Embedder._load_cache") == (
        "packages/pipeline/embedder.py::Embedder._load_cache"
    )


def test_expand_node_accepts_pack_seed_vocabulary():
    """The exact call that failed validation mid-ladder in the A/B transcript."""
    assert _resolve(seed_file="packages/pipeline/embedder.py", seed_symbol="_load_cache") == (
        "packages/pipeline/embedder.py::_load_cache"
    )


def test_expand_node_accepts_seed_file_alone():
    assert _resolve(seed_file="packages/pipeline/embedder.py") == "packages/pipeline/embedder.py"


def test_expand_node_normalises_windows_separators():
    assert _resolve(seed_file="packages\\pipeline\\embedder.py", seed_symbol="f") == (
        "packages/pipeline/embedder.py::f"
    )


def test_expand_node_falls_back_to_hottest_trace_card():
    prior = {
        "cards": [
            {"id": "packages/pipeline/a.py::cold_one", "heat": "cold"},
            {"id": "packages/pipeline/b.py::hot_one", "heat": "hot"},
        ]
    }
    assert _resolve(prior=prior) == "packages/pipeline/b.py::hot_one"


def test_expand_node_builds_id_from_file_and_symbol_card():
    prior = {"cards": [{"file": "packages/pipeline/c.py", "symbol": "sym", "heat": "hot"}]}
    assert _resolve(prior=prior) == "packages/pipeline/c.py::sym"


def test_expand_node_empty_when_nothing_to_go_on():
    assert _resolve() == ""
    assert _resolve(prior={"cards": []}) == ""


# --- CLI map must rank like the MCP surface ---------------------------------


def test_cli_ranking_floats_package_defs_above_scripts_and_tests():
    """Observed live: truth ranked 6th behind a script, tests and docs.

    The CLI skipped the shared re-rank the MCP surface applies, so the two
    surfaces answered the same question differently.
    """
    cards = [
        {"file": "scripts/e2e_mcp_idle_reconnect.py", "symbol": "main", "score": 4.47, "kind": "chunk"},
        {"file": "packages/pipeline/ce_service.py", "symbol": "shutdown", "score": 4.44, "kind": "function"},
        {"file": "tests/test_idle_shutdown_reliability.py", "symbol": "", "score": 4.40, "kind": "chunk"},
        {"file": "docs/session-handoff.md", "symbol": "", "score": 4.30, "kind": "chunk"},
        {
            "file": "packages/pipeline/lifecycle_runtime.py",
            "symbol": "apply_idle_policy",
            "score": 3.48,
            "kind": "function",
        },
    ]

    ranked = rank_soft_map_cards(cards)
    order = [c["file"] for c in ranked]

    assert order[0].startswith("packages/"), order
    assert order.index("packages/pipeline/lifecycle_runtime.py") < order.index(
        "scripts/e2e_mcp_idle_reconnect.py"
    )
    assert order.index("packages/pipeline/lifecycle_runtime.py") < order.index(
        "tests/test_idle_shutdown_reliability.py"
    )
    # scripts/ get a heavier path penalty than tests/docs, so they may sink last.
    assert order[-1].startswith(("tests/", "docs/", "scripts/")), order
    assert all(not f.startswith("packages/") for f in order[-3:]), order
    assert [c["rank"] for c in ranked] == [1, 2, 3, 4, 5]


def test_cli_map_applies_the_shared_ranker():
    """Guard the wiring, not just the ranker: cli_map must call it."""
    import inspect

    from pipeline import locate_cli

    src = inspect.getsource(locate_cli.cli_map)
    assert "rank_soft_map_cards(cards)" in src


# --- CLI JSON must survive a cp1252 console ---------------------------------


class _Cp1252Stdout:
    """Stand-in for a default Windows console that cannot encode em-dashes."""

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def write(self, text: str) -> int:
        text.encode("cp1252")  # raises UnicodeEncodeError exactly as the console does
        self.chunks.append(text)
        return len(text)

    def flush(self) -> None:  # pragma: no cover - nothing buffered
        return None


def test_emit_cli_json_survives_non_ascii_on_cp1252_console(monkeypatch, capsys):
    """`scubiee map` crashed outright because our own hint text has an em-dash."""
    monkeypatch.delenv("CTX_CLI_FULL", raising=False)
    payload = {
        "ok": True,
        "tool": "map",
        "read": {"how": "Native-Read loc spans for top ~5 — file:start-end only."},
    }

    stdout = _Cp1252Stdout()
    monkeypatch.setattr("sys.stdout", stdout)
    # full=True keeps the hint text; the slim view drops it and would never
    # reach the encoder that crashed.
    emit_cli_json(payload, full=True)
    monkeypatch.undo()

    printed = "".join(stdout.chunks)
    assert printed.strip(), "must print something rather than raise"
    decoded = json.loads(printed)
    assert decoded["ok"] is True
    assert "—" in decoded["read"]["how"], "escaping must stay lossless for JSON consumers"
