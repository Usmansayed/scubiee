"""Live-daemon stress harness: parallel 8× map() (exploration session suggestion).

Requires a warm Scubiee engine and an enrolled repo (defaults to this workspace).
Skipped automatically when the daemon is down or the repo is not managed.

Run manually:
  python -m pytest tests/test_mcp_parallel_map_stress.py -m integration -v
  python tests/test_mcp_parallel_map_stress.py
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Distinct code-vocabulary queries — avoid any cache duplicate short-circuit.
PARALLEL_MAP_QUERIES: tuple[str, ...] = (
    "daemon watchdog force_restart health poll CTX_WATCHDOG",
    "session store dedup handle expand already_in_session ledger",
    "merkle incremental sync dirty journal keeper root_probe",
    "embedder CodeRank FastEmbed batch fair scheduler acquire",
    "map_v3_server tool_map focus find phase SERVER_INSTRUCTIONS",
    "graphify AST extract build dedup entity graph IR",
    "conductor RRF BM25 dense fusion locate search hits",
    "resource manager memory budget admission pause resume sync",
)


def _repo_managed(repo: Path) -> bool:
    if not (repo / ".scubiee" / "id.json").is_file():
        return False
    try:
        from pipeline.project_id import read_id_file, load_registry

        pid = read_id_file(repo)
        if not pid:
            return False
        reg = load_registry()
        entry = (reg.get("projects") or {}).get(pid) or {}
        return bool(entry.get("managed"))
    except Exception:  # noqa: BLE001
        return False


def _engine_healthy(repo: Path) -> bool:
    try:
        from pipeline.client import EngineClient

        return EngineClient(workspace_path=str(repo)).healthy()
    except Exception:  # noqa: BLE001
        return False


def _ensure_warm(repo: Path) -> None:
    from pipeline.daemon import ensure_daemon

    ensure_daemon(repo, force_if_hung=False)


def _map_with_retry(
    map_fn: Callable[[dict], str],
    query: str,
    label: str,
) -> dict[str, Any]:
    """One Map V3 map() call; retry once on a transient failure note.

    Map V3 (pipeline.map_v3_server.tool_map) takes a single dict and returns
    plain text. A result is "ok" when it comes back as non-empty text that does
    not start with an error/failure marker.
    """
    last: dict[str, Any] = {"ok": False, "error": "no attempt", "label": label}
    for attempt in range(2):
        try:
            raw = map_fn({"config": "find", "query": query})
        except Exception as e:  # noqa: BLE001
            last = {"ok": False, "error": f"{type(e).__name__}: {e}", "label": label}
            if attempt == 1:
                return last
            time.sleep(0.4)
            continue
        text = (raw or "").strip()
        failed = (not text) or text.startswith("error:") or " failed:" in text.splitlines()[0]
        card: dict[str, Any] = {
            "ok": not failed,
            "tool": "map",
            "label": label,
            "chars": len(text),
            "head": text[:120],
        }
        last = card
        if card["ok"]:
            if attempt == 1:
                card["retried_after_should_retry"] = True
            return card
        if attempt == 1:
            return card
        time.sleep(0.4)
    return last


def _run_parallel_map_burst(
    repo: Path,
    *,
    workers: int = 8,
) -> list[dict[str, Any]]:
    os.environ["CTX_REPO"] = str(repo.resolve())
    os.environ["CTX_MCP_SURFACE"] = "phase"
    _ensure_warm(repo)

    from pipeline.map_v3_server import TOOLS

    map_fn = TOOLS["map"]["fn"]

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [
            pool.submit(_map_with_retry, map_fn, q, f"parallel-map-stress-{i}")
            for i, q in enumerate(PARALLEL_MAP_QUERIES[:workers])
        ]
        for fut in as_completed(futs):
            results.append(fut.result())
    return results


@pytest.mark.integration
def test_parallel_map_burst_no_unhandled_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    """8 concurrent map() calls must all succeed (possibly after one retry)."""
    repo = REPO_ROOT
    if not _repo_managed(repo):
        pytest.skip("workspace not enrolled — run: scubiee init .")
    if not _engine_healthy(repo):
        pytest.skip("Scubiee engine not reachable at CTX_ENGINE_URL")

    monkeypatch.chdir(repo)
    monkeypatch.setenv("CTX_REPO", str(repo.resolve()))
    monkeypatch.setenv("CTX_MCP_SURFACE", "phase")

    t0 = time.perf_counter()
    results = _run_parallel_map_burst(repo, workers=8)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    failures = [r for r in results if not r.get("ok")]
    assert not failures, (
        f"{len(failures)}/8 map calls failed after retry "
        f"({elapsed_ms:.0f}ms): {failures[0] if failures else {}}"
    )

    assert all(r.get("tool") == "map" for r in results)
    with_output = sum(1 for r in results if (r.get("chars") or 0) > 0)
    assert with_output >= 6, f"expected ≥6 non-empty map results, got {with_output}"

    retried = sum(1 for r in results if r.get("retried_after_should_retry"))
    # Informational — auto-retry path exercised when daemon flickers.
    assert retried >= 0


@pytest.mark.integration
def test_parallel_map_engine_still_healthy_after_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    """Engine must stay up after the burst (no silent crash)."""
    repo = REPO_ROOT
    if not _repo_managed(repo) or not _engine_healthy(repo):
        pytest.skip("needs enrolled repo + warm engine")

    monkeypatch.chdir(repo)
    monkeypatch.setenv("CTX_REPO", str(repo.resolve()))
    monkeypatch.setenv("CTX_MCP_SURFACE", "phase")

    _run_parallel_map_burst(repo, workers=8)
    assert _engine_healthy(repo), "engine died after parallel map burst"


def main() -> int:
    """CLI entry for manual smoke (outside pytest)."""
    repo = REPO_ROOT
    if not _repo_managed(repo):
        print("SKIP: repo not managed — run: scubiee init .", file=sys.stderr)
        return 2
    if not _engine_healthy(repo):
        print("SKIP: engine not healthy — run: scubiee engine ensure .", file=sys.stderr)
        return 2

    t0 = time.perf_counter()
    results = _run_parallel_map_burst(repo, workers=8)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    ok = sum(1 for r in results if r.get("ok"))
    retried = sum(1 for r in results if r.get("retried_after_should_retry"))
    print(f"parallel_map_x8: {ok}/8 ok in {elapsed_ms:.0f}ms (retried={retried})")
    for i, r in enumerate(results):
        status = "OK" if r.get("ok") else "FAIL"
        print(f"  [{status}] q{i} chars={r.get('chars', 0)} head={r.get('head', '')!r}")
        if not r.get("ok"):
            print(f"         error={r.get('error')}")
    alive = _engine_healthy(repo)
    print(f"engine_alive_after={alive}")
    return 0 if ok == 8 and alive else 1


if __name__ == "__main__":
    raise SystemExit(main())
