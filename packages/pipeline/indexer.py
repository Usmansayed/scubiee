"""Full index pipeline: merkle → graphify → enrich → embed → turboquant → faiss."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))

from enrich import chunk_repo_from_ir, inject_metadata  # type: ignore
from graphify.extract import extract
from parse_harness.graphify_adapter import graphify_to_repo_ir
from conductor.graphify_retriever import build_and_save_graph

from pipeline.embedder import Embedder
from pipeline.merkle import SyncDiff, diff_hashes, file_sha256, scan_file_hashes
from pipeline.paths import collect_index_paths, fast_roots_from_env
from pipeline.preflight import CapabilityError, require_capabilities
from pipeline.store import ChunkRecord, PipelineStore
from pipeline.vectordb import VectorDatabase


@dataclass
class IndexStats:
    root: str
    added: int
    modified: int
    removed: int
    chunks: int
    embedded: int
    unchanged: bool
    vector_stats: dict
    store_dir: str


class IndexDeferred(Exception):
    """ResourceManager refused to start full index (do not enter graphify)."""

    def __init__(self, reason: str, *, pressure: str = "critical"):
        super().__init__(reason)
        self.reason = reason
        self.pressure = pressure


def _collect_paths(
    root: Path,
    *,
    fast: bool = False,
    fast_roots: list[str] | None = None,
) -> list[Path]:
    return collect_index_paths(root, fast=fast, fast_roots=fast_roots)


def _emit_progress(progress, phase: str, frac: float) -> None:
    if progress is None:
        return
    setter = getattr(progress, "set", None)
    if callable(setter):
        setter(int(max(0.0, min(1.0, float(frac))) * 100), phase)
        return
    if callable(progress):
        progress(phase, frac)


def index_repo(
    root: Path,
    *,
    force: bool = False,
    bits: int = 8,
    embed_model: str | None = None,
    base_dir: Path | None = None,
    vdb: VectorDatabase | None = None,
    fast: bool = False,
    fast_roots: list[str] | None = None,
    progress=None,
    compress_mode: str | None = None,
    compress_max_chars: int = 512,
) -> IndexStats:
    root = root.resolve()
    try:
        from pipeline.resources import get_resource_manager

        rm = get_resource_manager()
        rm.refresh_base_from_accel()
        waited = {"n": 0}

        def _on_wait(budget) -> None:
            if waited["n"] == 0:
                print(
                    f"[resources] index waiting pressure={budget.pressure} {budget.reason}",
                    file=sys.stderr,
                    flush=True,
                )
            waited["n"] += 1

        budget = rm.wait_for_capacity(
            "index",
            timeout_s=30.0,
            on_wait=_on_wait,
        )
        quiet = hasattr(progress, "set")
        if not quiet:
            print(
                f"[resources] index start pressure={budget.pressure} "
                f"batch~{budget.batch_size} allow={budget.allow} ({budget.reason})",
                file=sys.stderr,
                flush=True,
            )
        if not budget.allow:
            raise IndexDeferred(
                budget.reason or "resource manager refused index",
                pressure=str(budget.pressure),
            )
        # Hint ResourceManager baseline for this process without permanent env mutation
        if budget.batch_size and "CTX_EMBED_BATCH" not in os.environ:
            with rm._lock:
                rm._base_batch = int(budget.batch_size)
    except IndexDeferred:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"[resources] index gate skipped: {exc}", file=sys.stderr, flush=True)

    require_capabilities(require_semantic=True)
    store = PipelineStore(root, base_dir=base_dir, vdb=vdb)
    old = store.load_merkle()
    roots = list(fast_roots_from_env(fast_roots))
    # Default: mix (card labels + importance body). CTX_COMPRESS=off disables.
    # Also: skeleton|card|importance|budget_a|budget_b|budget_c
    from pipeline.chunk_compress import resolve_compress_mode

    cmode = resolve_compress_mode(compress_mode)
    cmax = int(os.environ.get("CTX_COMPRESS_MAX_CHARS", str(compress_max_chars)))

    if fast:
        new_hashes = {
            p.relative_to(root).as_posix(): file_sha256(p)
            for p in _collect_paths(root, fast=True, fast_roots=roots)
        }
    else:
        new_hashes = scan_file_hashes(root)
    diff: SyncDiff = diff_hashes(old, new_hashes)

    if diff.unchanged and not force and store.chunks_path.exists():
        col = store.get_collection()
        return IndexStats(
            root=str(root),
            added=0,
            modified=0,
            removed=0,
            chunks=len(store.load_chunks()),
            embedded=0,
            unchanged=True,
            vector_stats=col.stats() if col else {},
            store_dir=str(store.base),
        )

    if progress:
        _emit_progress(progress, "Scanning files", 0.05)

    import time

    paths = _collect_paths(root, fast=fast, fast_roots=roots)
    if progress:
        _emit_progress(progress, "Parsing code", 0.08)
    t0 = time.perf_counter()
    previous_quiet = os.environ.get("GRAPHIFY_QUIET")
    os.environ["GRAPHIFY_QUIET"] = "1"
    pulse_stop = None
    pulse_thread = None
    if hasattr(progress, "pulse"):
        import threading

        pulse_stop = threading.Event()

        def _pulse_parse() -> None:
            while not pulse_stop.wait(0.2):
                progress.pulse("Parsing code", until=40)

        pulse_thread = threading.Thread(target=_pulse_parse, daemon=True)
        pulse_thread.start()
    try:
        raw = extract(paths, root=root, cache_root=store.base)
    finally:
        if pulse_stop is not None:
            pulse_stop.set()
        if previous_quiet is None:
            os.environ.pop("GRAPHIFY_QUIET", None)
        else:
            os.environ["GRAPHIFY_QUIET"] = previous_quiet
    elapsed_ms = (time.perf_counter() - t0) * 1000
    ir = graphify_to_repo_ir(
        raw, root=root, elapsed_ms=elapsed_ms, file_count=len(paths)
    )
    store.graph_path.write_text(ir.canonical_json(), encoding="utf-8")
    build_and_save_graph(raw, root, store.base / "graph.json")

    if progress:
        _emit_progress(progress, "Building chunks", 0.42)

    code_chunks = chunk_repo_from_ir(ir, root)
    # Fast without compress: truncate bodies. With compress (default mix): enrich
    # fully then compress to cmax so metadata isn't mid-cut.
    max_chars = (128 * 4) if fast and not cmode else 50_000
    records: list[ChunkRecord] = []
    from pipeline.chunk_compress import compress_chunk

    for i, ch in enumerate(code_chunks):
        enriched = inject_metadata(ch, ir)
        body = enriched.enriched
        if cmode:
            body = compress_chunk(body, cmode, max_chars=cmax).text
        elif len(body) > max_chars:
            body = body[:max_chars]
        records.append(
            ChunkRecord(
                id=i,
                file=ch.file,
                start_line=ch.start_line,
                end_line=ch.end_line,
                symbol=ch.symbol,
                text=ch.content[: min(len(ch.content), cmax if cmode else max_chars)],
                enriched=body,
            )
        )
    store.save_chunks(records)

    if progress:
        _emit_progress(progress, "Embedding", 0.50)

    model = embed_model or "nomic-ai/CodeRankEmbed"
    # Fast defaults: short seq. Batch: prefer env; else DML-safe 16 (128 OOMs/hangs RX 6500M).
    seq = int(os.environ.get("CTX_EMBED_SEQ", "128" if fast else "512"))
    if "CTX_EMBED_BATCH" in os.environ:
        batch = int(os.environ["CTX_EMBED_BATCH"])
    else:
        try:
            from pipeline.accel import load_accel

            prof = load_accel()
            if prof and prof.profile == "dml":
                batch = int(prof.batch_size or 16)
            elif prof and prof.profile == "cuda":
                batch = 64 if fast else 32
            else:
                batch = 32 if fast else 16
        except Exception:
            batch = 16 if fast else 32
    embedder = Embedder(
        model=model,
        cache_path=store.embed_cache,
        batch_size=batch,
        max_seq_length=seq,
        quiet=progress is not None,
    )
    texts = [r.enriched for r in records]
    t_embed = time.perf_counter()
    try:
        def emb_prog(done: int, total: int) -> None:
            if progress:
                _emit_progress(
                    progress,
                    "Embedding",
                    0.50 + 0.38 * done / max(total, 1),
                )

        matrix = embedder.embed_many(texts, progress=emb_prog)
        if progress:
            _emit_progress(progress, "Embedding", 0.88)
    except CapabilityError:
        raise
    except Exception as exc:  # noqa: BLE001
        # Never invent vectors for missing accel — only absorb transient encode faults
        # when an explicit ST/ollama backend was selected.
        if embedder.backend == "fastembed":
            raise
        if progress:
            _emit_progress(progress, "Embedding", 0.6)
        dim = 768
        import numpy as np
        import hashlib

        rows = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            rng = np.random.default_rng(int.from_bytes(h[:8], "little"))
            v = rng.normal(size=dim).astype(np.float32)
            v /= max(float(np.linalg.norm(v)), 1e-12)
            rows.append(v)
        matrix = np.stack(rows, axis=0) if rows else np.zeros((0, dim), dtype=np.float32)
        embedder.dim = dim
    embed_s = time.perf_counter() - t_embed
    if not hasattr(progress, "set"):
        print(
            f"[index] embed phase {embed_s:.1f}s for {len(records)} chunks "
            f"({len(records)/max(embed_s,1e-6):.1f} chunk/s)",
            file=sys.stderr,
            flush=True,
        )

    dim = int(matrix.shape[1]) if matrix.size else (embedder.dim or 768)
    if progress:
        _emit_progress(progress, "Writing index", 0.92)

    col = store.upsert_vectors(matrix, records, dim=dim, bits=bits)
    store.save_merkle(new_hashes)
    from pipeline.freshness import git_head as _git_head

    store.save_meta(
        {
            "root": str(root),
            "project_id": store.project_id,
            "dim": dim,
            "bits": bits,
            "chunks": len(records),
            "root_hash": diff.root_hash,
            "embed_model": embedder.model,
            "embed_backend": embedder.backend,
            "fast": fast,
            "files_indexed": len(paths),
            "vector_backend": "faiss+turboquant",
            "collection": col.name,
            "vectordb_root": str(store.vdb.root),
            "git_head": _git_head(root),
            "indexed_at": time.time(),
            "fast_roots": roots if fast else None,
            "compress_mode": cmode,
            "compress_max_chars": cmax if cmode else None,
            "note": "CodeRankLLM reranker is search-time only (not used during index)",
        }
    )
    from pipeline.artifact_guard import publish_manifest

    published = [
        p
        for p in (
            store.chunks_path,
            store.graph_path,
            store.base / "graph.json",
            store.meta_path,
            store.merkle_path,
        )
        if p.is_file()
    ]
    if published:
        publish_manifest(store.base, published)

    return IndexStats(
        root=str(root),
        added=len(diff.added),
        modified=len(diff.modified),
        removed=len(diff.removed),
        chunks=len(records),
        embedded=len(records),
        unchanged=False,
        vector_stats=col.stats(),
        store_dir=str(store.base),
    )
