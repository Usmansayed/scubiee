#!/usr/bin/env python3
"""In-process ship-surface check: gate → map → pack_context → expand_context.

No MCP bridge required. Exit 0 only if the default ship tool set is registered
and the ladder returns ok payloads for this repo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))

OUT = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-mcp-ship-check.json"


def main() -> int:
    from pipeline.mcp_ship_check import run_ship_ladder

    report = run_ship_ladder(repo=ROOT)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {k: report[k] for k in ("ok", "checks", "errors", "elapsed_ms")},
            indent=2,
        )
    )
    print("wrote", OUT)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
