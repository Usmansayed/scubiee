"""Blind-20 SIMPLE: warm-engine map → pack_context arms → freeze.

Uses the same engine MCP hits (CTX_ENGINE_URL :8765). No --local. No full-repo
compile_bundle venture bakeoff.

  python scripts/blind20_simple_map_pack.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "docs/superpowers/plans/2026-09-06-blind20-pack-queries.json"
OUT_DIR = ROOT / "docs/superpowers/plans/blind20_simple_runs"
RESULTS = ROOT / "docs/superpowers/plans/2026-09-06-blind20-simple-results.json"

# Production pack engines (CTX_TRACE_ENGINE). Use policy=strict so pack does not
# clear the repo cache on every call (policy=broad forces a polytrace one-shot reload).
PACK_ARMS = (
    ("composite_v1", "strict"),
    ("polytrace", "strict"),
    ("ultimate", "strict"),
)


def _map_warm(query: str, *, k: int = 10) -> dict[str, Any]:
    """Soft map via warm HTTP engine (same path MCP `map` uses under the hood)."""
    from pipeline.context_trace import pick_suggested_seed
    from pipeline.searcher import search_repo

    t0 = time.perf_counter()
    hits = search_repo(ROOT, query, top_k=k, use_server=True) or []
    cards = []
    for i, h in enumerate(hits, 1):
        f = str(getattr(h, "file", None) or "").replace("\\", "/")
        cards.append(
            {
                "rank": i,
                "file": f,
                "symbol": getattr(h, "symbol", None) or "",
                "score": float(getattr(h, "score", 0) or 0),
                "loc": getattr(h, "loc", None) or f"{f}:1-1",
                "why": (getattr(h, "snippet", None) or getattr(h, "text", None) or "")[:240],
            }
        )
    suggested = pick_suggested_seed(cards) if cards else None
    return {
        "ok": bool(cards),
        "tool": "map",
        "query": query,
        "cards": cards,
        "suggested_seed": suggested,
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "via": "search_repo(use_server=True)",
    }


def _pack_arm(
    query: str,
    seed_file: str,
    seed_symbol: str,
    *,
    engine: str,
    policy: str,
    clear_cache: bool = False,
) -> dict[str, Any]:
    from pipeline import context_trace as ct

    os.environ["CTX_TRACE_ENGINE"] = engine
    if clear_cache:
        ct._CACHE.clear()
    t0 = time.perf_counter()
    try:
        out = ct.run_pack_context(
            ROOT,
            query,
            seed_file=seed_file,
            seed_symbol=seed_symbol or "",
            mode="lean",
            policy=policy,
            k=12,
        )
        pack = out.get("pack") or out.get("heatmap") or []
        slim = []
        for p in pack[:16]:
            slim.append(
                {
                    "file": str(p.get("file") or "").replace("\\", "/"),
                    "symbol": p.get("symbol"),
                    "score": p.get("score"),
                    "loc": p.get("loc"),
                    "id": p.get("id"),
                }
            )
        return {
            "ok": bool(out.get("ok", True)) and not out.get("error"),
            "engine": engine,
            "policy": policy,
            "elapsed_s": round(time.perf_counter() - t0, 3),
            "n_pack": len(slim),
            "pack": slim,
            "error": out.get("error"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "engine": engine,
            "policy": policy,
            "elapsed_s": round(time.perf_counter() - t0, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    sys.path.insert(0, str(ROOT / "packages"))
    os.environ.setdefault("CTX_TRUST_ID_FILE", "1")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cases = json.loads(QUERIES.read_text(encoding="utf-8"))["cases"]
    t_all = time.perf_counter()

    print(f"Warm map × {len(cases)} then pack arms {[a[0] for a in PACK_ARMS]}", flush=True)

    # --- Phase A: maps only (warm engine) ---
    maps: dict[str, dict[str, Any]] = {}
    for i, case in enumerate(cases, 1):
        cid = case["id"]
        q = case["enrich_prompt"]
        print(f"[map {i}/{len(cases)}] {cid} …", flush=True)
        m = _map_warm(q, k=10)
        maps[cid] = m
        (OUT_DIR / f"{cid}_map.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
        seed = m.get("suggested_seed") or {}
        print(
            f"  {m['elapsed_s']}s cards={len(m.get('cards') or [])} "
            f"seed={seed.get('file')}::{seed.get('symbol')}",
            flush=True,
        )

    # Resolve seeds once
    seeds: dict[str, tuple[str, str]] = {}
    for case in cases:
        cid = case["id"]
        m = maps[cid]
        seed = dict(m.get("suggested_seed") or {})
        if not seed.get("file"):
            for c in m.get("cards") or []:
                f = str(c.get("file") or "")
                if f.startswith("packages/"):
                    seed = {"file": f, "symbol": c.get("symbol") or ""}
                    break
        seeds[cid] = (str(seed.get("file") or ""), str(seed.get("symbol") or ""))

    # --- Phase B: packs per engine (load AST once per engine, not per query) ---
    arm_results: dict[str, dict[str, Any]] = {c["id"]: {} for c in cases}
    for eng, pol in PACK_ARMS:
        print(f"\n=== pack engine={eng} policy={pol} (all {len(cases)} queries) ===", flush=True)
        for i, case in enumerate(cases, 1):
            cid = case["id"]
            q = case["enrich_prompt"]
            sf, ss = seeds[cid]
            print(f"[pack {eng} {i}/{len(cases)}] {cid} seed={sf}::{ss}", flush=True)
            if not sf:
                arm_results[cid][eng] = {"ok": False, "error": "no_seed"}
                continue
            # Only clear cache on first query of this engine
            clear = i == 1
            if clear:
                from pipeline import context_trace as ct

                prev = os.environ.get("CTX_TRACE_ENGINE")
                os.environ["CTX_TRACE_ENGINE"] = eng
                ct._CACHE.clear()
            a = _pack_arm(q, sf, ss, engine=eng, policy=pol, clear_cache=False)
            arm_results[cid][eng] = a
            print(
                f"  ok={a.get('ok')} n={a.get('n_pack')} {a.get('elapsed_s')}s {a.get('error') or ''}",
                flush=True,
            )
            (OUT_DIR / f"{cid}_pack_{eng}.json").write_text(
                json.dumps(a, indent=2), encoding="utf-8"
            )

    rows: list[dict[str, Any]] = []
    for case in cases:
        cid = case["id"]
        m = maps[cid]
        sf, ss = seeds[cid]
        row = {
            "id": cid,
            "family": case.get("family"),
            "task": case.get("task"),
            "enrich_prompt": case["enrich_prompt"],
            "map": {
                "elapsed_s": m.get("elapsed_s"),
                "n_cards": len(m.get("cards") or []),
                "suggested_seed": {"file": sf, "symbol": ss},
                "top_files": [c.get("file") for c in (m.get("cards") or [])[:5]],
            },
            "arms": arm_results[cid],
        }
        rows.append(row)
        (OUT_DIR / f"{cid}_row.json").write_text(json.dumps(row, indent=2), encoding="utf-8")

    result = {
        "protocol": "blind20_simple_warm_map_pack",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scored": False,
        "elapsed_s": round(time.perf_counter() - t_all, 2),
        "arms": [a[0] for a in PACK_ARMS],
        "note": "FROZEN maps+packs. GT/compare only after this file exists.",
        "rows": rows,
    }
    RESULTS.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"DONE {result['elapsed_s']}s → {RESULTS}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
