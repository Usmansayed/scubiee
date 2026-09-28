"""Hold one Cursor-style MCP bridge open (simulates an attached IDE).

Engine idle policy unloads/stops the engine when no MCP client is attached, so
HTTP-only probes (live_sync_probe, kill/recover) need a bridge held open.

Usage: python scripts/hold_mcp_bridge.py [--seconds 900]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from attach_pack_race import PID, _client  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=900.0)
    args = ap.parse_args()
    with _client("hold") as c:
        c.call_text("gate", project_id=PID)
        print("bridge held", flush=True)
        end = time.time() + args.seconds
        while time.time() < end:
            time.sleep(20.0)
            try:
                c.call_text("gate", project_id=PID)  # keep the session active
            except Exception as exc:  # noqa: BLE001
                print(f"gate failed: {exc}", flush=True)
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
