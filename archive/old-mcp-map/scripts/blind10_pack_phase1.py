"""Blind-10 Phase 1: enrich → map chunks → pack → store (NO scoring).

Requires Phase 0 green:
  pytest tests/test_venture_stack.py
  python scripts/venture_preflight.py

Usage:
  python scripts/blind10_pack_phase1.py              # all b01–b10
  python scripts/blind10_pack_phase1.py --ids b01    # single
  python scripts/blind10_pack_phase1.py --dry-run    # print plan only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "docs/superpowers/plans/2026-09-06-blind10-pack-queries.json"
OUT_DIR = ROOT / "docs/superpowers/plans/blind10_pack_runs"
SUMMARY = ROOT / "docs/superpowers/plans/2026-09-06-blind10-pack-results.json"
SCUBIEE = ROOT / ".venv" / "Scripts" / "scubiee.exe"


def _run_json(cmd: list[str], *, env: dict[str, str] | None = None) -> dict[str, Any]:
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(ROOT / "packages")
    merged["CTX_TRUST_ID_FILE"] = "1"
    if env:
        merged.update(env)
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=merged,
        check=False,
    )
    raw = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(
            f"cmd failed rc={proc.returncode}: {' '.join(cmd)}\n"
            f"stderr={(proc.stderr or '')[-2000:]}\nstdout={raw[-2000:]}"
        )
    # CLI may print warnings before JSON — take last {...} block
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"no JSON in output for {' '.join(cmd)}: {raw[:500]}")
    return json.loads(raw[start : end + 1])


def _require_phase0() -> dict[str, Any]:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "venture_preflight", ROOT / "scripts" / "venture_preflight.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "packages"))
    spec.loader.exec_module(mod)
    from trace_lab.cases import default_fixture_root

    rep = mod.preflight(fixture_root=default_fixture_root().resolve(), require_faiss=True)
    if not rep.get("ok"):
        raise SystemExit(f"PHASE0 FAIL — refuse Phase1: {rep.get('blockers')}")
    return rep


def _chunk_from_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "file": card.get("file"),
        "symbol": card.get("symbol"),
        "loc": card.get("loc"),
        "start_line": card.get("start_line"),
        "end_line": card.get("end_line"),
        "score": card.get("score"),
        "heat": card.get("heat"),
        "why": card.get("why"),
        "kind": card.get("kind"),
    }


def run_case(case: dict[str, Any], *, arm: str = "composite_v1") -> dict[str, Any]:
    cid = case["id"]
    prompt = case["enrich_prompt"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    map_payload = _run_json(
        [str(SCUBIEE), "map", prompt, str(ROOT), "--k", "10", "--local"]
    )
    map_path = OUT_DIR / f"{cid}_map.json"
    map_path.write_text(json.dumps(map_payload, indent=2), encoding="utf-8")

    cards = list(map_payload.get("cards") or map_payload.get("results") or [])
    chunks = [_chunk_from_card(c) for c in cards[:10]]
    seed = map_payload.get("suggested_seed") or {}
    if not seed and cards:
        c0 = cards[0]
        seed = {
            "file": c0.get("file"),
            "symbol": c0.get("symbol"),
            "line": c0.get("start_line"),
        }
    seed_file = str(seed.get("file") or "").replace("\\", "/")
    if not seed_file:
        raise RuntimeError(f"{cid}: map returned no suggested_seed/file")

    chunks_path = OUT_DIR / f"{cid}_chunks.json"
    chunks_path.write_text(
        json.dumps(
            {
                "id": cid,
                "enrich_prompt": prompt,
                "suggested_seed": seed,
                "chunks": chunks,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    pack_cmd = [
        str(SCUBIEE),
        "pack",
        prompt,
        str(ROOT),
        "--seed-file",
        seed_file,
        "--mode",
        "lean",
    ]
    if seed.get("symbol"):
        pack_cmd.extend(["--seed-symbol", str(seed["symbol"])])
    if seed.get("line") is not None:
        pack_cmd.extend(["--seed-line", str(seed["line"])])

    pack_payload = _run_json(pack_cmd, env={"CTX_TRACE_ENGINE": arm})
    pack_path = OUT_DIR / f"{cid}_pack_{arm}.json"
    pack_path.write_text(json.dumps(pack_payload, indent=2), encoding="utf-8")

    elapsed = round(time.perf_counter() - t0, 2)
    return {
        "id": cid,
        "family": case.get("family"),
        "task": case.get("task"),
        "enrich_prompt": prompt,
        "arm": arm,
        "seed": seed,
        "n_map_cards": len(cards),
        "n_chunks": len(chunks),
        "n_pack": len(pack_payload.get("pack") or []),
        "map_path": str(map_path.relative_to(ROOT)).replace("\\", "/"),
        "chunks_path": str(chunks_path.relative_to(ROOT)).replace("\\", "/"),
        "pack_path": str(pack_path.relative_to(ROOT)).replace("\\", "/"),
        "elapsed_s": elapsed,
        "scored": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", default=None, help="Subset e.g. b01 b02")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-phase0", action="store_true")
    ap.add_argument("--arm", default="composite_v1")
    args = ap.parse_args()

    if not SCUBIEE.is_file():
        print(f"missing scubiee exe: {SCUBIEE}", file=sys.stderr)
        return 2

    bundle = json.loads(QUERIES.read_text(encoding="utf-8"))
    cases = bundle["cases"]
    if args.ids:
        want = set(args.ids)
        cases = [c for c in cases if c["id"] in want]

    if args.dry_run:
        for c in cases:
            print(c["id"], c["family"], c["enrich_prompt"][:80])
        return 0

    phase0 = None
    if not args.skip_phase0:
        print("Phase0 gate…")
        phase0 = _require_phase0()
        print("Phase0 OK", phase0.get("faiss_product_repo", {}).get("n_hits"), "FAISS hits")

    rows: list[dict[str, Any]] = []
    for case in cases:
        print(f"== {case['id']} map→pack ({args.arm}) ==")
        row = run_case(case, arm=args.arm)
        rows.append(row)
        print(
            f"  seed={row['seed'].get('file')}::{row['seed'].get('symbol')} "
            f"cards={row['n_map_cards']} pack={row['n_pack']} {row['elapsed_s']}s"
        )

    summary = {
        "protocol": "blind10_pack_v1_phase1",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "arm": args.arm,
        "scored": False,
        "phase0": {
            "ok": True,
            "faiss_hits": (phase0 or {}).get("faiss_product_repo", {}).get("n_hits"),
            "meta_root": (phase0 or {}).get("faiss_product_repo", {}).get("meta_root"),
        }
        if phase0
        else {"skipped": True},
        "note": "FROZEN — do not score until Phase2 GT authored. No peeking.",
        "cases": rows,
    }
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {SUMMARY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
