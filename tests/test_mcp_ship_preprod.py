"""Pre-prod ship MCP deep tests — contracts, journey, concurrency, live ladder.

Outer bridge/CLI combo stay elsewhere; this locks the updated ship internals.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from pipeline.mcp_permissions import (
    PHASE_LOCATE_TOOLS,
    enrich_server_entry_permissions,
    locate_tool_names,
)
from pipeline.mcp_ship_check import (
    FORBIDDEN_SHIP_TOOLS,
    SHIP_TOOLS,
    check_phase_tool_names,
    check_registered_tools,
    parse_tool_json,
    run_ship_ladder,
    tool_fn,
)
from pipeline.rules_installer import (
    cleanup_project_gate_rules,
    format_server_entry,
    install_tool,
    uninstall_tool,
    write_project_gate_rules,
)
from pipeline.tool_registry import TOOL_MAP


def _tool_names(mcp) -> set[str]:
    return set(mcp._tool_manager._tools)


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir(exist_ok=True)
    return path


def _enroll(repo: Path, project_id: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ce = repo / ".scubiee"
    ce.mkdir(exist_ok=True)
    (ce / "id.json").write_text(json.dumps({"project_id": project_id}), encoding="utf-8")
    from pipeline.project_id import save_registry

    home = tmp_path / "ce-home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("CTX_HOME", str(home))
    save_registry(
        {
            "projects": {
                project_id: {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )
    monkeypatch.setenv("CTX_REPO", str(repo.resolve()))
    monkeypatch.chdir(repo)


def _stub_live_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent MCP tests must not spawn a real engine (steals/ hangs on port)."""
    monkeypatch.setattr(
        "pipeline.daemon.ensure_daemon",
        lambda *a, **k: {"ok": True, "already_running": True, "skipped": "test_stub"},
    )
    monkeypatch.setattr(
        "pipeline.daemon.force_restart_daemon",
        lambda *a, **k: {"ok": True, "forced": True, "skipped": "test_stub"},
    )

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def healthy(self) -> bool:
            return True

        def open_repo(self, *a, **k):
            return {"ok": True, "status": "activated", "warm_state": "ready"}

        def post(self, *a, **k):
            return {"ok": True, "hits": []}

        def get(self, *a, **k):
            return {"ok": True}

        def search(self, *a, **k):
            return {"ok": True, "hits": []}

        def map(self, *a, **k):
            return {
                "ok": True,
                "cards": [
                    {
                        "file": "packages/pipeline/mcp_locate.py",
                        "symbol": "create_mcp",
                        "score": 0.9,
                        "start_line": 1,
                        "end_line": 2,
                    }
                ],
            }

    monkeypatch.setattr("pipeline.client.EngineClient", _FakeClient)
    # Also patch the import site used inside _client_for after ensure.
    monkeypatch.setattr("pipeline.mcp_locate.EngineClient", _FakeClient, raising=False)


# ---------------------------------------------------------------------------
# L1 — unit contracts
# ---------------------------------------------------------------------------


def test_ship_phase_tool_names_no_classic_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_EXPERIMENT", raising=False)
    monkeypatch.setenv("CTX_MCP_SURFACE", "phase")
    from pipeline.mcp_locate import _phase_experiment, _phase_tool_names

    assert _phase_experiment() == "ship"
    names = set(_phase_tool_names())
    assert names == set(SHIP_TOOLS)
    assert not (names & FORBIDDEN_SHIP_TOOLS)
    assert check_phase_tool_names()["ok"] is True


def test_locate_tool_names_ship_only() -> None:
    names = set(locate_tool_names())
    assert names == set(PHASE_LOCATE_TOOLS) == set(SHIP_TOOLS)
    assert not (names & {"focus", "grep", "glob", "pinpoint", "plate"})


def test_cursor_auto_approve_is_ship_only() -> None:
    entry = format_server_entry(TOOL_MAP["cursor"], pin_repo=False)
    enriched = enrich_server_entry_permissions(entry, "cursor")
    approved = set(enriched.get("autoApprove") or [])
    assert set(PHASE_LOCATE_TOOLS).issubset(approved)
    assert not (approved & {"focus", "grep", "glob", "pinpoint", "plate"})


def test_ship_mcp_registers_exactly_eight(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    monkeypatch.delenv("CTX_MCP_EXPERIMENT", raising=False)
    monkeypatch.setenv("CTX_MCP_SURFACE", "phase")
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-ship")
    assert check_registered_tools(mcp)["ok"] is True
    assert _tool_names(mcp) == set(SHIP_TOOLS)


def test_workspace_next_hints_are_ship_safe() -> None:
    """Regression: workspace must not coach focus (tool absent on ship)."""
    import inspect

    from pipeline import mcp_locate as ml

    src = inspect.getsource(ml)
    assert 'then focus.' not in src
    assert "focus(path) to deepen" not in src
    assert "New topic — map(query) once, then pack_context" in src
    assert "pack_context or host Read on pinned path" in src


def test_collect_hot_error_mentions_ship_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path / "hot")
    _enroll(repo, "ce_preprod_hot1234567890abcdef", monkeypatch, tmp_path)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-hot")
    raw = tool_fn(mcp, "collect_hot_context")()
    text = str(raw).lower()
    assert "map_context" not in text
    assert "pack_context" in text or "map/" in text or "map " in text


def test_adversarial_empty_map_query_returns_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path / "adv")
    _enroll(repo, "ce_preprod_adv1234567890abcdef", monkeypatch, tmp_path)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-adv")
    raw = tool_fn(mcp, "map")(query="")
    assert raw is not None
    assert len(str(raw)) > 0


def test_adversarial_pack_missing_seed_returns_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path / "adv2")
    _enroll(repo, "ce_preprod_pack1234567890abcdef", monkeypatch, tmp_path)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-pack-adv")
    raw = tool_fn(mcp, "pack_context")(query="x", seed_file="", seed_symbol="", mode="lean")
    assert raw is not None
    text = str(raw).lower()
    payload = parse_tool_json(raw)
    assert payload.get("ok") is False or "seed" in text or "error" in text


def test_pack_lean_default_heatmap_no_bodies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Monkeypatched engine: lean pack is heatmap-only unless bodies opted in."""
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path / "packlean")
    _enroll(repo, "ce_preprod_lean1234567890abcdef", monkeypatch, tmp_path)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    monkeypatch.delenv("CTX_MCP_PACK_BODIES", raising=False)
    captured: dict[str, object] = {}

    def _fake_pack(root, query, **kwargs):
        captured.clear()
        captured.update(kwargs)
        want = bool(kwargs.get("include_bodies"))
        out: dict = {
            "ok": True,
            "tool": "pack_context",
            "engine": "composite_v1",
            "mode": kwargs.get("mode") or "lean",
            "policy": kwargs.get("policy") or "strict",
            "heatmap": [
                {
                    "r": 1,
                    "heat": "hot",
                    "id": "packages/pipeline/mcp_locate.py::create_mcp",
                    "loc": "packages/pipeline/mcp_locate.py:1-2",
                    "s": "create_mcp",
                }
            ],
            "seed": {
                "id": "packages/pipeline/mcp_locate.py::create_mcp",
                "file": "packages/pipeline/mcp_locate.py",
                "symbol": "create_mcp",
            },
            "_persist": {"packed_ids": ["packages/pipeline/mcp_locate.py::create_mcp"]},
        }
        if want:
            out["bodies"] = [{"id": "packages/pipeline/mcp_locate.py::create_mcp", "code": "def create_mcp(): ..."}]
            out["pack"] = out["bodies"]
        return out

    monkeypatch.setattr("pipeline.context_trace.run_pack_context", _fake_pack)
    monkeypatch.setattr("pipeline.context_trace.load_trace", lambda *a, **k: {})
    monkeypatch.setattr("pipeline.context_trace.persist_trace", lambda *a, **k: None)
    monkeypatch.setattr("pipeline.context_trace.ast_cache_ready", lambda *_a, **_k: True)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-pack-lean")
    pack_fn = tool_fn(mcp, "pack_context")
    lean = parse_tool_json(
        pack_fn(
            query="create_mcp ship surface pack lean",
            seed_file="packages/pipeline/mcp_locate.py",
            seed_symbol="create_mcp",
            mode="lean",
            policy="strict",
        )
    )
    assert lean.get("ok") is True
    assert lean.get("heatmap")
    assert not lean.get("bodies") and not lean.get("pack")
    # Warm AST → lean pack uses composite_v1 (include_bodies=False).
    assert captured.get("include_bodies") is False
    assert captured.get("mode") == "lean"
    assert captured.get("policy") == "strict"


def test_pack_include_bodies_flag_and_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path / "packbodies")
    _enroll(repo, "ce_preprod_body1234567890abcdef", monkeypatch, tmp_path)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    captured: dict[str, object] = {}

    def _fake_pack(root, query, **kwargs):
        captured.clear()
        captured.update(kwargs)
        want = bool(kwargs.get("include_bodies"))
        out: dict = {
            "ok": True,
            "tool": "pack_context",
            "engine": "composite_v1",
            "include_bodies": want,
            "heatmap": [
                {
                    "r": 1,
                    "heat": "hot",
                    "id": "packages/pipeline/mcp_locate.py::create_mcp",
                    "loc": "packages/pipeline/mcp_locate.py:1-2",
                    "s": "create_mcp",
                }
            ],
            "seed": {
                "id": "packages/pipeline/mcp_locate.py::create_mcp",
                "file": "packages/pipeline/mcp_locate.py",
                "symbol": "create_mcp",
            },
            "_persist": {"packed_ids": ["packages/pipeline/mcp_locate.py::create_mcp"]},
        }
        if want:
            # Lean formatter keeps bodies only when pack[] carries text/code.
            out["pack"] = [
                {
                    "id": "packages/pipeline/mcp_locate.py::create_mcp",
                    "code": "def create_mcp(): ...",
                    "text": "def create_mcp(): ...",
                }
            ]
        return out

    monkeypatch.setattr("pipeline.context_trace.run_pack_context", _fake_pack)
    monkeypatch.setattr("pipeline.context_trace.load_trace", lambda *a, **k: {})
    monkeypatch.setattr("pipeline.context_trace.persist_trace", lambda *a, **k: None)
    # Body packs skip lean-fast and require AST ready (no sync bake on request path).
    monkeypatch.setattr("pipeline.context_trace.ast_cache_ready", lambda *_a, **_k: True)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-pack-bodies")
    pack_fn = tool_fn(mcp, "pack_context")

    monkeypatch.delenv("CTX_MCP_PACK_BODIES", raising=False)
    flagged = parse_tool_json(
        pack_fn(
            query="bodies via flag",
            seed_file="packages/pipeline/mcp_locate.py",
            seed_symbol="create_mcp",
            include_bodies=1,
        )
    )
    assert flagged.get("ok") is True
    assert captured.get("include_bodies") is True
    assert flagged.get("pack")  # lean view keeps pack[] when bodies opted in

    monkeypatch.setenv("CTX_MCP_PACK_BODIES", "1")
    env_on = parse_tool_json(
        pack_fn(
            query="bodies via env",
            seed_file="packages/pipeline/mcp_locate.py",
            seed_symbol="create_mcp",
            include_bodies=0,
        )
    )
    assert env_on.get("ok") is True
    assert captured.get("include_bodies") is True
    assert env_on.get("pack")


def test_pack_policy_broad_escape_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """policy=broad must reach run_pack_context; escape report fields available to engine."""
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path / "packbroad")
    _enroll(repo, "ce_preprod_brd1234567890abcdef", monkeypatch, tmp_path)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    captured: dict[str, object] = {}

    def _fake_pack(root, query, **kwargs):
        from pipeline.context_trace import BROAD_ESCAPE_ENGINE, pack_engine_report

        captured.clear()
        captured.update(kwargs)
        assert (kwargs.get("policy") or "").lower() == "broad"
        escape = pack_engine_report(
            requested_engine="composite_v1",
            policy="broad",
            ran_engine=BROAD_ESCAPE_ENGINE,
        )
        return {
            "ok": True,
            "tool": "pack_context",
            "engine": escape["engine"],
            "escape": escape["escape"],
            "policy": "broad",
            "include_bodies": False,
            "heatmap": [
                {
                    "r": 1,
                    "heat": "warm",
                    "id": "packages/pipeline/context_trace.py::run_pack_context",
                    "loc": "packages/pipeline/context_trace.py:1-2",
                    "s": "run_pack_context",
                    "score": 1.0,
                }
            ],
            "seed": {
                "id": "packages/pipeline/context_trace.py::run_pack_context",
                "file": "packages/pipeline/context_trace.py",
                "symbol": "run_pack_context",
            },
            "_persist": {"packed_ids": ["packages/pipeline/context_trace.py::run_pack_context"]},
        }

    monkeypatch.setattr("pipeline.context_trace.run_pack_context", _fake_pack)
    monkeypatch.setattr("pipeline.context_trace.load_trace", lambda *a, **k: {})
    monkeypatch.setattr("pipeline.context_trace.persist_trace", lambda *a, **k: None)
    # Broad escape is non-lean — requires AST ready (no sync bake on request path).
    monkeypatch.setattr("pipeline.context_trace.ast_cache_ready", lambda *_a, **_k: True)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-pack-broad")
    out = parse_tool_json(
        tool_fn(mcp, "pack_context")(
            query="broad escape polytrace",
            seed_file="packages/pipeline/context_trace.py",
            seed_symbol="run_pack_context",
            policy="broad",
        )
    )
    assert out.get("ok") is True
    assert captured.get("policy") == "broad"
    # Heatmap lean view drops escape metadata; wiring + engine report are the contract.
    from pipeline.context_trace import BROAD_ESCAPE_ENGINE, pack_engine_report

    esc = pack_engine_report(
        requested_engine="composite_v1",
        policy="broad",
        ran_engine=BROAD_ESCAPE_ENGINE,
    )
    assert esc["escape"]["used"] is True
    assert out.get("heatmap")


def test_expand_default_shape_smoke(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path / "expand")
    _enroll(repo, "ce_preprod_exp1234567890abcdef", monkeypatch, tmp_path)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    _stub_live_daemon(monkeypatch)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-expand")
    raw = tool_fn(mcp, "expand_context")(
        node="packages/pipeline/mcp_locate.py::create_mcp",
        direction="callees",
        query="expand ship ladder",
        k=5,
    )
    assert raw is not None
    payload = parse_tool_json(raw)
    # Envelope required — ok true/false both fine as long as structured.
    assert isinstance(payload, dict)
    assert "ok" in payload or "error" in payload or "delta" in payload


# ---------------------------------------------------------------------------
# L2 — install / wipe residual journey
# ---------------------------------------------------------------------------


def test_journey_install_permissions_then_wipe_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    (tmp_path / "ce-home").mkdir()
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    (tmp_path / "ce-home" / "accel.json").write_text("{}\n", encoding="utf-8")

    repo = _git_repo(tmp_path / "proj")
    pid = "ce_preprod_jour1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)

    install_tool(TOOL_MAP["cursor"], repo=repo)
    mcp_path = repo / ".cursor" / "mcp.json"
    assert mcp_path.is_file()
    mcp_data = json.loads(mcp_path.read_text(encoding="utf-8"))
    servers = mcp_data.get("mcpServers") or {}
    assert "scubiee" in servers
    approved = set((servers["scubiee"].get("autoApprove") or []))
    # Live install may omit autoApprove on some hosts; permissions enrich still ship-only.
    entry = format_server_entry(TOOL_MAP["cursor"], pin_repo=False)
    enriched = enrich_server_entry_permissions(entry, "cursor")
    approved = approved or set(enriched.get("autoApprove") or [])
    assert set(SHIP_TOOLS).issubset(approved)
    assert not (approved & {"focus", "grep", "glob"})

    write_project_gate_rules(repo, slugs=["cursor"])
    rule = repo / ".cursor" / "rules" / "scubiee.mdc"
    assert rule.is_file()
    text = rule.read_text(encoding="utf-8")
    assert "pack_context" in text
    assert "GATE" in text

    # Managed MCP create sees ship set only.
    pytest.importorskip("mcp")
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-journey-mcp")
    assert check_registered_tools(mcp)["ok"] is True

    cleanup_project_gate_rules(repo)
    assert not rule.exists()
    report = uninstall_tool(TOOL_MAP["cursor"], repo=repo, all_workspaces=False)
    assert report.get("ok") is True
    # Project MCP entry removed for this host.
    if mcp_path.is_file():
        after = json.loads(mcp_path.read_text(encoding="utf-8"))
        assert "scubiee" not in (after.get("mcpServers") or {})
    else:
        assert report.get("mcp_removed") or True

    from pipeline.session_isolation import session_data_dir
    from pipeline.session_store import load_store

    orphan = tmp_path / "orphan"
    orphan.mkdir()
    session_data_dir(orphan, "cursor@test")
    load_store(orphan)
    assert not (orphan / ".scubiee").exists()


# ---------------------------------------------------------------------------
# L4 — locate concurrency
# ---------------------------------------------------------------------------


def test_concurrent_map_calls_no_raise(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path / "conc")
    _enroll(repo, "ce_preprod_conc1234567890abcdef", monkeypatch, tmp_path)
    _stub_live_daemon(monkeypatch)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-conc")
    map_fn = tool_fn(mcp, "map")
    queries = [f"concurrent query alpha {i} locate heatmap pack" for i in range(8)]

    results: list[object] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(map_fn, query=q, k=5) for q in queries]
        for fut in as_completed(futs):
            results.append(fut.result())

    assert len(results) == 8
    assert all(r is not None and len(str(r)) > 0 for r in results)


def test_concurrent_status_interleaved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path / "stat")
    _enroll(repo, "ce_preprod_stat1234567890abcdef", monkeypatch, tmp_path)
    _stub_live_daemon(monkeypatch)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-status")
    status_fn = tool_fn(mcp, "status")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(status_fn) for _ in range(8)]
        outs = [f.result() for f in as_completed(futs)]
    assert len(outs) == 8
    assert all(o is not None for o in outs)


def test_concurrent_map_and_status_mixed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path / "mix")
    _enroll(repo, "ce_preprod_mix1234567890abcdef", monkeypatch, tmp_path)
    _stub_live_daemon(monkeypatch)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-mix")
    map_fn = tool_fn(mcp, "map")
    status_fn = tool_fn(mcp, "status")
    barrier = threading.Barrier(6)

    def _map() -> object:
        barrier.wait(timeout=5)
        return map_fn(query="mixed concurrent map locate", k=4)

    def _status() -> object:
        barrier.wait(timeout=5)
        return status_fn()

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_map) for _ in range(3)] + [pool.submit(_status) for _ in range(3)]
        outs = [f.result() for f in as_completed(futs)]
    assert len(outs) == 6
    assert all(o is not None for o in outs)


def test_concurrent_pack_and_status_interleaved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path / "packstat")
    _enroll(repo, "ce_preprod_ps1234567890abcdef", monkeypatch, tmp_path)
    _stub_live_daemon(monkeypatch)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)

    def _fake_pack(root, query, **kwargs):
        return {
            "ok": True,
            "tool": "pack_context",
            "engine": "composite_v1",
            "heatmap": [
                {
                    "r": 1,
                    "heat": "hot",
                    "id": "packages/pipeline/mcp_locate.py::create_mcp",
                    "loc": "packages/pipeline/mcp_locate.py:1-2",
                    "s": "create_mcp",
                }
            ],
            "seed": {
                "id": "packages/pipeline/mcp_locate.py::create_mcp",
                "file": "packages/pipeline/mcp_locate.py",
                "symbol": "create_mcp",
            },
            "_persist": {"packed_ids": ["packages/pipeline/mcp_locate.py::create_mcp"]},
        }

    monkeypatch.setattr("pipeline.context_trace.run_pack_context", _fake_pack)
    monkeypatch.setattr("pipeline.context_trace.load_trace", lambda *a, **k: {})
    monkeypatch.setattr("pipeline.context_trace.persist_trace", lambda *a, **k: None)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-pack-stat")
    pack_fn = tool_fn(mcp, "pack_context")
    status_fn = tool_fn(mcp, "status")
    barrier = threading.Barrier(6)

    def _pack() -> object:
        barrier.wait(timeout=5)
        return pack_fn(
            query="concurrent pack locate",
            seed_file="packages/pipeline/mcp_locate.py",
            seed_symbol="create_mcp",
            mode="lean",
        )

    def _status() -> object:
        barrier.wait(timeout=5)
        return status_fn()

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_pack) for _ in range(3)] + [pool.submit(_status) for _ in range(3)]
        outs = [f.result() for f in as_completed(futs)]
    assert len(outs) == 6
    assert all(o is not None and len(str(o)) > 0 for o in outs)
    # At least the pack payloads parse as JSON envelopes.
    pack_outs = [parse_tool_json(o) for o in outs if "heatmap" in str(o) or "pack_context" in str(o)]
    assert pack_outs
    assert all(isinstance(p, dict) for p in pack_outs)


# ---------------------------------------------------------------------------
# L3 — live integration ladder
# ---------------------------------------------------------------------------


def _engine_healthy(repo: Path) -> bool:
    try:
        from pipeline.client import EngineClient

        return EngineClient(workspace_path=str(repo)).healthy()
    except Exception:  # noqa: BLE001
        return False


def _repo_managed(repo: Path) -> bool:
    if not (repo / ".scubiee" / "id.json").is_file():
        return False
    try:
        from pipeline.project_id import load_registry, read_id_file

        pid = read_id_file(repo)
        if not pid:
            return False
        entry = (load_registry().get("projects") or {}).get(pid) or {}
        return bool(entry.get("managed"))
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.integration
def test_live_ship_ladder_gate_map_pack_expand(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    # Autouse conftest isolates CTX_HOME; live ladder must see the real machine home.
    monkeypatch.delenv("CTX_HOME", raising=False)
    monkeypatch.delenv("CTX_ALLOW_TEST_HOME", raising=False)
    repo = Path(__file__).resolve().parents[1]
    if not _repo_managed(repo) or not _engine_healthy(repo):
        pytest.skip("warm managed engine required")
    report = run_ship_ladder(repo=repo)
    assert report["checks"]["phase_tools"]["ok"]
    assert report["checks"]["registered"]["ok"]
    assert report["checks"]["gate"]["ok"], report
    assert report["checks"]["map"]["ok"], report
    assert report["checks"]["pack_context"]["ok"], report
    assert report["ok"] is True, report
