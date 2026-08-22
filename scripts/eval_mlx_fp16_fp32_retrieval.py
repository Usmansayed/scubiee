#!/usr/bin/env python3
"""Compare MLX FP32 vs FP16 retrieval on the same codebase.

NOTE (product 0.2.18+): production weights are FP16-only. ``CTX_MLX_DTYPE=float32``
is ignored by ``pipeline.mlx_mac.resolve_embed_dtype`` — both legs run FP16.
This script is kept for historical A/B notes only.

Indexes this repo twice (FP32 then FP16), runs 50 grounded queries
(35 soft NL, 15 hard symbol/confusable/multihop), reports hit@k / MRR.

    python scripts/eval_mlx_fp16_fp32_retrieval.py --repo . --index --eval
    python scripts/eval_mlx_fp16_fp32_retrieval.py --repo . --eval-only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))

OUT = ROOT / "docs" / "mlx-fp16-fp32-retrieval.json"

# 35 soft + 15 hard — gold is any path suffix match in top-k file list.
SOFT_QUERIES: list[dict] = [
    {"id": "soft01", "query": "how does the MLX backend embed CodeRank on the Apple GPU", "files_substr": ["mlx_mac.py"]},
    {"id": "soft02", "query": "where do we refuse to run MLX on CPU when Metal is unavailable", "files_substr": ["mlx_mac.py"]},
    {"id": "soft03", "query": "pad each embedding batch only to its longest sequence not always five twelve", "files_substr": ["mlx_mac.py", "embedder.py"]},
    {"id": "soft04", "query": "detect which source files changed since the last index using content hashes", "files_substr": ["merkle.py", "freshness.py"]},
    {"id": "soft05", "query": "compress embedding vectors with turboquant before storing in faiss", "files_substr": ["turbo_quant.py", "vectordb.py"]},
    {"id": "soft06", "query": "adaptive batch size when the machine is under memory or cpu pressure during embed", "files_substr": ["resources.py", "resource_envelope.py"]},
    {"id": "soft07", "query": "patch CoreML ONNX when RoPE leaves an empty tensor slice", "files_substr": ["coreml_mac.py"]},
    {"id": "soft08", "query": "capability cards that answer soft natural language locate queries", "files_substr": ["capability.py"]},
    {"id": "soft09", "query": "MCP tools for map focus and expand context navigation", "files_substr": ["mcp_locate.py", "locate.py"]},
    {"id": "soft10", "query": "resolve a stable project id when the repository path moves", "files_substr": ["project_id.py"]},
    {"id": "soft11", "query": "compress chunk bodies with mix or skeleton modes before embedding", "files_substr": ["chunk_compress.py"]},
    {"id": "soft12", "query": "extract symbols and imports from source files into a graph", "files_substr": ["graphify/extract.py", "symbol_resolution.py"]},
    {"id": "soft13", "query": "decide whether search needs a full reindex or incremental sync", "files_substr": ["freshness.py", "incremental.py"]},
    {"id": "soft14", "query": "search the faiss vector collection for nearest chunk embeddings", "files_substr": ["vectordb.py", "searcher.py"]},
    {"id": "soft15", "query": "classify a query as soft natural language versus path-like hard lookup", "files_substr": ["query_router.py"]},
    {"id": "soft16", "query": "background daemon that serves search over http", "files_substr": ["daemon.py", "server.py"]},
    {"id": "soft17", "query": "choose between fastembed onnx and mlx for document embedding", "files_substr": ["embedder.py", "accel.py"]},
    {"id": "soft18", "query": "preflight checks that refuse index when semantic backend is missing", "files_substr": ["preflight.py"]},
    {"id": "soft19", "query": "combine bm25 dense and graph signals in the D channel reranker", "files_substr": ["architectures.py", "conductor.py"]},
    {"id": "soft20", "query": "patch bm25 text from disk while dense embeddings catch up after edits", "files_substr": ["hot_patch.py", "engine.py"]},
    {"id": "soft21", "query": "persist session state and token budgets for agent workflows", "files_substr": ["session_store.py", "work_session.py"]},
    {"id": "soft22", "query": "register the CodeRank ONNX model with fastembed custom models", "files_substr": ["accel.py"]},
    {"id": "soft23", "query": "incrementally re-embed only changed chunks not the whole repository", "files_substr": ["incremental.py"]},
    {"id": "soft24", "query": "store vectors in named collections under the context engine home directory", "files_substr": ["vectordb.py", "store.py"]},
    {"id": "soft25", "query": "convert graphify extraction output into repo ir for chunking", "files_substr": ["parse_harness/graphify_adapter.py"]},
    {"id": "soft26", "query": "inject file and symbol metadata into enriched chunk text", "files_substr": ["enrich", "indexer.py"]},
    {"id": "soft27", "query": "track which files were touched in the current working session", "files_substr": ["work_session.py"]},
    {"id": "soft28", "query": "fair scheduling priority for embed versus index jobs", "files_substr": ["fair_schedule.py"]},
    {"id": "soft29", "query": "checksum guard when publishing index artifacts", "files_substr": ["artifact_guard.py"]},
    {"id": "soft30", "query": "background live reindex when files change during development", "files_substr": ["live_reindex.py", "sync_loop.py"]},
    {"id": "soft31", "query": "sealed navigation read outline and neighbors over the code graph", "files_substr": ["context_nav.py", "graphify_mcp_tools.py"]},
    {"id": "soft32", "query": "estimate token savings from compact search hits versus reading whole files", "files_substr": ["token_meter.py"]},
    {"id": "soft33", "query": "merkle snapshot per chunk for fine grained invalidation", "files_substr": ["chunk_merkle.py"]},
    {"id": "soft34", "query": "policy for where indexes and vector db files are stored on disk", "files_substr": ["storage_policy.py", "project_id.py"]},
    {"id": "soft35", "query": "detect hardware and persist recommended acceleration profile", "files_substr": ["hardware.py", "accel.py"]},
]

HARD_QUERIES: list[dict] = [
    {"id": "hard01", "bucket": "symbol", "query": "CodeRankMLX forward_tokens embed_ids", "files_substr": ["mlx_mac.py"]},
    {"id": "hard02", "bucket": "symbol", "query": "require_mlx_gpu mlx_device_report", "files_substr": ["mlx_mac.py"]},
    {"id": "hard03", "bucket": "symbol", "query": "bypass_empty_rotary_remainders norot0 onnx", "files_substr": ["coreml_mac.py"]},
    {"id": "hard04", "bucket": "symbol", "query": "scaled_dot_product_attention CTX_MLX_FAST_ATTN", "files_substr": ["mlx_mac.py"]},
    {"id": "hard05", "bucket": "symbol", "query": "resolve_runtime CTX_EMBED_BACKEND mlx overlay", "files_substr": ["accel.py"]},
    {"id": "hard06", "bucket": "symbol", "query": "FaissDenseAdapter col.search IndexIDMap2", "files_substr": ["searcher.py"]},
    {"id": "hard07", "bucket": "symbol", "query": "retrieve_D_channel_best MultiArchConductor", "files_substr": ["architectures.py", "engine.py"]},
    {"id": "hard08", "bucket": "symbol", "query": "tokenize_batch enable_padding longest batch", "files_substr": ["mlx_mac.py"]},
    {"id": "hard09", "bucket": "symbol", "query": "PipelineStore upsert_vectors turboquant", "files_substr": ["store.py", "vectordb.py"]},
    {"id": "hard10", "bucket": "symbol", "query": "IndexDeferred wait_for_capacity resource manager", "files_substr": ["indexer.py", "resources.py"]},
    {"id": "hard11", "bucket": "confusable", "query": "CoreML static batch pad 512 CodeRank onnx metal", "files_substr": ["coreml_mac.py"]},
    {"id": "hard12", "bucket": "confusable", "query": "validate_provider inspect_accel preflight not configure", "files_substr": ["preflight.py"]},
    {"id": "hard13", "bucket": "multihop", "query": "rotate-half RoPE base 1000 head dim 64 nomic bert", "files_substr": ["mlx_mac.py"]},
    {"id": "hard14", "bucket": "multihop", "query": "Represent this query for searching relevant code prefix is_query", "files_substr": ["embedder.py"]},
    {"id": "hard15", "bucket": "distractor", "query": "sentence-transformers coderank pytorch fallback backend", "files_substr": ["embedder.py"]},
]

ALL_QUERIES = SOFT_QUERIES + HARD_QUERIES


@dataclass
class CaseResult:
    id: str
    kind: str
    bucket: str
    query: str
    hit: bool
    rank: int | None
    returned: list[str]
    elapsed_ms: float


def _norm(path: str) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def _hit(files: list[str], gold: list[str], top_k: int) -> tuple[bool, int | None]:
    for i, f in enumerate(files[:top_k], start=1):
        nf = _norm(f)
        if any(nf.endswith(g) or g in nf for g in gold):
            return True, i
    return False, None


def run_retrieval(repo: Path, top_k: int = 8) -> dict:
    os.environ["CTX_REPO"] = str(repo.resolve())
    os.environ.setdefault("CTX_CAPABILITY", "off")
    os.environ.setdefault("CTX_RETRIEVE", "D_channel_best")

    from pipeline.engine import clear_engines, load_engine

    clear_engines()
    # Drop cached embedder so query vectors use current CTX_MLX_* env.
    import pipeline.engine as eng

    with eng._LOCK:
        eng._EMBEDDERS.clear()

    engine = load_engine(repo, force_reload=True)
    meta = engine.store.load_meta()
    results: list[CaseResult] = []
    for item in ALL_QUERIES:
        t0 = time.perf_counter()
        hits = engine.search(item["query"], top_k=top_k, skip_freshness=True)
        ms = (time.perf_counter() - t0) * 1000
        files = [h.file for h in hits]
        ok, rank = _hit(files, item["files_substr"], top_k)
        results.append(
            CaseResult(
                id=item["id"],
                kind="soft" if item["id"].startswith("soft") else "hard",
                bucket=item.get("bucket", "soft"),
                query=item["query"],
                hit=ok,
                rank=rank,
                returned=files[:top_k],
                elapsed_ms=round(ms, 1),
            )
        )

    def _summary(rows: list[CaseResult]) -> dict:
        n = len(rows)
        hits = sum(1 for r in rows if r.hit)
        ranks = [r.rank for r in rows if r.rank]
        mrr = sum(1 / r for r in ranks) / n if n else 0.0
        hit1 = sum(1 for r in rows if r.rank == 1)
        hit5 = sum(1 for r in rows if r.rank is not None and r.rank <= 5)
        return {
            "n": n,
            "hits": hits,
            "hit@1": round(hit1 / n, 4) if n else 0.0,
            "hit@5": round(hit5 / n, 4) if n else 0.0,
            f"hit@{top_k}": round(hits / n, 4) if n else 0.0,
            "mrr": round(mrr, 4),
        }

    soft = [r for r in results if r.kind == "soft"]
    hard = [r for r in results if r.kind == "hard"]
    return {
        "embed_backend": meta.get("embed_backend"),
        "embed_model": meta.get("embed_model"),
        "chunks": meta.get("chunks"),
        "top_k": top_k,
        "overall": _summary(results),
        "soft": _summary(soft),
        "hard": _summary(hard),
        "cases": [r.__dict__ for r in results],
    }


def index_repo(repo: Path, *, label: str, env: dict[str, str]) -> float:
    run_env = os.environ.copy()
    run_env.update(env)
    run_env["CTX_RM_DISABLE"] = "1"
    run_env["CTX_EMBED_NO_CACHE"] = "1"
    run_env["CTX_EMBED_BACKEND"] = "mlx"
    store = Path.home() / ".context-engine" / "projects"
    # clear embed cache for project after resolve — indexer uses store.embed_cache
    cmd = [sys.executable, "-m", "pipeline", "index", str(repo), "--force"]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env=run_env, cwd=str(repo), capture_output=True, text=True)
    wall = time.perf_counter() - t0
    if proc.returncode != 0:
        print(proc.stdout, proc.stderr, file=sys.stderr)
        raise SystemExit(f"{label} index failed rc={proc.returncode}")
    print(f"[index] {label} done in {wall:.1f}s", flush=True)
    return wall


def compare(fp32: dict, fp16: dict) -> dict:
    agree = 0
    same_top1 = 0
    n = len(fp32["cases"])
    deltas = []
    for a, b in zip(fp32["cases"], fp16["cases"], strict=True):
        if a["hit"] == b["hit"]:
            agree += 1
        if a["returned"] and b["returned"] and a["returned"][0] == b["returned"][0]:
            same_top1 += 1
        deltas.append({"id": a["id"], "fp32_hit": a["hit"], "fp16_hit": b["hit"], "fp32_rank": a["rank"], "fp16_rank": b["rank"]})
    fp32_only = [d["id"] for d in deltas if d["fp32_hit"] and not d["fp16_hit"]]
    fp16_only = [d["id"] for d in deltas if d["fp16_hit"] and not d["fp32_hit"]]
    return {
        "agreement_hit": round(agree / n, 4) if n else 0.0,
        "same_top1": round(same_top1 / n, 4) if n else 0.0,
        "fp32_only_hits": fp32_only,
        "fp16_only_hits": fp16_only,
        "regressions_fp16": fp32_only,
        "improvements_fp16": fp16_only,
        "per_case": deltas,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--index", action="store_true", help="run fp32 then fp16 index before eval")
    ap.add_argument("--eval-only", action="store_true")
    ap.add_argument("--label", default="", help="eval single label: fp32 or fp16")
    ap.add_argument("--out-json", default="", help="write report fragment to path (for subprocess)")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()

    fp32_env = {
        "CTX_MLX_DTYPE": "float32",
        "CTX_EMBED_BATCH": "96",
        "CTX_MLX_EVAL": "output",
        "CTX_MLX_CACHE_MB": "256",
    }
    fp16_env = {
        "CTX_MLX_DTYPE": "float16",
        "CTX_EMBED_BATCH": "48",
        "CTX_MLX_EVAL": "output",
        "CTX_MLX_CACHE_MB": "256",
        "CTX_MLX_FAST_ATTN": "1",
        "CTX_MLX_FAST_LN": "1",
    }

    report: dict = {"repo": str(repo), "queries": len(ALL_QUERIES), "soft": len(SOFT_QUERIES), "hard": len(HARD_QUERIES)}

    if args.label:
        os.environ.update(fp32_env if args.label == "fp32" else fp16_env)
        os.environ["CTX_EMBED_BACKEND"] = "mlx"
        fragment = run_retrieval(repo, top_k=args.top_k)
        if args.out_json:
            Path(args.out_json).write_text(json.dumps(fragment, indent=2) + "\n")
        else:
            print(json.dumps(fragment, indent=2))
        return 0

    if args.index and not args.eval_only:
        report["index_fp32_s"] = round(index_repo(repo, label="fp32", env=fp32_env), 2)
        os.environ.update(fp32_env)
        os.environ["CTX_EMBED_BACKEND"] = "mlx"
        report["fp32"] = run_retrieval(repo, top_k=args.top_k)

        report["index_fp16_s"] = round(index_repo(repo, label="fp16", env=fp16_env), 2)
        os.environ.update(fp16_env)
        os.environ["CTX_EMBED_BACKEND"] = "mlx"
        report["fp16"] = run_retrieval(repo, top_k=args.top_k)
    elif args.eval_only:
        import tempfile

        for label, env in [("fp32", fp32_env), ("fp16", fp16_env)]:
            with tempfile.NamedTemporaryFile(suffix=f"-{label}.json", delete=False) as tf:
                out_path = tf.name
            env2 = os.environ.copy()
            env2.update(env)
            env2["CTX_EMBED_BACKEND"] = "mlx"
            p = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--repo",
                    str(repo),
                    "--top-k",
                    str(args.top_k),
                    "--label",
                    label,
                    "--out-json",
                    out_path,
                ],
                env=env2,
                capture_output=True,
                text=True,
            )
            if p.returncode != 0:
                print(p.stdout, p.stderr, file=sys.stderr)
                raise SystemExit(p.returncode)
            report[label] = json.loads(Path(out_path).read_text())
            Path(out_path).unlink(missing_ok=True)
    else:
        raise SystemExit("Pass --index (full fp32/fp16 index + eval) or --eval-only")

    if "fp32" in report and "fp16" in report:
        report["compare"] = compare(report["fp32"], report["fp16"])
        c = report["compare"]
        print("\n=== RETRIEVAL: FP32 vs FP16 ===")
        for label in ("fp32", "fp16"):
            s = report[label]["overall"]
            ss = report[label]["soft"]
            sh = report[label]["hard"]
            print(
                f"{label:>4}  hit@{args.top_k}={s[f'hit@{args.top_k}']:.1%} ({s['hits']}/{s['n']})  "
                f"mrr={s['mrr']:.3f}  soft={ss[f'hit@{args.top_k}']:.1%}  hard={sh[f'hit@{args.top_k}']:.1%}"
            )
        print(
            f"agreement={c['agreement_hit']:.1%}  same_top1={c['same_top1']:.1%}  "
            f"fp32_only={c['fp32_only_hits']}  fp16_only={c['fp16_only_hits']}"
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
