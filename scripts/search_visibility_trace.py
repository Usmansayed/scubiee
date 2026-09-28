"""Write one new file, then log every /v1/search call: send time, duration, hit or miss.

Separates "search blocked by the keeper" from "published but not yet findable".
Usage: python scripts/search_visibility_trace.py <repo> [seconds]
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"
REPO = Path(sys.argv[1]).resolve()
LIMIT_S = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0


def search(query: str) -> tuple[float, list[dict]]:
    body = json.dumps({"query": query, "top_k": 10, "path": str(REPO)}).encode()
    req = urllib.request.Request(
        BASE + "/v1/search", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    return (time.perf_counter() - t0) * 1000, list(data.get("results") or data.get("hits") or [])


def status_generation() -> int:
    with urllib.request.urlopen(BASE + "/v1/status", timeout=30) as r:
        return int(json.loads(r.read().decode("utf-8")).get("generation") or 0)


def main() -> int:
    token = f"zzvis{int(time.time() * 1000)}"
    path = REPO / "packages" / "pipeline" / f"{token}.py"
    src = (
        f'"""Visibility probe."""\n\n\ndef {token}_handler(payload):\n'
        f'    """Unique probe symbol {token}."""\n    return payload\n'
    )
    gen0 = status_generation()
    t_write = time.perf_counter()
    path.write_text(src, encoding="utf-8")
    first_hit = None
    rows = []
    try:
        while time.perf_counter() - t_write < LIMIT_S:
            sent = (time.perf_counter() - t_write) * 1000
            dur, hits = search(token)
            hit = any(token in json.dumps(h) for h in hits)
            rows.append({"sent_ms": round(sent), "dur_ms": round(dur), "hit": hit})
            if hit and first_hit is None:
                first_hit = round((time.perf_counter() - t_write) * 1000)
                break
            time.sleep(0.2)
        gen1 = status_generation()
    finally:
        path.unlink(missing_ok=True)
    for row in rows:
        print(json.dumps(row))
    slow = [r for r in rows if r["dur_ms"] > 1000]
    print(
        json.dumps(
            {
                "first_hit_ms": first_hit,
                "searches": len(rows),
                "slow_searches": len(slow),
                "max_search_ms": max((r["dur_ms"] for r in rows), default=0),
                "gen_before": gen0,
                "gen_after": gen1,
            }
        )
    )
    return 0 if first_hit is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
