"""Blind-10 Phase 2: score frozen Phase1 packs against GT (author GT AFTER Phase1).

Usage (after writing GT file):
  python scripts/blind10_pack_phase2.py

Refuses to run if Phase1 summary is missing or already claims scored=true mid-flight.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "docs/superpowers/plans/2026-09-06-blind10-pack-results.json"
GT = ROOT / "docs/superpowers/plans/2026-09-06-blind10-pack-gt.json"
OUT_MD = ROOT / "docs/superpowers/plans/2026-09-06-blind10-pack-phase2.md"


def main() -> int:
    if not SUMMARY.is_file():
        print("PHASE2 FAIL: run Phase1 first (missing results summary)", file=sys.stderr)
        return 2
    if not GT.is_file():
        print(
            f"PHASE2 FAIL: author GT at {GT.relative_to(ROOT)} AFTER Phase1 freeze "
            "(must files/symbols per b01–b10). Do not invent GT from pack output.",
            file=sys.stderr,
        )
        return 2

    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    gt = json.loads(GT.read_text(encoding="utf-8"))
    if summary.get("scored"):
        print("PHASE2: summary already scored — writing a new compare pass anyway")

    # Minimal scorer: must-file / must-symbol hit rates from pack[].file/symbol
    by_id = {c["id"]: c for c in summary.get("cases") or []}
    lines = ["# Blind-10 Phase 2", "", f"Arm: `{summary.get('arm')}`", ""]
    rows = []
    for g in gt.get("cases") or []:
        cid = g["id"]
        row = by_id.get(cid)
        if not row:
            lines.append(f"- `{cid}`: MISSING from Phase1 freeze")
            continue
        pack_path = ROOT / row["pack_path"]
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        items = pack.get("pack") or []
        files = {str(x.get("file") or "").replace("\\", "/") for x in items}
        syms = {str(x.get("symbol") or "") for x in items}
        must_files = [str(x).replace("\\", "/") for x in (g.get("must_files") or [])]
        must_syms = [str(x) for x in (g.get("must_symbols") or [])]
        mf = sum(1 for f in must_files if f in files) / max(len(must_files), 1)
        ms = sum(1 for s in must_syms if s in syms) / max(len(must_syms), 1)
        rows.append({"id": cid, "must_file": round(mf, 3), "must_symbol": round(ms, 3)})
        lines.append(f"- `{cid}`: must_file={mf:.2f} must_symbol={ms:.2f}")

    summary["scored"] = True
    summary["phase2"] = {"rows": rows, "gt": str(GT.relative_to(ROOT)).replace("\\", "/")}
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
