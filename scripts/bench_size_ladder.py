"""Size ladder: shrink char budget without changing packing policy.

Insight from prior work: seq window ≠ bottleneck; density is.
Question: how small can mix (and budget_c at tight sizes) go before soft R@5 drops?

Budgets: 450, 350, 300, 250, 200
Policies: mix at all; budget_c at 300 & 250 (rare-ident challenger when tight)

Usage:
  python -u scripts/bench_size_ladder.py
"""

from __future__ import annotations

import json
import math
import os
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "scripts"))

from bench_mix_seq_ab import HARD, SOFT  # noqa: E402
from conductor.architectures import MultiArchConductor
from conductor.bm25_index import BM25Index
from conductor.conductor import ConductorConfig
from conductor.graphify_retriever import ChunkSpan, GraphifyChunkRetriever
from enrich import chunk_repo_from_ir, inject_metadata
from graphify.serve import _load_graph
from repo_ir import Edge, FileIR, RepoIR, Symbol

from pipeline.chunk_compress import compress_chunk
from pipeline.embedder import Embedder
from pipeline.searcher import FaissDenseAdapter
from pipeline.store import ChunkRecord, PipelineStore
from pipeline.vectordb import VectorDatabase

REPO = ROOT / "testdata" / "frontend-mcp"
OUT = ROOT / "out" / "size_ladder"
SEQ = 512

# (mode, max_chars)
ARMS: list[tuple[str, int]] = [
    ("mix", 450),
    ("mix", 350),
    ("mix", 300),
    ("mix", 250),
    ("mix", 200),
    ("budget_c", 300),
    ("budget_c", 250),
]


def load_repo_ir(path: Path) -> RepoIR:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return RepoIR(
        root=raw["root"],
        parser=raw.get("parser") or "graphify",
        files={k: FileIR(**v) for k, v in (raw.get("files") or {}).items()},
        symbols={k: Symbol(**v) for k, v in (raw.get("symbols") or {}).items()},
        edges=[Edge(**e) for e in (raw.get("edges") or [])],
        stats=raw.get("stats") or {},
    )


def full_chunks(repo: Path, ir: RepoIR) -> list[ChunkRecord]:
    out: list[ChunkRecord] = []
    for i, ch in enumerate(chunk_repo_from_ir(ir, repo)):
        en = inject_metadata(ch, ir)
        out.append(
            ChunkRecord(
                id=i,
                file=ch.file,
                start_line=ch.start_line,
                end_line=ch.end_line,
                symbol=ch.symbol,
                text=ch.content,
                enriched=en.enriched,
            )
        )
    return out


def _hit(files: list[str], needles: list[str]) -> bool:
    blob = " ".join(f.replace("\\", "/").lower() for f in files)
    return any(n.lower() in blob for n in needles)


def _rank(files: list[str], needles: list[str]) -> int | None:
    for i, f in enumerate(files, 1):
        fl = f.replace("\\", "/").lower()
        if any(n.lower() in fl for n in needles):
            return i
    return None


def _dcg(rels: list[float]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def _ndcg(gains: list[float], k: int = 10) -> float:
    g = gains[:k]
    ideal = sorted(gains, reverse=True)[:k]
    idcg = _dcg(ideal)
    return 0.0 if idcg <= 0 else _dcg(g) / idcg


def eval_suite(cond: MultiArchConductor, emb: Embedder, suite: list[dict[str, Any]]) -> dict[str, Any]:
    r1 = r5 = r10 = 0
    rr = 0.0
    ndcgs: list[float] = []
    fails: list[str] = []
    for item in suite:
        q, rel = item["q"], item["relevant"]
        qv = emb.embed_one(q, is_query=True)
        hits = cond.retrieve_R_plan(q, qv, top_k=10)
        files = [h.file.replace("\\", "/") for h in hits]
        ok1, ok5, ok10 = _hit(files[:1], rel), _hit(files[:5], rel), _hit(files[:10], rel)
        r1 += int(ok1)
        r5 += int(ok5)
        r10 += int(ok10)
        if not ok10:
            fails.append(q)
        rank = _rank(files, rel)
        if rank:
            rr += 1.0 / rank
        gains = [1.0 if _hit([f], rel) else 0.0 for f in files[:10]]
        ndcgs.append(_ndcg(gains, 10))
    n = max(len(suite), 1)
    return {
        "n": n,
        "recall_at_1": round(r1 / n, 4),
        "recall_at_5": round(r5 / n, 4),
        "recall_at_10": round(r10 / n, 4),
        "mrr": round(rr / n, 4),
        "ndcg_at_10": round(statistics.mean(ndcgs), 4),
        "failures": fails,
    }


def arm_key(mode: str, budget: int) -> str:
    return f"{mode}_{budget}"


def build_arm(
    mode: str,
    budget: int,
    source: list[ChunkRecord],
    graph: Path,
    emb: Embedder,
) -> tuple[MultiArchConductor, dict[str, Any]]:
    key = arm_key(mode, budget)
    texts = [compress_chunk(c.enriched or "", mode, max_chars=budget).text for c in source]
    base = OUT / "indexes" / key
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    store = PipelineStore(REPO.resolve(), base_dir=base / "store", vdb=VectorDatabase(root=base / "vectordb"))
    records = [
        ChunkRecord(
            id=i,
            file=c.file,
            start_line=c.start_line,
            end_line=c.end_line,
            symbol=c.symbol,
            text=c.text,
            enriched=texts[i],
        )
        for i, c in enumerate(source)
    ]
    print(f"\n=== EMBED {key} avg={statistics.mean(len(t) for t in texts):.1f} ===", flush=True)
    t0 = time.perf_counter()
    matrix = emb.embed_many(texts)
    embed_sec = time.perf_counter() - t0
    col = store.upsert_vectors(matrix, records, dim=int(matrix.shape[1]), bits=4)
    store.save_chunks(records)
    files = [c.file.replace("\\", "/") for c in records]
    G = _load_graph(str(graph))
    spans = [
        ChunkSpan(index=c.id, file=files[i], start_line=c.start_line, end_line=c.end_line)
        for i, c in enumerate(records)
    ]
    cond = MultiArchConductor(
        files=files,
        bm25=BM25Index(texts),
        dense=FaissDenseAdapter(col, n_chunks=len(records)),
        graph=GraphifyChunkRetriever(G, spans, depth=2),
        config=ConductorConfig(),
    )
    meta = {
        "mode": mode,
        "budget": budget,
        "avg_chars": round(statistics.mean(len(t) for t in texts), 1),
        "p50_chars": float(sorted(len(t) for t in texts)[len(texts) // 2]),
        "embed_sec": round(embed_sec, 2),
        "chunk_per_s": round(len(texts) / max(embed_sec, 1e-6), 2),
    }
    print(json.dumps(meta, indent=2), flush=True)
    return cond, meta


def main() -> int:
    os.environ.setdefault("CTX_EMBED_BATCH", "16")
    os.environ.setdefault("CTX_ACCEL_PROFILE", "dml")
    repo = REPO.resolve()
    store = PipelineStore(repo)
    ir_path = store.base / "graph_ir.json"
    graph = store.base / "graph.json"
    if not ir_path.is_file() or not graph.is_file():
        print("ERROR: need indexed frontend-mcp graph_ir + graph", flush=True)
        return 2

    print("re-enrich…", flush=True)
    ir = load_repo_ir(ir_path)
    ir.root = str(repo)
    source = full_chunks(repo, ir)
    print(f"chunks={len(source)} arms={ARMS} soft={len(SOFT)} hard={len(HARD)}", flush=True)

    emb = Embedder(
        model="nomic-ai/CodeRankEmbed",
        cache_path=None,
        batch_size=int(os.environ.get("CTX_EMBED_BATCH", "16")),
        max_seq_length=SEQ,
    )
    emb.embed_one("warmup", is_query=True)

    results: dict[str, Any] = {}
    for mode, budget in ARMS:
        key = arm_key(mode, budget)
        cond, meta = build_arm(mode, budget, source, graph, emb)
        soft = eval_suite(cond, emb, SOFT)
        hard = eval_suite(cond, emb, HARD)
        print(
            json.dumps(
                {
                    "arm": key,
                    "soft_R@5": soft["recall_at_5"],
                    "soft_MRR": soft["mrr"],
                    "hard_R@5": hard["recall_at_5"],
                    "soft_fails": len(soft["failures"]),
                },
                indent=2,
            ),
            flush=True,
        )
        results[key] = {"meta": meta, "soft": soft, "hard": hard}

    base_soft = results["mix_450"]["soft"]["recall_at_5"]
    lines = [
        "# Size ladder — smaller embed text without losing quality?",
        "",
        "Prior insight: allocation > window size. This asks: **how small can we go?**",
        f"seq={SEQ} | soft={len(SOFT)} | hard={len(HARD)} | FAISS+TQ",
        "",
        "| Arm | Avg chars | Soft R@5 | Soft MRR | Hard R@5 | ΔR@5 vs mix@450 | Soft fails | Embed s |",
        "|-----|-----------|----------|----------|----------|-----------------|------------|---------|",
    ]
    for mode, budget in ARMS:
        key = arm_key(mode, budget)
        r = results[key]
        d = r["soft"]["recall_at_5"] - base_soft
        lines.append(
            f"| {key} | {r['meta']['avg_chars']} | {r['soft']['recall_at_5']} | {r['soft']['mrr']} | "
            f"{r['hard']['recall_at_5']} | {d:+.4f} | {len(r['soft']['failures'])}/{r['soft']['n']} | "
            f"{r['meta']['embed_sec']} |"
        )

    # knee: smallest mix budget with soft R@5 >= mix_450 - 0.02 and hard R@5 >= 0.9
    knee = None
    for budget in (450, 350, 300, 250, 200):
        key = arm_key("mix", budget)
        s = results[key]["soft"]["recall_at_5"]
        h = results[key]["hard"]["recall_at_5"]
        if s >= base_soft - 0.02 and h >= 0.9:
            knee = budget
    lines += [
        "",
        f"## Knee (mix, soft R@5 within −0.02 of mix@450, hard R@5≥0.9): **{knee}**",
        "",
        "## Research notes",
        "",
        "- If mix@300 ≈ mix@450 → ship smaller default `CTX_COMPRESS_MAX_CHARS=300`.",
        "- If budget_c@250 ≥ mix@250 → rare-idents help more when the window is tight.",
        "- Embed speed should rise as avg chars fall (same batch/seq).",
        "",
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    md = "\n".join(lines) + "\n"
    (OUT / "REPORT.md").write_text(md, encoding="utf-8")
    (OUT / "report.json").write_text(
        json.dumps({"knee_mix": knee, "base_soft_r5": base_soft, "results": results}, indent=2),
        encoding="utf-8",
    )
    print(md, flush=True)
    print(f"wrote {OUT / 'REPORT.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
