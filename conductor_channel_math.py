"""Channel-level math diagnostics on suite + diverse gold (read-only insights).

For each query, measure gold's rank in graph / bm25 / dense / hybrid independently,
then summarize:
  - which channel is oracle most often @5
  - P(hit@5 | channel) and complementarity (only-one-channel hits)
  - Spearman-ish agreement proxy via shared top-10 overlap

Usage:
  .\\.venv\\Scripts\\python -u conductor_channel_math.py
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "packages"))

from conductor.architectures import MultiArchConductor  # noqa: E402
from conductor.bm25_index import BM25Index  # noqa: E402
from conductor.conductor import ConductorConfig  # noqa: E402
from conductor.dense_index import DenseIndex, load_cache, text_key  # noqa: E402
from conductor.diverse_bank import DIVERSE_SUITES  # noqa: E402
from conductor.graphify_retriever import (  # noqa: E402
    ChunkSpan,
    GraphifyChunkRetriever,
    load_or_build_graph,
)
from conductor.suite_bank import SUITES  # noqa: E402
from enrich import chunk_repo_from_ir  # noqa: E402
from parse_harness.graphify_adapter import graphify_to_repo_ir  # noqa: E402
from graphify.extract import collect_files, extract  # noqa: E402
from conductor_arch_benchmark import (  # noqa: E402
    EMBED_CACHE,
    GRAPH_JSON,
    REPO,
    collect_py_paths,
    embed_query,
    match_gold,
)

OUT = ROOT / "out" / "conductor_channel_math.json"


def file_rank(ranking: list[str], substrs: list[str]) -> int | None:
    return match_gold(ranking, substrs)


def main() -> None:
    print("=== Channel math diagnostics ===", flush=True)
    root = REPO.resolve()
    paths = collect_py_paths(root)
    t0 = time.perf_counter()
    extraction = extract(paths, root=root, cache_root=root, parallel=True)
    ir = graphify_to_repo_ir(
        extraction, root=root, elapsed_ms=(time.perf_counter() - t0) * 1000, file_count=len(paths)
    )
    chunks = chunk_repo_from_ir(ir, root)
    texts = [c.content for c in chunks]
    files = [c.file.replace("\\", "/") for c in chunks]
    G = load_or_build_graph(extraction, root, GRAPH_JSON)
    spans = [
        ChunkSpan(index=i, file=files[i], start_line=c.start_line, end_line=c.end_line)
        for i, c in enumerate(chunks)
    ]
    cond = MultiArchConductor(
        files=files,
        bm25=BM25Index(texts),
        dense=DenseIndex.from_texts_and_cache(texts, load_cache(EMBED_CACHE)),
        graph=GraphifyChunkRetriever(G, spans, depth=2),
        config=ConductorConfig(),
    )
    cache = load_cache(EMBED_CACHE)

    golds = []
    for sname, gs in SUITES.items():
        for g in gs:
            golds.append(("suite", sname, g))
    for sname, gs in DIVERSE_SUITES.items():
        for g in gs:
            golds.append(("diverse", sname, g))

    rows = []
    oracle = Counter()
    hit5 = Counter()
    only = Counter()
    none_hit = 0
    top10_jaccard_sum = defaultdict(float)
    pair_n = 0

    for bank, sname, g in golds:
        tk = text_key(g["query"])
        if tk in cache:
            qv = np.asarray(cache[tk], dtype=np.float32)
        else:
            qv = np.asarray(embed_query(g["query"]), dtype=np.float32)
        _, _, _, _, _, rankings = cond._file_channel_rankings(g["query"], qv)
        ranks = {ch: file_rank(rankings[ch], g["files_substr"]) for ch in ("graph", "bm25", "dense", "hybrid")}
        hits = {ch: (r is not None and r <= 5) for ch, r in ranks.items()}
        for ch, h in hits.items():
            if h:
                hit5[ch] += 1
        hit_chs = [ch for ch, h in hits.items() if h and ch != "hybrid"]
        if not hit_chs:
            # hybrid might still hit
            if not hits["hybrid"]:
                none_hit += 1
        elif len(hit_chs) == 1:
            only[hit_chs[0]] += 1
        # oracle among graph/bm25/dense
        best = None
        best_r = 10**9
        for ch in ("graph", "bm25", "dense"):
            r = ranks[ch]
            if r is not None and r < best_r:
                best_r = r
                best = ch
        if best is not None and best_r <= 5:
            oracle[best] += 1

        # pairwise top10 overlap
        for a, b in (("graph", "bm25"), ("graph", "dense"), ("bm25", "dense")):
            sa, sb = set(rankings[a][:10]), set(rankings[b][:10])
            j = len(sa & sb) / max(len(sa | sb), 1)
            top10_jaccard_sum[f"{a}|{b}"] += j
        pair_n += 1

        rows.append(
            {
                "bank": bank,
                "suite": sname,
                "id": g["id"],
                "ranks": ranks,
                "hits_at_5": hits,
            }
        )

    n = len(golds)
    report = {
        "n_queries": n,
        "recall_at_5_by_channel": {ch: round(hit5[ch] / n, 4) for ch in ("graph", "bm25", "dense", "hybrid")},
        "oracle_channel_when_any_hits_at_5": dict(oracle),
        "exclusive_hits_at_5_graph_bm25_dense": dict(only),
        "miss_all_channels_at_5": none_hit,
        "mean_top10_jaccard": {k: round(v / pair_n, 4) for k, v in top10_jaccard_sum.items()},
        "insight_notes": [
            "Low Jaccard → channels are complementary (fusion helps).",
            "High exclusive hits → need OR-style fusion (min-rank / CombMNZ), not AND.",
            "Oracle counts show which channel should get more weight when adaptive.",
        ],
        "per_query": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\nn={n}", flush=True)
    print("R@5 by channel:", report["recall_at_5_by_channel"], flush=True)
    print("Oracle@5 channel counts:", dict(oracle), flush=True)
    print("Exclusive@5 (only one of g/b/d):", dict(only), flush=True)
    print("Miss all @5:", none_hit, flush=True)
    print("Mean top10 Jaccard:", report["mean_top10_jaccard"], flush=True)
    print(f"Wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
