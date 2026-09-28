"""Frozen OOD locate seed gate — general ranking, not one-query recipes.

    python scripts/eval_locate_ood_seeds.py
    python scripts/eval_locate_ood_seeds.py --json out.json

Exit non-zero when pass rate < fixture min_pass_rate.
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
FIX = ROOT / "tests" / "fixtures" / "locate_ood_seeds.json"
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))


def _leaf(sym: object) -> str:
    return str(sym or "").rsplit(".", 1)[-1]


def _norm(path: object) -> str:
    return str(path or "").replace("\\", "/")


def _pass_case(seed: dict[str, Any] | None, case: dict[str, Any]) -> tuple[bool, str]:
    if not seed:
        return False, "no_seed"
    file = _norm(seed.get("file"))
    sym = _leaf(seed.get("symbol"))
    file_ok = any(f in file for f in (case.get("file_any") or []))
    want_syms = list(case.get("symbol_any") or [])
    sym_ok = (not want_syms) or (sym in want_syms)
    if file_ok and sym_ok:
        return True, f"{sym}@{file}"
    return False, f"got {sym}@{file}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=ROOT)
    ap.add_argument("--fixture", type=Path, default=FIX)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--wait-ready", type=float, default=30.0)
    args = ap.parse_args()

    # Avoid FastEmbed/DML reload AV on Windows during long sequential maps.
    os.environ.setdefault("CTX_EMBED_IDLE_DEMOTE_S", "3600")

    from pipeline.locate_cli import cli_map

    data = json.loads(args.fixture.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = list(data.get("cases") or [])
    min_rate = float(data.get("min_pass_rate") or 0.7)
    rows: list[dict[str, Any]] = []
    passed = 0
    t0 = time.perf_counter()
    for case in cases:
        q = str(case.get("query") or "")
        m = cli_map(q, path=args.repo, k=10, wait_ready=float(args.wait_ready))
        seed = m.get("suggested_seed") if m.get("ok") else None
        ok, detail = _pass_case(seed if isinstance(seed, dict) else None, case)
        if ok:
            passed += 1
        rows.append(
            {
                "id": case.get("id"),
                "ok": ok,
                "detail": detail,
                "map_ok": bool(m.get("ok")),
                "error": m.get("error"),
                "seed": seed,
            }
        )
        mark = "PASS" if ok else "FAIL"
        print(f"{mark}  {case.get('id')}: {detail}")

    total = len(cases) or 1
    rate = passed / total
    summary = {
        "passed": passed,
        "total": total,
        "pass_rate": round(rate, 4),
        "min_pass_rate": min_rate,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "rows": rows,
    }
    print(
        f"\nOOD seed gate: {passed}/{total} = {rate:.0%} "
        f"(min {min_rate:.0%}) in {summary['elapsed_s']}s"
    )
    if args.json:
        args.json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    return 0 if rate + 1e-9 >= min_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
