"""A/B: map k=12 vs map k=8 + pack_context — better starting point?

Arms:
  map_k12          — warm map top-12 files (file recall)
  map_k12_chunks   — same map, pick ≤3 relevant symbol chunks (no pack)
  map8_pack        — map k=8 → pick chunks → pack_context(query+chunks)

Usage:
  python scripts/blind20_map12_vs_map8_pack.py
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
GT = ROOT / "docs/superpowers/plans/2026-09-06-blind20-triple-pack-gt.json"
OUT_DIR = ROOT / "docs/superpowers/plans/blind20_map12_vs_map8_pack_runs"
RESULTS = ROOT / "docs/superpowers/plans/2026-09-06-blind20-map12-vs-map8-pack-results.json"
REPORT = ROOT / "docs/superpowers/plans/2026-09-06-blind20-map12-vs-map8-pack-report.md"

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _toks(s: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(s or "")}


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("./")


def _map_warm(query: str, *, k: int) -> dict[str, Any]:
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
            }
        )
    return {"ok": bool(cards), "k": k, "cards": cards, "elapsed_s": round(time.perf_counter() - t0, 3)}


def _map_files(cards: list[dict[str, Any]], *, n: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for c in cards:
        f = _norm(str(c.get("file") or ""))
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
    priv = name.startswith("_") and not name.startswith("__")
    priv_pen = 4.0 if priv and name.lower() not in q else 0.0
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
    hit += 0.35 * len(q & _toks(text[:800]))
    return hit + kind_bonus - priv_pen


def _select_chunks(query: str, files: list[str], nodes: dict[str, Any], *, max_chunks: int = 3) -> list[dict[str, Any]]:
    cands: list[tuple[float, dict[str, Any]]] = []
    file_set = set(files)
    for n in nodes.values():
        f = n.file.replace("\\", "/")
        if f not in file_set or n.kind not in {"function", "method", "class"}:
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
                },
            )
        )
    cands.sort(key=lambda x: (-x[0], x[1]["file"], x[1]["symbol"]))
    picked: list[dict[str, Any]] = []
    per_file: dict[str, int] = {}
    for _sc, ch in cands:
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
    if files and picked and picked[0]["file"] != files[0]:
        top = [ch for sc, ch in cands if ch["file"] == files[0]]
        if top:
            best = top[0]
            picked = [best] + [
                p for p in picked if not (p["file"] == best["file"] and p["symbol"] == best["symbol"])
            ]
            picked = picked[:max_chunks]
    return picked


def _pack_context(query: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    from pipeline.context_trace import run_pack_context

    if not chunks:
        return {"ok": False, "error": "no_chunks", "pack": [], "chain": [], "n_pack": 0}
    c0, c1 = chunks[0], (chunks[1] if len(chunks) > 1 else None)
    chunk_bits = " | ".join(f"{c['file']}::{c['symbol']}@{c['loc']}" for c in chunks)
    pack_q = f"{query}\nrelevant_chunks: {chunk_bits}"
    t0 = time.perf_counter()
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
        engine="composite_v1",
        tool_name="pack_context",
        prior_packed_ids=set(),
    )
    pack = [
        {
            "file": _norm(str(p.get("file") or "")),
            "symbol": p.get("symbol"),
            "loc": p.get("loc"),
            "id": p.get("id"),
            "chars": len(p.get("text") or ""),
        }
        for p in (out.get("pack") or [])[:16]
    ]
    chain = [
        {"id": c.get("id"), "loc": c.get("loc"), "edge": c.get("edge"), "symbol": c.get("symbol")}
        for c in (out.get("chain") or [])[:12]
    ]
    return {
        "ok": bool(out.get("ok", True)) and not out.get("error"),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "n_pack": len(pack),
        "pack": pack,
        "chain": chain,
        "seed": out.get("seed"),
        "error": out.get("error"),
    }


def _files_syms_from_cards(cards: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    files, syms = set(), set()
    for c in cards:
        f = _norm(str(c.get("file") or ""))
        s = str(c.get("symbol") or "").strip()
        if f:
            files.add(f)
        if s:
            syms.add(s)
            syms.add(s.split(".")[-1])
    return files, syms


def _files_syms_from_chunks(chunks: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    return _files_syms_from_cards(chunks)


def _files_syms_from_pack(arm: dict[str, Any]) -> tuple[set[str], set[str]]:
    files, syms = set(), set()
    for p in list(arm.get("pack") or []) + list(arm.get("chain") or []):
        f = _norm(str(p.get("file") or ""))
        s = str(p.get("symbol") or "").strip()
        iid = str(p.get("id") or "")
        loc = str(p.get("loc") or "")
        if "::" in iid:
            ff, ss = iid.split("::", 1)
            f = f or _norm(ff)
            s = s or ss.strip()
        if not f and ":" in loc:
            f = _norm(loc.split(":")[0])
        if f:
            files.add(f)
        if s:
            syms.add(s)
            syms.add(s.split(".")[-1])
    return files, syms


def _recall(got: set[str], must: list[str]) -> float:
    if not must:
        return 1.0
    hit = 0
    for m in must:
        ml = m.strip()
        if not ml:
            continue
        if ml in got or _norm(ml) in got or ml.split(".")[-1] in got:
            hit += 1
            continue
        if any(g.endswith(ml) or ml.endswith(g) for g in got):
            hit += 1
    return hit / len(must)


def main() -> int:
    sys.path.insert(0, str(ROOT / "packages"))
    os.environ.setdefault("CTX_TRUST_ID_FILE", "1")
    os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from pipeline.context_trace import _CACHE, _load_repo

    cases = json.loads(QUERIES.read_text(encoding="utf-8"))["cases"]
    gt = {c["id"]: c for c in json.loads(GT.read_text(encoding="utf-8"))["cases"]}
    print("Loading nodes…", flush=True)
    nodes = _load_repo(ROOT).nodes
    t_all = time.perf_counter()

    rows: list[dict[str, Any]] = []
    for i, case in enumerate(cases, 1):
        cid = case["id"]
        q = case["enrich_prompt"]
        print(f"[{i}/{len(cases)}] {cid}", flush=True)

        m12 = _map_warm(q, k=12)
        m8 = _map_warm(q, k=8)
        files12 = _map_files(m12["cards"], n=8)
        files8 = _map_files(m8["cards"], n=5)
        chunks12 = _select_chunks(q, files12, nodes, max_chunks=3)
        chunks8 = _select_chunks(q, files8, nodes, max_chunks=3)

        _CACHE.clear() if i == 1 else None
        pack = _pack_context(q, chunks8)

        g = gt[cid]
        must_f = list(g.get("must_files") or [])
        must_s = list(g.get("must_symbols") or [])

        map12_f, map12_s = _files_syms_from_cards(m12["cards"])
        ch12_f, ch12_s = _files_syms_from_chunks(chunks12)
        ch8_f, ch8_s = _files_syms_from_chunks(chunks8)
        pk_f, pk_s = _files_syms_from_pack(pack)
        pack_f, pack_s = pk_f | ch8_f, pk_s | ch8_s

        scores = {
            "map_k12": {
                "file": round(_recall(map12_f, must_f), 3),
                "symbol": round(_recall(map12_s, must_s), 3) if must_s else 1.0,
                "note": "raw map cards (symbols often empty)",
            },
            "map_k12_chunks": {
                "file": round(_recall(ch12_f, must_f), 3),
                "symbol": round(_recall(ch12_s, must_s), 3) if must_s else 1.0,
                "chunks": [c.get("symbol") for c in chunks12],
            },
            "map8_pack": {
                "file": round(_recall(pack_f, must_f), 3),
                "symbol": round(_recall(pack_s, must_s), 3) if must_s else 1.0,
                "n_pack": pack.get("n_pack"),
                "chunks": [c.get("symbol") for c in chunks8],
                "elapsed_s": pack.get("elapsed_s"),
            },
        }
        row = {
            "id": cid,
            "family": case.get("family"),
            "task": case.get("task"),
            "must_files": must_f,
            "must_symbols": must_s,
            "map_k12": {"elapsed_s": m12["elapsed_s"], "top_files": [_norm(c["file"]) for c in m12["cards"][:8]]},
            "map_k8": {"elapsed_s": m8["elapsed_s"], "top_files": [_norm(c["file"]) for c in m8["cards"][:5]]},
            "chunks_k12": chunks12,
            "chunks_k8": chunks8,
            "pack": pack,
            "scores": scores,
        }
        rows.append(row)
        (OUT_DIR / f"{cid}.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        print(
            f"  map12_f={scores['map_k12']['file']} "
            f"map12_chunks={scores['map_k12_chunks']['symbol']}/{scores['map_k12_chunks']['file']} "
            f"map8_pack={scores['map8_pack']['symbol']}/{scores['map8_pack']['file']} "
            f"n_pack={pack.get('n_pack')}",
            flush=True,
        )

    # Aggregate
    arms = ["map_k12", "map_k12_chunks", "map8_pack"]
    mean_f = {a: 0.0 for a in arms}
    mean_s = {a: 0.0 for a in arms}
    for row in rows:
        for a in arms:
            mean_f[a] += row["scores"][a]["file"]
            mean_s[a] += row["scores"][a]["symbol"]
    n = len(rows)
    mean_f = {k: round(v / n, 3) for k, v in mean_f.items()}
    mean_s = {k: round(v / n, 3) for k, v in mean_s.items()}

    # Winner for "starting point": symbol first (exact), then file; map_k12 raw symbols ignored as unfair
    start_arms = ["map_k12_chunks", "map8_pack"]
    winner = max(start_arms, key=lambda a: (mean_s[a], mean_f[a]))
    # Also note raw map file coverage
    file_leader = max(arms, key=lambda a: mean_f[a])

    result = {
        "protocol": "blind20_map12_vs_map8_pack",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.perf_counter() - t_all, 2),
        "n": n,
        "mean_must_file": mean_f,
        "mean_must_symbol": mean_s,
        "starting_point_winner": winner,
        "file_coverage_leader": file_leader,
        "rows": rows,
    }
    RESULTS.write_text(json.dumps(result, indent=2), encoding="utf-8")

    lines = [
        "# Map k=12 vs map k=8 + pack_context",
        "",
        f"Cases: **{n}** · wall **{result['elapsed_s']}s**",
        "",
        f"**Starting-point winner (symbol→file):** `{winner}`",
        f"**File coverage leader:** `{file_leader}`",
        "",
        "## Means",
        "",
        "| Arm | Must-file | Must-symbol | What agent gets |",
        "|-----|-----------|-------------|-----------------|",
        f"| map k=12 (raw cards) | {mean_f['map_k12']} | {mean_s['map_k12']} | file list (symbols usually empty) |",
        f"| map k=12 + chunk pick (no pack) | {mean_f['map_k12_chunks']} | {mean_s['map_k12_chunks']} | 3 symbol locs, no bodies/chain |",
        f"| map k=8 + chunks + **pack_context** | {mean_f['map8_pack']} | {mean_s['map8_pack']} | chunks + bodies + call chain |",
        "",
        "## Read",
        "",
        "- Raw map@12 wins **files** if symbols empty — good neighborhood, not exact funcs.",
        "- Chunk-pick from wider map ≈ chunk-pick from map@8 if top files overlap.",
        "- pack_context wins if it lifts **symbol** recall and/or delivers bodies (exact starting code).",
        "",
        "## Per case (sym/file)",
        "",
    ]
    for row in rows:
        s = row["scores"]
        lines.append(
            f"- {row['id']} map12={s['map_k12']['file']} "
            f"chunks12={s['map_k12_chunks']['symbol']}/{s['map_k12_chunks']['file']} "
            f"pack={s['map8_pack']['symbol']}/{s['map8_pack']['file']} "
            f"n={s['map8_pack']['n_pack']}"
        )
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "mean_file": mean_f,
        "mean_symbol": mean_s,
        "starting_point_winner": winner,
        "file_coverage_leader": file_leader,
        "elapsed_s": result["elapsed_s"],
    }, indent=2))
    print(f"wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
