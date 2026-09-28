"""Phase 0: map-only for NEW u01–u20 (parallel-safe with multipack embed)."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCUBIEE = ROOT / ".venv" / "Scripts" / "scubiee.exe"
QUERIES = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-blind-multipack-20-queries.json"
OUT = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-blind-multipack-20-maps.json"
OUT_DIR = ROOT / "docs" / "superpowers" / "plans" / "blind_multipack_20_runs"


def _run(args: list[str], timeout: int = 240) -> dict[str, Any]:
    t0 = time.time()
    try:
        proc = subprocess.run(
            args,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONPATH": str(ROOT / "packages")},
        )
        out = (proc.stdout or "").strip()
        parsed = None
        if out:
            try:
                parsed = json.loads(out)
            except json.JSONDecodeError:
                s, e = out.find("{"), out.rfind("}")
                if s >= 0 and e > s:
                    try:
                        parsed = json.loads(out[s : e + 1])
                    except json.JSONDecodeError:
                        parsed = None
        return {
            "ok": proc.returncode == 0 and parsed is not None,
            "elapsed_s": round(time.time() - t0, 3),
            "stderr_tail": (proc.stderr or "")[-500:],
            "json": parsed,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "elapsed_s": round(time.time() - t0, 3), "stderr_tail": "TIMEOUT", "json": None}


def _seed(mj: dict | None) -> dict[str, str]:
    if not mj:
        return {"file": "", "symbol": "", "source": "missing"}
    sug = mj.get("suggested_seed") or {}
    if isinstance(sug, dict) and sug.get("file"):
        return {
            "file": str(sug.get("file") or "").replace("\\", "/"),
            "symbol": str(sug.get("symbol") or ""),
            "source": "suggested_seed",
        }
    cards = mj.get("cards") or []
    if cards:
        c0 = cards[0]
        return {
            "file": str(c0.get("file") or "").replace("\\", "/"),
            "symbol": str(c0.get("symbol") or ""),
            "source": "cards[0]",
        }
    return {"file": "", "symbol": "", "source": "none"}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = json.loads(QUERIES.read_text(encoding="utf-8"))["cases"]
    rows = []
    for i, c in enumerate(cases, 1):
        q = c["enrich_map_query"]
        print(f"[{i}/{len(cases)}] {c['id']} …", flush=True)
        res = _run([str(SCUBIEE), "map", q, "--k", "10"])
        seed = _seed(res.get("json"))
        cards = []
        for card in (res.get("json") or {}).get("cards") or []:
            if isinstance(card, dict):
                cards.append(
                    {
                        "file": str(card.get("file") or "").replace("\\", "/"),
                        "symbol": str(card.get("symbol") or ""),
                        "loc": card.get("loc"),
                        "score": card.get("score"),
                    }
                )
        row = {
            "id": c["id"],
            "family": c.get("family"),
            "task": c.get("task"),
            "enrich_map_query": q,
            "map_ok": res["ok"],
            "map_elapsed_s": res["elapsed_s"],
            "suggested_seed": seed,
            "map_top_cards": cards[:10],
            "stderr_tail": res.get("stderr_tail"),
        }
        rows.append(row)
        (OUT_DIR / f"{c['id']}_map_only.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        print(f"  ok={res['ok']} seed={seed['file']}::{seed['symbol']} ({res['elapsed_s']}s)", flush=True)

    OUT.write_text(json.dumps({"protocol": "maps_only", "rows": rows}, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
