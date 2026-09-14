#!/usr/bin/env python3
"""MCP host simulator CLI — Lane A (bridge) / Lane B (Kiro pins).

Examples:
  python scripts/mcp_host_sim.py --lane a --skip-idle
  python scripts/mcp_host_sim.py --lane a --idle-s 120
  python scripts/mcp_host_sim.py --lane b
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))


def main() -> int:
    ap = argparse.ArgumentParser(description="MCP host simulator (warm/locate/unload SLAs)")
    ap.add_argument("--lane", choices=["a", "b", "both"], default="a")
    ap.add_argument("--repo", type=Path, default=ROOT)
    ap.add_argument("--project-id", default="")
    ap.add_argument("--engine-url", default="")
    ap.add_argument("--idle-s", type=float, default=120.0)
    ap.add_argument("--skip-idle", action="store_true", help="Skip 120s idle hold (faster smoke)")
    ap.add_argument(
        "--true-first-map",
        action="store_true",
        help="Skip locate_warmup so map_first is the real first MCP map after attach",
    )
    ap.add_argument(
        "--settle-s",
        type=float,
        default=0.0,
        help="After soft-ready, idle until host_start+N seconds with no map; "
        "then first map must be ≤1s (implies --true-first-map)",
    )
    ap.add_argument("--live", action="store_true", help="Use real ~/.scubiee (needed for indexed repos)")
    ap.add_argument(
        "--sandbox",
        action="store_true",
        help="Isolate CTX_HOME under .scubiee_sim_home (requires indexed fixture under that home)",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "docs" / "superpowers" / "plans",
    )
    args = ap.parse_args()

    import os

    if args.sandbox and not args.live:
        sandbox = ROOT / ".scubiee_sim_home"
        sandbox.mkdir(parents=True, exist_ok=True)
        os.environ["CTX_HOME"] = str(sandbox)
        print(f"[mcp_host_sim] sandbox CTX_HOME={sandbox}", file=sys.stderr)
    else:
        # Default / --live: real machine home so enrolled index is visible.
        print("[mcp_host_sim] using real CTX_HOME (~/.scubiee)", file=sys.stderr)
        if not args.live and not args.sandbox:
            print(
                "[mcp_host_sim] tip: pass --sandbox only with a fixture indexed into that home",
                file=sys.stderr,
            )

    from pipeline.mcp_host_sim.scenario import run_scenario

    report = run_scenario(
        lane=args.lane,
        repo=args.repo,
        project_id=args.project_id or None,
        engine_url=args.engine_url or None,
        idle_s=args.idle_s,
        live=bool(args.live),
        out_dir=args.out_dir,
        skip_idle=bool(args.skip_idle),
        true_first_map=bool(args.true_first_map),
        settle_s=float(args.settle_s),
    )
    print(json.dumps({k: report[k] for k in ("ok", "lane", "elapsed_ms", "errors", "report_paths") if k in report}, indent=2))
    for p in report.get("phases") or []:
        print(
            f"  phase {p.get('name')}: ok={p.get('ok')} "
            f"ms={p.get('elapsed_ms')} code={p.get('code')}"
        )
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
