"""Blind-20 production loop: map → pick relevant chunks → pack(query+chunks).

1) Warm soft-map → candidate files
2) Score in-file symbols vs enrich query (prefer real functions, skip _helpers)
3) Feed top chunks + query into all three pack tools (seed + seed2)
4) Freeze — GT scoring is separate (phase2)

Usage:
  python scripts/blind20_map_chunks_pack.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "docs/superpowers/plans/2026-09-06-blind20-triple-pack-queries.json"
OUT_DIR = ROOT / "docs/superpowers/plans/blind20_map_chunks_pack_runs"
RESULTS = ROOT / "docs/superpowers/plans/2026-09-06-blind20-map-chunks-pack-results.json"

PACK_ARMS = (
    ("pack_context", "composite_v1"),
    ("pack_poly_embed", "poly_embed"),
    ("pack_semantic", "semantic_tracer_fuse"),
)

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _toks(s: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(s or "")}


def _map_warm(query: str, *, k: int = 10) -> dict[str, Any]:
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
    return {
        "ok": bool(cards),
        "query": query,
        "cards": cards,
        "elapsed_s": round(time.perf_counter() - t0, 3),
    }


def _map_files(soft: dict[str, Any], *, n: int = 5) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for c in soft.get("cards") or []:
        f = str(c.get("file") or "").replace("\\", "/")
        if not f.startswith("packages/") or not f.endswith(".py"):
            continue
        if f in seen:
            continue
        seen.add(f)
        out.append(f)
        if len(out) >= n:
            break
    return out


def _score_symbol(query: str, file: str, symbol: str, kind: str, text: str) -> float:
    q = _toks(query)
    name = (symbol or "").split(".")[-1]
    if not name or name in {"ROOT", "__init__"}:
        return -1e9
    # Prefer real functions; demote private helpers unless query names them
    priv = name.startswith("_") and not name.startswith("__")
    if priv and name.lower() not in q:
        priv_pen = 4.0
    else:
        priv_pen = 0.0
    kind_bonus = {"function": 3.0, "method": 2.5, "class": 0.5, "const": -1.0}.get(kind, 0.0)
    name_l = name.lower()
    sym_l = (symbol or "").lower()
    hit = 0.0
    for t in q:
        if t == name_l or t in name_l or name_l in t:
            hit += 3.0
        elif t in sym_l:
            hit += 1.5
        elif t in file.lower().replace("/", " ").replace(".", " ").replace("_", " "):
            hit += 0.15
    # Light body overlap (caps noise)
    body = _toks(text[:800])
    hit += 0.35 * len(q & body)
    return hit + kind_bonus - priv_pen


def _select_chunks(
    query: str,
    files: list[str],
    nodes: dict[str, Any],
    *,
    max_chunks: int = 3,
) -> list[dict[str, Any]]:
    cands: list[tuple[float, dict[str, Any]]] = []
    file_set = set(files)
    for n in nodes.values():
        f = n.file.replace("\\", "/")
        if f not in file_set:
            continue
        if n.kind not in {"function", "method", "class"}:
            continue
        sc = _score_symbol(query, f, n.symbol, n.kind, n.text or "")
        if sc < -100:
            continue
        cands.append(
            (
                sc,
                {
                    "file": f,
                    "symbol": n.symbol,
                    "kind": n.kind,
                    "loc": f"{f}:{n.start_line}-{n.end_line}",
                    "start_line": n.start_line,
                    "end_line": n.end_line,
                    "score": round(sc, 3),
                    "excerpt": (n.text or "")[:180],
                },
            )
        )
    cands.sort(key=lambda x: (-x[0], x[1]["file"], x[1]["symbol"]))
    # Diversity: at most 2 from same file, prefer covering multiple map files
    picked: list[dict[str, Any]] = []
    per_file: dict[str, int] = {}
    for sc, ch in cands:
        if sc < 0.5 and picked:
            # keep searching for a better first seed
            if not picked:
                continue
        f = ch["file"]
        if per_file.get(f, 0) >= 2:
            continue
        key = f"{f}::{ch['symbol']}"
        if any(f"{p['file']}::{p['symbol']}" == key for p in picked):
            continue
        picked.append(ch)
        per_file[f] = per_file.get(f, 0) + 1
        if len(picked) >= max_chunks:
            break
    # Guarantee at least one chunk from top map file if possible
    if files and (not picked or picked[0]["file"] != files[0]):
        top = [ch for sc, ch in cands if ch["file"] == files[0]]
        if top:
            best = top[0]
            picked = [best] + [p for p in picked if p["file"] != files[0] or p["symbol"] != best["symbol"]]
            picked = picked[:max_chunks]
    return picked


def _pack_arm(
    query: str,
    chunks: list[dict[str, Any]],
    *,
    tool: str,
    engine: str,
) -> dict[str, Any]:
    from pipeline.context_trace import run_pack_context

    if not chunks:
        return {"ok": False, "tool": tool, "engine": engine, "error": "no_chunks"}
    c0 = chunks[0]
    c1 = chunks[1] if len(chunks) > 1 else None
    chunk_bits = " | ".join(f"{c['file']}::{c['symbol']}@{c['loc']}" for c in chunks)
    pack_q = f"{query}\nrelevant_chunks: {chunk_bits}"
    t0 = time.perf_counter()
    try:
        out = run_pack_context(
            ROOT,
            pack_q,
            seed_file=c0["file"],
            seed_symbol=c0.get("symbol") or "",
            seed_line=int(c0.get("start_line") or 0),
            seed2_file=(c1 or {}).get("file") or "",
            seed2_symbol=(c1 or {}).get("symbol") or "",
            seed2_line=int((c1 or {}).get("start_line") or 0),
            mode="lean",
            policy="strict",
            k=16,
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
            for c in (out.get("chain") or [])[:12]
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
            "pack_query": pack_q,
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
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from pipeline.context_trace import _load_repo

    cases = json.loads(QUERIES.read_text(encoding="utf-8"))["cases"]
    t_all = time.perf_counter()
    print(f"map→chunks→pack x{len(cases)} arms={[a[0] for a in PACK_ARMS]}", flush=True)

    print("Loading trace nodes once…", flush=True)
    rt = _load_repo(ROOT)
    nodes = rt.nodes

    maps: dict[str, Any] = {}
    chunks_by: dict[str, list[dict[str, Any]]] = {}
    for i, case in enumerate(cases, 1):
        cid = case["id"]
        q = case["enrich_prompt"]
        print(f"[map {i}/{len(cases)}] {cid}", flush=True)
        soft = _map_warm(q, k=10)
        files = _map_files(soft, n=5)
        chunks = _select_chunks(q, files, nodes, max_chunks=3)
        maps[cid] = soft
        chunks_by[cid] = chunks
        (OUT_DIR / f"{cid}_map.json").write_text(json.dumps(soft, indent=2), encoding="utf-8")
        (OUT_DIR / f"{cid}_chunks.json").write_text(json.dumps(chunks, indent=2), encoding="utf-8")
        print(
            f"  map={soft['elapsed_s']}s files={files[:3]} "
            f"chunks={[c['symbol'] for c in chunks]}",
            flush=True,
        )

    arm_results: dict[str, dict[str, Any]] = {c["id"]: {} for c in cases}
    for tool, engine in PACK_ARMS:
        print(f"\n=== {tool} / {engine} ===", flush=True)
        from pipeline import context_trace as ct

        ct._CACHE.clear()
        for i, case in enumerate(cases, 1):
            cid = case["id"]
            chunks = chunks_by[cid]
            print(
                f"[pack {tool} {i}/{len(cases)}] {cid} "
                f"{[c.get('symbol') for c in chunks]}",
                flush=True,
            )
            a = _pack_arm(case["enrich_prompt"], chunks, tool=tool, engine=engine)
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
        soft = maps[cid]
        row = {
            "id": cid,
            "family": case.get("family"),
            "task": case.get("task"),
            "enrich_prompt": case["enrich_prompt"],
            "map": {
                "elapsed_s": soft.get("elapsed_s"),
                "top_files": [c.get("file") for c in (soft.get("cards") or [])[:5]],
            },
            "selected_chunks": chunks_by[cid],
            "arms": arm_results[cid],
        }
        rows.append(row)
        (OUT_DIR / f"{cid}_row.json").write_text(json.dumps(row, indent=2), encoding="utf-8")

    result = {
        "protocol": "blind20_map_chunks_pack_v1",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scored": False,
        "elapsed_s": round(time.perf_counter() - t_all, 2),
        "arms": [a[0] for a in PACK_ARMS],
        "note": "Production loop: map → select relevant chunks → pack(query+chunks).",
        "rows": rows,
    }
    RESULTS.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"DONE {result['elapsed_s']}s -> {RESULTS}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
