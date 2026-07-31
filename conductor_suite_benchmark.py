"""Multi-suite architecture bake-off — no per-suite tuning.

Runs the same arch set across 5 deliberately different gold suites and reports
per-suite R@5 plus macro-average (primary ranking key).

Usage:
  .\\.venv\\Scripts\\python -u conductor_suite_benchmark.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "packages"))

from conductor.architectures import MultiArchConductor  # noqa: E402
from conductor.bm25_index import BM25Index  # noqa: E402
from conductor.conductor import ConductorConfig  # noqa: E402
from conductor.dense_index import DenseIndex, load_cache, text_key  # noqa: E402
from conductor.graphify_retriever import (  # noqa: E402
    ChunkSpan,
    GraphifyChunkRetriever,
    load_or_build_graph,
)
from conductor.suite_bank import SUITE_BLURBS, SUITES  # noqa: E402
from enrich import chunk_repo_from_ir  # noqa: E402
from parse_harness.graphify_adapter import graphify_to_repo_ir  # noqa: E402
from graphify.extract import collect_files, extract  # noqa: E402

# Reuse helpers / constants from arch benchmark
from conductor_arch_benchmark import (  # noqa: E402
    EMBED_CACHE,
    GRAPH_JSON,
    MODEL,
    REPO,
    collect_py_paths,
    embed_query,
    eval_rows,
    match_gold,
    unique_files,
)

OUT_REPORT = ROOT / "out" / "conductor_suite_benchmark.json"

ARCHS = [
    "baseline_graphify",
    "baseline_hybrid",
    "baseline_minrank",
    "A_minrank_expand",
    "C_gear",
    "D_rerank",
    "E_multiprobe",
    "F_f95",
]


def main() -> None:
    n_q = sum(len(v) for v in SUITES.values())
    print("=== Multi-suite conductor bake-off (no tuning) ===", flush=True)
    print(f"  suites={len(SUITES)} queries={n_q} archs={len(ARCHS)}", flush=True)
    for name, blurb in SUITE_BLURBS.items():
        print(f"  - {name}: {blurb} ({len(SUITES[name])} q)", flush=True)

    root = REPO.resolve()
    paths = collect_py_paths(root)
    print(f"\n=== Parse ({len(paths)} py) ===", flush=True)
    t0 = time.perf_counter()
    extraction = extract(paths, root=root, cache_root=root, parallel=True)
    ir = graphify_to_repo_ir(
        extraction, root=root, elapsed_ms=(time.perf_counter() - t0) * 1000, file_count=len(paths)
    )
    chunks = chunk_repo_from_ir(ir, root)
    texts = [c.content for c in chunks]
    files = [c.file.replace("\\", "/") for c in chunks]
    print(f"  chunks={len(chunks)} ({time.perf_counter() - t0:.1f}s)", flush=True)

    print("\n=== Indexes ===", flush=True)
    G = load_or_build_graph(extraction, root, GRAPH_JSON)
    spans = [
        ChunkSpan(index=i, file=files[i], start_line=c.start_line, end_line=c.end_line)
        for i, c in enumerate(chunks)
    ]
    graph_ret = GraphifyChunkRetriever(G, spans, depth=2)
    bm25 = BM25Index(texts)
    cache = load_cache(EMBED_CACHE)
    dense = DenseIndex.from_texts_and_cache(texts, cache)
    print(f"  graph nodes={G.number_of_nodes()} dense={dense.matrix.shape}", flush=True)

    cond = MultiArchConductor(files=files, bm25=bm25, dense=dense, graph=graph_ret, config=ConductorConfig())

    all_gold = [(sname, g) for sname, gs in SUITES.items() for g in gs]
    print("\n=== Embed queries ===", flush=True)
    qvecs: dict[str, np.ndarray] = {}
    for sname, g in all_gold:
        key = f"{sname}:{g['id']}"
        tk = text_key(g["query"])
        if tk in cache:
            vec = np.asarray(cache[tk], dtype=np.float32)
        else:
            vec = np.asarray(embed_query(g["query"]), dtype=np.float32)
            EMBED_CACHE.parent.mkdir(parents=True, exist_ok=True)
            with EMBED_CACHE.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": tk, "embedding": vec.tolist()}) + "\n")
            cache[tk] = vec.tolist()
        qvecs[key] = vec
    print(f"  embedded {len(qvecs)}", flush=True)

    # results[arch][suite] = metrics + rows
    results: dict[str, dict] = {}
    for arch in ARCHS:
        print(f"\n======== {arch} ========", flush=True)
        results[arch] = {"suites": {}, "macro": {}}
        suite_r5: list[float] = []
        suite_r10: list[float] = []
        suite_mrr: list[float] = []
        for sname, gold in SUITES.items():
            rows = []
            t_s = time.perf_counter()
            for g in gold:
                key = f"{sname}:{g['id']}"
                hits = cond.retrieve_arch(arch, g["query"], qvecs[key], top_k=15)
                top_files = unique_files(hits)[:10]
                rank = match_gold(top_files, g["files_substr"])
                rows.append(
                    {
                        "id": g["id"],
                        "rank": rank,
                        "hit_at_5": rank is not None and rank <= 5,
                        "hit_at_10": rank is not None and rank <= 10,
                        "top_files": top_files[:5],
                    }
                )
            wall = time.perf_counter() - t_s
            overall = {**eval_rows(rows, 5), "recall_at_10": eval_rows(rows, 10)["recall_at_10"]}
            results[arch]["suites"][sname] = {
                "overall": overall,
                "wall_seconds": round(wall, 2),
                "per_query": rows,
            }
            suite_r5.append(overall["recall_at_5"])
            suite_r10.append(overall["recall_at_10"])
            suite_mrr.append(overall["mrr"])
            miss = sum(1 for r in rows if not r["hit_at_5"])
            print(
                f"  {sname}: R@5={overall['recall_at_5']:.1%} R@10={overall['recall_at_10']:.1%} "
                f"MRR={overall['mrr']:.3f} miss@5={miss} ({wall:.1f}s)",
                flush=True,
            )
        macro = {
            "recall_at_5": round(sum(suite_r5) / len(suite_r5), 4),
            "recall_at_10": round(sum(suite_r10) / len(suite_r10), 4),
            "mrr": round(sum(suite_mrr) / len(suite_mrr), 4),
            # also micro over all queries
        }
        # micro
        all_rows = [r for s in results[arch]["suites"].values() for r in s["per_query"]]
        micro = {**eval_rows(all_rows, 5), "recall_at_10": eval_rows(all_rows, 10)["recall_at_10"]}
        results[arch]["macro"] = macro
        results[arch]["micro"] = micro
        print(
            f"  >> MACRO R@5={macro['recall_at_5']:.1%} R@10={macro['recall_at_10']:.1%} "
            f"MRR={macro['mrr']:.3f} | MICRO R@5={micro['recall_at_5']:.1%}",
            flush=True,
        )

    def rank_key(a: str):
        m = results[a]["macro"]
        return (m["recall_at_5"], m["recall_at_10"], m["mrr"])

    best = max(ARCHS, key=rank_key)

    # suite winners
    suite_winners: dict[str, str] = {}
    for sname in SUITES:
        suite_winners[sname] = max(
            ARCHS,
            key=lambda a: (
                results[a]["suites"][sname]["overall"]["recall_at_5"],
                results[a]["suites"][sname]["overall"]["recall_at_10"],
                results[a]["suites"][sname]["overall"]["mrr"],
            ),
        )

    report = {
        "repo": str(REPO),
        "model": MODEL,
        "n_chunks": len(chunks),
        "n_queries": n_q,
        "suites": {k: {"n": len(v), "blurb": SUITE_BLURBS[k]} for k, v in SUITES.items()},
        "architectures": results,
        "best_by_macro_r5": best,
        "suite_winners": suite_winners,
        "summary_macro": {a: results[a]["macro"] for a in ARCHS},
        "summary_micro": {a: results[a]["micro"] for a in ARCHS},
        "note": "Suites authored before this run; no architecture was tuned to these queries.",
    }
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("\n=== MACRO SUMMARY (primary) ===", flush=True)
    print(f"{'arch':22s} macroR@5  macroR@10  macroMRR  microR@5", flush=True)
    for a in sorted(ARCHS, key=rank_key, reverse=True):
        m, u = results[a]["macro"], results[a]["micro"]
        mark = " <<" if a == best else ""
        print(
            f"{a:22s} {m['recall_at_5']:.1%}     {m['recall_at_10']:.1%}      "
            f"{m['mrr']:.3f}    {u['recall_at_5']:.1%}{mark}",
            flush=True,
        )
    print("\n=== SUITE WINNERS ===", flush=True)
    for sname, w in suite_winners.items():
        print(f"  {sname}: {w}", flush=True)
    print(f"\nBest overall (macro R@5): {best}", flush=True)
    print(f"Wrote {OUT_REPORT}", flush=True)


if __name__ == "__main__":
    main()
