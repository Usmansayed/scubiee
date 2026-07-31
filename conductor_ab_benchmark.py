"""A/B: Graphify-only vs BM25+dense hybrid vs triple-signal conductor.

Usage:
  .\\.venv\\Scripts\\python -u conductor_ab_benchmark.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "packages"))

from conductor import Conductor, ConductorConfig  # noqa: E402
from conductor.bm25_index import BM25Index  # noqa: E402
from conductor.dense_index import DenseIndex, load_cache, text_key  # noqa: E402
from conductor.graphify_retriever import (  # noqa: E402
    ChunkSpan,
    GraphifyChunkRetriever,
    build_and_save_graph,
    load_or_build_graph,
)
from enrich import chunk_repo_from_ir  # noqa: E402
from parse_harness.graphify_adapter import graphify_to_repo_ir  # noqa: E402
from graphify.extract import collect_files, extract  # noqa: E402

REPO = ROOT / "testdata" / "frontend-mcp"
EMBED_CACHE = ROOT / "out" / "embed_cache_frontend_mcp_nomic768.jsonl"
GRAPH_JSON = REPO / "graphify-out" / "graph.json"
OUT_REPORT = ROOT / "out" / "conductor_ab_benchmark.json"

MODEL = "nomic-embed-text"
ENDPOINT = "http://localhost:11434/api/embed"
DIMENSION = 768
TOP_K = 5
CANDIDATE_K = 50

HARD_GOLD = [
    {
        "id": "mcp_server_entry",
        "query": "MCP server entrypoint that registers frontend perception tools for the coding agent",
        "files_substr": ["navigation/mcp/server.py"],
    },
    {
        "id": "mcp_tools_catalog",
        "query": "definitions of perception MCP tools exposed to Cursor or Claude for browser observation",
        "files_substr": ["navigation/mcp/tools.py"],
    },
    {
        "id": "browser_session",
        "query": "manage browser-use sessions lifecycle connect disconnect and reuse for visual navigation",
        "files_substr": ["browser_session_manager.py"],
    },
    {
        "id": "perception_runtime",
        "query": "inspiration intelligence perception runtime that drives browser observation without an LLM inside the server",
        "files_substr": ["perception_runtime.py"],
    },
    {
        "id": "optional_code_graph",
        "query": "optional code review graph behind an interface so browser automation continues when CRG is unavailable",
        "files_substr": ["code_graph", "ICodeGraph", "crg"],
    },
    {
        "id": "coordination_score",
        "query": "compute coordination score for multi-agent frontend navigation validation harness",
        "files_substr": ["coordination_score.py"],
    },
    {
        "id": "execution_harness",
        "query": "execution validation harness that records browser action outcomes for frontend perception",
        "files_substr": ["execution_validation/harness.py"],
    },
    {
        "id": "component_browser_validator",
        "query": "validate UI components in a live browser for component intelligence",
        "files_substr": ["browser_validator.py"],
    },
    {
        "id": "install_cli",
        "query": "CLI installer that sets up frontend perception engine package and optional chromium browser",
        "files_substr": ["install"],
    },
    {
        "id": "figma_community_browser",
        "query": "browser helper for figma community duplication intelligence scraping",
        "files_substr": ["figma_intelligence", "community_duplication/browser.py"],
    },
    {
        "id": "distillation_build",
        "query": "distillation build pipeline in the coordination layer that validates distilled navigation knowledge",
        "files_substr": ["coordination_layer/distillation/build.py"],
    },
    {
        "id": "workflow_recorder",
        "query": "recorder that stores coordination validation workflow traces for later scoring",
        "files_substr": ["coordination_validation/recorder.py"],
    },
    {
        "id": "agent_bootstrap",
        "query": "bootstrap path that loads navigation package modules for the frontend mcp runtime",
        "files_substr": ["_bootstrap.py", "demo.py"],
    },
    {
        "id": "deterministic_mcp_no_llm",
        "query": "design principle that the MCP server is deterministic evidence runtime and the coding agent remains the brain",
        "files_substr": ["mcp/", "perception"],
    },
    {
        "id": "visual_browser_intelligence",
        "query": "visual browser intelligence session orchestration for screenshot and DOM grounded navigation",
        "files_substr": ["visual_browser_intelligence"],
    },
]


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
    resp = requests.post(
        ENDPOINT,
        json={"model": MODEL, "input": [text]},
        timeout=120,
    )
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


def eval_arm(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        "recall_at_1": round(sum(1 for r in rows if r["hit_at_1"]) / n, 4),
        "recall_at_5": round(sum(1 for r in rows if r["hit_at_5"]) / n, 4),
        "mrr": round(sum((1 / r["rank"]) if r["rank"] else 0.0 for r in rows) / n, 4),
        "per_query": rows,
    }


def main() -> None:
    print("=== Conductor A/B: graphify vs hybrid vs conductor ===", flush=True)
    print(f"  repo={REPO}", flush=True)

    print("\n=== Parse + chunk ===", flush=True)
    root = REPO.resolve()
    paths = collect_py_paths(root)
    print(f"  py files={len(paths)}", flush=True)
    t0 = time.perf_counter()
    extraction = extract(paths, root=root, cache_root=root, parallel=True)
    print(f"  extract {time.perf_counter() - t0:.1f}s", flush=True)
    ir = graphify_to_repo_ir(
        extraction,
        root=root,
        elapsed_ms=(time.perf_counter() - t0) * 1000,
        file_count=len(paths),
    )
    chunks = chunk_repo_from_ir(ir, root)
    texts = [c.content for c in chunks]
    files = [c.file.replace("\\", "/") for c in chunks]
    print(f"  chunks={len(chunks)}", flush=True)

    print("\n=== Graphify graph.json ===", flush=True)
    t0 = time.perf_counter()
    if GRAPH_JSON.exists():
        print(f"  loading existing {GRAPH_JSON}", flush=True)
        G = load_or_build_graph(extraction, root, GRAPH_JSON)
    else:
        print(f"  building {GRAPH_JSON}", flush=True)
        G = build_and_save_graph(extraction, root, GRAPH_JSON)
    print(f"  nodes={G.number_of_nodes()} edges={G.number_of_edges()} ({time.perf_counter()-t0:.1f}s)", flush=True)

    spans = [
        ChunkSpan(index=i, file=files[i], start_line=c.start_line, end_line=c.end_line)
        for i, c in enumerate(chunks)
    ]
    graph_ret = GraphifyChunkRetriever(G, spans, depth=2)

    print("\n=== BM25 + dense indexes ===", flush=True)
    t0 = time.perf_counter()
    bm25 = BM25Index(texts)
    print(f"  bm25 {time.perf_counter()-t0:.1f}s", flush=True)
    cache = load_cache(EMBED_CACHE)
    print(f"  embed cache entries={len(cache)}", flush=True)
    t0 = time.perf_counter()
    dense = DenseIndex.from_texts_and_cache(texts, cache)
    print(f"  dense matrix {dense.matrix.shape} ({time.perf_counter()-t0:.1f}s)", flush=True)

    cond = Conductor(
        files=files,
        bm25=bm25,
        dense=dense,
        graph=graph_ret,
        config=ConductorConfig(candidate_pool=CANDIDATE_K),
    )

    print("\n=== Embed hard queries ===", flush=True)
    qvecs: dict[str, np.ndarray] = {}
    for g in HARD_GOLD:
        # prefer cache if query was embedded before
        k = text_key(g["query"])
        if k in cache:
            vec = np.asarray(cache[k], dtype=np.float32)
        else:
            vec = np.asarray(embed_query(g["query"]), dtype=np.float32)
            # append to cache for reuse
            EMBED_CACHE.parent.mkdir(parents=True, exist_ok=True)
            with EMBED_CACHE.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": k, "embedding": vec.tolist()}) + "\n")
            cache[k] = vec.tolist()
        qvecs[g["id"]] = vec
        print(f"  {g['id']}: ok", flush=True)

    arms = ("graphify", "hybrid", "conductor")
    results: dict[str, dict] = {}

    print("\n=== Retrieve ===", flush=True)
    for arm in arms:
        rows = []
        print(f"  --- {arm} ---", flush=True)
        for g in HARD_GOLD:
            t0 = time.perf_counter()
            explain = None
            if arm == "graphify":
                hits = cond.retrieve_graphify(g["query"], top_k=TOP_K * 3)
            elif arm == "hybrid":
                hits = cond.retrieve_hybrid(g["query"], qvecs[g["id"]], top_k=TOP_K * 3)
            else:
                explain = cond.explain(g["query"], qvecs[g["id"]])
                hits = cond.retrieve_conductor(g["query"], qvecs[g["id"]], top_k=TOP_K * 3)
            latency = (time.perf_counter() - t0) * 1000
            top_files = unique_files(hits)[:TOP_K]
            rank = match_gold(top_files, g["files_substr"])
            row = {
                "id": g["id"],
                "rank": rank,
                "hit_at_1": rank == 1,
                "hit_at_5": rank is not None,
                "top_files": top_files,
                "latency_ms": round(latency, 2),
            }
            if explain:
                row["coordination"] = explain
            rows.append(row)
            status = f"@{rank}" if rank else "MISS"
            lead = ""
            if explain:
                lead = f" mode={explain.get('mode', explain.get('lead', ''))}"
            print(f"    [{g['id']}] {status}{lead} -> {top_files[0] if top_files else '∅'}", flush=True)
        results[arm] = eval_arm(rows)

    # Per-query winners
    winners = []
    for g in HARD_GOLD:
        ranks = {arm: next(r["rank"] for r in results[arm]["per_query"] if r["id"] == g["id"]) for arm in arms}
        best = None
        best_rank = None
        for arm, rk in ranks.items():
            if rk is None:
                continue
            if best_rank is None or rk < best_rank:
                best = arm
                best_rank = rk
        winners.append({"id": g["id"], "ranks": ranks, "best": best})

    report = {
        "repo": str(REPO),
        "n_chunks": len(chunks),
        "n_graph_nodes": G.number_of_nodes(),
        "n_graph_edges": G.number_of_edges(),
        "model": MODEL,
        "dim": DIMENSION,
        "config": {
            "rrf_k": cond.config.rrf_k,
            "w_graph": cond.config.w_graph,
            "w_bm25": cond.config.w_bm25,
            "w_dense": cond.config.w_dense,
            "agree_bonus": cond.config.agree_bonus,
            "iterations": cond.config.iterations,
            "candidate_pool": cond.config.candidate_pool,
        },
        "arms": results,
        "winners": winners,
        "summary": {arm: {k: results[arm][k] for k in ("recall_at_1", "recall_at_5", "mrr")} for arm in arms},
    }
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("\n=== SUMMARY ===", flush=True)
    print(f"{'arm':12s} hard@1   hard@5   MRR", flush=True)
    for arm in arms:
        s = results[arm]
        print(
            f"{arm:12s} {s['recall_at_1']:.2%}  {s['recall_at_5']:.2%}  {s['mrr']:.3f}",
            flush=True,
        )
    print(f"Wrote {OUT_REPORT}", flush=True)


if __name__ == "__main__":
    main()
