"""Budget-allocation bakeoff: how to spend ~450 chars for code retrieval.

Modes:
  skeleton, card  — classic compress baselines
  budget_a        — identity-heavy  (40/30/20/10 meta/sym/api/body)
  budget_b        — balanced        (25/25/20/30)
  budget_c        — body-heavy      (20/20/10/50) with rare-ident fill
  mix             — shipped hybrid (reference)

Fixed char budget=450, embed seq=512, FAISS+TQ, soft52+hard12.

Usage:
  python -u scripts/bench_budget_alloc.py
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

from conductor.architectures import MultiArchConductor
from conductor.bm25_index import BM25Index
from conductor.conductor import ConductorConfig
from conductor.graphify_retriever import ChunkSpan, GraphifyChunkRetriever
from enrich import chunk_repo_from_ir, inject_metadata
from graphify.serve import _load_graph
from repo_ir import Edge, FileIR, RepoIR, Symbol

from pipeline.chunk_compress import TARGET_SOFT, compress_chunk
from pipeline.embedder import Embedder
from pipeline.searcher import FaissDenseAdapter
from pipeline.store import ChunkRecord, PipelineStore
from pipeline.vectordb import VectorDatabase

REPO = ROOT / "testdata" / "frontend-mcp"
OUT = ROOT / "out" / "budget_alloc"
MODES = ("skeleton", "card", "budget_a", "budget_b", "budget_c", "mix")
BUDGET = TARGET_SOFT  # 450
SEQ = 512

# Import suites from seq A/B script if present, else inline minimal
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from bench_mix_seq_ab import HARD, SOFT  # type: ignore
except Exception:  # noqa: BLE001
    HARD = [
        {"q": "probe_validation_form FormProbeResult", "relevant": ["form_probe.py"]},
        {"q": "handle_session_start perception_session_start", "relevant": ["handlers.py", "dispatch_registry.py"]},
        {"q": "form probe invalid submit then valid", "relevant": ["form_probe.py"]},
        {"q": "browser session manager lock queue", "relevant": ["browser_session_manager.py", "session_store.py"]},
        {"q": "perception_runtime inspiration browser", "relevant": ["perception_runtime.py"]},
        {"q": "envelope make_envelope session start response", "relevant": ["envelope.py", "handlers.py"]},
        {"q": "where is perception_session_start registered", "relevant": ["dispatch_registry.py", "tools.py"]},
        {"q": "agent guidance session not found unreachable", "relevant": ["agent_guidance.py"]},
        {"q": "tool_catalog perception_session_start MCP tools", "relevant": ["tool_catalog.py", "tools.py"]},
        {"q": "dispatch_registry wire perception handlers", "relevant": ["dispatch_registry.py"]},
        {"q": "MCP instructions health session_start spine", "relevant": ["instructions.py", "agent_guidance.py"]},
        {"q": "component probe validation form", "relevant": ["form_probe.py"]},
    ]
    SOFT = HARD  # fallback


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


def build_mode(
    mode: str,
    source: list[ChunkRecord],
    graph: Path,
    emb: Embedder,
) -> tuple[MultiArchConductor, dict[str, Any]]:
    texts = [compress_chunk(c.enriched or "", mode, max_chars=BUDGET).text for c in source]
    base = OUT / "indexes" / mode
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
    print(f"\n=== EMBED {mode} avg_chars={statistics.mean(len(t) for t in texts):.1f} ===", flush=True)
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
        "avg_chars": round(statistics.mean(len(t) for t in texts), 1),
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
        print("ERROR: need graph_ir.json + graph.json from indexed frontend-mcp", flush=True)
        return 2

    print("re-enriching full corpus…", flush=True)
    ir = load_repo_ir(ir_path)
    ir.root = str(repo)
    source = full_chunks(repo, ir)
    print(f"chunks={len(source)} budget={BUDGET} seq={SEQ} modes={MODES}", flush=True)

    # example dump
    mid = sorted(source, key=lambda c: abs(len(c.text or "") - 400))[0]
    print(f"\n--- example {mid.file} ---", flush=True)
    for m in MODES:
        t = compress_chunk(mid.enriched or "", m, max_chars=BUDGET).text
        print(f"[{m} {len(t)}c]\n{t[:300]}\n…\n", flush=True)

    emb = Embedder(
        model="nomic-ai/CodeRankEmbed",
        cache_path=None,
        batch_size=int(os.environ.get("CTX_EMBED_BATCH", "16")),
        max_seq_length=SEQ,
    )
    emb.embed_one("warmup", is_query=True)

    results: dict[str, Any] = {}
    for mode in MODES:
        cond, meta = build_mode(mode, source, graph, emb)
        soft = eval_suite(cond, emb, SOFT)
        hard = eval_suite(cond, emb, HARD)
        print(
            json.dumps(
                {
                    "mode": mode,
                    "soft_R@5": soft["recall_at_5"],
                    "soft_MRR": soft["mrr"],
                    "hard_R@5": hard["recall_at_5"],
                    "hard_MRR": hard["mrr"],
                    "soft_fails": len(soft["failures"]),
                },
                indent=2,
            ),
            flush=True,
        )
        results[mode] = {"meta": meta, "soft": soft, "hard": hard}

    ranked = sorted(
        MODES,
        key=lambda m: (
            -results[m]["soft"]["recall_at_5"],
            -results[m]["hard"]["recall_at_5"],
            -results[m]["soft"]["mrr"],
            -results[m]["hard"]["mrr"],
        ),
    )

    lines = [
        "# Budget allocation bakeoff (fixed ~450 chars)",
        "",
        "Question: **how should we spend a fixed embedding budget** for code retrieval?",
        f"Budget={BUDGET} chars | seq={SEQ} | FAISS+TurboQuant | soft={len(SOFT)} hard={len(HARD)}",
        "",
        "| Mode | Alloc | Avg chars | Soft R@5 | Soft MRR | Hard R@5 | Hard MRR | Soft fails |",
        "|------|-------|-----------|----------|----------|----------|----------|------------|",
    ]
    alloc_note = {
        "skeleton": "AST skeleton",
        "card": "card (meta-first)",
        "budget_a": "40/30/20/10 meta/sym/api/body",
        "budget_b": "25/25/20/30",
        "budget_c": "20/20/10/50 + rare-idents",
        "mix": "shipped mix (ref)",
    }
    for m in MODES:
        r = results[m]
        lines.append(
            f"| {m} | {alloc_note[m]} | {r['meta']['avg_chars']} | {r['soft']['recall_at_5']} | "
            f"{r['soft']['mrr']} | {r['hard']['recall_at_5']} | {r['hard']['mrr']} | "
            f"{len(r['soft']['failures'])}/{r['soft']['n']} |"
        )
    lines += [
        "",
        f"## Winner: **{ranked[0]}**",
        "",
        f"Order: {' > '.join(ranked)}",
        "",
        "## Insight",
        "",
        "Body fill uses **rare-identifier** packing (not first-N characters).",
        "Compare budget_a vs budget_c to see identity-heavy vs rare-body spend at fixed total.",
        "",
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    md = "\n".join(lines) + "\n"
    (OUT / "REPORT.md").write_text(md, encoding="utf-8")
    (OUT / "report.json").write_text(
        json.dumps({"winner": ranked[0], "ranking": list(ranked), "budget": BUDGET, "seq": SEQ, "results": results}, indent=2),
        encoding="utf-8",
    )
    print(md, flush=True)
    print(f"wrote {OUT / 'REPORT.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
