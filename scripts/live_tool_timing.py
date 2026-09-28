#!/usr/bin/env python3
"""Live Scubiee warm + tool latency consistency probe (HTTP EngineClient).

Does not use shell `scubiee map|pack` — talks to the running engine.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_UV = Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "scubiee" / "Lib" / "site-packages"
if _UV.is_dir():
    sys.path.insert(0, str(_UV))
else:
    sys.path.insert(0, str(ROOT / "packages"))
os.environ.setdefault("CTX_TRUST_ID_FILE", "1")

QUERY = (
    "mcp_locate ensure_mcp_runtime pack_context map gate warming "
    "process_job hidden_run CREATE_NO_WINDOW pythonw spawn_child_process"
)


def main() -> int:
    from pipeline.client import EngineClient
    from pipeline.daemon import is_running

    repo = str(ROOT)
    eng = EngineClient(workspace_path=repo, client="live-consistency", timeout=60.0)
    report: dict = {"repo": repo, "checks": []}

    def row(name: str, **kw):
        report["checks"].append({"name": name, **kw})
        print(f"[{name}] {json.dumps(kw, default=str)}")

    t0 = time.perf_counter()
    health = eng.health()
    row(
        "health",
        wall_ms=round((time.perf_counter() - t0) * 1000, 1),
        ok=bool(health.get("ok")),
        warm_state=health.get("warm_state"),
        embedder_loaded=health.get("embedder_loaded"),
        running=is_running(),
    )

    t1 = time.perf_counter()
    opened = eng.open_repo(repo, wait=False)
    row(
        "open_repo_wait_false",
        wall_ms=round((time.perf_counter() - t1) * 1000, 1),
        ok=opened.get("ok"),
        warm_state=opened.get("warm_state") or opened.get("status"),
    )

    map_ms: list[float] = []
    for i in range(1, 6):
        t = time.perf_counter()
        # Prefer dedicated map endpoint if present; else search shaped like map.
        try:
            out = eng.post(
                "/v1/search",
                {"path": repo, "query": QUERY, "k": 12, "mode": "soft"},
            )
        except Exception as exc:  # noqa: BLE001
            out = {"ok": False, "error": str(exc)}
        wall = round((time.perf_counter() - t) * 1000, 1)
        map_ms.append(wall)
        row(
            f"search_{i}",
            wall_ms=wall,
            ok=out.get("ok"),
            warming=bool(out.get("warming") or out.get("should_retry")),
            n=len(out.get("hits") or out.get("cards") or []),
            elapsed_ms=out.get("elapsed_ms"),
        )
        time.sleep(0.15)

    if len(map_ms) >= 2:
        warm = map_ms[1:]
        row(
            "search_consistency",
            first_ms=map_ms[0],
            warm_mean_ms=round(statistics.mean(warm), 1),
            warm_stdev_ms=round(statistics.pstdev(warm), 1) if len(warm) > 1 else 0,
            warm_min_ms=min(warm),
            warm_max_ms=max(warm),
            p95ish_ms=sorted(warm)[max(0, int(0.95 * (len(warm) - 1)))],
        )

    # Note locate then three more searches (streak path)
    try:
        eng.note_locate(path=repo)
    except Exception:  # noqa: BLE001
        pass
    streak_ms: list[float] = []
    for i in range(1, 4):
        t = time.perf_counter()
        out = eng.post("/v1/search", {"path": repo, "query": QUERY, "k": 8, "mode": "soft"})
        wall = round((time.perf_counter() - t) * 1000, 1)
        streak_ms.append(wall)
        row(f"search_after_note_{i}", wall_ms=wall, ok=out.get("ok"))

    if streak_ms:
        row(
            "streak_consistency",
            mean_ms=round(statistics.mean(streak_ms), 1),
            stdev_ms=round(statistics.pstdev(streak_ms), 1) if len(streak_ms) > 1 else 0,
            min_ms=min(streak_ms),
            max_ms=max(streak_ms),
        )

    # Lean pack arms (local context_trace — same code MCP locate uses).
    try:
        from pipeline.context_trace import run_pack_context

        pack_q = (
            "run_pack_context composite_v1 pack_context lean heatmap seed "
            "multi_seed_v1 merge_seed_heatmaps agreement corridor TraceNode"
        )
        for label, kwargs in (
            (
                "pack_1seed",
                {
                    "query": pack_q,
                    "seed_file": "packages/pipeline/context_trace.py",
                    "seed_symbol": "run_pack_context",
                    "mode": "lean",
                    "k": 16,
                },
            ),
            (
                "pack_3seed",
                {
                    "query": pack_q
                    + " run_map_context daemon is_running pipeline/daemon",
                    "seed_file": "packages/pipeline/context_trace.py",
                    "seed_symbol": "run_map_context",
                    "seed2_file": "packages/trace_lab/multi_seed.py",
                    "seed2_symbol": "merge_seed_heatmaps",
                    "seed3_file": "packages/pipeline/daemon.py",
                    "seed3_symbol": "is_running",
                    "mode": "lean",
                    "k": 16,
                },
            ),
        ):
            t = time.perf_counter()
            out = run_pack_context(ROOT, **kwargs)
            wall = round((time.perf_counter() - t) * 1000, 1)
            row(
                label,
                wall_ms=wall,
                ok=out.get("ok"),
                elapsed_ms=out.get("elapsed_ms"),
                sla=out.get("sla"),
                timing=out.get("timing"),
                engine=out.get("engine"),
                n_seeds=len(out.get("seeds") or []),
                adaptive_skips=(out.get("timing") or {}).get("adaptive_skips"),
            )
    except Exception as exc:  # noqa: BLE001
        row("pack_arms", ok=False, error=str(exc))

    print("---SUMMARY---")
    print(json.dumps(report["checks"][-3:] + [c for c in report["checks"] if c["name"] == "health"], indent=2))
    out_path = ROOT / "docs" / "architecture" / "_live_tool_timing.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
