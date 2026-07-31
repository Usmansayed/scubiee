"""Top-3 + experimental R&D bake-off across all eval surfaces.

Surfaces:
  - 5-suite bank (dev-ish)
  - holdout hard_v3
  - diverse bank (LOCKED gate — new domains)
  - hard_v2 (regression only)

Consistency = mean(suite_macro R@5, holdout_v3 R@5, diverse_macro R@5).
Accept experimental only if consistency rises AND diverse_macro does not fall.

Usage:
  .\\.venv\\Scripts\\python -u conductor_top3_benchmark.py
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
from conductor.diverse_bank import DIVERSE_BLURBS, DIVERSE_SUITES  # noqa: E402
from conductor.graphify_retriever import (  # noqa: E402
    ChunkSpan,
    GraphifyChunkRetriever,
    load_or_build_graph,
)
from conductor.hard_v2_gold import HARD_V2  # noqa: E402
from conductor.hard_v3_gold import HARD_V3  # noqa: E402
from conductor.suite_bank import SUITE_BLURBS, SUITES  # noqa: E402
from conductor.top3 import (  # noqa: E402
    EXPERIMENTAL_ARCHS,
    EXPERIMENTAL_ROLES,
    TOP3_ARCHS,
    TOP3_ROLES,
)
from enrich import chunk_repo_from_ir  # noqa: E402
from parse_harness.graphify_adapter import graphify_to_repo_ir  # noqa: E402
from graphify.extract import collect_files, extract  # noqa: E402
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

OUT_REPORT = ROOT / "out" / "conductor_top3_benchmark.json"

ALL_ARCHS = TOP3_ARCHS + EXPERIMENTAL_ARCHS
ALL_ROLES = {**TOP3_ROLES, **EXPERIMENTAL_ROLES}


def _eval_gold(cond: MultiArchConductor, arch: str, gold: list[dict], qvecs: dict) -> dict:
    rows = []
    t0 = time.perf_counter()
    for g in gold:
        hits = cond.retrieve_arch(arch, g["query"], qvecs[g["id"]], top_k=15)
        top_files = unique_files(hits)[:10]
        rank = match_gold(top_files, g["files_substr"])
        rows.append(
            {
                "id": g["id"],
                "bucket": g.get("bucket", ""),
                "rank": rank,
                "hit_at_5": rank is not None and rank <= 5,
                "hit_at_10": rank is not None and rank <= 10,
                "top_files": top_files[:5],
            }
        )
    wall = time.perf_counter() - t0
    return {
        "wall_seconds": round(wall, 2),
        "overall": {**eval_rows(rows, 5), "recall_at_10": eval_rows(rows, 10)["recall_at_10"]},
        "per_query": rows,
    }


def _eval_suite_map(
    cond: MultiArchConductor, arch: str, suite_map: dict[str, list[dict]], qvecs: dict, prefix: str
) -> dict:
    suite_block: dict = {}
    r5s, r10s, mrrs = [], [], []
    for sname, gold in suite_map.items():
        rows = []
        for g in gold:
            key = f"{prefix}:{sname}:{g['id']}"
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
        overall = {**eval_rows(rows, 5), "recall_at_10": eval_rows(rows, 10)["recall_at_10"]}
        suite_block[sname] = {"overall": overall, "per_query": rows}
        r5s.append(overall["recall_at_5"])
        r10s.append(overall["recall_at_10"])
        mrrs.append(overall["mrr"])
    all_rows = [r for s in suite_block.values() for r in s["per_query"]]
    return {
        "suites": suite_block,
        "macro": {
            "recall_at_5": round(sum(r5s) / len(r5s), 4),
            "recall_at_10": round(sum(r10s) / len(r10s), 4),
            "mrr": round(sum(mrrs) / len(mrrs), 4),
        },
        "micro": {**eval_rows(all_rows, 5), "recall_at_10": eval_rows(all_rows, 10)["recall_at_10"]},
    }


def main() -> None:
    print("=== Top-3 + experimental R&D bake-off ===", flush=True)
    for a in TOP3_ARCHS:
        print(f"  control  {a}: {ALL_ROLES[a]}", flush=True)
    for a in EXPERIMENTAL_ARCHS:
        print(f"  experiment {a}: {ALL_ROLES[a]}", flush=True)

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

    G = load_or_build_graph(extraction, root, GRAPH_JSON)
    spans = [
        ChunkSpan(index=i, file=files[i], start_line=c.start_line, end_line=c.end_line)
        for i, c in enumerate(chunks)
    ]
    graph_ret = GraphifyChunkRetriever(G, spans, depth=2)
    bm25 = BM25Index(texts)
    cache = load_cache(EMBED_CACHE)
    dense = DenseIndex.from_texts_and_cache(texts, cache)
    cond = MultiArchConductor(files=files, bm25=bm25, dense=dense, graph=graph_ret, config=ConductorConfig())
    print(f"  graph={G.number_of_nodes()} dense={dense.matrix.shape}", flush=True)

    print("\n=== Embed queries ===", flush=True)
    qvecs: dict[str, np.ndarray] = {}

    def ensure(qid: str, query: str) -> None:
        tk = text_key(query)
        if tk in cache:
            qvecs[qid] = np.asarray(cache[tk], dtype=np.float32)
            return
        vec = np.asarray(embed_query(query), dtype=np.float32)
        EMBED_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with EMBED_CACHE.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": tk, "embedding": vec.tolist()}) + "\n")
        cache[tk] = vec.tolist()
        qvecs[qid] = vec

    for g in HARD_V2:
        ensure(g["id"], g["query"])
    for g in HARD_V3:
        ensure(g["id"], g["query"])
    for sname, gs in SUITES.items():
        for g in gs:
            ensure(f"suite:{sname}:{g['id']}", g["query"])
    for sname, gs in DIVERSE_SUITES.items():
        for g in gs:
            ensure(f"diverse:{sname}:{g['id']}", g["query"])
    print(f"  embedded {len(qvecs)}", flush=True)

    results: dict[str, dict] = {}
    for arch in ALL_ARCHS:
        kind = "EXP" if arch in EXPERIMENTAL_ARCHS else "CTL"
        print(f"\n======== [{kind}] {arch} ========", flush=True)

        suites = _eval_suite_map(cond, arch, SUITES, qvecs, "suite")
        print(f"  suites  macro R@5={suites['macro']['recall_at_5']:.1%}", flush=True)

        diverse = _eval_suite_map(cond, arch, DIVERSE_SUITES, qvecs, "diverse")
        print(f"  diverse macro R@5={diverse['macro']['recall_at_5']:.1%}", flush=True)
        for sname, block in diverse["suites"].items():
            o = block["overall"]
            print(f"    {sname}: R@5={o['recall_at_5']:.1%}", flush=True)

        v3 = _eval_gold(cond, arch, HARD_V3, qvecs)
        print(f"  holdout_v3 R@5={v3['overall']['recall_at_5']:.1%}", flush=True)

        v2 = _eval_gold(cond, arch, HARD_V2, qvecs)
        print(f"  hard_v2    R@5={v2['overall']['recall_at_5']:.1%}", flush=True)

        consistency = round(
            (
                suites["macro"]["recall_at_5"]
                + v3["overall"]["recall_at_5"]
                + diverse["macro"]["recall_at_5"]
            )
            / 3.0,
            4,
        )
        results[arch] = {
            "role": ALL_ROLES[arch],
            "experimental": arch in EXPERIMENTAL_ARCHS,
            "suites": suites,
            "diverse": diverse,
            "holdout_v3": v3,
            "hard_v2": v2,
            "consistency_r5": consistency,
        }
        print(f"  >> consistency R@5={consistency:.1%}", flush=True)

    best_control = max(TOP3_ARCHS, key=lambda a: results[a]["consistency_r5"])
    best_all = max(ALL_ARCHS, key=lambda a: results[a]["consistency_r5"])

    # Accept/reject each experimental vs best control
    decisions: dict[str, dict] = {}
    base = results[best_control]
    for a in EXPERIMENTAL_ARCHS:
        exp = results[a]
        ok = (
            exp["consistency_r5"] >= base["consistency_r5"]
            and exp["diverse"]["macro"]["recall_at_5"] >= base["diverse"]["macro"]["recall_at_5"] - 1e-9
            and exp["holdout_v3"]["overall"]["recall_at_5"]
            >= base["holdout_v3"]["overall"]["recall_at_5"] - 1e-9
        )
        decisions[a] = {
            "vs_control": best_control,
            "accept": ok,
            "delta_consistency": round(exp["consistency_r5"] - base["consistency_r5"], 4),
            "delta_diverse": round(
                exp["diverse"]["macro"]["recall_at_5"] - base["diverse"]["macro"]["recall_at_5"], 4
            ),
            "delta_holdout_v3": round(
                exp["holdout_v3"]["overall"]["recall_at_5"] - base["holdout_v3"]["overall"]["recall_at_5"],
                4,
            ),
        }

    report = {
        "repo": str(REPO),
        "model": MODEL,
        "n_chunks": len(chunks),
        "controls": TOP3_ARCHS,
        "experimental": EXPERIMENTAL_ARCHS,
        "suite_blurbs": SUITE_BLURBS,
        "diverse_blurbs": DIVERSE_BLURBS,
        "architectures": results,
        "best_control_by_consistency_r5": best_control,
        "best_all_by_consistency_r5": best_all,
        "rd_decisions": decisions,
        "summary": {
            a: {
                "consistency_r5": results[a]["consistency_r5"],
                "suite_macro_r5": results[a]["suites"]["macro"]["recall_at_5"],
                "diverse_macro_r5": results[a]["diverse"]["macro"]["recall_at_5"],
                "holdout_v3_r5": results[a]["holdout_v3"]["overall"]["recall_at_5"],
                "hard_v2_r5": results[a]["hard_v2"]["overall"]["recall_at_5"],
                "experimental": results[a]["experimental"],
            }
            for a in ALL_ARCHS
        },
        "rd_rule": (
            "Accept experiment only if consistency >= best control AND "
            "diverse_macro and holdout_v3 do not fall vs that control."
        ),
    }
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("\n=== SUMMARY ===", flush=True)
    print(
        f"{'arch':22s} consis  suites  diverse holdout hard_v2",
        flush=True,
    )
    for a in sorted(ALL_ARCHS, key=lambda x: results[x]["consistency_r5"], reverse=True):
        s = report["summary"][a]
        tag = " EXP" if s["experimental"] else ""
        mark = " <<" if a == best_all else ""
        print(
            f"{a:22s} {s['consistency_r5']:.1%}  {s['suite_macro_r5']:.1%}   "
            f"{s['diverse_macro_r5']:.1%}   {s['holdout_v3_r5']:.1%}   {s['hard_v2_r5']:.1%}{tag}{mark}",
            flush=True,
        )
    print(f"\nBest control: {best_control}", flush=True)
    for a, d in decisions.items():
        status = "ACCEPT" if d["accept"] else "REJECT"
        print(
            f"R&D {a}: {status} vs {d['vs_control']} "
            f"(d_cons={d['delta_consistency']:+.1%} d_div={d['delta_diverse']:+.1%} "
            f"d_v3={d['delta_holdout_v3']:+.1%})",
            flush=True,
        )
    print(f"Wrote {OUT_REPORT}", flush=True)


if __name__ == "__main__":
    main()
