#!/usr/bin/env python3
"""Compare ONNX FP32 vs FP16 vs INT8 retrieval quality for CodeRankEmbed.

Real-world GPU eval: DirectML-accelerated embedding of the full repo corpus
(3k+ chunks), 50 hard NL queries, hit@k / MRR / per-query agreement.

    python scripts/eval_onnx_fp32_fp16_int8.py --repo .

Run with the Python that has onnxruntime-directml installed (scubiee's Python).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / "docs" / "onnx-fp32-fp16-int8-retrieval.json"

# ---------------------------------------------------------------------------
# 50 HARD soft queries — all natural-language, intentionally tricky.
# Ground truth: any file-path suffix match in top-k file-deduped results.
# ---------------------------------------------------------------------------

QUERIES: list[dict] = [
    {"id": "q01", "query": "initialize the sentence embedding model with hardware-specific acceleration providers", "files_substr": ["embedder.py", "accel.py"]},
    {"id": "q02", "query": "register a custom ONNX model definition so the fast embedding library knows about it", "files_substr": ["accel.py"]},
    {"id": "q03", "query": "prepend instruction prefix to search queries before encoding them", "files_substr": ["embedder.py"]},
    {"id": "q04", "query": "warm up the embedding session by running a dummy batch through the model", "files_substr": ["embedder.py", "accel.py"]},
    {"id": "q05", "query": "choose between GPU-accelerated and CPU-only execution providers at runtime", "files_substr": ["accel.py"]},
    {"id": "q06", "query": "split source code into overlapping semantic chunks before embedding", "files_substr": ["chunker.py", "chunk_compress.py"]},
    {"id": "q07", "query": "detect which repository files have changed since the last indexing run", "files_substr": ["merkle.py", "freshness.py"]},
    {"id": "q08", "query": "persist embedded vectors to a local FAISS collection on disk", "files_substr": ["vectordb.py", "store.py"]},
    {"id": "q09", "query": "extract import relationships and function calls into a dependency graph", "files_substr": ["graphify", "extract.py"]},
    {"id": "q10", "query": "skip binary files and large generated assets during the indexing walk", "files_substr": ["walk.py", "filter"]},
    {"id": "q11", "query": "blend dense vector similarity with sparse keyword matching for hybrid results", "files_substr": ["architectures.py", "conductor.py"]},
    {"id": "q12", "query": "boost results that are structurally connected to the query via the code graph", "files_substr": ["architectures.py", "graph"]},
    {"id": "q13", "query": "find nearest neighbors in the vector index given a query embedding", "files_substr": ["vectordb.py", "searcher.py"]},
    {"id": "q14", "query": "classify whether a user query is asking about a specific symbol or a general concept", "files_substr": ["query_router.py"]},
    {"id": "q15", "query": "rerank candidate results using multiple signal channels before returning", "files_substr": ["architectures.py", "conductor.py"]},
    {"id": "q16", "query": "start a background HTTP server that answers search requests from AI tools", "files_substr": ["daemon.py", "server.py"]},
    {"id": "q17", "query": "expose code navigation tools over the model context protocol for IDE plugins", "files_substr": ["mcp_locate.py", "locate.py"]},
    {"id": "q18", "query": "keep the search index fresh by watching filesystem events in real time", "files_substr": ["live_reindex.py", "sync_loop.py", "watcher"]},
    {"id": "q19", "query": "handle graceful shutdown of the engine daemon when the system sends a signal", "files_substr": ["daemon.py", "engine.py"]},
    {"id": "q20", "query": "health check endpoint that reports whether the engine is ready to serve queries", "files_substr": ["daemon.py", "server.py", "engine.py"]},
    {"id": "q21", "query": "command line interface entry point that dispatches subcommands", "files_substr": ["__main__.py"]},
    {"id": "q22", "query": "wipe all local data including downloaded models and tool configurations", "files_substr": ["wipe.py"]},
    {"id": "q23", "query": "run diagnostic checks and produce a shareable report for support", "files_substr": ["__main__.py", "diagnose"]},
    {"id": "q24", "query": "connect the search engine as an MCP server to multiple AI coding tools at once", "files_substr": ["__main__.py", "connect"]},
    {"id": "q25", "query": "inspect available hardware resources like GPU memory and CPU cores", "files_substr": ["resources.py", "hardware"]},
    {"id": "q26", "query": "convert ONNX float weights into half-precision numpy arrays for Apple GPU", "files_substr": ["mlx_mac.py"]},
    {"id": "q27", "query": "run the full transformer forward pass using Metal compute shaders", "files_substr": ["mlx_mac.py"]},
    {"id": "q28", "query": "apply rotary position embeddings to query and key tensors in attention", "files_substr": ["mlx_mac.py"]},
    {"id": "q29", "query": "CoreML static batch padding workaround for the ONNX runtime on Intel Mac", "files_substr": ["coreml_mac.py"]},
    {"id": "q30", "query": "benchmark embedding throughput across different batch sizes on Apple hardware", "files_substr": ["bench_apple_silicon", "bench_mlx"]},
    {"id": "q31", "query": "derive a stable unique identifier for a repository that survives path renames", "files_substr": ["project_id.py"]},
    {"id": "q32", "query": "manage multiple indexed repositories from a central registry file", "files_substr": ["registry", "project_id.py"]},
    {"id": "q33", "query": "compress stored chunk embeddings using scalar quantization to save disk space", "files_substr": ["turbo_quant.py", "vectordb.py"]},
    {"id": "q34", "query": "cache embedding results so identical text does not get re-encoded", "files_substr": ["embedder.py", "cache"]},
    {"id": "q35", "query": "load and save engine metadata alongside the vector index files", "files_substr": ["store.py", "engine.py"]},
    {"id": "q36", "query": "integration test that verifies end-to-end indexing and search on a fixture repo", "files_substr": ["test_cli", "test_index", "test_search"]},
    {"id": "q37", "query": "validate that the AST parser handles edge cases like decorators and nested classes", "files_substr": ["test_ast", "ast"]},
    {"id": "q38", "query": "measure retrieval precision against a curated set of known-good query answers", "files_substr": ["eval_", "retrieval"]},
    {"id": "q39", "query": "mock the GPU runtime to test fallback behavior on machines without acceleration", "files_substr": ["test_install_profile", "test_accel"]},
    {"id": "q40", "query": "verify the daemon starts and responds to search requests correctly", "files_substr": ["test_daemon", "test_server"]},
    {"id": "q41", "query": "session-aware context that remembers which files the developer recently opened", "files_substr": ["work_session.py", "session"]},
    {"id": "q42", "query": "pin important files so they always rank higher in search results", "files_substr": ["workspace", "pin"]},
    {"id": "q43", "query": "navigate from a code location to its structural neighbors like callers and callees", "files_substr": ["context_nav.py", "graph"]},
    {"id": "q44", "query": "limit memory consumption during embedding by controlling the batch window", "files_substr": ["memory_budget.py", "resources.py"]},
    {"id": "q45", "query": "gracefully degrade search quality when the index is being rebuilt in the background", "files_substr": ["hot_patch.py", "engine.py"]},
    {"id": "q46", "query": "first-time setup wizard that downloads models and calibrates embedding speed", "files_substr": ["__main__.py", "accel.py"]},
    {"id": "q47", "query": "user preferences file that controls default behavior like batch size and backend", "files_substr": ["accel.py", "settings"]},
    {"id": "q48", "query": "preflight validation that blocks indexing if required dependencies are missing", "files_substr": ["preflight.py"]},
    {"id": "q49", "query": "data migration logic when the index schema changes between versions", "files_substr": ["migrate", "migration"]},
    {"id": "q50", "query": "generate MCP configuration JSON for each supported AI coding tool", "files_substr": ["__main__.py", "connect", "mcp"]},
]

QUERY_PREFIX = "Represent this query for searching relevant code: "


@dataclass
class CaseResult:
    id: str
    query: str
    hit: bool
    rank: int | None
    returned: list[str]


# ---------------------------------------------------------------------------
# Direct embedding using FastEmbed (same as Scubiee production)
# ---------------------------------------------------------------------------

def _register_coderank() -> None:
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    try:
        TextEmbedding.add_custom_model(
            model="nomic-ai/CodeRankEmbed",
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf="jamie8johnson/CodeRankEmbed-onnx"),
            dim=768,
            model_file="onnx/model.onnx",
            description="CodeRankEmbed ONNX",
            license="mit",
            size_in_gb=0.5,
        )
    except ValueError:
        pass  # already registered


def _prepare_variant_workspace(snap: Path, variant_onnx: Path, workspace: Path) -> Path:
    """Build an isolated model dir with tokenizer + this variant as onnx/model.onnx.

    Avoids copying onto the shared FastEmbed cache (often locked by CE daemon)
    and avoids shutil.copy2(same, same) which fails on Windows.
    """
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)

    for name in ("config.json", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json"):
        src = snap / name
        if src.is_file():
            shutil.copy2(src, workspace / name)

    onnx_dir = workspace / "onnx"
    onnx_dir.mkdir(parents=True, exist_ok=True)
    dest = onnx_dir / "model.onnx"
    # Prefer hardlink (instant, no extra disk) then fall back to copy.
    try:
        os.link(variant_onnx, dest)
    except OSError:
        shutil.copy2(variant_onnx, dest)
    return workspace


def _stop_ce_holders() -> None:
    """Best-effort stop of pipeline engine/MCP so shared ORT files can be read."""
    try:
        subprocess.run(
            [sys.executable, "-m", "pipeline", "engine", "stop"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        pass
    # Kill leftover watchdog/MCP holders if stop did not clear them.
    try:
        import psutil
    except ImportError:
        return
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info.get("cmdline") or [])
        except (psutil.Error, TypeError):
            continue
        if "pipeline" in cmd and any(
            token in cmd for token in ("engine", "mcp_locate", "watchdog")
        ):
            try:
                proc.kill()
            except psutil.Error:
                pass


class OnnxEmbedder:
    """CodeRankEmbed via FastEmbed with DirectML GPU — same path as Scubiee."""

    def __init__(self, model_dir: Path):
        """Load from an isolated model dir (must contain onnx/model.onnx)."""
        import onnxruntime as ort
        from fastembed import TextEmbedding

        _register_coderank()

        providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        avail = ort.get_available_providers()
        providers = [p for p in providers if p in avail]

        # Force a fresh model load from the isolated workspace (no shared-cache swap).
        self._model = TextEmbedding.__new__(TextEmbedding)
        self._model.__init__(
            model_name="nomic-ai/CodeRankEmbed",
            threads=1,
            providers=providers,
            lazy_load=True,
            specific_model_path=str(model_dir),
        )
        # Warmup GPU
        list(self._model.embed(["warmup GPU pipeline"], batch_size=1, parallel=None))
        self._providers = providers

    def embed(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        """Embed all texts using FastEmbed's optimized pipeline with progress bar."""
        total = len(texts)
        bar_width = 40
        t0 = time.perf_counter()

        # FastEmbed .embed() is a generator — consume in batches and track progress
        all_vecs = []
        for i, vec in enumerate(self._model.embed(texts, batch_size=batch_size, parallel=None)):
            all_vecs.append(vec)
            done = i + 1
            if done % batch_size == 0 or done == total:
                pct = done / total
                filled = int(bar_width * pct)
                elapsed = time.perf_counter() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                bar = "#" * filled + "-" * (bar_width - filled)
                print(f"\r    [{bar}] {done}/{total} ({pct:.0%}) {rate:.0f} chunks/s  ETA {eta:.0f}s", end="", flush=True)
        print()
        return np.asarray(all_vecs, dtype=np.float32)


# ---------------------------------------------------------------------------
# Corpus: full repo chunking (50 lines, 15 overlap — same as production)
# ---------------------------------------------------------------------------

def collect_chunks(repo: Path) -> list[dict]:
    """Walk the full repo and chunk every indexable file (matching Scubiee's scope)."""
    chunks = []
    extensions = {".py", ".ts", ".js", ".md", ".json", ".toml", ".yaml", ".yml",
                  ".cfg", ".txt", ".sh", ".ps1", ".html", ".css"}
    ignore_dirs = {".git", "node_modules", "__pycache__", ".pytest_cache",
                   "dist", "build", ".venv", "venv", ".freebuff", ".agents",
                   ".cursor", ".kiro", ".superpowers",
                   # Large fixture/output dirs that aren't real source code
                   "out", "testdata", "graphify-out", "research"}

    for dirpath, dirnames, filenames in os.walk(repo):
        # Filter out ignored and all dot-prefixed directories
        dirnames[:] = [d for d in dirnames
                       if d not in ignore_dirs
                       and not d.startswith(".")]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() not in extensions:
                continue
            rel = str(fpath.relative_to(repo)).replace("\\", "/")
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if not text.strip() or len(text) > 200_000:
                continue
            lines = text.splitlines()
            chunk_size, overlap = 50, 15
            step = chunk_size - overlap
            for start in range(0, max(1, len(lines)), step):
                block = "\n".join(lines[start:start + chunk_size])
                if block.strip():
                    chunks.append({"file": rel, "text": block[:2000]})
    return chunks


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _hit(files: list[str], gold: list[str], top_k: int) -> tuple[bool, int | None]:
    for i, f in enumerate(files[:top_k], start=1):
        nf = _norm(f)
        if any(nf.endswith(g) or g in nf for g in gold):
            return True, i
    return False, None


def run_eval(embedder: OnnxEmbedder, chunk_vecs: np.ndarray,
             chunk_files: list[str], top_k: int) -> dict:
    """Embed queries, FAISS search, compute metrics."""
    import faiss

    dim = chunk_vecs.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(chunk_vecs)

    results: list[CaseResult] = []
    # Embed all queries at once (FastEmbed handles prefix internally via passage_embed)
    query_texts = [QUERY_PREFIX + item["query"] for item in QUERIES]
    query_vecs = embedder.embed(query_texts, batch_size=len(query_texts))

    for i, item in enumerate(QUERIES):
        q_vec = query_vecs[i:i+1]
        _, indices = index.search(q_vec, top_k * 4)

        seen: set[str] = set()
        ranked_files: list[str] = []
        for idx in indices[0]:
            if idx < 0:
                continue
            f = chunk_files[idx]
            if f not in seen:
                seen.add(f)
                ranked_files.append(f)
            if len(ranked_files) >= top_k:
                break

        ok, rank = _hit(ranked_files, item["files_substr"], top_k)
        results.append(CaseResult(
            id=item["id"], query=item["query"],
            hit=ok, rank=rank, returned=ranked_files[:top_k],
        ))

    n = len(results)
    hits_count = sum(1 for r in results if r.hit)
    ranks = [r.rank for r in results if r.rank]
    mrr = sum(1 / r for r in ranks) / n if n else 0.0
    hit1 = sum(1 for r in results if r.rank == 1)
    hit5 = sum(1 for r in results if r.rank is not None and r.rank <= 5)

    return {
        "n": n, "hits": hits_count,
        "hit@1": round(hit1 / n, 4),
        "hit@5": round(hit5 / n, 4),
        f"hit@{top_k}": round(hits_count / n, 4),
        "mrr": round(mrr, 4),
        "cases": [asdict(r) for r in results],
    }


def compare_three(fp32: dict, fp16: dict, int8: dict) -> dict:
    n = len(fp32["cases"])
    results: dict = {"n": n}
    pairs = [("fp32_vs_fp16", fp32, fp16), ("fp32_vs_int8", fp32, int8), ("fp16_vs_int8", fp16, int8)]
    for label, a_data, b_data in pairs:
        agree = same_top1 = 0
        for a, b in zip(a_data["cases"], b_data["cases"], strict=True):
            if a["hit"] == b["hit"]:
                agree += 1
            if a["returned"] and b["returned"] and a["returned"][0] == b["returned"][0]:
                same_top1 += 1
        results[label] = {
            "agreement_hit": round(agree / n, 4),
            "same_top1": round(same_top1 / n, 4),
            "a_only": [a["id"] for a, b in zip(a_data["cases"], b_data["cases"]) if a["hit"] and not b["hit"]],
            "b_only": [a["id"] for a, b in zip(a_data["cases"], b_data["cases"]) if b["hit"] and not a["hit"]],
        }
    per_case = []
    for f32, f16, i8 in zip(fp32["cases"], fp16["cases"], int8["cases"], strict=True):
        per_case.append({
            "id": f32["id"],
            "fp32_hit": f32["hit"], "fp32_rank": f32["rank"],
            "fp16_hit": f16["hit"], "fp16_rank": f16["rank"],
            "int8_hit": i8["hit"], "int8_rank": i8["rank"],
        })
    results["per_case"] = per_case
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="ONNX FP32 vs FP16 vs INT8 retrieval eval (DirectML GPU)")
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()
    repo = Path(args.repo).resolve()

    print("=" * 60)
    print("  ONNX FP32 vs FP16 vs INT8 - CodeRankEmbed - DirectML GPU")
    print("=" * 60)
    print(f"  Repo:    {repo}")
    print(f"  Queries: {len(QUERIES)} (all soft NL, hard-phrased)")
    print(f"  Top-k:   {args.top_k}")
    print(f"  Batch:   {args.batch_size}")
    print()

    # --- Locate models ---
    model_dir = Path(os.environ.get("TEMP", "C:/Windows/Temp")) / "fastembed_cache" / \
        "models--jamie8johnson--CodeRankEmbed-onnx"
    if not model_dir.is_dir():
        model_dir = Path.home() / "AppData" / "Local" / "Temp" / "fastembed_cache" / \
            "models--jamie8johnson--CodeRankEmbed-onnx"

    snap = None
    for s in (model_dir / "snapshots").iterdir():
        if s.is_dir() and (s / "onnx" / "model.onnx").is_file():
            snap = s
            break
    if snap is None:
        print("ERROR: CodeRankEmbed model not found. Run `scubiee setup` first.")
        return 1

    fp32_path = snap / "onnx" / "model.onnx"
    fp16_path = snap / "onnx" / "model_fp16.onnx"
    int8_path = snap / "onnx" / "model_int8.onnx"
    # Prefer untouched FP32 backup if a prior swap left model.onnx as another precision.
    fp32_backup = snap / "onnx" / "model_original_fp32.onnx"
    if fp32_backup.is_file() and fp32_backup.stat().st_size >= fp32_path.stat().st_size:
        fp32_path = fp32_backup

    for label, p in [("FP32", fp32_path), ("FP16", fp16_path), ("INT8", int8_path)]:
        if not p.is_file():
            print(f"ERROR: {label} model not found at {p}")
            return 1
        print(f"  {label}: {p.name} ({p.stat().st_size / 1e6:.1f} MB)")

    # --- Collect corpus ---
    print(f"\n[corpus] Chunking full repo...", flush=True)
    t0 = time.perf_counter()
    chunks = collect_chunks(repo)
    print(f"[corpus] {len(chunks)} chunks in {time.perf_counter() - t0:.1f}s")

    chunk_texts = [c["text"] for c in chunks]
    chunk_files = [c["file"] for c in chunks]

    # --- Eval each variant on GPU ---
    variants = {"fp32": fp32_path, "fp16": fp16_path, "int8": int8_path}
    eval_results: dict = {}

    # Stop CE holders so ORT can open model files; swaps are isolated anyway.
    _stop_ce_holders()
    time.sleep(1)

    work_root = Path(os.environ.get("TEMP", "C:/Windows/Temp")) / "onnx_fp_eval_workspace"
    if work_root.exists():
        shutil.rmtree(work_root, ignore_errors=True)
    work_root.mkdir(parents=True, exist_ok=True)

    for label, model_path in variants.items():
        print(f"\n{'-' * 55}")
        print(f"  [{label.upper()}] Preparing isolated workspace -> {model_path.name}...", flush=True)

        variant_dir = _prepare_variant_workspace(snap, model_path, work_root / label)

        print(f"  [{label.upper()}] Loading on DirectML GPU via FastEmbed...", flush=True)
        embedder = OnnxEmbedder(variant_dir)

        print(f"  [{label.upper()}] Embedding {len(chunk_texts)} chunks (batch={args.batch_size})...", flush=True)
        t0 = time.perf_counter()
        chunk_vecs = embedder.embed(chunk_texts, batch_size=args.batch_size)
        embed_s = time.perf_counter() - t0
        tps = len(chunk_texts) / embed_s

        print(f"  [{label.upper()}] Done in {embed_s:.1f}s ({tps:.0f} chunks/s)")
        print(f"  [{label.upper()}] Running 50-query retrieval eval...", flush=True)

        result = run_eval(embedder, chunk_vecs, chunk_files, top_k=args.top_k)
        result["embed_time_s"] = round(embed_s, 1)
        result["chunks_per_sec"] = round(tps, 1)
        eval_results[label] = result

        print(f"  [{label.upper()}] hit@{args.top_k}={result[f'hit@{args.top_k}']:.0%}  "
              f"hit@5={result['hit@5']:.0%}  hit@1={result['hit@1']:.0%}  "
              f"MRR={result['mrr']:.4f}")
        # Drop session before next variant so ORT releases GPU memory.
        del embedder

    # Cleanup isolated workspaces (shared FastEmbed cache was never mutated).
    shutil.rmtree(work_root, ignore_errors=True)

    # --- Comparison ---
    print(f"\n{'=' * 55}")
    print("  RESULTS")
    print("=" * 55)

    comparison = compare_three(eval_results["fp32"], eval_results["fp16"], eval_results["int8"])

    print(f"\n  {'Metric':<16} {'FP32':>8} {'FP16':>8} {'INT8':>8}")
    print(f"  {'-' * 44}")
    for metric in ["hit@1", "hit@5", f"hit@{args.top_k}", "mrr"]:
        vals = [f"{eval_results[v].get(metric, 0):.4f}" for v in ["fp32", "fp16", "int8"]]
        print(f"  {metric:<16} {vals[0]:>8} {vals[1]:>8} {vals[2]:>8}")

    print(f"\n  {'Metric':<16} {'FP32':>8} {'FP16':>8} {'INT8':>8}")
    print(f"  {'-' * 44}")
    print(f"  {'embed (s)':<16} {eval_results['fp32']['embed_time_s']:>7.1f}s {eval_results['fp16']['embed_time_s']:>7.1f}s {eval_results['int8']['embed_time_s']:>7.1f}s")
    print(f"  {'chunks/sec':<16} {eval_results['fp32']['chunks_per_sec']:>8.0f} {eval_results['fp16']['chunks_per_sec']:>8.0f} {eval_results['int8']['chunks_per_sec']:>8.0f}")
    print(f"  {'model MB':<16} {fp32_path.stat().st_size/1e6:>7.1f}  {fp16_path.stat().st_size/1e6:>7.1f}  {int8_path.stat().st_size/1e6:>7.1f}")

    print(f"\n  {'Pair':<20} {'Agreement':>10} {'Same Top-1':>11}")
    print(f"  {'-' * 44}")
    for pair_label in ["fp32_vs_fp16", "fp32_vs_int8", "fp16_vs_int8"]:
        c = comparison[pair_label]
        print(f"  {pair_label:<20} {c['agreement_hit']:>9.0%} {c['same_top1']:>10.0%}")

    for pair_label in ["fp32_vs_fp16", "fp32_vs_int8"]:
        c = comparison[pair_label]
        if c["a_only"]:
            print(f"\n  Regressions ({pair_label}): {c['a_only']}")
        if c["b_only"]:
            print(f"  Improvements ({pair_label}): {c['b_only']}")

    # --- Save ---
    report = {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "repo": str(repo),
        "queries": len(QUERIES),
        "chunks": len(chunks),
        "top_k": args.top_k,
        "batch_size": args.batch_size,
        "gpu": "DirectML",
        "sizes_mb": {k: round(v.stat().st_size / 1e6, 1) for k, v in variants.items()},
        "results": {k: {key: val for key, val in v.items() if key != "cases"} for k, v in eval_results.items()},
        "comparison": comparison,
        "eval_results": eval_results,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\n  [done] Report: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
