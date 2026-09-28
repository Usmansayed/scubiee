"""Phase1b: resolve symbol seeds via map_context on frozen soft-map files, then re-pack.

Still blind (no GT). Uses docs/.../blind20_triple_pack_runs/*_map.json.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "docs/superpowers/plans/2026-09-06-blind20-triple-pack-queries.json"
OUT_DIR = ROOT / "docs/superpowers/plans/blind20_triple_pack_runs"
RESULTS = ROOT / "docs/superpowers/plans/2026-09-06-blind20-triple-pack-results.json"

PACK_ARMS = (
    ("pack_context", "composite_v1"),
    ("pack_poly_embed", "poly_embed"),
    ("pack_semantic", "semantic_tracer_fuse"),
)


def _py_seed_file(soft_map: dict[str, Any]) -> str:
    for c in soft_map.get("cards") or []:
        f = str(c.get("file") or "").replace("\\", "/")
        if f.startswith("packages/") and f.endswith(".py"):
            return f
    return ""


def _resolve_via_map_context(query: str, seed_file: str) -> dict[str, Any]:
    from pipeline.context_trace import pick_suggested_seed, run_map_context

    t0 = time.perf_counter()
    out = run_map_context(ROOT, query, seed_file=seed_file, k=12)
    cards = list(out.get("heatmap") or out.get("cards") or [])
    seed = out.get("seed") or pick_suggested_seed(cards) or {}
    # Prefer function/method with non-empty symbol in seed file
    if not str(seed.get("symbol") or "").strip():
        for c in cards:
            if str(c.get("file") or "").replace("\\", "/") != seed_file:
                continue
            sym = str(c.get("symbol") or "").strip()
            if sym and c.get("kind") in {"function", "method", None, ""}:
                seed = c
                break
        if not str(seed.get("symbol") or "").strip() and cards:
            for c in cards:
                sym = str(c.get("symbol") or "").strip()
                if sym:
                    seed = c
                    break
    chunks = []
    for c in cards[:5]:
        chunks.append(
            {
                "file": str(c.get("file") or "").replace("\\", "/"),
                "symbol": c.get("symbol"),
                "loc": c.get("loc"),
                "score": c.get("score"),
                "kind": c.get("kind"),
            }
        )
    return {
        "ok": bool(out.get("ok", True)),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "seed_file": seed_file,
        "seed": {
            "file": str(seed.get("file") or seed_file).replace("\\", "/"),
            "symbol": str(seed.get("symbol") or "").strip(),
            "id": seed.get("id"),
            "loc": seed.get("loc"),
        },
        "chunks": chunks,
        "n_cards": len(cards),
        "error": out.get("error"),
    }


def _pack_arm(query: str, seed_file: str, seed_symbol: str, *, tool: str, engine: str) -> dict[str, Any]:
    from pipeline.context_trace import run_pack_context

    t0 = time.perf_counter()
    try:
        out = run_pack_context(
            ROOT,
            query,
            seed_file=seed_file,
            seed_symbol=seed_symbol or "",
            mode="lean",
            policy="strict",
            k=12,
            engine=engine,
            tool_name=tool,
            prior_packed_ids=set(),
        )
        pack = [
            {
                "file": str(p.get("file") or "").replace("\\", "/"),
                "symbol": p.get("symbol"),
                "score": p.get("score"),
                "loc": p.get("loc"),
                "id": p.get("id"),
                "chars": len(p.get("text") or ""),
            }
            for p in (out.get("pack") or [])[:16]
        ]
        chain = [
            {"id": c.get("id"), "loc": c.get("loc"), "edge": c.get("edge"), "score": c.get("score")}
            for c in (out.get("chain") or [])[:10]
        ]
        return {
            "ok": bool(out.get("ok", True)) and not out.get("error"),
            "tool": tool,
            "engine": out.get("engine") or engine,
            "elapsed_s": round(time.perf_counter() - t0, 3),
            "n_pack": len(pack),
            "seed": out.get("seed"),
            "pack": pack,
            "chain": chain,
            "error": out.get("error"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "tool": tool,
            "engine": engine,
            "elapsed_s": round(time.perf_counter() - t0, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    sys.path.insert(0, str(ROOT / "packages"))
    os.environ.setdefault("CTX_TRUST_ID_FILE", "1")
    os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")

    cases = json.loads(QUERIES.read_text(encoding="utf-8"))["cases"]
    t_all = time.perf_counter()

    # --- Resolve symbol seeds from soft maps ---
    seeds: dict[str, dict[str, Any]] = {}
    for i, case in enumerate(cases, 1):
        cid = case["id"]
        soft = json.loads((OUT_DIR / f"{cid}_map.json").read_text(encoding="utf-8"))
        sf = _py_seed_file(soft)
        print(f"[enrich-map {i}/{len(cases)}] {cid} seed_file={sf}", flush=True)
        if not sf:
            seeds[cid] = {"ok": False, "error": "no_py_seed_file"}
            continue
        resolved = _resolve_via_map_context(case["enrich_prompt"], sf)
        seeds[cid] = resolved
        (OUT_DIR / f"{cid}_enrich_seed.json").write_text(
            json.dumps(resolved, indent=2), encoding="utf-8"
        )
        print(
            f"  {resolved['elapsed_s']}s symbol={resolved['seed'].get('symbol')} "
            f"cards={resolved['n_cards']}",
            flush=True,
        )

    # --- Packs ---
    arm_results: dict[str, dict[str, Any]] = {c["id"]: {} for c in cases}
    for tool, engine in PACK_ARMS:
        print(f"\n=== {tool} / {engine} ===", flush=True)
        from pipeline import context_trace as ct

        ct._CACHE.clear()
        for i, case in enumerate(cases, 1):
            cid = case["id"]
            r = seeds[cid]
            seed = r.get("seed") or {}
            sf = str(seed.get("file") or "")
            ss = str(seed.get("symbol") or "")
            chunks = r.get("chunks") or []
            chunk_bits = " ".join(
                f"{c.get('file')}::{c.get('symbol')}" for c in chunks if c.get("symbol")
            )
            pack_q = f"{case['enrich_prompt']} | seeds: {chunk_bits}".strip()
            print(f"[pack {tool} {i}/{len(cases)}] {cid} {sf}::{ss}", flush=True)
            if not sf:
                arm_results[cid][tool] = {"ok": False, "error": "no_seed"}
                continue
            a = _pack_arm(pack_q, sf, ss, tool=tool, engine=engine)
            a["seed_chunks"] = chunks[:3]
            a["pack_query"] = pack_q
            arm_results[cid][tool] = a
            print(
                f"  ok={a.get('ok')} n={a.get('n_pack')} {a.get('elapsed_s')}s "
                f"{a.get('error') or ''}",
                flush=True,
            )
            (OUT_DIR / f"{cid}_pack_{tool}.json").write_text(
                json.dumps(a, indent=2), encoding="utf-8"
            )

    rows = []
    for case in cases:
        cid = case["id"]
        soft = json.loads((OUT_DIR / f"{cid}_map.json").read_text(encoding="utf-8"))
        r = seeds[cid]
        row = {
            "id": cid,
            "family": case.get("family"),
            "task": case.get("task"),
            "enrich_prompt": case["enrich_prompt"],
            "map": {
                "elapsed_s": soft.get("elapsed_s"),
                "n_cards": len(soft.get("cards") or []),
                "top_files": [c.get("file") for c in (soft.get("cards") or [])[:5]],
            },
            "enrich_seed": r,
            "arms": arm_results[cid],
        }
        rows.append(row)
        (OUT_DIR / f"{cid}_row.json").write_text(json.dumps(row, indent=2), encoding="utf-8")

    result = {
        "protocol": "blind20_triple_pack_v1",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scored": False,
        "elapsed_s": round(time.perf_counter() - t_all, 2),
        "arms": [a[0] for a in PACK_ARMS],
        "note": "FROZEN after enrich-map symbol resolve + triple pack. GT only after this.",
        "phase1b": True,
        "rows": rows,
    }
    RESULTS.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"DONE {result['elapsed_s']}s -> {RESULTS}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
