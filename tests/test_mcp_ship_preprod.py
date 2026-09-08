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
    entry = format_server_entry(TOOL_MAP["cursor"], pin_repo=False)
    enriched = enrich_server_entry_permissions(entry, "cursor")
    approved = set(enriched.get("autoApprove") or [])
    assert set(SHIP_TOOLS).issubset(approved)
    assert not (approved & {"focus", "grep", "glob"})

    write_project_gate_rules(repo, slugs=["cursor"])
    rule = repo / ".cursor" / "rules" / "scubiee.mdc"
    assert rule.is_file()
    text = rule.read_text(encoding="utf-8")
    assert "pack_context" in text
    assert "GATE" in text

    cleanup_project_gate_rules(repo)
    assert not rule.exists()
    uninstall_tool(TOOL_MAP["cursor"], repo=repo)

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
