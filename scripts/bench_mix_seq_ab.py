"""Fair A/B: mix@512 chars, embed seq=128 vs seq=512.

Same compressed texts; only CodeRank max_seq_length differs.
Scores soft (52) + hard (12) via R_plan on FAISS+TurboQuant.

Usage:
  python -u scripts/bench_mix_seq_ab.py
"""

from __future__ import annotations

import json
import math
import os
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
from graphify.serve import _load_graph

from pipeline.chunk_compress import compress_chunk, prepare_enriched_from_parts
from pipeline.embedder import Embedder
from pipeline.searcher import FaissDenseAdapter
from pipeline.store import ChunkRecord, PipelineStore
from pipeline.vectordb import VectorDatabase

REPO = ROOT / "testdata" / "frontend-mcp"
OUT = ROOT / "out" / "mix_seq_ab"
SEQS = (128, 512)

HARD: list[dict[str, Any]] = [
    {"q": "probe_validation_form FormProbeResult", "relevant": ["form_probe.py"]},
    {"q": "handle_session_start perception_session_start", "relevant": ["handlers.py", "dispatch_registry.py"]},
    {"q": "agent guidance session not found unreachable", "relevant": ["agent_guidance.py"]},
    {"q": "tool_catalog perception_session_start MCP tools", "relevant": ["tool_catalog.py", "tools.py"]},
    {"q": "dispatch_registry wire perception handlers", "relevant": ["dispatch_registry.py"]},
    {"q": "form probe invalid submit then valid", "relevant": ["form_probe.py"]},
    {"q": "browser session manager lock queue", "relevant": ["browser_session_manager.py", "session_store.py", "session.py"]},
    {"q": "perception_runtime inspiration browser", "relevant": ["perception_runtime.py"]},
    {"q": "MCP instructions health session_start spine", "relevant": ["instructions.py", "agent_guidance.py"]},
    {"q": "envelope make_envelope session start response", "relevant": ["envelope.py", "handlers.py"]},
    {"q": "component probe validation form", "relevant": ["form_probe.py"]},
    {"q": "where is perception_session_start registered", "relevant": ["dispatch_registry.py", "tools.py", "tool_catalog.py"]},
]

SOFT: list[dict[str, Any]] = [
    {"q": "how does an agent start a browser session and get an id back", "relevant": ["handlers.py", "dispatch_registry.py", "session_store.py", "tools.py"]},
    {"q": "where do we check the page form the wrong way first then the right way", "relevant": ["form_probe.py"]},
    {"q": "what tells the agent what to do when the session disappeared", "relevant": ["agent_guidance.py"]},
    {"q": "how are mcp tools listed and what should run after health check", "relevant": ["tool_catalog.py", "instructions.py", "tools.py"]},
    {"q": "where does the runtime register session start so tools can find it", "relevant": ["dispatch_registry.py"]},
    {"q": "how do we keep two tools from stepping on the same browser at once", "relevant": ["browser_session_manager.py", "handler_runner.py", "observability.py", "lock"]},
    {"q": "where does inspiration open a headed browser for looking at sites", "relevant": ["perception_runtime.py"]},
    {"q": "what packages the json response when a session starts successfully", "relevant": ["envelope.py", "handlers.py"]},
    {"q": "how does the agent know the ordered steps from cold start to verify", "relevant": ["instructions.py", "agent_guidance.py", "tool_catalog.py"]},
    {"q": "where is the playbook for invalid form submit then valid submit", "relevant": ["form_probe.py"]},
    {"q": "what happens if the site is down before we even start a session", "relevant": ["agent_guidance.py", "handlers.py", "health"]},
    {"q": "how do we observe the page after the session is already open", "relevant": ["observe", "handlers.py", "visual_capture"]},
    {"q": "where are design consistency checks decided for a screen", "relevant": ["consistency"]},
    {"q": "how does the system pick a component foundation before integrating", "relevant": ["component", "foundation", "integrate"]},
    {"q": "what captures network and console noise while diagnosing the ui", "relevant": ["console", "network", "observ"]},
    {"q": "where do we end the browser session cleanly when the agent is done", "relevant": ["session_end", "handlers.py", "dispatch_registry.py"]},
    {"q": "how does perception decide the next tool from the agent summary card", "relevant": ["agent_summary", "tool_catalog", "coordinator", "card"]},
    {"q": "what blocks implementation until enough evidence is gathered", "relevant": ["implement_blocked", "evidence", "owed", "pack"]},
    {"q": "where is auth handled before browser actions are allowed", "relevant": ["auth", "gate"]},
    {"q": "how do we take screenshots packs for design review feedback", "relevant": ["screenshot", "visual_feedback", "visual_capture"]},
    {"q": "how do i open a perception session when i first connect", "relevant": ["handlers.py", "dispatch_registry.py", "tools.py"]},
    {"q": "whats the tool name the agent should call to begin browsing", "relevant": ["tools.py", "tool_catalog.py", "instructions.py"]},
    {"q": "where is session_id created and handed back to the caller", "relevant": ["handlers.py", "envelope.py", "session_store.py"]},
    {"q": "how does closing the browser session work when finished", "relevant": ["handlers.py", "dispatch_registry.py", "session"]},
    {"q": "what error text means the session is gone and how to recover", "relevant": ["agent_guidance.py"]},
    {"q": "how do we intentionally submit a bad form to learn the rules", "relevant": ["form_probe.py"]},
    {"q": "where is the helper that probes forms without guessing fields", "relevant": ["form_probe.py"]},
    {"q": "invalid then valid form verification flow for agents", "relevant": ["form_probe.py"]},
    {"q": "what result object comes back from probing a validation form", "relevant": ["form_probe.py"]},
    {"q": "stop two mcp calls from racing on one browser tab", "relevant": ["browser_session", "handler_runner", "lock", "observability"]},
    {"q": "where is the headed browser spun up for inspiration scouting", "relevant": ["perception_runtime.py"]},
    {"q": "how do we snapshot the page for a design look after navigate", "relevant": ["visual_capture", "screenshot", "observe", "visual_feedback"]},
    {"q": "capture console errors and network failures during a diagnosis", "relevant": ["console", "network", "observ"]},
    {"q": "ordered mcp calls from health check through verify", "relevant": ["instructions.py", "tool_catalog.py", "agent_guidance.py"]},
    {"q": "what does the agent summary card tell us to call next", "relevant": ["tool_catalog", "agent_summary", "coordinator", "card"]},
    {"q": "when is the agent blocked from editing until evidence is enough", "relevant": ["implement_blocked", "evidence", "owed", "pack"]},
    {"q": "auth wall before any browser action is allowed", "relevant": ["auth", "gate"]},
    {"q": "how do we audit whether the ui matches design tokens", "relevant": ["consistency", "token"]},
    {"q": "pick a foundation component before wiring a new ui piece", "relevant": ["component", "foundation", "select_component"]},
    {"q": "inspiration pulse thumbs for copying chrome layout density", "relevant": ["inspiration", "pulse", "visual_feedback"]},
    {"q": "where is figma related intelligence for pulling design context", "relevant": ["figma"]},
    {"q": "seo checks that decide if a page fails visibility rules", "relevant": ["seo"]},
    {"q": "resource search for icons fonts illustrations without leaving mcp", "relevant": ["resource", "icon", "font"]},
    {"q": "how does the coordinator start an episode for the agent", "relevant": ["coordinator", "episode"]},
    {"q": "framework detection so docs and audits know react vs other", "relevant": ["framework", "detect"]},
    {"q": "full diagnosis that bundles console network and page state", "relevant": ["diagnosis", "full_diagnosis", "correlate"]},
    {"q": "wire the session start handler into the dispatch table", "relevant": ["dispatch_registry.py"]},
    {"q": "json envelope wrapping a successful session start reply", "relevant": ["envelope.py", "handlers.py"]},
    {"q": "site unreachable before session_start what should the agent do", "relevant": ["agent_guidance.py", "health"]},
    {"q": "take a design screenshot pack for visual feedback review", "relevant": ["screenshot", "visual_feedback", "visual_capture"]},
    {"q": "cold start playbook health then session then observe", "relevant": ["instructions.py", "tool_catalog.py", "agent_guidance.py"]},
    {"q": "end session tool after the agent finishes the flow", "relevant": ["session_end", "handlers.py", "dispatch_registry.py"]},
]


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


def eval_suite(conductor: MultiArchConductor, embedder: Embedder, suite: list[dict[str, Any]]) -> dict[str, Any]:
    r1 = r5 = r10 = 0
    rr = 0.0
    ndcgs: list[float] = []
    qms: list[float] = []
    fails: list[str] = []
    for item in suite:
        q, rel = item["q"], item["relevant"]
        t0 = time.perf_counter()
        qv = embedder.embed_one(q, is_query=True)
        hits = conductor.retrieve_R_plan(q, qv, top_k=10)
        qms.append((time.perf_counter() - t0) * 1000)
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
        "avg_query_ms": round(statistics.mean(qms), 1),
        "failures": fails,
    }


def build_arm(
    seq: int,
    mix_texts: list[str],
    source: list[ChunkRecord],
    graph_path: Path,
    embedder: Embedder,
) -> MultiArchConductor:
    out_base = OUT / f"seq{seq}"
    if out_base.exists():
        import shutil

        shutil.rmtree(out_base)
    out_base.mkdir(parents=True, exist_ok=True)
    vdb = VectorDatabase(root=out_base / "vectordb")
    store = PipelineStore(REPO.resolve(), base_dir=out_base / "store", vdb=vdb)

    records = [
        ChunkRecord(
            id=i,
            file=c.file,
            start_line=c.start_line,
            end_line=c.end_line,
            symbol=c.symbol,
            text=c.text,
            enriched=mix_texts[i],
        )
        for i, c in enumerate(source)
    ]

    print(f"\n=== EMBED mix seq={seq} chunks={len(mix_texts)} ===", flush=True)
    t0 = time.perf_counter()
    matrix = embedder.embed_many(mix_texts)
    embed_sec = time.perf_counter() - t0
    dim = int(matrix.shape[1])
    col = store.upsert_vectors(matrix, records, dim=dim, bits=4)
    store.save_chunks(records)
    store.save_meta({"compress_mode": "mix", "embed_seq": seq, "chunks": len(records), "collection": col.name})
    print(
        json.dumps(
            {
                "seq": seq,
                "embed_sec": round(embed_sec, 2),
                "chunk_per_s": round(len(mix_texts) / max(embed_sec, 1e-6), 2),
                "avg_chars": round(statistics.mean(len(t) for t in mix_texts), 1),
            },
            indent=2,
        ),
        flush=True,
    )

    files = [c.file.replace("\\", "/") for c in records]
    G = _load_graph(str(graph_path))
    spans = [
        ChunkSpan(index=c.id, file=files[i], start_line=c.start_line, end_line=c.end_line)
        for i, c in enumerate(records)
    ]
    return MultiArchConductor(
        files=files,
        bm25=BM25Index(mix_texts),
        dense=FaissDenseAdapter(col, n_chunks=len(records)),
        graph=GraphifyChunkRetriever(G, spans, depth=2),
        config=ConductorConfig(),
    )


def main() -> int:
    os.environ.setdefault("CTX_EMBED_BATCH", "16")
    os.environ.setdefault("CTX_ACCEL_PROFILE", "dml")
    repo = REPO.resolve()
    src = PipelineStore(repo)
    chunks = src.load_chunks()
    graph = src.base / "graph.json"
    if not chunks or not graph.is_file():
        print("ERROR: need indexed frontend-mcp (chunks + graph.json)", flush=True)
        return 2

    print(f"source chunks={len(chunks)} — building mix@512 texts once…", flush=True)
    mix_texts: list[str] = []
    for c in chunks:
        # Live store already mix-compressed; re-run mix for determinism if separator present
        src_txt = prepare_enriched_from_parts(c.file, c.symbol, c.text or "", c.enriched or "")
        # If already mix (no full enrich sep), use stored enriched as-is when short
        if "--------------------------------" not in (c.enriched or "") and len(c.enriched or "") <= 512:
            mix_texts.append(c.enriched or "")
        else:
            mix_texts.append(compress_chunk(src_txt, "mix", max_chars=512).text)

    print(
        json.dumps(
            {
                "n": len(mix_texts),
                "avg_chars": round(statistics.mean(len(t) for t in mix_texts), 1),
                "p50": sorted(len(t) for t in mix_texts)[len(mix_texts) // 2],
                "soft": len(SOFT),
                "hard": len(HARD),
            },
            indent=2,
        ),
        flush=True,
    )

    results: dict[str, Any] = {}
    for seq in SEQS:
        embedder = Embedder(
            model="nomic-ai/CodeRankEmbed",
            cache_path=None,  # fair wall times
            batch_size=int(os.environ.get("CTX_EMBED_BATCH", "16")),
            max_seq_length=seq,
        )
        embedder.embed_one("warmup", is_query=True)
        cond = build_arm(seq, mix_texts, chunks, graph, embedder)
        print(f"=== EVAL soft seq={seq} ===", flush=True)
        soft = eval_suite(cond, embedder, SOFT)
        print(json.dumps({k: soft[k] for k in ("recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10", "avg_query_ms")} | {"fails": len(soft["failures"])}, indent=2), flush=True)
        print(f"=== EVAL hard seq={seq} ===", flush=True)
        hard = eval_suite(cond, embedder, HARD)
        print(json.dumps({k: hard[k] for k in ("recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10", "avg_query_ms")} | {"fails": len(hard["failures"])}, indent=2), flush=True)
        results[str(seq)] = {"soft": soft, "hard": hard}

    # winner by soft R@5 then hard R@5 then soft MRR
    ranked = sorted(
        SEQS,
        key=lambda s: (
            -results[str(s)]["soft"]["recall_at_5"],
            -results[str(s)]["hard"]["recall_at_5"],
            -results[str(s)]["soft"]["mrr"],
            -results[str(s)]["hard"]["mrr"],
        ),
    )
    lines = [
        "# Mix@512 chars — embed seq 128 vs 512",
        "",
        "Identical mix texts; only `max_seq_length` differs. FAISS+TurboQuant 4-bit, R_plan.",
        "",
        "## Soft (52)",
        "",
        "| Seq | R@1 | R@5 | R@10 | MRR | nDCG | Q ms | Fails |",
        "|-----|-----|-----|------|-----|------|------|-------|",
    ]
    for s in SEQS:
        r = results[str(s)]["soft"]
        lines.append(
            f"| {s} | {r['recall_at_1']} | {r['recall_at_5']} | {r['recall_at_10']} | "
            f"{r['mrr']} | {r['ndcg_at_10']} | {r['avg_query_ms']} | {len(r['failures'])}/{r['n']} |"
        )
    lines += [
        "",
        "## Hard (12)",
        "",
        "| Seq | R@1 | R@5 | R@10 | MRR | nDCG | Q ms | Fails |",
        "|-----|-----|-----|------|-----|------|------|-------|",
    ]
    for s in SEQS:
        r = results[str(s)]["hard"]
        lines.append(
            f"| {s} | {r['recall_at_1']} | {r['recall_at_5']} | {r['recall_at_10']} | "
            f"{r['mrr']} | {r['ndcg_at_10']} | {r['avg_query_ms']} | {len(r['failures'])}/{r['n']} |"
        )
    lines += ["", f"## Winner: **seq={ranked[0]}**", "", f"Order: {' > '.join(str(x) for x in ranked)}", ""]
    s128, s512 = results["128"]["soft"], results["512"]["soft"]
    lines.append(
        f"Soft R@5 Δ(512−128) = {s512['recall_at_5'] - s128['recall_at_5']:+.4f}; "
        f"MRR Δ = {s512['mrr'] - s128['mrr']:+.4f}"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    md = "\n".join(lines) + "\n"
    (OUT / "REPORT.md").write_text(md, encoding="utf-8")
    (OUT / "report.json").write_text(
        json.dumps({"winner": ranked[0], "ranking": list(ranked), "results": results}, indent=2),
        encoding="utf-8",
    )
    print(md, flush=True)
    print(f"wrote {OUT / 'REPORT.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
