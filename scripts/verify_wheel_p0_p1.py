"""Verify built wheel contains P0/P1 journey fixes."""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

WHEEL = Path(__file__).resolve().parents[1] / "dist" / "scubiee-0.2.82-py3-none-any.whl"


def main() -> int:
    if not WHEEL.is_file():
        print(f"MISSING: {WHEEL}", file=sys.stderr)
        return 1
    with zipfile.ZipFile(WHEEL) as z:
        agent = z.read("pipeline/templates/context-agent.mdc").decode()
        md = z.read("pipeline/templates/context-engine.md").decode()
        mdc = z.read("pipeline/templates/context-engine.mdc").decode()
        ml = z.read("pipeline/mcp_locate.py").decode()

    pause_block = ml.split("Scubiee is paused", 1)[1][:300] if "Scubiee is paused" in ml else ""
    checks = {
        "agent_no_poll": "Do not call it every turn" in agent,
        "agent_resume": "scubiee resume" in agent,
        "md_no_ignore_forever": "ignore this rule entirely" not in md.lower(),
        "mdc_no_ignore_forever": "ignore this rule entirely" not in mdc.lower(),
        "hint_resume_not_wake": "scubiee resume" in pause_block and "wake" not in pause_block.lower(),
        "paused_no_retry_status": "should_retry_status\": False" in ml or "should_retry_status': False" in ml,
        "ok_not_managed_or": "healthy or _is_repo_managed()" not in ml,
        "ok_healthy_only": '"ok": healthy' in ml,
        "warming_hint_anti_poll": "Do not poll status()" in ml,
    }
    print(json.dumps(checks, indent=2))
    if not all(checks.values()):
        print("WHEEL_VERIFY_FAILED", file=sys.stderr)
        return 1
    print("WHEEL_VERIFY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
