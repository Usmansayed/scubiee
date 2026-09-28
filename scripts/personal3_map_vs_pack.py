"""Personal 3-query A/B: map-only vs map+pack_context (blind enrich prompts).

Queries authored without naming files/functions. Store full payloads for compare.
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
OUT = ROOT / "docs/superpowers/plans/2026-09-06-personal3-map-vs-pack.json"
OUT_MD = ROOT / "docs/superpowers/plans/2026-09-06-personal3-map-vs-pack.md"

# Blind enrich prompts: developer intent + vocab, NO known file/symbol names.
CASES = [
    {
        "id": "p01",
        "task": "I need to figure out how the tool gets wired into my editor when I connect it.",
        "enrich_query": (
            "when I run connect how does the tool install into the editor "
            "write mcp config permissions allowlist auto approve project rules "
            "gate text so the agent can call locate tools"
        ),
    },
    {
        "id": "p02",
        "task": "Search feels stale after I edit files — how does refresh / sync decide to update?",
        "enrich_query": (
            "after I change code when does background sync or freshness decide "
            "the index is stale and refresh embeddings or search without full rebuild"
        ),
    },
    {
        "id": "p03",
        "task": "I want to understand how a pack request turns a seed into a small set of code bodies.",
        "enrich_query": (
            "how does pack take a seed and query then walk calls to build a lean "
            "heatmap and return hottest function bodies under a character budget"
        ),
    },
]

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
        f = _norm(str(getattr(h, "file", None) or ""))
        cards.append(
            {
                "rank": i,
                "file": f,
                "symbol": getattr(h, "symbol", None) or "",
                "score": float(getattr(h, "score", 0) or 0),
                "chunk_id": getattr(h, "chunk_id", None),
                "preview": (getattr(h, "preview", None) or "")[:280],
                "source": getattr(h, "source", None),
                "loc": getattr(h, "loc", None) or f"{f}:1-1",
            }
        )
    return {
        "ok": bool(cards),
        "k": k,
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "cards": cards,
    }


def _map_files(cards: list[dict[str, Any]], *, n: int = 5) -> list[str]:
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
    kind_bonus = {"function": 3.0, "method": 2.5, "class": 0.5}.get(kind, 0.0)
    name_l, sym_l = name.lower(), (symbol or "").lower()
    hit = 0.0
    for t in q:
        if t == name_l or t in name_l or name_l in t:
            hit += 3.0
        elif t in sym_l:
            hit += 1.5
        elif t in file.lower().replace("/", " ").replace("_", " ").replace(".", " "):
            hit += 0.2
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
                    "excerpt": (n.text or "")[:220],
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
    return picked


def _pack(query: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    from pipeline.context_trace import run_pack_context

    if not chunks:
        return {"ok": False, "error": "no_chunks", "pack": [], "chain": []}
    c0 = chunks[0]
    c1 = chunks[1] if len(chunks) > 1 else None
    bits = " | ".join(f"{c['file']}::{c['symbol']}@{c['loc']}" for c in chunks)
    pack_q = f"{query}\nrelevant_chunks: {bits}"
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
    pack = []
    for p in out.get("pack") or []:
        pack.append(
            {
                "file": _norm(str(p.get("file") or "")),
                "symbol": p.get("symbol"),
                "loc": p.get("loc"),
                "id": p.get("id"),
                "score": p.get("score"),
                "chars": len(p.get("text") or ""),
                "text": p.get("text") or "",
            }
        )
    chain = [
        {
            "id": c.get("id"),
            "loc": c.get("loc"),
            "edge": c.get("edge"),
            "score": c.get("score"),
        }
        for c in (out.get("chain") or [])[:12]
    ]
    return {
        "ok": bool(out.get("ok", True)) and not out.get("error"),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "engine": out.get("engine") or "composite_v1",
        "seed": out.get("seed"),
        "n_pack": len(pack),
        "pack": pack,
        "chain": chain,
        "pack_query": pack_q,
        "error": out.get("error"),
        "cold": [
            {"id": c.get("id"), "loc": c.get("loc"), "score": c.get("score")}
            for c in (out.get("cold") or [])[:12]
        ],
    }


def _compare_row(case: dict[str, Any], map12: dict[str, Any], chunks: list[dict[str, Any]], pack: dict[str, Any]) -> dict[str, Any]:
    map_files = [_norm(c["file"]) for c in map12.get("cards") or [] if c.get("file")]
    pack_files = sorted(
        {
            _norm(p.get("file") or "")
            for p in (pack.get("pack") or [])
            if p.get("file")
        }
        | {
            _norm(str(c.get("id") or "").split("::")[0])
            for c in (pack.get("chain") or [])
            if "::" in str(c.get("id") or "")
        }
    )
    pack_syms = [p.get("symbol") for p in (pack.get("pack") or [])]
    body_chars = sum(int(p.get("chars") or 0) for p in (pack.get("pack") or []))
    return {
        "map_only": {
            "what_you_get": "ranked files + short previews; usually no function names/bodies",
            "n_cards": len(map12.get("cards") or []),
            "files": map_files,
            "symbols_on_cards": [c.get("symbol") for c in (map12.get("cards") or [])],
            "elapsed_s": map12.get("elapsed_s"),
            "can_start_reading_files": True,
            "has_function_bodies": False,
            "has_call_chain": False,
        },
        "map_plus_pack": {
            "what_you_get": "selected symbol chunks + pack bodies + call chain",
            "selected_chunks": [
                {"file": c["file"], "symbol": c["symbol"], "loc": c["loc"], "score": c["score"]}
                for c in chunks
            ],
            "n_pack_bodies": pack.get("n_pack"),
            "pack_symbols": pack_syms,
            "pack_files": pack_files,
            "chain": pack.get("chain"),
            "body_chars": body_chars,
            "elapsed_s_pack": pack.get("elapsed_s"),
            "can_start_reading_files": True,
            "has_function_bodies": body_chars > 0,
            "has_call_chain": bool(pack.get("chain")),
        },
        "delta": {
            "files_only_in_map": sorted(set(map_files) - set(pack_files)),
            "files_only_in_pack": sorted(set(pack_files) - set(map_files)),
            "symbols_pack_added": pack_syms,
            "bodies_bytes": body_chars,
            "verdict_hint": (
                "pack_better_for_exact_edit"
                if body_chars > 200 and pack_syms
                else "map_enough_for_file_skimming"
            ),
        },
    }


def main() -> int:
    sys.path.insert(0, str(ROOT / "packages"))
    os.environ.setdefault("CTX_TRUST_ID_FILE", "1")
    os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")

    from pipeline.context_trace import _CACHE, _load_repo

    print("Loading nodes…", flush=True)
    nodes = _load_repo(ROOT).nodes
    _CACHE.clear()
    t0 = time.perf_counter()
    rows = []

    for i, case in enumerate(CASES, 1):
        q = case["enrich_query"]
        print(f"[{i}/3] {case['id']}: map…", flush=True)
        m12 = _map_warm(q, k=12)
        files = _map_files(m12["cards"], n=5)
        chunks = _select_chunks(q, files, nodes, max_chunks=3)
        print(f"  chunks={[c['symbol'] for c in chunks]} → pack…", flush=True)
        pack = _pack(q, chunks)
        cmp_ = _compare_row(case, m12, chunks, pack)
        row = {
            "id": case["id"],
            "task": case["task"],
            "enrich_query": q,
            "arm_map_k12": m12,
            "selected_chunks": chunks,
            "arm_map8ish_plus_pack_context": pack,
            "compare": cmp_,
        }
        rows.append(row)
        print(
            f"  map_files={len(cmp_['map_only']['files'])} "
            f"pack_n={pack.get('n_pack')} body_chars={cmp_['map_plus_pack']['body_chars']} "
            f"verdict={cmp_['delta']['verdict_hint']}",
            flush=True,
        )

    doc = {
        "protocol": "personal3_map_vs_map_pack",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "note": (
            "3 blind enrich queries (no known file/function names). "
            "Arms: warm map k=12 vs map→chunk-pick→pack_context."
        ),
        "cases": rows,
        "summary": {
            "n": len(rows),
            "map_avg_cards": round(
                sum(len(r["arm_map_k12"]["cards"]) for r in rows) / len(rows), 2
            ),
            "pack_avg_bodies": round(
                sum(int(r["arm_map8ish_plus_pack_context"].get("n_pack") or 0) for r in rows)
                / len(rows),
                2,
            ),
            "pack_avg_body_chars": round(
                sum(int(r["compare"]["map_plus_pack"]["body_chars"]) for r in rows) / len(rows),
                1,
            ),
            "verdicts": [r["compare"]["delta"]["verdict_hint"] for r in rows],
        },
    }
    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    lines = [
        "# Personal 3: map vs map+pack",
        "",
        "Blind enrich queries (no known paths/symbols). Full JSON: "
        f"`{OUT.relative_to(ROOT).as_posix()}`",
        "",
        f"Wall: **{doc['elapsed_s']}s**",
        "",
        "## Summary",
        "",
        f"- map avg cards: {doc['summary']['map_avg_cards']}",
        f"- pack avg bodies: {doc['summary']['pack_avg_bodies']}",
        f"- pack avg body chars: {doc['summary']['pack_avg_body_chars']}",
        f"- verdicts: {doc['summary']['verdicts']}",
        "",
    ]
    for r in rows:
        c = r["compare"]
        lines += [
            f"## {r['id']} — {r['task']}",
            "",
            f"**Enrich:** `{r['enrich_query']}`",
            "",
            "### Map-only (k=12)",
            f"- files: `{c['map_only']['files'][:8]}`",
            f"- symbols on cards: `{c['map_only']['symbols_on_cards'][:8]}`",
            f"- bodies/chain: no / no · {c['map_only']['elapsed_s']}s",
            "",
            "### Map + pack_context",
            f"- chunks: `{[x['symbol'] for x in c['map_plus_pack']['selected_chunks']]}`",
            f"- pack symbols: `{c['map_plus_pack']['pack_symbols']}`",
            f"- locs: `{[p.get('loc') for p in r['arm_map8ish_plus_pack_context'].get('pack') or []]}`",
            f"- body_chars: **{c['map_plus_pack']['body_chars']}** · chain edges: "
            f"`{[x.get('edge') for x in (c['map_plus_pack'].get('chain') or [])]}`",
            f"- verdict: **{c['delta']['verdict_hint']}**",
            "",
        ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(doc["summary"], indent=2))
    print(f"wrote {OUT}")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
