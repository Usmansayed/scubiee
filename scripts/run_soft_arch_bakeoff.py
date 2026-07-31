"""Soft-query architecture bake-off (locked soft_bank).

Controls: baseline_graphify, D_rerank, C_gear, A_minrank_expand, B_ppr
Experiments: D_floor, D_hippo, X_soft

Soft gates vs D_rerank:
  1. soft R@5 >= D
  2. g_win slice R@5 >= 3/4
  3. d_win slice does not fall by more than 1 query vs D

Usage:
  .\\.venv\\Scripts\\python -u scripts/run_soft_arch_bakeoff.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT))

from conductor.architectures import MultiArchConductor  # noqa: E402
from conductor.bm25_index import BM25Index  # noqa: E402
from conductor.conductor import ConductorConfig  # noqa: E402
from conductor.dense_index import DenseIndex, load_cache, text_key  # noqa: E402
from conductor.graphify_retriever import (  # noqa: E402
    ChunkSpan,
    GraphifyChunkRetriever,
    load_or_build_graph,
)
from conductor.soft_bank import SOFT_BANK, SOFT_BLURB  # noqa: E402
from conductor_arch_benchmark import (  # noqa: E402
    EMBED_CACHE,
    GRAPH_JSON,
    REPO,
    collect_py_paths,
    embed_query,
    eval_rows,
    match_gold,
    unique_files,
)
from enrich import chunk_repo_from_ir  # noqa: E402
from graphify.extract import extract  # noqa: E402
from parse_harness.graphify_adapter import graphify_to_repo_ir  # noqa: E402

OUT = ROOT / "out" / "conductor_soft_bakeoff.json"

ARCHS = [
    "baseline_graphify",
    "D_rerank",
    "R_gated_floor",
]


def _slice_stats(rows: list[dict], bucket: str) -> dict:
    sub = [r for r in rows if r["bucket"] == bucket]
    n = len(sub)
    if n == 0:
        return {"n": 0, "recall_at_5": None, "hits": 0}
    hits = sum(1 for r in sub if r["hit_at_5"])
    return {"n": n, "recall_at_5": round(hits / n, 4), "hits": hits}


def _gate(summary: dict) -> dict:
    d = summary["D_rerank"]
    out = {}
    for arch, s in summary.items():
        if arch == "D_rerank":
            continue
        soft_ok = s["recall_at_5"] >= d["recall_at_5"]
        g_ok = (s["slices"]["g_win"]["hits"] or 0) >= 3
        d_drop = d["slices"]["d_win"]["hits"] - s["slices"]["d_win"]["hits"]
        d_ok = d_drop <= 1
        accept = soft_ok and g_ok and d_ok
        out[arch] = {
            "soft_r5_ge_D": soft_ok,
            "g_win_hits_ge_3": g_ok,
            "d_win_drop_le_1": d_ok,
            "d_win_drop": d_drop,
            "accept_soft_gate": accept,
        }
    return out


def main() -> None:
    print(SOFT_BLURB, flush=True)
    t0 = time.perf_counter()
    root = REPO.resolve()
    paths = collect_py_paths(root)
    extraction = extract(paths, root=root, cache_root=root, parallel=True)
    ir = graphify_to_repo_ir(
        extraction,
        root=root,
        elapsed_ms=(time.perf_counter() - t0) * 1000,
        file_count=len(paths),
    )
    chunks = chunk_repo_from_ir(ir, root)
    texts = [c.content for c in chunks]
    files = [c.file.replace("\\", "/") for c in chunks]
    spans = [
        ChunkSpan(index=i, file=files[i], start_line=c.start_line, end_line=c.end_line)
        for i, c in enumerate(chunks)
    ]
    print(f"chunks={len(chunks)} ({time.perf_counter() - t0:.1f}s)", flush=True)

    G = load_or_build_graph(extraction, root, GRAPH_JSON)
    graph = GraphifyChunkRetriever(G, spans, depth=2)
    cache = load_cache(EMBED_CACHE)
    bm25 = BM25Index(texts)
    dense = DenseIndex.from_texts_and_cache(texts, cache)
    cond = MultiArchConductor(
        files=files, bm25=bm25, dense=dense, graph=graph, config=ConductorConfig()
    )

    qvecs: dict[str, np.ndarray] = {}
    for g in SOFT_BANK:
        k = text_key(g["query"])
        if k in cache:
            vec = np.asarray(cache[k], dtype=np.float32)
        else:
            vec = np.asarray(embed_query(g["query"]), dtype=np.float32)
            EMBED_CACHE.parent.mkdir(parents=True, exist_ok=True)
            with EMBED_CACHE.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": k, "embedding": vec.tolist()}) + "\n")
            cache[k] = vec.tolist()
        qvecs[g["id"]] = vec
    print(f"embedded {len(qvecs)} queries", flush=True)

    summary: dict = {}
    all_rows: dict = {}
    for arch in ARCHS:
        rows = []
        t1 = time.perf_counter()
        for g in SOFT_BANK:
            hits = cond.retrieve_arch(arch, g["query"], qvecs[g["id"]], top_k=15)
            top_files = unique_files(hits)[:10]
            rank = match_gold(top_files, g["files_substr"])
            rows.append(
                {
                    "id": g["id"],
                    "bucket": g["bucket"],
                    "rank": rank,
                    "hit_at_5": rank is not None and rank <= 5,
                    "top3": top_files[:3],
                }
            )
        elapsed = time.perf_counter() - t1
        metrics = eval_rows(rows, 5)
        slices = {
            b: _slice_stats(rows, b)
            for b in ("d_win", "g_win", "tie", "miss_both")
        }
        summary[arch] = {
            **metrics,
            "latency_s": round(elapsed, 3),
            "slices": slices,
        }
        all_rows[arch] = rows
        print(
            f"{arch:22} R@5={metrics['recall_at_5']:.3f} MRR={metrics['mrr']:.3f} "
            f"g_win={slices['g_win']['hits']}/{slices['g_win']['n']} "
            f"d_win={slices['d_win']['hits']}/{slices['d_win']['n']}",
            flush=True,
        )

    gates = _gate(summary)
    print("\n=== Soft gates vs D_rerank ===", flush=True)
    for arch, g in gates.items():
        mark = "ACCEPT" if g["accept_soft_gate"] else "REJECT"
        print(f"  {arch:22} {mark}  {g}", flush=True)

    report = {
        "blurb": SOFT_BLURB,
        "n": len(SOFT_BANK),
        "archs": ARCHS,
        "summary": summary,
        "soft_gates": gates,
        "rows": all_rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
