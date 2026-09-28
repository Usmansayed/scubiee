"""Blind-20 triple pack Phase1: warm map → seeds → three MCP pack engines → freeze.

NO codebase GT peeking. Arms = shipped MCP packs:
  pack_context (composite_v1), pack_poly_embed, pack_semantic

Usage:
  python scripts/blind20_triple_pack_phase1.py
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


def _map_warm(query: str, *, k: int = 10) -> dict[str, Any]:
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
                "start_line": getattr(h, "start_line", None),
                "end_line": getattr(h, "end_line", None),
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


def _pick_seed(map_out: dict[str, Any]) -> dict[str, Any]:
    """Prefer packages/* with a real symbol (avoid empty-symbol thin packs)."""
    seed = dict(map_out.get("suggested_seed") or {})
    cards = list(map_out.get("cards") or [])

    def ok(c: dict[str, Any]) -> bool:
        f = str(c.get("file") or "").replace("\\", "/")
        s = str(c.get("symbol") or "").strip()
        if not f.startswith("packages/"):
            return False
        if not s:
            return False
        # Prefer functions over __init__ noise when possible
        return True

    if ok(seed):
        return {
            "file": str(seed["file"]).replace("\\", "/"),
            "symbol": str(seed.get("symbol") or "").strip(),
            "loc": seed.get("loc"),
            "source": "suggested_seed",
        }

    ranked = sorted(
        [c for c in cards if ok(c)],
        key=lambda c: (
            0 if str(c.get("symbol") or "").endswith(".__init__") else -1,
            -float(c.get("score") or 0),
            int(c.get("rank") or 99),
        ),
    )
    if ranked:
        c = ranked[0]
        return {
            "file": str(c["file"]).replace("\\", "/"),
            "symbol": str(c.get("symbol") or "").strip(),
            "loc": c.get("loc"),
            "source": "map_card",
        }

    # Last resort: any packages file
    for c in cards:
        f = str(c.get("file") or "").replace("\\", "/")
        if f.startswith("packages/"):
            return {
                "file": f,
                "symbol": str(c.get("symbol") or "").strip(),
                "loc": c.get("loc"),
                "source": "packages_fallback",
            }
    if cards:
        c = cards[0]
        return {
            "file": str(c.get("file") or "").replace("\\", "/"),
            "symbol": str(c.get("symbol") or "").strip(),
            "loc": c.get("loc"),
            "source": "top_card",
        }
    return {"file": "", "symbol": "", "source": "none"}


def _seed_chunks(map_out: dict[str, Any], seed: dict[str, Any], *, n: int = 3) -> list[dict[str, Any]]:
    chunks = []
    seen = set()
    for c in map_out.get("cards") or []:
        f = str(c.get("file") or "").replace("\\", "/")
        s = str(c.get("symbol") or "").strip()
        key = f"{f}::{s}"
        if key in seen:
            continue
        if not f.startswith("packages/"):
            continue
        seen.add(key)
        chunks.append(
            {
                "file": f,
                "symbol": s,
                "loc": c.get("loc"),
                "score": c.get("score"),
                "why": c.get("why"),
            }
        )
        if len(chunks) >= n:
            break
    # Ensure seed is first
    sid = f"{seed.get('file')}::{seed.get('symbol')}"
    chunks = [c for c in chunks if f"{c['file']}::{c['symbol']}" != sid]
    if seed.get("file"):
        chunks = [
            {
                "file": seed["file"],
                "symbol": seed.get("symbol") or "",
                "loc": seed.get("loc"),
                "score": 1.0,
                "why": "selected_seed",
            }
        ] + chunks
    return chunks[:n]


def _pack_arm(
    query: str,
    seed_file: str,
    seed_symbol: str,
    *,
    tool_name: str,
    engine: str,
) -> dict[str, Any]:
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
            tool_name=tool_name,
            prior_packed_ids=set(),  # fresh each arm (blind compare)
        )
        pack = out.get("pack") or []
        slim = []
        for p in pack[:16]:
            slim.append(
                {
                    "file": str(p.get("file") or "").replace("\\", "/"),
                    "symbol": p.get("symbol"),
                    "score": p.get("score"),
                    "loc": p.get("loc"),
                    "id": p.get("id"),
                    "chars": len(p.get("text") or ""),
                }
            )
        chain = []
        for c in (out.get("chain") or [])[:10]:
            chain.append(
                {
                    "id": c.get("id"),
                    "loc": c.get("loc"),
                    "edge": c.get("edge"),
                    "score": c.get("score"),
                }
            )
        return {
            "ok": bool(out.get("ok", True)) and not out.get("error"),
            "tool": tool_name,
            "engine": out.get("engine") or engine,
            "elapsed_s": round(time.perf_counter() - t0, 3),
            "n_pack": len(slim),
            "seed": out.get("seed"),
            "pack": slim,
            "chain": chain,
            "error": out.get("error"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "tool": tool_name,
            "engine": engine,
            "elapsed_s": round(time.perf_counter() - t0, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    sys.path.insert(0, str(ROOT / "packages"))
    os.environ.setdefault("CTX_TRUST_ID_FILE", "1")
    os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cases = json.loads(QUERIES.read_text(encoding="utf-8"))["cases"]
    t_all = time.perf_counter()
    print(
        f"Blind-20 triple pack: map×{len(cases)} then arms {[a[0] for a in PACK_ARMS]}",
        flush=True,
    )

    maps: dict[str, dict[str, Any]] = {}
    seeds: dict[str, dict[str, Any]] = {}
    for i, case in enumerate(cases, 1):
        cid = case["id"]
        q = case["enrich_prompt"]
        print(f"[map {i}/{len(cases)}] {cid} …", flush=True)
        m = _map_warm(q, k=10)
        maps[cid] = m
        seed = _pick_seed(m)
        seeds[cid] = seed
        (OUT_DIR / f"{cid}_map.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
        print(
            f"  {m['elapsed_s']}s cards={len(m.get('cards') or [])} "
            f"seed={seed.get('file')}::{seed.get('symbol')} ({seed.get('source')})",
            flush=True,
        )

    arm_results: dict[str, dict[str, Any]] = {c["id"]: {} for c in cases}
    for tool_name, engine in PACK_ARMS:
        print(f"\n=== {tool_name} engine={engine} ===", flush=True)
        from pipeline import context_trace as ct

        ct._CACHE.clear()
        for i, case in enumerate(cases, 1):
            cid = case["id"]
            q = case["enrich_prompt"]
            seed = seeds[cid]
            chunks = _seed_chunks(maps[cid], seed)
            # Production-like: enrich + seed path/symbol (+ chunk locs as query suffix)
            chunk_bits = " ".join(
                f"{c['file']}::{c['symbol']}" for c in chunks if c.get("symbol")
            )
            pack_q = f"{q} | seeds: {chunk_bits}".strip()
            print(
                f"[pack {tool_name} {i}/{len(cases)}] {cid} "
                f"{seed.get('file')}::{seed.get('symbol')}",
                flush=True,
            )
            if not seed.get("file"):
                arm_results[cid][tool_name] = {"ok": False, "error": "no_seed"}
                continue
            a = _pack_arm(
                pack_q,
                seed["file"],
                seed.get("symbol") or "",
                tool_name=tool_name,
                engine=engine,
            )
            a["seed_chunks"] = chunks
            a["pack_query"] = pack_q
            arm_results[cid][tool_name] = a
            print(
                f"  ok={a.get('ok')} n={a.get('n_pack')} {a.get('elapsed_s')}s "
                f"{a.get('error') or ''}",
                flush=True,
            )
            (OUT_DIR / f"{cid}_pack_{tool_name}.json").write_text(
                json.dumps(a, indent=2), encoding="utf-8"
            )

    rows: list[dict[str, Any]] = []
    for case in cases:
        cid = case["id"]
        m = maps[cid]
        seed = seeds[cid]
        row = {
            "id": cid,
            "family": case.get("family"),
            "task": case.get("task"),
            "enrich_prompt": case["enrich_prompt"],
            "map": {
                "elapsed_s": m.get("elapsed_s"),
                "n_cards": len(m.get("cards") or []),
                "suggested_seed": seed,
                "top_files": [c.get("file") for c in (m.get("cards") or [])[:5]],
                "top_symbols": [
                    {"file": c.get("file"), "symbol": c.get("symbol")}
                    for c in (m.get("cards") or [])[:5]
                ],
            },
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
        "note": "FROZEN. Author GT only after this file exists. No mid-run peeking.",
        "rows": rows,
    }
    RESULTS.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"DONE {result['elapsed_s']}s → {RESULTS}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
