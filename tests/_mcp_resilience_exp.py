"""MCP / engine resilience experiments for laptop-class setups.

Scenarios:
  1. Happy-path locate (map/grep/glob/status) via EngineClient HTTP
  2. Engine stopped → MCP-style ensure + recover
  3. Concurrent locate bursts
  4. Garbage / huge queries fail soft (no crash)
  5. Memory budget constants present (800/800/8000, touch 400)

Run:
  python -u tests/_mcp_resilience_exp.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("CTX_REPO", str(ROOT))
os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")


@dataclass
class Case:
    name: str
    ok: bool
    ms: float
    detail: str = ""


def _post(path: str, body: dict, timeout: float = 30.0) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:8765{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str, timeout: float = 10.0) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:8765{path}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run() -> list[Case]:
    from pipeline.daemon import ensure_daemon
    from pipeline.incremental import DEFAULT_MAX_TOUCH
    from pipeline.memory_budget import (
        BACKGROUND_RSS_CAP_MB,
        BOOTSTRAP_RSS_CAP_MB,
        LARGE_REINDEX_RSS_CAP_MB,
    )

    cases: list[Case] = []

    # --- constants (any-laptop budgets) ---
    t0 = time.perf_counter()
    ok = (
        DEFAULT_MAX_TOUCH == 400
        and BOOTSTRAP_RSS_CAP_MB == 800
        and BACKGROUND_RSS_CAP_MB == 800
        and LARGE_REINDEX_RSS_CAP_MB == 8000
    )
    cases.append(
        Case(
            "budget_constants",
            ok,
            (time.perf_counter() - t0) * 1000,
            f"touch={DEFAULT_MAX_TOUCH} rss={BOOTSTRAP_RSS_CAP_MB}/{BACKGROUND_RSS_CAP_MB}/{LARGE_REINDEX_RSS_CAP_MB}",
        )
    )

    # --- ensure warm ---
    t0 = time.perf_counter()
    try:
        out = ensure_daemon(ROOT)
        h = _get("/health")
        cases.append(
            Case(
                "ensure_daemon_warm",
                bool(h.get("ok") and h.get("warm")),
                (time.perf_counter() - t0) * 1000,
                json.dumps({"ensure_ok": out.get("ok"), "warm": h.get("warm_state")})[:200],
            )
        )
    except Exception as exc:  # noqa: BLE001
        cases.append(Case("ensure_daemon_warm", False, (time.perf_counter() - t0) * 1000, str(exc)[:200]))

    # --- locate via HTTP (what MCP wraps) ---
    for name, path, body in (
        ("http_search", "/v1/search", {"query": "memory budget confirm", "path": str(ROOT), "top_k": 4}),
        ("http_grep", "/v1/grep", {"pattern": "DEFAULT_MAX_TOUCH", "glob": "*.py", "max_hits": 5, "path": str(ROOT)}),
        ("http_locate", "/v1/locate", {"query": "incremental_sync confirm", "path": str(ROOT), "top_k": 4}),
    ):
        t0 = time.perf_counter()
        try:
            r = _post(path, body, timeout=45.0)
            cases.append(
                Case(
                    name,
                    bool(r.get("ok", True) and not r.get("error")),
                    (time.perf_counter() - t0) * 1000,
                    f"keys={sorted(r.keys())[:8]}",
                )
            )
        except Exception as exc:  # noqa: BLE001
            cases.append(Case(name, False, (time.perf_counter() - t0) * 1000, str(exc)[:200]))

    # --- concurrent burst ---
    t0 = time.perf_counter()
    errs = 0

    def one(i: int) -> bool:
        try:
            r = _post(
                "/v1/search",
                {"query": f"pipeline memory budget {i}", "path": str(ROOT), "top_k": 3},
                timeout=60.0,
            )
            return not r.get("error")
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(one, i) for i in range(8)]
        for f in as_completed(futs):
            if not f.result():
                errs += 1
    cases.append(
        Case(
            "concurrent_search_x8",
            errs == 0,
            (time.perf_counter() - t0) * 1000,
            f"errors={errs}/8",
        )
    )

    # --- soft-fail garbage ---
    t0 = time.perf_counter()
    try:
        r = _post(
            "/v1/search",
            {"query": "x" * 8000, "path": str(ROOT), "top_k": 2},
            timeout=45.0,
        )
        # Must not crash the process; empty/weak hits still ok
        cases.append(
            Case(
                "huge_query_soft",
                "error" not in r or r.get("ok") is not False,
                (time.perf_counter() - t0) * 1000,
                f"hits={len(r.get('hits') or r.get('results') or [])}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        # Timeout/abort still counts as soft if engine stays up
        try:
            h = _get("/health", timeout=5.0)
            alive = bool(h.get("ok"))
        except Exception:
            alive = False
        cases.append(
            Case(
                "huge_query_soft",
                alive,
                (time.perf_counter() - t0) * 1000,
                f"exc={type(exc).__name__} engine_alive={alive}",
            )
        )

    # --- kill engine, recover via ensure (laptop sleep / crash) ---
    t0 = time.perf_counter()
    try:
        from pipeline.daemon import stop_daemon

        stop_daemon()
        time.sleep(1.0)
        down = False
        try:
            _get("/health", timeout=2.0)
        except Exception:
            down = True
        recovered = ensure_daemon(ROOT)
        time.sleep(1.5)
        h = _get("/health", timeout=10.0)
        # wait warm up to 60s
        warm = bool(h.get("warm"))
        deadline = time.time() + 60
        while not warm and time.time() < deadline:
            time.sleep(2)
            h = _get("/health", timeout=10.0)
            warm = bool(h.get("warm"))
        # post-recover search
        r = _post(
            "/v1/search",
            {"query": "DEFAULT_MAX_TOUCH", "path": str(ROOT), "top_k": 3},
            timeout=45.0,
        )
        cases.append(
            Case(
                "engine_kill_recover",
                down and bool(recovered.get("ok")) and warm and not r.get("error"),
                (time.perf_counter() - t0) * 1000,
                f"down={down} warm={h.get('warm_state')} gen={h.get('generation')}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        cases.append(Case("engine_kill_recover", False, (time.perf_counter() - t0) * 1000, str(exc)[:240]))

    return cases


def main() -> int:
    cases = run()
    print(json.dumps([asdict(c) for c in cases], indent=2))
    failed = [c for c in cases if not c.ok]
    print(f"\nPASSED={len(cases) - len(failed)} FAILED={len(failed)} TOTAL={len(cases)}")
    for c in failed:
        print(f"  FAIL {c.name}: {c.detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
