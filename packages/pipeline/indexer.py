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
from pipeline.merkle import SyncDiff, diff_hashes, file_sha256
from pipeline.paths import collect_index_paths, collect_index_relpaths, fast_roots_from_env
from pipeline.preflight import CapabilityError, require_capabilities
from pipeline.store import ChunkRecord, PipelineStore
from pipeline.vectordb import VectorDatabase


def _schema_version() -> int:
    """Current index schema version — stamped into meta.json on every index."""
    from pipeline.migrate import SCHEMA_VERSION

    return SCHEMA_VERSION


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


from pipeline.incremental import IndexConfirmRequired  # re-export for CLI/tests


def _collect_paths(
    root: Path,
    *,
    fast: bool = False,
    fast_roots: list[str] | None = None,
) -> list[Path]:
    return collect_index_paths(root, fast=fast, fast_roots=fast_roots)


def _index_file_hashes(
    root: Path,
    *,
    fast: bool = False,
    fast_roots: list[str] | None = None,
) -> dict[str, str]:
    """Hash only paths that graphify/index will actually touch (not testdata/vendor)."""
    return {
        p.relative_to(root).as_posix(): file_sha256(p)
        for p in _collect_paths(root, fast=fast, fast_roots=fast_roots)
    }


def _emit_progress(progress, phase: str, frac: float) -> None:
    if progress is None:
        return
    setter = getattr(progress, "set", None)
    if callable(setter):
        setter(int(max(0.0, min(1.0, float(frac))) * 100), phase)
        return
    if callable(progress):
        progress(phase, frac)


def count_indexable_files(
    root: Path,
    *,
    fast: bool = False,
    fast_roots: list[str] | None = None,
) -> int:
    """Cheap preflight count for confirm gates (before graphify/embed)."""
    root = root.resolve()
    return len(collect_index_relpaths(root, fast=fast, fast_roots=fast_roots))


def index_repo(
    root: Path,
    *,
    force: bool = False,
    confirm: bool = False,
    bits: int = 8,
    embed_model: str | None = None,
    base_dir: Path | None = None,
    vdb: VectorDatabase | None = None,
    fast: bool = False,
    fast_roots: list[str] | None = None,
    progress=None,
    compress_mode: str | None = None,
    compress_max_chars: int = 512,
    quiesce: bool = True,
    staging_collection: str | None = None,
) -> IndexStats:
    root = root.resolve()
    from pipeline.incremental import preflight_index_scope

    preflight_index_scope(
        root,
        fast=fast,
        fast_roots=fast_roots,
        confirm=confirm,
        force=force,
    )
    try:
        from pipeline.resources import get_resource_manager

        rm = get_resource_manager()
        rm.refresh_base_from_accel()
        waited = {"n": 0}
        _quiet_rm = hasattr(progress, "set") or os.environ.get("CTX_QUIET") == "1"

        def _on_wait(budget) -> None:
            if waited["n"] == 0 and not _quiet_rm:
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
        if not _quiet_rm:
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
        if not (hasattr(progress, "set") or os.environ.get("CTX_QUIET") == "1"):
            print(f"[resources] index gate skipped: {exc}", file=sys.stderr, flush=True)

    require_capabilities(require_semantic=True)
    store = PipelineStore(root, base_dir=base_dir, vdb=vdb)
    if staging_collection:
        # Blue/green staged build (B3): embed into a temp collection so the live
        # one keeps serving until promote. The caller swaps it onto the live name.
        store.collection_name = staging_collection
    if quiesce:
        try:
            from pipeline.store_lock import quiesce_background_indexing

            quiesce_background_indexing(store_dir=store.base)
        except Exception:  # noqa: BLE001
            pass
    from pipeline.memory_budget import (
        apply_index_memory_budget,
        is_bootstrap_index,
        mlx_compute_summary,
        process_rss_peak_mb,
        resolve_index_memory_budget,
    )

    mem_budget = resolve_index_memory_budget(background=False, store=store)
    apply_index_memory_budget(mem_budget)
    wall_start = time.perf_counter()
    quiet = hasattr(progress, "set") or os.environ.get("CTX_QUIET") == "1"
    if not quiet:
        print(
            f"[index] memory mode={mem_budget.mode} rss_cap={mem_budget.rss_cap_mb}MB "
            f"bootstrap={is_bootstrap_index(store)} "
            f"mlx_batch={mem_budget.mlx_batch} cache={mem_budget.mlx_cache_mb}MB",
            file=sys.stderr,
            flush=True,
        )
    old = store.load_merkle()
    roots = list(fast_roots_from_env(fast_roots))
    # Default: mix (card labels + importance body). CTX_COMPRESS=off disables.
    # Also: skeleton|card|importance|budget_a|budget_b|budget_c
    from pipeline.chunk_compress import resolve_compress_mode

    cmode = resolve_compress_mode(compress_mode)
    cmax = int(os.environ.get("CTX_COMPRESS_MAX_CHARS", str(compress_max_chars)))

    new_hashes = _index_file_hashes(root, fast=fast, fast_roots=roots)
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

    from pipeline.incremental import require_index_confirm

    require_index_confirm(len(new_hashes), confirm=confirm, force=force)

    paths = _collect_paths(root, fast=fast, fast_roots=roots)
    if progress:
        _emit_progress(progress, "Scanning files", 0.05)
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
        # Keep GRAPHIFY_QUIET=1 for the rest of the index run (build_and_save_graph
        # also emits "[graphify] Deduplicated" messages). Restore only at the end.
    elapsed_ms = (time.perf_counter() - t0) * 1000
    parse_s = elapsed_ms / 1000.0
    if not quiet:
        print(
            f"[index] parse+ir {parse_s:.1f}s for {len(paths)} files",
            file=sys.stderr,
            flush=True,
        )
    ir = graphify_to_repo_ir(
        raw, root=root, elapsed_ms=elapsed_ms, file_count=len(paths)
    )
    store.graph_path.write_text(ir.canonical_json(), encoding="utf-8")
    build_and_save_graph(raw, root, store.base / "graph.json")

    if progress:
        _emit_progress(progress, "Building chunks", 0.42)

    t_chunk = time.perf_counter()
    code_chunks = chunk_repo_from_ir(ir, root)
    from pipeline.incremental import require_chunk_force

    require_chunk_force(len(code_chunks), force=force)
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
                text=(ch.content or "").lstrip("\ufeff")[: min(len(ch.content), cmax if cmode else max_chars)],
                enriched=body.lstrip("\ufeff") if isinstance(body, str) else body,
            )
        )
    store.save_chunks(records)
    chunk_s = time.perf_counter() - t_chunk
    if not quiet:
        print(
            f"[index] chunk {chunk_s:.1f}s -> {len(records)} chunks",
            file=sys.stderr,
            flush=True,
        )

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
            mlx_env = os.environ.get("CTX_EMBED_BACKEND", "").strip().lower() == "mlx"
            mlx_prof = bool(prof and (prof.profile == "mlx" or getattr(prof, "backend", "") == "mlx"))
            if mlx_env or mlx_prof:
                batch = int(os.environ.get("CTX_EMBED_BATCH", str(mem_budget.mlx_batch)))
            elif prof and prof.profile == "dml":
                batch = int(prof.batch_size or 16)
            elif prof and prof.profile == "cuda":
                batch = 64 if fast else 32
            else:
                batch = 32 if fast else 16
        except Exception:
            batch = 16 if fast else 32
    batch = min(batch, mem_budget.embed_batch_ceiling)
    # Index-build embedder backend. The default is whatever Embedder resolves
    # normally — i.e. MLX on Apple Silicon (the chosen accelerator). We do NOT
    # silently swap to FastEmbed on Darwin: that split the embedder (FastEmbed
    # index vectors vs MLX query vectors) and reversed a deliberate architecture
    # choice. The MLX index-write crash (MLX's Metal allocator leaving the heap
    # dirty before the numpy-LAPACK / faiss write in turbo_quant) is addressed on
    # the MLX path itself via mlx_mac.quiesce_mlx() before store.upsert_vectors.
    #
    # CTX_INDEX_EMBED_BACKEND remains an explicit escape hatch (e.g. "fastembed"
    # or "cpu") for anyone who needs to force a non-MLX index build, but it is
    # OFF by default — MLX stays the index backend on Apple Silicon.
    index_backend: str | None = None
    _forced = (os.environ.get("CTX_INDEX_EMBED_BACKEND") or "").strip().lower()
    if _forced in {"mlx", "fastembed", "coderank", "cpu"}:
        index_backend = "fastembed" if _forced == "cpu" else _forced
    embedder = Embedder(
        model=model,
        cache_path=store.embed_cache,
        batch_size=batch,
        max_seq_length=seq,
        quiet=progress is not None,
        backend=index_backend,
    )
    texts = [r.enriched for r in records]

    # --- Checkpoint-based resume: if a prior index was interrupted, the embed
    # cache (jsonl/npz) already holds partial results. We write a checkpoint
    # file so that on restart we can report progress and confirm resume is
    # working. The Embedder's cache lookup in embed_many automatically skips
    # already-embedded chunks, so no explicit slice logic is needed here.
    checkpoint_path = store.base / "embed_checkpoint.json"
    _checkpoint_interval = 500  # flush checkpoint every N chunks

    # If checkpoint exists from a prior interrupted run, log the resume.
    if checkpoint_path.is_file():
        try:
            _ckpt = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            _ckpt_done = _ckpt.get("chunks_done", 0)
            if not quiet:
                print(
                    f"[index] resuming embed from checkpoint: {_ckpt_done}/{_ckpt.get('total', '?')} "
                    f"chunks previously cached",
                    file=sys.stderr,
                    flush=True,
                )
        except (json.JSONDecodeError, OSError):
            pass  # Corrupt checkpoint — proceed normally, cache handles dedup

    t_embed = time.perf_counter()
    try:
        _chunks_reported = {"n": 0}

        def emb_prog(done: int, total: int) -> None:
            if progress:
                _emit_progress(
                    progress,
                    f"Embedding {done}/{total}",
                    0.50 + 0.38 * done / max(total, 1),
                )
            # Write checkpoint every _checkpoint_interval chunks for resume
            if done - _chunks_reported["n"] >= _checkpoint_interval or done >= total:
                _chunks_reported["n"] = done
                try:
                    checkpoint_path.write_text(
                        json.dumps({
                            "chunks_done": done,
                            "total": total,
                            "timestamp": time.time(),
                        }) + "\n",
                        encoding="utf-8",
                    )
                    # Also flush the embedder's cache so entries are on disk
                    embedder.flush_cache()
                except OSError:
                    pass  # Non-fatal: checkpoint is best-effort

        matrix = embedder.embed_many(texts, progress=emb_prog)
        if progress:
            _emit_progress(progress, "Embedding", 0.88)
    except CapabilityError:
        raise
    except Exception as exc:  # noqa: BLE001
        if not quiet:
            print(
                f"[index] ERROR: embedding failed ({exc}); index aborted (no random-vector fallback).",
                file=sys.stderr,
                flush=True,
            )
        raise

    # Embed succeeded — remove checkpoint file (no longer needed for resume)
    try:
        checkpoint_path.unlink(missing_ok=True)
    except OSError:
        pass
    embed_s = time.perf_counter() - t_embed
    if not quiet:
        print(
            f"[index] embed phase {embed_s:.1f}s for {len(records)} chunks "
            f"({len(records)/max(embed_s,1e-6):.1f} chunk/s)",
            file=sys.stderr,
            flush=True,
        )
    stats = getattr(embedder, "_last_stats", None) or {}
    if not quiet:
        print(
            f"[index] embed stats backend={stats.get('backend')} device={stats.get('device')} "
            f"tokens={stats.get('tokens')} tok/s={stats.get('tok_per_s')} "
            f"chunk/s={stats.get('chunk_per_s')} timings={stats.get('timings_s')}",
            file=sys.stderr,
            flush=True,
        )

    dim = int(matrix.shape[1]) if matrix.size else (embedder.dim or 768)
    if progress:
        _emit_progress(progress, "Writing index", 0.92)

    # macOS/MLX: fully flush + idle the Metal GPU before the faiss/turbo_quant
    # vector write. upsert_vectors builds the quantizer rotation via numpy-LAPACK
    # (turbo_quant QR); running that while MLX still has Metal buffers/streams in
    # flight races the native allocators and intermittently SIGSEGVs init at the
    # "Writing index" step. Quiescing MLX here (under the embed lock) removes the
    # race. No-op off Apple Silicon / non-MLX backends.
    if sys.platform == "darwin" and getattr(embedder, "backend", "") == "mlx":
        try:
            from pipeline.mlx_mac import quiesce_mlx

            quiesce_mlx()
        except Exception:  # noqa: BLE001
            pass

    t_write = time.perf_counter()
    col = store.upsert_vectors(matrix, records, dim=dim, bits=bits)
    write_s = time.perf_counter() - t_write
    if not quiet:
        print(
            f"[index] vector write {write_s:.2f}s for {len(records)} chunks",
            file=sys.stderr,
            flush=True,
        )
    store.save_merkle(new_hashes)
    from pipeline.freshness import git_head as _git_head

    store.save_meta(
        {
            "root": str(root),
            "project_id": store.project_id,
            "schema_version": _schema_version(),
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
    from pipeline.artifact_guard import invalidate_manifest, publish_manifest

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
        # Fail closed for readers while we seal the new generation.
        try:
            invalidate_manifest(store.base)
        except Exception:  # noqa: BLE001
            pass
        publish_manifest(store.base, published)
        try:
            from pipeline.bm25_cache import invalidate_bm25_cache

            invalidate_bm25_cache(store.base)
        except Exception:  # noqa: BLE001
            pass

    wall_s = time.perf_counter() - wall_start
    compute = mlx_compute_summary(stats.get("timings_s"))
    rss_peak = process_rss_peak_mb()
    if not quiet:
        print(
            f"[index] summary wall={wall_s:.1f}s parse={parse_s:.1f}s chunk={chunk_s:.1f}s "
            f"embed={embed_s:.1f}s write={write_s:.2f}s "
            f"e2e={len(records)/max(wall_s,1e-6):.1f} chunk/s "
            f"rss_peak={rss_peak:.0f}MB mode={mem_budget.mode}",
            file=sys.stderr,
            flush=True,
        )
        print(
            f"[index] model compute inference={compute['model_inference_s']}s "
            f"tokens={stats.get('tokens')} tok/s={stats.get('tok_per_s')} "
            f"chunks={len(records)} chunk/s={stats.get('chunk_per_s')}",
            file=sys.stderr,
            flush=True,
        )

    # Restore GRAPHIFY_QUIET now that the entire index run is complete.
    if previous_quiet is None:
        os.environ.pop("GRAPHIFY_QUIET", None)
    else:
        os.environ["GRAPHIFY_QUIET"] = previous_quiet

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


def _pid_alive(pid: int) -> bool:
    """Cross-platform best-effort liveness check for a staging dir's owner pid."""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not h:
                return False
            exit_code = ctypes.c_ulong(0)
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(h)
            return exit_code.value == 259  # STILL_ACTIVE
        os.kill(pid, 0)
        return True
    except (OSError, Exception):  # noqa: BLE001
        return False


def _begin_build_record(
    project_id: str | None,
    *,
    kind: str,
    staging_base: Path,
    live_base: Path,
) -> str | None:
    """Write a durable 'index build in progress' record (spec C4). Best-effort.

    Returns the build_id (or None). Any failure is swallowed so the index path
    is unchanged — the record is a recovery aid, never a correctness dependency.
    """
    if not project_id:
        return None
    try:
        import time as _time
        import uuid as _uuid

        from pipeline.index_state import BuildRecord, load_index_state, transition

        # total_units: the existing live chunk count is a reasonable proxy for a
        # forced full reindex (exactness is not required — this drives resume /
        # pending signalling, not correctness).
        total = 0
        try:
            prev = load_index_state(project_id)
            total = int((prev.pending.total_units if prev.pending else 0) or 0)
        except Exception:  # noqa: BLE001
            total = 0
        build_id = _uuid.uuid4().hex[:12]
        transition(
            project_id,
            state="indexing",
            build=BuildRecord(
                build_id=build_id,
                pid=os.getpid(),
                kind=kind,  # type: ignore[arg-type]
                started_at=_time.time(),
                staging_dir=staging_base.name,
                total_units=total,
                done_units=0,
                phase="parse",
            ),
        )
        return build_id
    except Exception:  # noqa: BLE001
        return None


def _complete_build_record(project_id: str | None, *, chunks: int = 0) -> None:
    """Clear the build-intent record after a successful promote (spec C4).

    Marks FRESH, drops the build record, and bumps the durable generation
    counter. Best-effort; never raises into the index path.
    """
    if not project_id:
        return
    try:
        from pipeline.index_state import load_index_state, transition

        doc = load_index_state(project_id)
        transition(
            project_id,
            state="fresh",
            build=None,
            pending=None,
            generation_counter=int(doc.generation_counter) + 1,
        )
    except Exception:  # noqa: BLE001
        pass


def _sweep_stale_staging(live_base: Path, live_collection: str, vdb) -> None:
    """Remove `<base>.staging-<pid>/` dirs and `<collection>__staging_<pid>`
    collections whose owner pid is dead (orphaned by a killed index)."""
    import shutil as _shutil

    prefix = f"{live_base.name}.staging-"
    try:
        for d in live_base.parent.glob(f"{live_base.name}.staging-*"):
            if not d.is_dir():
                continue
            try:
                pid = int(d.name[len(prefix):])
            except ValueError:
                continue
            if pid == os.getpid() or _pid_alive(pid):
                continue  # ours or a live concurrent index — leave it
            _shutil.rmtree(d, ignore_errors=True)
            # drop the matching staged collection if it survived
            try:
                stale_col = f"{live_collection}__staging_{pid}"
                if vdb.has_collection(stale_col):
                    vdb.drop_collection(stale_col)
            except Exception:  # noqa: BLE001
                pass
    except OSError:
        pass


def index_repo_staged(
    root: Path,
    *,
    force: bool = True,
    confirm: bool = False,
    bits: int = 8,
    embed_model: str | None = None,
    fast: bool = False,
    fast_roots: list[str] | None = None,
    progress=None,
    compress_mode: str | None = None,
    compress_max_chars: int = 512,
) -> IndexStats:
    """Zero-downtime forced reindex (blue/green, B2+B3).

    Builds a complete new generation in a sibling staging dir with a temp FAISS
    collection — the live store and the serving engine are untouched for the
    whole build+embed phase — then promotes text artifacts + the collection
    atomically under one store lock + the manifest fence. If anything fails
    before promote, the live generation is left exactly as it was.

    The caller (cmd_index) still does the engine reload handoff after this
    returns so the binder picks up the promoted generation.
    """
    import shutil

    from pipeline.artifact_guard import promote_staged_store
    from pipeline.vectordb import VectorDatabase

    root = root.resolve()
    # Resolve the live store to learn where to promote to.
    live_store = PipelineStore(root)
    live_base = live_store.base
    live_collection = live_store.collection_name
    vdb = VectorDatabase()  # shared collection root

    # Sweep orphaned staging artifacts from prior runs that were KILLED mid-index
    # (a hard kill skips the finally-cleanup, leaving `<base>.staging-<pid>/` and
    # `<collection>__staging_<pid>` behind — a slow disk leak over repeated
    # interruptions). Any staging whose pid is no longer alive is garbage.
    _sweep_stale_staging(live_base, live_collection, vdb)

    staging_base = live_base.parent / f"{live_base.name}.staging-{os.getpid()}"
    staging_collection = f"{live_collection}__staging_{os.getpid()}"
    if staging_base.exists():
        shutil.rmtree(staging_base, ignore_errors=True)
    staging_base.mkdir(parents=True, exist_ok=True)

    # Durable build-intent record (spec C4, task 2.2): mark INDEXING before any
    # staging mutation so a crash mid-build is detectable on restart (the owner
    # pid will be dead → INTERRUPTED → sweep + resume). Cleared only after the
    # manifest publishes. Fully best-effort: never change index success/failure.
    _bi_project = getattr(live_store, "project_id", None)
    _bi_build_id = _begin_build_record(
        _bi_project, kind="full", staging_base=staging_base, live_base=live_base
    )

    try:
        stats = index_repo(
            root,
            force=force,
            confirm=confirm,
            bits=bits,
            embed_model=embed_model,
            base_dir=staging_base,
            vdb=vdb,
            fast=fast,
            fast_roots=fast_roots,
            progress=progress,
            compress_mode=compress_mode,
            compress_max_chars=compress_max_chars,
            quiesce=False,  # we are not writing the live store during the build
            staging_collection=staging_collection,
        )

        # The staged meta.json records the TEMP collection name; the live store
        # must serve under the original name after the swap. Rewrite it in the
        # staging dir before promote so the promoted meta is self-consistent.
        staged_meta_path = staging_base / "meta.json"
        if staged_meta_path.is_file():
            try:
                m = json.loads(staged_meta_path.read_text(encoding="utf-8"))
                if m.get("collection") == staging_collection:
                    m["collection"] = live_collection
                    staged_meta_path.write_text(
                        json.dumps(m, indent=2) + "\n", encoding="utf-8"
                    )
            except Exception:  # noqa: BLE001
                pass

        # Promote: swap the FAISS collection + replace text artifacts as one
        # fenced generation. The collection swap runs inside promote's lock via
        # the extra_swap callback so vectors and text land together.
        def _swap_collection() -> None:
            vdb.swap_collection(staging_collection, live_collection)

        result = promote_staged_store(
            staging_base, live_base, extra_swap=_swap_collection
        )
        if not result.get("ok"):
            # Promote failed — drop the staged collection so it does not linger.
            try:
                vdb.drop_collection(staging_collection)
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(f"staged promote failed: {result}")

        # Manifest published → clear the build-intent record and mark FRESH
        # (spec C4). Done only AFTER promote so an interruption before this
        # point stays detectable. Best-effort.
        _complete_build_record(_bi_project, chunks=int(getattr(stats, "chunks", 0) or 0))

        # meta.json records the live collection name; after the swap the live
        # store serves the promoted collection under its original name.
        return IndexStats(
            root=stats.root,
            added=stats.added,
            modified=stats.modified,
            removed=stats.removed,
            chunks=stats.chunks,
            embedded=stats.embedded,
            unchanged=stats.unchanged,
            vector_stats=stats.vector_stats,
            store_dir=str(live_base),
        )
    finally:
        # Always clean the staging dir; the collection is either promoted
        # (renamed away) or dropped above. Retry a few times — graph build
        # scratch (graphify-out) can still hold a handle for a beat right after
        # promote, and ignore_errors=True would otherwise leave a stale temp dir.
        for _attempt in range(5):
            if not staging_base.exists():
                break
            shutil.rmtree(staging_base, ignore_errors=True)
            if staging_base.exists():
                time.sleep(0.3)
        if staging_base.exists():
            print(
                f"[index] note: staging dir not fully removed: {staging_base}",
                file=sys.stderr,
                flush=True,
            )
        # Belt-and-suspenders: if a staged collection survived a mid-promote
        # failure, drop it so it does not accumulate.
        try:
            if vdb.has_collection(staging_collection):
                vdb.drop_collection(staging_collection)
        except Exception:  # noqa: BLE001
            pass
