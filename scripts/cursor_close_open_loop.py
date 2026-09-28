#!/usr/bin/env python3
"""Simulate: close Cursor → wait engine unload → open Cursor → settle → map ≤1s.

FAIL-CLOSED gates (no more quiet-sim false greens):
  - preflight: DirectML EP present when profile=dml; no HEALTH_WEDGE
  - default: poll /health during settle (live status-storm)
  - after map: /health must still answer

  python scripts/cursor_close_open_loop.py --rounds 5 --settle-s 35
  python scripts/cursor_close_open_loop.py --quiet-settle   # opt out of health storm

Each round:
  1. Round 0 only: hard clean_slate (kill leftover MCP + stop engine)
  2. BridgeHost attach  (= Cursor open / MCP client spawn)
  3. Settle ≥ settle-s (health-poll by default)
  4. map_first ≤1s + pack ≤1s
  5. host.stop()         (= Cursor quit / MCP stdin close)
  6. Wait until ``pipeline engine run`` is gone (unload SLA)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
SCRIPTS = ROOT / "scripts"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--settle-s", type=float, default=35.0)
    ap.add_argument(
        "--settle-health-poll",
        action="store_true",
        default=True,
        help="Poll /health during settle (DEFAULT ON — live status-storm stress)",
    )
    ap.add_argument(
        "--quiet-settle",
        action="store_true",
        help="Opt out of health-poll settle (old false-positive path)",
    )
    ap.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip ORT/DirectML + HEALTH_WEDGE preflight (not recommended)",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "_cursor_close_open_loop",
    )
    ap.add_argument("--fail-fast", action="store_true", default=True)
    ap.add_argument(
        "--keep-going",
        action="store_true",
        help="Run all rounds even after a failure (overrides --fail-fast).",
    )
    args = ap.parse_args()
    fail_fast = not args.keep_going
    settle_health_poll = bool(args.settle_health_poll) and not bool(args.quiet_settle)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("CTX_EMBED_KEEPALIVE", "1")
    os.environ.setdefault("CTX_EMBED_KEEPALIVE_S", "8")
    os.environ.setdefault("CTX_EMBED_PREWARM", "1")
    os.environ.setdefault("CTX_ENGINE_CPU_CAP_PCT", "0")

    preflight: dict[str, Any] = {"ok": True, "skipped": True}
    if not args.skip_preflight:
        from cursor_open_preflight import run_preflight

        preflight = run_preflight(require_engine_up=False)
        (out_dir / "PREFLIGHT.json").write_text(
            json.dumps(preflight, indent=2), encoding="utf-8"
        )
        print(
            f"[cursor_close_open_loop] preflight ok={preflight.get('ok')} "
            f"ort={((preflight.get('ort') or {}).get('ort_version'))} "
            f"providers={((preflight.get('ort') or {}).get('providers'))} "
            f"errors={preflight.get('errors')}",
            flush=True,
        )
        if not preflight.get("ok"):
            print(
                "[cursor_close_open_loop] FAIL CLOSED on preflight — "
                "refusing to run a quiet-sim that would false-green",
                flush=True,
            )
            (out_dir / "SUMMARY.json").write_text(
                json.dumps(
                    {"ok": False, "preflight": preflight, "rounds": []},
                    indent=2,
                ),
                encoding="utf-8",
            )
            return 1

    from pipeline.mcp_host_sim.scenario import run_scenario

    rounds: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    overall_ok = True

    for i in range(max(1, int(args.rounds))):
        round_dir = out_dir / f"round_{i:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        print(
            f"\n=== close->unload->open->settle({args.settle_s:.0f}s) round {i + 1}/"
            f"{args.rounds} (skip_clean={i > 0} health_poll={settle_health_poll}) ===\n",
            flush=True,
        )
        t_round = time.perf_counter()
        report = run_scenario(
            lane="a",
            repo=ROOT,
            live=True,
            skip_idle=True,
            settle_s=float(args.settle_s),
            mcp_client="cursor",
            skip_clean=(i > 0),
            settle_health_poll=settle_health_poll,
            out_dir=round_dir,
        )
        wall_ms = round((time.perf_counter() - t_round) * 1000, 1)
        ok = bool(report.get("ok"))

        post_health: dict[str, Any] = {}
        try:
            from cursor_open_preflight import check_health_alive

            post_health = check_health_alive(timeout_s=10.0)
            if post_health.get("code") == "HEALTH_WEDGE":
                ok = False
                report.setdefault("errors", []).append(
                    f"post_round HEALTH_WEDGE: {post_health}"
                )
        except Exception as exc:  # noqa: BLE001
            post_health = {"ok": False, "error": str(exc)}

        phase_bits = []
        for p in report.get("phases") or []:
            phase_bits.append(
                f"{p.get('name')}={'ok' if p.get('ok') else p.get('code')} "
                f"{p.get('elapsed_ms')}ms"
            )
        row = {
            "round": i,
            "ok": ok,
            "wall_ms": wall_ms,
            "skip_clean": i > 0,
            "settle_health_poll": settle_health_poll,
            "post_health": post_health,
            "errors": report.get("errors") or [],
            "phases": phase_bits,
            "report_paths": report.get("report_paths"),
        }
        rounds.append(row)
        print(
            f"[cursor_close_open_loop] round {i} ok={ok} wall_ms={wall_ms} "
            f"post_health={post_health.get('ok')} "
            f"phases={'; '.join(phase_bits[:6])}",
            flush=True,
        )
        if not ok:
            overall_ok = False
            if fail_fast:
                break

    summary = {
        "ok": overall_ok,
        "preflight": preflight,
        "rounds_requested": int(args.rounds),
        "rounds_ran": len(rounds),
        "settle_s": float(args.settle_s),
        "settle_health_poll": settle_health_poll,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        "rounds": rounds,
    }
    (out_dir / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    lines = [
        "# Cursor close->open loop",
        "",
        f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Rounds:** {len(rounds)}/{args.rounds} settle={args.settle_s:.0f}s "
        f"health_poll={settle_health_poll}",
        f"**Preflight:** {'PASS' if preflight.get('ok') else 'FAIL'}",
        f"**Verdict: {'PASS' if overall_ok else 'FAIL'}**",
        "",
        "| Round | Result | Wall | Post-health | Phases |",
        "|-------|--------|------|-------------|--------|",
    ]
    for r in rounds:
        ph = r.get("post_health") or {}
        lines.append(
            f"| {r['round']} | {'PASS' if r['ok'] else 'FAIL'} | "
            f"{r['wall_ms']}ms | {'ok' if ph.get('ok') else ph.get('code') or 'err'} | "
            f"{'; '.join((r.get('phases') or [])[:4])} |"
        )
    if not overall_ok:
        lines.extend(["", "## Errors", ""])
        for e in preflight.get("errors") or []:
            lines.append(f"- preflight: {e}")
        for r in rounds:
            if r.get("ok"):
                continue
            for e in r.get("errors") or []:
                lines.append(f"- round {r['round']}: {e}")
    (out_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"\n[cursor_close_open_loop] overall_ok={overall_ok} "
        f"report={out_dir / 'REPORT.md'}",
        flush=True,
    )
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
