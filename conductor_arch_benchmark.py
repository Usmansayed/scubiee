"""Architecture bake-off on hard gold sets (v2 or holdout v3).

Usage:
  .\\.venv\\Scripts\\python -u conductor_arch_benchmark.py --gold v3
  .\\.venv\\Scripts\\python -u conductor_arch_benchmark.py --gold v2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import requests

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
from conductor.hard_v2_gold import HARD_V2  # noqa: E402
from conductor.hard_v3_gold import HARD_V3  # noqa: E402
from enrich import chunk_repo_from_ir  # noqa: E402
from parse_harness.graphify_adapter import graphify_to_repo_ir  # noqa: E402
from graphify.extract import collect_files, extract  # noqa: E402

REPO = ROOT / "testdata" / "frontend-mcp"
EMBED_CACHE = ROOT / "out" / "embed_cache_frontend_mcp_nomic768.jsonl"
GRAPH_JSON = REPO / "graphify-out" / "graph.json"

MODEL = "nomic-embed-text"
ENDPOINT = "http://localhost:11434/api/embed"
DIMENSION = 768
TOP_KS = (5, 10)

# Holdout comparison set — includes F95 + priors + extras
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

GOLD_SETS = {
    "v2": (HARD_V2, ROOT / "out" / "conductor_arch_benchmark.json"),
    "v3": (HARD_V3, ROOT / "out" / "conductor_holdout_v3_benchmark.json"),
}


def collect_py_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for name in ("src", "packages", "execution_layer", "coordination_layer"):
        d = root / name
        if d.exists():
            paths.extend(collect_files(d, root=root))
    out = []
    for p in paths:
        s = p.as_posix().lower()
        if p.suffix != ".py":
            continue
        if any(x in s for x in ["/vendor/", "node_modules", "/dist/", "__pycache__"]):
            continue
        out.append(p)
    return out


def embed_query(text: str) -> list[float]:
    resp = requests.post(ENDPOINT, json={"model": MODEL, "input": [text]}, timeout=120)
    resp.raise_for_status()
    emb = resp.json()["embeddings"][0]
    if len(emb) != DIMENSION:
        raise RuntimeError(f"bad dim {len(emb)}")
    return emb


def match_gold(top_files: list[str], substrs: list[str]) -> int | None:
    for rank, f in enumerate(top_files, start=1):
        fl = f.replace("\\", "/")
        for s in substrs:
            if s.replace("\\", "/") in fl:
                return rank
    return None


def unique_files(hits) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for h in hits:
        if h.file not in seen:
            out.append(h.file)
            seen.add(h.file)
    return out


def eval_rows(rows: list[dict], k: int) -> dict:
    n = len(rows)
    hits_k = sum(1 for r in rows if r["rank"] is not None and r["rank"] <= k)
    return {
        f"recall_at_{k}": round(hits_k / n, 4),
        "mrr": round(sum((1 / r["rank"]) if r["rank"] else 0.0 for r in rows) / n, 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Conductor architecture bake-off")
    ap.add_argument("--gold", choices=sorted(GOLD_SETS), default="v3", help="gold set (v3=holdout)")
    args = ap.parse_args()
    gold, out_report = GOLD_SETS[args.gold]

    print(f"=== Conductor architecture bake-off (hard_{args.gold}) ===", flush=True)
    print(f"  queries={len(gold)} archs={len(ARCHS)} out={out_report.name}", flush=True)

    root = REPO.resolve()
    paths = collect_py_paths(root)
    print(f"\n=== Parse ({len(paths)} py) ===", flush=True)
    t0 = time.perf_counter()
    extraction = extract(paths, root=root, cache_root=root, parallel=True)
    ir = graphify_to_repo_ir(extraction, root=root, elapsed_ms=(time.perf_counter() - t0) * 1000, file_count=len(paths))
    chunks = chunk_repo_from_ir(ir, root)
    texts = [c.content for c in chunks]
    files = [c.file.replace("\\", "/") for c in chunks]
    print(f"  chunks={len(chunks)} ({time.perf_counter()-t0:.1f}s)", flush=True)

    print("\n=== Indexes ===", flush=True)
    G = load_or_build_graph(extraction, root, GRAPH_JSON)
    spans = [ChunkSpan(index=i, file=files[i], start_line=c.start_line, end_line=c.end_line) for i, c in enumerate(chunks)]
    graph_ret = GraphifyChunkRetriever(G, spans, depth=2)
    bm25 = BM25Index(texts)
    cache = load_cache(EMBED_CACHE)
    dense = DenseIndex.from_texts_and_cache(texts, cache)
    print(f"  graph nodes={G.number_of_nodes()} dense={dense.matrix.shape}", flush=True)

    cond = MultiArchConductor(files=files, bm25=bm25, dense=dense, graph=graph_ret, config=ConductorConfig())

    print("\n=== Embed queries ===", flush=True)
    qvecs: dict[str, np.ndarray] = {}
    for g in gold:
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
    print(f"  embedded {len(qvecs)}", flush=True)

    results: dict[str, dict] = {}
    for arch in ARCHS:
        print(f"\n=== {arch} ===", flush=True)
        rows = []
        t_arch = time.perf_counter()
        for g in gold:
            t0 = time.perf_counter()
            hits = cond.retrieve_arch(arch, g["query"], qvecs[g["id"]], top_k=15)
            latency = (time.perf_counter() - t0) * 1000
            top_files = unique_files(hits)[:10]
            rank = match_gold(top_files, g["files_substr"])
            rows.append(
                {
                    "id": g["id"],
                    "bucket": g["bucket"],
                    "rank": rank,
                    "hit_at_5": rank is not None and rank <= 5,
                    "hit_at_10": rank is not None and rank <= 10,
                    "top_files": top_files[:5],
                    "latency_ms": round(latency, 2),
                }
            )
            status = f"@{rank}" if rank else "MISS"
            print(f"  [{g['bucket'][:4]}] {g['id']}: {status}", flush=True)
        wall = time.perf_counter() - t_arch
        by_bucket: dict[str, list] = {}
        for r in rows:
            by_bucket.setdefault(r["bucket"], []).append(r)
        bucket_stats = {
            b: {
                "recall_at_5": eval_rows(rs, 5)["recall_at_5"],
                "recall_at_10": eval_rows(rs, 10)["recall_at_10"],
                "mrr": eval_rows(rs, 5)["mrr"],
            }
            for b, rs in by_bucket.items()
        }
        results[arch] = {
            "wall_seconds": round(wall, 2),
            "overall": {**eval_rows(rows, 5), "recall_at_10": eval_rows(rows, 10)["recall_at_10"]},
            "by_bucket": bucket_stats,
            "per_query": rows,
        }
        o = results[arch]["overall"]
        print(
            f"  >> R@5={o['recall_at_5']:.2%} R@10={o['recall_at_10']:.2%} MRR={o['mrr']:.3f} ({wall:.1f}s)",
            flush=True,
        )

    def key(name: str):
        o = results[name]["overall"]
        return (o["recall_at_5"], o["recall_at_10"], o["mrr"])

    best = max(ARCHS, key=key)
    report = {
        "repo": str(REPO),
        "gold": f"hard_{args.gold}",
        "n_queries": len(gold),
        "n_chunks": len(chunks),
        "model": MODEL,
        "architectures": results,
        "best_by_recall_at_5": best,
        "summary_table": {a: results[a]["overall"] for a in ARCHS},
    }
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("\n=== SUMMARY ===", flush=True)
    print(f"{'arch':22s} R@5     R@10    MRR", flush=True)
    for a in ARCHS:
        o = results[a]["overall"]
        mark = " <<" if a == best else ""
        print(f"{a:22s} {o['recall_at_5']:.2%}  {o['recall_at_10']:.2%}  {o['mrr']:.3f}{mark}", flush=True)
    print(f"\nBest: {best}", flush=True)
    print(f"Wrote {out_report}", flush=True)


if __name__ == "__main__":
    main()
