#!/usr/bin/env python3
"""Wall-clock: trigger Scubiee → response-ready (health + first locate)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_UV = Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "scubiee" / "Lib" / "site-packages"
sys.path.insert(0, str(_UV if _UV.is_dir() else ROOT / "packages"))
os.environ.setdefault("CTX_TRUST_ID_FILE", "1")
# Stay on the uv interpreter for daemon spawn if possible.
_UV_PY = Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "scubiee" / "Scripts" / "pythonw.exe"
if _UV_PY.is_file():
    os.environ.setdefault("CTX_DAEMON_PYTHON", str(_UV_PY))


def main() -> int:
    from pipeline.client import EngineClient
    from pipeline.daemon import is_running, stop_daemon
    from pipeline.mcp_lifecycle import ensure_mcp_runtime

    repo = str(ROOT)
    cid = "mcp:ready-timing"
    print("== stop (cold baseline) ==")
    try:
        stop_daemon()
    except Exception as exc:  # noqa: BLE001
        print(f"stop note: {exc}")
    time.sleep(0.4)
    print(f"running_after_stop={is_running()}")

    t0 = time.perf_counter()
    marks: list[tuple[str, float]] = []

    def mark(label: str) -> None:
        marks.append((label, time.perf_counter() - t0))
        print(f"  +{marks[-1][1]*1000:7.0f}ms  {label}")

    mark("T0 kick ensure_mcp_runtime(blocking=False)")
    warm = ensure_mcp_runtime(repo, client_id=cid, blocking=False)
    mark(f"ensure returned ok={warm.get('ok')} deferred={warm.get('deferred')} state={warm.get('warm_state')}")

    eng = EngineClient(workspace_path=repo, client=cid, timeout=3.0)
    health_ok = False
    for _ in range(80):
        h = eng.health()
        if h.get("ok"):
            mark(f"/health ok embedder={h.get('embedder_loaded')} warm_state={h.get('warm_state')}")
            health_ok = True
            break
        time.sleep(0.25)
    if not health_ok:
        mark("FAIL: /health never ok")
        return 1

    # First locate-shaped response (may be warming or hits)
    t_search = time.perf_counter()
    out = eng.post(
        "/v1/search",
        {
            "path": repo,
            "query": "hidden_run ensure_mcp_runtime map pack_context",
            "k": 8,
            "mode": "soft",
        },
    )
    search_ms = (time.perf_counter() - t_search) * 1000
    n = len(out.get("hits") or out.get("cards") or [])
    mark(
        f"first /v1/search wall={search_ms:.0f}ms ok={out.get('ok')} "
        f"warming={bool(out.get('warming') or out.get('should_retry'))} n={n}"
    )

    # Wait until embedder loaded (semantic ready)
    for _ in range(60):
        h = eng.health()
        if h.get("embedder_loaded"):
            mark("embedder_loaded=true (semantic ready)")
            break
        try:
            eng.post("/v1/embed/prewarm", {"path": repo, "wait": False, "sync": False})
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.25)
    else:
        mark("embedder still false after wait")

    t2 = time.perf_counter()
    out2 = eng.post(
        "/v1/search",
        {
            "path": repo,
            "query": "hidden_run ensure_mcp_runtime map pack_context",
            "k": 8,
            "mode": "soft",
        },
    )
    mark(
        f"warm /v1/search wall={(time.perf_counter()-t2)*1000:.0f}ms "
        f"ok={out2.get('ok')} n={len(out2.get('hits') or [])}"
    )

    print("\n== READY TIMELINE ==")
    for label, s in marks:
        print(f"{s*1000:8.0f} ms | {label}")
    print(f"\nTotal to last mark: {marks[-1][1]:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
