"""Incremental re-index: only re-embed files that Merkle/git say changed."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))

from conductor.graphify_retriever import build_and_save_graph, patch_and_save_graph
from enrich import chunk_file_from_ir, inject_metadata
from graphify.extract import extract
from parse_harness.graphify_adapter import graphify_to_repo_ir

from pipeline.chunk_merkle import chunk_digest, chunk_key, diff_chunk_records
from pipeline.embedder import Embedder
from pipeline.freshness import check_freshness
from pipeline.merkle import file_sha256
from pipeline.paths import collect_index_paths, collect_index_relpaths
from pipeline.store import ChunkRecord, PipelineStore
from pipeline.vectordb import VectorDatabase


AUTO_FULL_INDEX_CHUNKS = int(os.environ.get("CTX_AUTO_FULL_INDEX_CHUNKS", "10000"))


@dataclass
class IncrementalResult:
    refreshed: bool
    files: list[str]
    chunks_upserted: int
    chunks_removed: int
    ms: float
    strategy: str
    error: str | None = None
    graph_error: str | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            "refreshed": self.refreshed,
            "files": self.files,
            "chunks_upserted": self.chunks_upserted,
            "chunks_removed": self.chunks_removed,
            "ms": round(self.ms, 1),
            "strategy": self.strategy,
            "error": self.error,
            "graph_error": self.graph_error,
            "warnings": self.warnings or [],
        }


def _paths_for_files(root: Path, rels: list[str]) -> list[Path]:
    out = []
    for r in rels:
        p = root / r
        if p.is_file():
            out.append(p)
    return out


def incremental_sync(
    root: Path,
    *,
    base_dir: Path | None = None,
    vdb: VectorDatabase | None = None,
    bits: int = 4,
    max_chars: int = 1200,
    force_files: list[str] | None = None,
    bulk: bool = False,
) -> IncrementalResult:
    """Re-parse + re-embed only changed/removed files; upsert into FAISS collection.

    When *bulk* is True the bootstrap memory budget (800 MB RSS, batch 48) is
    used instead of the conservative background budget, suitable for 501–10000
    chunk changes that should complete in minutes like an initial index.
    """
    t0 = time.perf_counter()
    root = root.resolve()
    try:
        from pipeline.resources import get_resource_manager

        rm = get_resource_manager()
        budget = rm.wait_for_capacity("sync", timeout_s=90.0)
        if not budget.allow:
            return IncrementalResult(
                refreshed=False,
                files=[],
                chunks_upserted=0,
                chunks_removed=0,
                ms=(time.perf_counter() - t0) * 1000,
                strategy="deferred",
                error=f"resource pressure — sync deferred ({budget.pressure}: {budget.reason})",
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[resources] sync gate skipped: {exc}", file=sys.stderr, flush=True)

    store = PipelineStore(root, base_dir=base_dir, vdb=vdb)
    from pipeline.memory_budget import apply_index_memory_budget, resolve_index_memory_budget

    mem_budget = resolve_index_memory_budget(background=not bulk, store=store)
    apply_index_memory_budget(mem_budget)
    print(
        f"[sync] memory mode={mem_budget.mode} rss_cap={mem_budget.rss_cap_mb}MB "
        f"mlx_batch={mem_budget.mlx_batch} cache={mem_budget.mlx_cache_mb}MB"
        f"{' [BULK]' if bulk else ''}",
        file=sys.stderr,
        flush=True,
    )
    meta = store.load_meta()
    old = store.load_merkle()
    report = check_freshness(
        root, old, indexed_head=meta.get("git_head"), file_mtimes=store.load_mtimes()
    )
    if force_files:
        from pipeline.merkle import SyncDiff, root_hash as _rh

        added, modified, removed_f = [], [], []
        for rel in {f.replace("\\", "/") for f in force_files}:
            p = root / rel
            if p.is_file():
                if rel not in old:
                    added.append(rel)
                else:
                    modified.append(rel)  # force re-embed even if hash matches
            elif rel in old:
                removed_f.append(rel)
        report.diff = SyncDiff(
            added=sorted(added),
            modified=sorted(modified),
            removed=sorted(removed_f),
            root_hash=_rh(old),
            unchanged=False,
        )
        report.clean = False
        report.strategy = "incremental"
        report.reason = "force_files"
        report.detection = "force"

    # Merkle is a closed snapshot of already-indexed files. Discover newcomers
    # with the same path filter as a full/fast index so untracked modules sync.
    if not force_files:
        from pipeline.merkle import SyncDiff, root_hash as _rh

        newcomers = sorted(
            collect_index_relpaths(
                root, fast=bool(meta.get("fast")), fast_roots=meta.get("fast_roots")
            )
            - set(old)
        )
        if newcomers:
            added = sorted(set(report.diff.added) | set(newcomers))
            report.diff = SyncDiff(
                added=added,
                modified=list(report.diff.modified),
                removed=list(report.diff.removed),
                root_hash=_rh(old),
                unchanged=False,
            )
            report.clean = False
            if report.strategy == "none":
                kind = "fast roots" if meta.get("fast") else "index paths"
                report.strategy = "incremental"
                report.reason = f"{len(newcomers)} new file(s) under {kind}"
                report.detection = "index_paths_new"

    if report.clean and not force_files:
        return IncrementalResult(
            refreshed=False,
            files=[],
            chunks_upserted=0,
            chunks_removed=0,
            ms=(time.perf_counter() - t0) * 1000,
            strategy="none",
        )

    if report.strategy == "full" and not force_files:
        return IncrementalResult(
            refreshed=False,
            files=[],
            chunks_upserted=0,
            chunks_removed=0,
            ms=(time.perf_counter() - t0) * 1000,
            strategy="full",
            error=(
                "large drift — refusing incremental extract; "
                "run `ctx index . --force --fast --roots packages`"
            ),
        )

    changed = sorted(set(report.diff.changed_files) | set(force_files or []))
    removed = list(report.diff.removed)
    # Hard cap — never extract thousands of accidental paths in one sync
    max_touch = int(os.environ.get("CTX_INCREMENTAL_MAX_TOUCH", "80"))
    if len(changed) + len(removed) > max_touch and not force_files:
        return IncrementalResult(
            refreshed=False,
            files=(changed + removed)[:50],
            chunks_upserted=0,
            chunks_removed=0,
            ms=(time.perf_counter() - t0) * 1000,
            strategy=report.strategy,
            error=f"refusing to touch {len(changed)+len(removed)} files (>{max_touch})",
        )
    touch = sorted(set(changed) | set(removed))

    try:
        # Re-extract graph for touched files + neighbors? Keep simple: re-extract touched only,
        # rebuild full graph from all currently indexed file set + new
        existing = store.load_chunks()
        keep = [c for c in existing if c.file.replace("\\", "/") not in set(touch)]
        removed_ids = [c.id for c in existing if c.file.replace("\\", "/") in set(touch)]

        paths = _paths_for_files(root, changed)
        new_records: list[ChunkRecord] = []
        next_id = (max((c.id for c in existing), default=-1) + 1) if existing else 0
        graph_error: str | None = None
        matrix = None
        embedder = None
        warnings: list[str] = []
        raw: dict = {"nodes": [], "edges": [], "hyperedges": []}

        if paths:
            raw = extract(paths, root=root, cache_root=store.base)
            ir = graphify_to_repo_ir(
                raw, root=root, elapsed_ms=0.0, file_count=len(paths)
            )
            for file_path in sorted({p.relative_to(root).as_posix() for p in paths}):
                for ch in chunk_file_from_ir(ir, root, file_path):
                    enriched = inject_metadata(ch, ir)
                    body = enriched.enriched
                    from pipeline.chunk_compress import compress_chunk, resolve_compress_mode

                    # meta.compress_mode if set; else default mix (CTX_COMPRESS=off disables)
                    cmode = resolve_compress_mode(meta.get("compress_mode"))
                    cmax = int(
                        meta.get("compress_max_chars")
                        or os.environ.get("CTX_COMPRESS_MAX_CHARS", "512")
                    )
                    if cmode:
                        body = compress_chunk(body, cmode, max_chars=cmax).text
                        text_cap = cmax
                    else:
                        if len(body) > max_chars:
                            body = body[:max_chars]
                        text_cap = max_chars
                    new_records.append(
                        ChunkRecord(
                            id=next_id,
                            file=ch.file,
                            start_line=ch.start_line,
                            end_line=ch.end_line,
                            symbol=ch.symbol,
                            text=ch.content[:text_cap],
                            enriched=body,
                        )
                    )
                    next_id += 1

        changed_chunk_count = len(removed_ids) + len(new_records)
        if changed_chunk_count > AUTO_FULL_INDEX_CHUNKS:
            limit = AUTO_FULL_INDEX_CHUNKS
            return IncrementalResult(
                refreshed=False,
                files=touch,
                chunks_upserted=0,
                chunks_removed=0,
                ms=(time.perf_counter() - t0) * 1000,
                strategy="explicit_full_index_required",
                error=(
                    f"{changed_chunk_count} chunks changed, exceeding the automatic "
                    f"limit of {limit}; run `ctx index {root} --force` explicitly"
                ),
                warnings=[
                    "No graph or vector artifacts were published for this oversized change."
                ],
            )

        # Patch graph from changed-file extract only (same AST pass as chunks).
        # Fallback: full extract if graph.json missing.
        try:
            graph_json = store.base / "graph.json"
            if graph_json.is_file():
                patch_and_save_graph(
                    raw,
                    root,
                    graph_json,
                    prune_sources=list(removed) if removed else None,
                )
            else:
                roots = meta.get("fast_roots")
                all_paths = collect_index_paths(
                    root, fast=bool(meta.get("fast")), fast_roots=roots
                )
                full_raw = extract(all_paths, root=root, cache_root=store.base)
                build_and_save_graph(full_raw, root, graph_json)
            if not graph_json.exists():
                graph_error = "graph.json missing after rebuild"
                warnings.append(graph_error)
        except Exception as gexc:  # noqa: BLE001
            graph_error = str(gexc)
            warnings.append(f"graph rebuild failed: {gexc}")
            print(f"[incremental] WARNING: graph rebuild failed: {gexc}", file=sys.stderr, flush=True)

        # A file Merkle diff decides what to parse. A chunk Merkle diff decides
        # what to embed. We still rebuild every dirty file's AST/graph patch,
        # but reuse vectors for chunks whose stable key and embedding input are
        # identical to the prior indexed generation.
        old_by_file: dict[str, list[ChunkRecord]] = {}
        for record in existing:
            old_by_file.setdefault(record.file.replace("\\", "/"), []).append(record)
        new_by_file: dict[str, list[ChunkRecord]] = {}
        for record in new_records:
            new_by_file.setdefault(record.file.replace("\\", "/"), []).append(record)
        embed_records: list[ChunkRecord] = []
        for file, records in new_by_file.items():
            diff = diff_chunk_records(old_by_file.get(file, []), records)
            embed_records.extend(
                record for record in records if chunk_key(record) in diff.changed
            )

        if embed_records:
            model = str(meta.get("embed_model") or "nomic-ai/CodeRankEmbed")
            try:
                from pipeline.engine import get_embedder

                embedder = get_embedder(
                    model, dim=meta.get("dim"), cache_path=store.embed_cache
                )
            except Exception:
                embedder = Embedder(
                    model=model,
                    cache_path=store.embed_cache,
                    batch_size=64,
                    max_seq_length=256 if meta.get("fast") else 512,
                    dim=meta.get("dim"),
                )
            matrix = embedder.embed_many([r.enriched for r in embed_records])

        # Merge chunk list
        merged = keep + new_records
        # IDs are durable payload identities. Gaps after deletion are expected;
        # compaction rebuilds storage without renumbering surviving chunks.
        store.save_chunks(merged)

        col = store.get_collection()
        dim = int(meta.get("dim") or (matrix.shape[1] if matrix is not None and matrix.size else 768))
        bits_i = int(meta.get("bits") or bits)
        if col is None:
            # create empty then replace
            store.upsert_vectors(
                matrix if matrix is not None else __import__("numpy").zeros((0, dim), dtype="float32"),
                merged,
                dim=dim,
                bits=bits_i,
            )
        else:
            # Full replace of collection vectors from all merged texts (correct, simpler than delete-by-file)
            # For true scale later: delete ids + add. For ≤ few k chunks, replace_all of changed subset
            # is wrong without all vectors — so re-embed ONLY new and keep old vectors for keep ids.
            import numpy as np

            if keep and col.ntotal:
                # rebuild matrix: old vectors for kept ids in old order mapping
                old_by_file_chunk = {
                    (c.file.replace("\\", "/"), chunk_key(c), chunk_digest(c)): c.id
                    for c in existing
                }
                old_mat = col.compressed.to_float32()
                id_to_row = {int(vid): i for i, vid in enumerate(col.ids)}
                rows = []
                payloads = []
                for c in merged:
                    key = (c.file.replace("\\", "/"), chunk_key(c), chunk_digest(c))
                    old_id = old_by_file_chunk.get(key)
                    if old_id is not None and int(old_id) in id_to_row:
                        rows.append(old_mat[id_to_row[int(old_id)]])
                    else:
                        rows.append(None)  # type: ignore
                    payloads.append(
                        {
                            "file": c.file,
                            "start_line": c.start_line,
                            "end_line": c.end_line,
                            "symbol": c.symbol,
                            "chunk_id": c.id,
                        }
                    )
                # Fill changed/new chunks from the smaller embedding batch.
                new_map = {
                    (r.file.replace("\\", "/"), chunk_key(r), chunk_digest(r)): j
                    for j, r in enumerate(embed_records)
                }
                for i, c in enumerate(merged):
                    if rows[i] is None and matrix is not None:
                        j = new_map.get(
                            (c.file.replace("\\", "/"), chunk_key(c), chunk_digest(c))
                        )
                        if j is not None:
                            rows[i] = matrix[j]
                missing_idx = [i for i, row in enumerate(rows) if row is None]
                if missing_idx:
                    if embedder is None:
                        model = str(meta.get("embed_model") or "nomic-ai/CodeRankEmbed")
                        try:
                            from pipeline.engine import get_embedder

                            embedder = get_embedder(
                                model, dim=meta.get("dim"), cache_path=store.embed_cache
                            )
                        except Exception:
                            embedder = Embedder(
                                model=model,
                                cache_path=store.embed_cache,
                                batch_size=64,
                                max_seq_length=256 if meta.get("fast") else 512,
                                dim=meta.get("dim"),
                            )
                    extra = embedder.embed_many(
                        [merged[i].enriched for i in missing_idx]
                    )
                    for j, i in enumerate(missing_idx):
                        rows[i] = extra[j]
                full = np.stack(rows, axis=0).astype(np.float32)
                col.replace_all(full, [c.id for c in merged], payloads)
                store.vdb.save_collection(col.name)
            else:
                store.upsert_vectors(
                    matrix if matrix is not None else np.zeros((0, dim), dtype=np.float32),
                    merged,
                    dim=dim,
                    bits=bits_i,
                )

        # Update merkle for whole tree scan of current indexed set
        if meta.get("fast"):
            new_hashes = {
                p.relative_to(root).as_posix(): file_sha256(p)
                for p in collect_index_paths(
                    root, fast=True, fast_roots=meta.get("fast_roots")
                )
            }
        else:
            from pipeline.merkle import scan_file_hashes

            new_hashes = scan_file_hashes(root)
        store.save_merkle(new_hashes)
        store.save_chunk_merkle(
            {
                file: {chunk_key(chunk): chunk_digest(chunk) for chunk in records}
                for file, records in {
                    **{
                        file: [
                            chunk for chunk in existing
                            if chunk.file.replace("\\", "/") == file
                        ]
                        for file in new_hashes
                        if file not in new_by_file
                    },
                    **new_by_file,
                }.items()
            }
        )
        meta["git_head"] = report.git_head
        meta["chunks"] = len(merged)
        meta["last_incremental_at"] = time.time()
        if graph_error:
            meta["last_graph_error"] = graph_error
        else:
            meta.pop("last_graph_error", None)
        store.save_meta(meta)
        # Incremental sync mutates the same published artifacts as a full
        # index. Refresh the manifest only after all of those writes complete,
        # otherwise readiness will reject every live update as corruption.
        from pipeline.artifact_guard import publish_manifest

        published = [
            path
            for path in (
                store.chunks_path,
                store.graph_path,
                store.base / "graph.json",
                store.meta_path,
                store.merkle_path,
            )
            if path.is_file()
        ]
        if published:
            publish_manifest(store.base, published)
        try:
            from pipeline.capability import ensure_cards

            ensure_cards(
                root,
                store.base,
                indexed_files=[c.file for c in merged],
                force=True,
            )
        except Exception as cap_exc:  # noqa: BLE001
            warnings = list(warnings or [])
            warnings.append(f"capability_cards: {cap_exc}")
        from pipeline.engine import clear_engines

        clear_engines()

        return IncrementalResult(
            refreshed=True,
            files=touch,
            chunks_upserted=len(embed_records),
            chunks_removed=len(removed_ids),
            ms=(time.perf_counter() - t0) * 1000,
            strategy=report.strategy,
            graph_error=graph_error,
            warnings=warnings or None,
        )
    except Exception as exc:  # noqa: BLE001
        return IncrementalResult(
            refreshed=False,
            files=touch,
            chunks_upserted=0,
            chunks_removed=0,
            ms=(time.perf_counter() - t0) * 1000,
            strategy=report.strategy,
            error=str(exc),
        )


def ensure_fresh_for_search(
    root: Path,
    *,
    base_dir: Path | None = None,
    vdb: VectorDatabase | None = None,
) -> dict:
    """Low-friction gate before search.

    incremental → sync now (block)
    background → kick thread, return dirty file boost set
    full → background force reindex (Zoekt-style rebuild after large delta)
    none → clean
    """
    import threading

    root = root.resolve()
    store = PipelineStore(root, base_dir=base_dir, vdb=vdb)
    meta = store.load_meta()
    report = check_freshness(
        root,
        store.load_merkle(),
        indexed_head=meta.get("git_head"),
        file_mtimes=store.load_mtimes(),
    )
    out = {"freshness": report.to_dict(), "sync": None}

    if report.strategy == "none":
        return out

    if report.strategy == "incremental":
        result = incremental_sync(root, base_dir=base_dir, vdb=vdb)
        out["sync"] = result.to_dict()
        if not result.refreshed:
            out["dirty_boost_files"] = report.diff.changed_files
        return out

    if report.strategy == "full":
        # Default OFF — auto full reindex previously walked .venv-proof / site-packages
        # and thrashing RAM/GPU froze the host. Opt in with CTX_ALLOW_BG_FULL=1.
        allow_bg = os.environ.get("CTX_ALLOW_BG_FULL", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if allow_bg:

            def _full():
                from pipeline.indexer import index_repo

                print(
                    f"[freshness] WARNING: full reindex starting for {root}",
                    file=sys.stderr,
                    flush=True,
                )
                try:
                    index_repo(
                        root,
                        force=True,
                        fast=bool(meta.get("fast")),
                        fast_roots=meta.get("fast_roots"),
                        embed_model=meta.get("embed_model"),
                        base_dir=base_dir,
                        vdb=vdb,
                        bits=int(meta.get("bits") or 4),
                    )
                    from pipeline.engine import clear_engines

                    clear_engines()
                    print("[freshness] WARNING: full reindex complete", file=sys.stderr, flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[freshness] WARNING: full reindex failed: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )

            threading.Thread(target=_full, name="ctx-full-reindex", daemon=True).start()
            note = "background force reindex started; BM25 hot-patch + dirty boost until done"
        else:
            print(
                "[freshness] WARNING: large drift detected — NOT auto-reindexing "
                "(set CTX_ALLOW_BG_FULL=1 or run: ctx index . --force --fast --roots packages)",
                file=sys.stderr,
                flush=True,
            )
            note = (
                "full reindex skipped (CTX_ALLOW_BG_FULL=0); "
                "run `ctx index . --force` manually if needed"
            )
        out["sync"] = {
            "refreshed": False,
            "strategy": "full",
            "files": (report.diff.changed_files + report.diff.removed)[:50],
            "note": note,
        }
        out["dirty_boost_files"] = report.diff.changed_files[:50]
        return out

    # background: incremental in daemon
    def _bg():
        incremental_sync(root, base_dir=base_dir, vdb=vdb)

    threading.Thread(target=_bg, name="ctx-incremental", daemon=True).start()
    out["sync"] = {
        "refreshed": False,
        "strategy": "background",
        "files": report.diff.changed_files + report.diff.removed,
        "note": "search continues; BM25 hot-patched from disk; dense may lag",
    }
    out["dirty_boost_files"] = report.diff.changed_files
    return out
