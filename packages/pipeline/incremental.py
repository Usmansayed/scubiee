"""Incremental re-index: only re-embed files that Merkle/git say changed."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))

from conductor.graphify_retriever import build_and_save_graph, patch_and_save_graph
from enrich import chunk_file_from_ir, inject_metadata
from graphify.extract import extract
from parse_harness.graphify_adapter import graphify_to_repo_ir

from pipeline.artifact_guard import atomic_write_text
from pipeline.chunk_merkle import chunk_digest, chunk_key, diff_chunk_records
from pipeline.embedder import Embedder
from pipeline.freshness import check_freshness
from pipeline.merkle import canonical_relpath, file_sha256
from pipeline.paths import collect_index_paths, collect_index_relpaths
from pipeline.store import ChunkRecord, PipelineStore
from pipeline.store_lock import store_write_lock
from pipeline.vectordb import VectorDatabase

# Auto-touch without asking. Normal repos are 500–thousands of files; this
# cap is only for "that looks like a mistake" (home/drive is a separate gate).
DEFAULT_MAX_TOUCH = 25_000
DEFAULT_MAX_CHUNKS = 20_000

_BG_SYNC_LOCK = threading.Lock()
_BG_SYNC_RUNNING = False


def _trust_id_file_env() -> bool:
    return os.environ.get("CTX_TRUST_ID_FILE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _run_single_flight(name: str, fn) -> bool:
    """Run *fn* at most once globally; return False if already running."""
    global _BG_SYNC_RUNNING
    with _BG_SYNC_LOCK:
        if _BG_SYNC_RUNNING:
            return False
        _BG_SYNC_RUNNING = True

    def _wrapper() -> None:
        global _BG_SYNC_RUNNING
        try:
            fn()
        finally:
            with _BG_SYNC_LOCK:
                _BG_SYNC_RUNNING = False

    threading.Thread(target=_wrapper, name=name, daemon=True).start()
    return True


class IndexConfirmRequired(Exception):
    """Full index or sync would touch more files than the auto cap."""

    def __init__(
        self,
        n_files: int,
        *,
        max_touch: int = DEFAULT_MAX_TOUCH,
        message: str | None = None,
        kind: str = "large_scope",
    ):
        self.n_files = n_files
        self.max_touch = max_touch
        self.kind = kind
        super().__init__(message or _confirm_hint(n_files, max_touch=max_touch))

    def to_payload(self, root: Path) -> dict:
        broad = is_broad_index_root(root)
        if self.kind == "too_many_chunks":
            return {
                "ok": False,
                "status": "warning",
                "warning": "too_many_chunks",
                "needs_force": True,
                "needs_confirm": False,
                "root": str(root.resolve()),
                "n_chunks": self.n_files,
                "max_chunks": self.max_touch,
                "message": str(self),
                "action": (
                    "This codebase has too many tokens for a default index. "
                    "If you still want to index it, re-run with --force "
                    "(e.g. `scubiee init . --force` or `scubiee index . --force`), "
                    "or narrow scope with `--roots packages`."
                ),
                "hint": str(self),
            }
        if self.kind == "broad_root" or (self.n_files == 0 and broad):
            return {
                "ok": False,
                "status": "warning",
                "warning": "broad_index_scope",
                "needs_confirm": True,
                "root": str(root.resolve()),
                "n_files": self.n_files,
                "max_touch": self.max_touch,
                "message": str(self),
                "action": (
                    "Change into your project directory, or re-run with --confirm "
                    "if you intentionally want to index this broad path."
                ),
            }
        return {
            "ok": False,
            "status": "warning",
            "warning": "large_index_scope",
            "needs_confirm": True,
            "root": str(root.resolve()),
            "n_files": self.n_files,
            "max_touch": self.max_touch,
            "message": (
                f"Safety pause: {self.n_files} indexable files (cap {self.max_touch}). "
                "This is not a failure — confirm when you are ready."
            ),
            "action": (
                "Re-run with --confirm, or narrow scope: "
                "`scubiee init . --roots packages`"
            ),
            "hint": str(self),
        }


def is_broad_index_root(root: Path) -> str | None:
    """Return a short reason when *root* is too broad for silent ``init``."""
    root = root.resolve()
    home = Path.home().resolve()
    if root == home:
        return "user home directory"
    if os.name == "nt":
        drive, tail = os.path.splitdrive(str(root))
        tail = tail.strip("\\/")
        if drive and not tail:
            return "drive root"
    elif root == Path("/"):
        return "filesystem root"
    return None


def _broad_root_hint(root: Path, reason: str, n_files: int) -> str:
    count_line = (
        f"Found {n_files} indexable files under this path. "
        if n_files
        else ""
    )
    return (
        f"Safety pause: refusing to index {root} ({reason}). "
        f"{count_line}"
        "This protects you from indexing an overly broad folder by accident. "
        "Change into your project directory and run `scubiee init`, "
        "or re-run with --confirm if you really want to index here."
    )


def preflight_index_scope(
    root: Path,
    *,
    fast: bool = False,
    fast_roots: list[str] | None = None,
    confirm: bool = False,
    force: bool = False,
) -> int:
    """Cheap count + safety gates before any parse/embed work."""
    root = root.resolve()
    broad = is_broad_index_root(root)
    if broad and not confirm and not force:
        raise IndexConfirmRequired(
            0,
            max_touch=max_index_touch(),
            kind="broad_root",
            message=_broad_root_hint(root, broad, 0),
        )
    n = len(collect_index_relpaths(root, fast=fast, fast_roots=fast_roots))
    require_index_confirm(n, confirm=confirm, force=force)
    return n


def max_index_touch() -> int:
    return int(os.environ.get("CTX_INCREMENTAL_MAX_TOUCH", str(DEFAULT_MAX_TOUCH)))


def max_index_chunks() -> int:
    return int(os.environ.get("CTX_MAX_INDEX_CHUNKS", str(DEFAULT_MAX_CHUNKS)))


def require_index_confirm(
    n_files: int,
    *,
    confirm: bool = False,
    force: bool = False,
) -> None:
    if force or confirm:
        return
    cap = max_index_touch()
    if n_files > cap:
        raise IndexConfirmRequired(n_files, max_touch=cap)


def require_chunk_force(
    n_chunks: int,
    *,
    force: bool = False,
) -> None:
    """Block indexes above the chunk/token cap unless ``--force`` is set.

    ``--confirm`` alone is not enough — large chunk counts mean high embed cost.
    """
    if force:
        return
    cap = max_index_chunks()
    if n_chunks > cap:
        raise IndexConfirmRequired(
            n_chunks,
            max_touch=cap,
            kind="too_many_chunks",
            message=_chunk_force_hint(n_chunks, max_chunks=cap),
        )


def _chunk_force_hint(n_chunks: int, *, max_chunks: int) -> str:
    return (
        f"This codebase has {n_chunks:,} chunks (cap {max_chunks:,}) — "
        "too many tokens for a default index. "
        "If you still want to index it, add --force, e.g. "
        "`scubiee init . --force` or `scubiee index . --force`. "
        "Or narrow scope: `scubiee init . --roots packages`."
    )


def _confirm_hint(n_files: int, *, max_touch: int) -> str:
    return (
        f"Safety pause: {n_files} files would be indexed (cap {max_touch}). "
        "Re-run with --confirm when ready, e.g. "
        "`scubiee init . --confirm`, `scubiee index . --confirm`, "
        "or `scubiee sync . --confirm`. "
        "For large repos prefer: `scubiee init . --roots packages`."
    )


def is_safety_pause_message(msg: str | None) -> bool:
    return bool(msg and msg.startswith("Safety pause:"))


AUTO_FULL_INDEX_CHUNKS = int(os.environ.get("CTX_AUTO_FULL_INDEX_CHUNKS", "10000"))

# Chunks re-embedded per sync when chunks.jsonl and the vector store disagree.
# Bounded so one keeper tick cannot turn into a full reindex.
VECTOR_BACKFILL_CAP = int(os.environ.get("CTX_VECTOR_BACKFILL_CAP", "2000"))


@dataclass
class HotDelta:
    """New chunk rows plus their vectors, for an append-only patch publish.

    The publisher needs the float32 rows this sync just embedded; re-reading them
    from the collection means decompressing the whole matrix inside the 5s save
    budget. This travels on a side channel rather than inside the keeper payload
    because that payload is returned as JSON by ``/v1/status``.

    ``records`` are in the order they were appended to ``chunks.jsonl`` and
    ``matrix`` row ``i`` is the vector for ``records[i]`` — only when
    ``full_embed_coverage`` is true. ``base_chunk_count`` is the corpus size
    before the append, so the publisher can refuse to patch a binder that has
    drifted from the corpus this delta was computed against.
    """

    records: list[ChunkRecord]
    matrix: Any | None
    removed_ids: list[int]
    dim: int
    full_embed_coverage: bool
    base_chunk_count: int
    # Deferred collection save. Anything that reloads vectors from disk (the
    # full-publish fallback) must call this first or it publishes chunks with
    # no vectors.
    flush: Any | None = None

    @property
    def append_only(self) -> bool:
        return not self.removed_ids and bool(self.records) and self.full_embed_coverage


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
    confirmation_required: bool = False
    # Never serialized (see HotDelta): keep out of ``to_dict``.
    hot_delta: "HotDelta | None" = field(default=None, repr=False, compare=False)
    stages: dict[str, float] | None = field(default=None, repr=False, compare=False)
    # Files whose graph patch a hot save deferred; the keeper re-queues them so a
    # non-hot sync carries them into graph.json.
    graph_pending: list[str] | None = field(default=None, repr=False, compare=False)
    # Hot lane only: persists the collection. The keeper runs it right after the
    # publish, before the next sync reads the disk.
    vector_flush: Any | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        out = {
            "refreshed": self.refreshed,
            "files": self.files,
            "chunks_upserted": self.chunks_upserted,
            "chunks_removed": self.chunks_removed,
            "ms": round(self.ms, 1),
            "strategy": self.strategy,
            "error": self.error,
            "graph_error": self.graph_error,
            "warnings": self.warnings or [],
            "confirmation_required": self.confirmation_required,
        }
        if is_safety_pause_message(self.error):
            out["status"] = "warning"
            out["warning"] = "confirm_required"
            out["needs_confirm"] = True
        return out


def _paths_for_files(root: Path, rels: list[str]) -> list[Path]:
    out = []
    for r in rels:
        p = root / r
        if p.is_file():
            out.append(p)
    return out


def _slice_chunk_file(
    store: PipelineStore, touch: set[str]
) -> tuple[list[str], list[ChunkRecord], int]:
    """Keep untouched chunk lines as raw text. Parse only the named files."""
    kept: list[str] = []
    touched: list[ChunkRecord] = []
    max_id = -1
    path = store.chunks_path
    if not path.exists():
        return kept, touched, 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cid = int(row.get("id", -1))
        if cid > max_id:
            max_id = cid
        rel = str(row.get("file", "")).replace("\\", "/")
        if rel in touch:
            touched.append(ChunkRecord(**row))
        else:
            kept.append(line)
    return kept, touched, max_id + 1


def _write_sliced_chunks(
    store: PipelineStore, kept_lines: list[str], new_records: list[ChunkRecord]
) -> None:
    body = "".join(line + "\n" for line in kept_lines)
    body += "".join(json.dumps(asdict(c), ensure_ascii=False) + "\n" for c in new_records)
    with store_write_lock(store.base):
        atomic_write_text(store.chunks_path, body)


class _OnceFlush:
    """Deferred ``save_collection``; safe to call from both publisher and keeper.

    The publisher calls it before any full ``load_engine`` (which reads vectors
    from disk), the keeper calls it after publish either way. Only the first call
    writes; a failed write can be retried.
    """

    def __init__(self, vdb, name: str) -> None:
        self._vdb = vdb
        self._name = name
        self._lock = threading.Lock()
        self.done = False

    def __call__(self) -> bool:
        with self._lock:
            if self.done:
                return False
            self._vdb.save_collection(self._name)
            self.done = True
            return True


def _upsert_named_vectors(
    store: PipelineStore,
    col,
    embed_records,
    matrix,
    removed_ids,
    *,
    dim: int,
    bits: int,
    hot_lane: bool = False,
    stages: dict[str, float] | None = None,
    defer_save: bool = False,
):
    """Apply the named delta to the collection; returns a flush callable when deferred.

    ``defer_save``: persisting the collection rewrites every vector file
    (~0.5–1.7s here) and does not change what the live binder serves, so the hot
    lane returns a flush for the keeper to run right *after* publish, on the same
    thread and before the next sync reads the disk. A crash in between leaves
    chunks without vectors, which ``reconcile_vector_store`` re-embeds.
    """
    if col is None:
        if embed_records and matrix is not None:
            store.upsert_vectors(matrix, embed_records, dim=dim, bits=bits)
        return None
    t_mutate = time.perf_counter()
    if removed_ids:
        # Compact after a delete so ids.npy, payloads.jsonl and faiss.index keep
        # the same length. ``add`` already compacts when an upsert hits existing
        # ids; a delete-only batch reaches none of that, so tombstones pile up
        # and the artifacts drift apart. Drift there is what lets search index
        # into an array the chunk corpus no longer agrees with.
        #
        # ``hot_lane``: a rebuild of the whole collection cannot fit the 5s
        # save→map budget (it is seconds on a 7k corpus, now also holding the
        # collection lock against readers). Tombstones + ``dead_ids`` are
        # already honoured by FaissDenseAdapter and reconcile_vector_store, so
        # a save leaves them behind and idle/bulk reclaims later.
        compact = getattr(col, "compact", None)
        dropped = col.delete(list(removed_ids))
        if dropped and callable(compact) and not hot_lane:
            compact()
    if embed_records and matrix is not None:
        payloads = [
            {
                "file": c.file,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "symbol": c.symbol,
                "chunk_id": c.id,
            }
            for c in embed_records
        ]
        col.add(matrix, [c.id for c in embed_records], payloads)
    t_save = time.perf_counter()
    if stages is not None:
        stages["vec_mutate_ms"] = (t_save - t_mutate) * 1000
    if defer_save:
        return _OnceFlush(store.vdb, col.name)
    store.vdb.save_collection(col.name)
    if stages is not None:
        stages["vec_save_ms"] = (time.perf_counter() - t_save) * 1000
    return None


def _patch_file_merkle(store: PipelineStore, root: Path, old: dict[str, str], touch: list[str]) -> None:
    """Update the file Merkle for the paths we just processed.

    ``load_merkle`` returns *canonical* keys — and ``canonical_relpath`` ends in
    ``os.path.normcase``, which on Windows turns ``/`` back into ``\\`` and
    lower-cases. Patching with the posix form therefore inserted a duplicate row
    for a live file and, worse, silently failed to delete a dead one: the
    canonical entry survived, ``root_probe`` kept reporting the path as removed,
    and the keeper re-synced it on every poll forever. Write and delete the
    canonical key, and sweep the raw spellings so older snapshots converge.
    """
    hashes = dict(old)
    for rel in touch:
        rel_posix = rel.replace("\\", "/")
        canonical = canonical_relpath(rel_posix)
        for key in {canonical, rel_posix, rel}:
            hashes.pop(key, None)
        path = root / rel_posix
        if path.is_file():
            hashes[canonical] = file_sha256(path)
    store.save_merkle(hashes)


def _refresh_publication(store: PipelineStore) -> None:
    """Re-stamp the publication manifest over the artifacts we just rewrote.

    Incremental sync mutates the same published artifacts as a full index, so the
    manifest has to be refreshed after *every* write that touches one of them —
    including a no-delta batch that only patches the Merkle. Skipping it makes
    readiness reject the live update as checksum corruption.
    """
    from pipeline.artifact_guard import invalidate_manifest, publish_manifest

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
    if not published:
        return
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


def reconcile_vector_store(
    store: PipelineStore,
    *,
    meta: dict | None = None,
    cap: int = VECTOR_BACKFILL_CAP,
) -> dict[str, int]:
    """Make the vector collection agree with ``chunks.jsonl``, both directions.

    The corpus and the vectors are two files that can drift apart — a crash or an
    aborted FAISS write between them, or an older build that wrote chunks first.
    Drift is not cosmetic:

    * A chunk with no vector can never be returned. Dense is the only channel
      allowed to admit a file into the result pool, so the file is invisible to
      search until something re-embeds it. Re-embedding uses the stored
      ``enriched`` text, so the repository file need not still exist on disk.
    * A vector with no chunk keeps a deleted file's content resident and
      rankable-looking, and it is what made the two stores disagree on length in
      the first place.

    Returns ``{"missing": n, "embedded": k, "stale": m, "dropped": m}``.
    """
    empty = {"missing": 0, "embedded": 0, "stale": 0, "dropped": 0}
    col = store.get_collection()
    meta_obj = getattr(col, "meta", None)
    if col is None or getattr(col, "ids", None) is None or meta_obj is None:
        return dict(empty)
    chunks = store.load_chunks()
    if not chunks:
        return dict(empty)
    dead = {int(x) for x in (getattr(meta_obj, "dead_ids", None) or [])}
    live = {int(vid) for vid in col.ids if int(vid) not in dead}
    corpus = {int(c.id) for c in chunks}
    orphans = [c for c in chunks if int(c.id) not in live]
    stale = sorted(live - corpus)
    if not orphans and not stale:
        return dict(empty)

    dropped = 0
    if stale:
        delete = getattr(col, "delete", None)
        compact = getattr(col, "compact", None)
        if callable(delete):
            dropped = int(delete(stale) or 0)
            if dropped and callable(compact):
                compact()

    batch: list[ChunkRecord] = []
    if orphans:
        batch = orphans[: max(1, int(cap))]
        meta = meta if meta is not None else store.load_meta()
        model = str(meta.get("embed_model") or "nomic-ai/CodeRankEmbed")
        try:
            from pipeline.engine import get_embedder

            embedder = get_embedder(model, dim=meta.get("dim"), cache_path=store.embed_cache)
        except Exception:  # noqa: BLE001
            embedder = Embedder(
                model=model,
                cache_path=store.embed_cache,
                batch_size=64,
                max_seq_length=256 if meta.get("fast") else 512,
                dim=meta.get("dim"),
            )
        matrix = embedder.embed_many([c.enriched for c in batch])
        payloads = [
            {
                "file": c.file,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "symbol": c.symbol,
                "chunk_id": c.id,
            }
            for c in batch
        ]
        col.add(matrix, [int(c.id) for c in batch], payloads)

    store.vdb.save_collection(col.name)
    print(
        f"[sync] vector reconcile embedded={len(batch)} missing={len(orphans)} "
        f"dropped={dropped} stale={len(stale)}",
        file=sys.stderr,
        flush=True,
    )
    return {
        "missing": len(orphans),
        "embedded": len(batch),
        "stale": len(stale),
        "dropped": dropped,
    }


def _patch_capability_cards(root: Path, store: PipelineStore, touch: list[str]) -> None:
    from pipeline.capability import build_cards, load_cards, save_cards

    touch_set = {f.replace("\\", "/") for f in touch}
    kept = [
        card
        for card in load_cards(store.base)
        if str(getattr(card, "path", "")).replace("\\", "/") not in touch_set
    ]
    fresh = build_cards(root, rels=[f for f in touch_set if f.endswith(".py")])
    save_cards(store.base, kept + fresh)


def incremental_sync(
    root: Path,
    *,
    base_dir: Path | None = None,
    vdb: VectorDatabase | None = None,
    bits: int = 4,
    max_chars: int = 1200,
    force_files: list[str] | None = None,
    bulk: bool = False,
    confirm: bool = False,
    discover_newcomers: bool = True,
    capacity_wait_s: float = 90.0,
    inline: bool = True,
    hot_lane: bool = False,
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
        budget = rm.wait_for_capacity("sync", timeout_s=capacity_wait_s)
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

    mem_budget = resolve_index_memory_budget(
        background=not bulk,
        store=store,
        touch_files=len(force_files) if force_files else None,
    )
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
    if force_files:
        # Named dirty set. Do not stat or hash the rest of the corpus first.
        from pipeline.freshness import FreshnessReport
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
        report = FreshnessReport(
            clean=False,
            root=str(root),
            diff=SyncDiff(
                added=sorted(added),
                modified=sorted(modified),
                removed=sorted(removed_f),
                root_hash=_rh(old),
                unchanged=False,
            ),
            strategy="incremental",
            reason="force_files",
            detection="force",
        )
    else:
        report = check_freshness(
            root, old, indexed_head=meta.get("git_head"), file_mtimes=store.load_mtimes()
        )

    # Merkle is a closed snapshot of already-indexed files. Discover newcomers
    # with the same path filter as a full/fast index so untracked modules sync.
    if discover_newcomers and not force_files:
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

    if report.strategy == "full" and not force_files and not confirm:
        n = report.changed_count
        max_touch = max_index_touch()
        if n > max_touch:
            return IncrementalResult(
                refreshed=False,
                files=[],
                chunks_upserted=0,
                chunks_removed=0,
                ms=(time.perf_counter() - t0) * 1000,
                strategy="full",
                error=_confirm_hint(n, max_touch=max_touch),
            )

    changed = sorted(set(report.diff.changed_files) | set(force_files or []))
    if not hot_lane:
        # Catch up on graph work a previous hot save deferred. Re-parsing these
        # files is cheap (the chunk Merkle finds no delta, so nothing re-embeds);
        # it exists so their nodes/edges reach graph.json.
        owed = [
            str(p).replace("\\", "/")
            for p in (store.load_meta().get("graph_pending") or [])
        ]
        owed = [p for p in owed if (root / p).is_file()]
        if owed:
            changed = sorted(set(changed) | set(owed))
    removed = list(report.diff.removed)
    # Soft auto-cap — larger than this needs an explicit --confirm (not --force/--fast).
    max_touch = int(os.environ.get("CTX_INCREMENTAL_MAX_TOUCH", str(DEFAULT_MAX_TOUCH)))
    touch_n = len(changed) + len(removed)
    if touch_n > max_touch and not force_files and not confirm:
        return IncrementalResult(
            refreshed=False,
            files=(changed + removed)[:50],
            chunks_upserted=0,
            chunks_removed=0,
            ms=(time.perf_counter() - t0) * 1000,
            strategy=report.strategy,
            error=_confirm_hint(touch_n, max_touch=max_touch),
        )
    touch = sorted(set(changed) | set(removed))
    if not inline:
        return IncrementalResult(
            refreshed=False,
            files=touch[:50],
            chunks_upserted=0,
            chunks_removed=0,
            ms=(time.perf_counter() - t0) * 1000,
            strategy="deferred",
            error="queued for keeper; request thread does not embed",
        )

    try:
        # Per-stage wall clock. When a save misses the 5s map SLA the log has to
        # name the stage that ate it (parse vs embed vs write vs publish) instead
        # of one opaque total.
        stages: dict[str, float] = {}
        # Re-extract graph for touched files + neighbors? Keep simple: re-extract touched only,
        # rebuild full graph from all currently indexed file set + new
        touch_set = {f.replace("\\", "/") for f in touch}
        kept_lines: list[str] | None = None
        t_slice = time.perf_counter()
        if force_files:
            kept_lines, existing, next_id = _slice_chunk_file(store, touch_set)
            removed_ids = [c.id for c in existing]
        else:  # noqa: RET505 — full-corpus path keeps its own branch below
            existing = store.load_chunks()
            removed_ids = [c.id for c in existing if c.file.replace("\\", "/") in touch_set]
            next_id = (max((c.id for c in existing), default=-1) + 1) if existing else 0
        keep = [c for c in existing if c.file.replace("\\", "/") not in touch_set]
        stages["slice_ms"] = (time.perf_counter() - t_slice) * 1000
        # Known as soon as the chunk file is sliced: the hot lane needs it before
        # the graph stage, and the write stage re-reads it further down.
        named_delta = bool(force_files) and kept_lines is not None

        paths = _paths_for_files(root, changed)
        new_records: list[ChunkRecord] = []
        graph_error: str | None = None
        matrix = None
        embedder = None
        warnings: list[str] = []
        raw: dict = {"nodes": [], "edges": [], "hyperedges": []}

        t_parse = time.perf_counter()
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
                    raw_text = (ch.content or "").lstrip("\ufeff")
                    if isinstance(body, str):
                        body = body.lstrip("\ufeff")
                    new_records.append(
                        ChunkRecord(
                            id=next_id,
                            file=ch.file,
                            start_line=ch.start_line,
                            end_line=ch.end_line,
                            symbol=ch.symbol,
                            text=raw_text[:text_cap],
                            enriched=body,
                        )
                    )
                    next_id += 1
        stages["parse_ms"] = (time.perf_counter() - t_parse) * 1000

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
                    f"limit of {limit}; run `scubiee index {root} --force` explicitly"
                ),
                warnings=[
                    "No graph or vector artifacts were published for this oversized change."
                ],
            )

        # Patch graph from changed-file extract only (same AST pass as chunks).
        # Fallback: full extract if graph.json missing.
        #
        # Hot lane: ``build_merge`` reloads graph.json and rebuilds the whole
        # graph through ``build(dedup=True)`` — ~6.7s for 15.9k nodes on this
        # repo, which is more than the entire save→map budget. Graph affinity is
        # not what admits a file into map's pool (dense is), so a save defers it:
        # graph.json is left untouched (so the published manifest stays coherent)
        # and the paths are queued for a non-hot catch-up sync.
        t_graph = time.perf_counter()
        graph_pending: list[str] = []
        if hot_lane and named_delta:
            graph_pending = sorted(touch_set)
            pending_meta = sorted(
                {str(p) for p in (meta.get("graph_pending") or [])} | touch_set
            )
            meta["graph_pending"] = pending_meta
        else:
            try:
                graph_json = store.base / "graph.json"
                if graph_json.is_file() or force_files:
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
                print(
                    f"[incremental] WARNING: graph rebuild failed: {gexc}",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                # This sync carried the graph, so nothing is owed any more.
                if meta.get("graph_pending"):
                    meta.pop("graph_pending", None)
        stages["graph_ms"] = (time.perf_counter() - t_graph) * 1000

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
        # Drop vectors only for chunks that are gone or whose text changed.
        # Unchanged chunks keep their ids so a no-op edit is not a deletion.
        embed_ids = {id(record) for record in embed_records}
        truly_removed: list[int] = []
        for record in existing:
            file = record.file.replace("\\", "/")
            key = chunk_key(record)
            replacement = next(
                (item for item in new_by_file.get(file, []) if chunk_key(item) == key),
                None,
            )
            if replacement is None or id(replacement) in embed_ids:
                truly_removed.append(record.id)
            else:
                replacement.id = record.id
        removed_ids = truly_removed

        if embed_records:
            t_embed = time.perf_counter()
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
            stages["embed_ms"] = (time.perf_counter() - t_embed) * 1000
            stages["embed_chunks"] = float(len(embed_records))

        if not embed_records and not removed_ids:
            # Nothing to embed or drop for these paths. Two things still have to
            # happen, or the engine never converges:
            #
            # 1. Record the disk hashes we just verified. Without this the file
            #    Merkle keeps disagreeing with disk, root_probe re-reports the
            #    same paths on every poll, and the keeper re-syncs them forever
            #    (~9s a cycle) — including paths that were deleted and were
            #    never in chunks.jsonl to begin with.
            # 2. Repair any chunk that lost its vector in an earlier crash.
            #    Dense is the only channel that can admit a file into the
            #    result pool, so those chunks are unsearchable until re-embedded.
            backfilled = 0
            if named_delta:
                try:
                    # Persist graph-debt bookkeeping: a hot save records owed
                    # files here, and a catch-up that carried them usually has no
                    # chunk delta. Must precede _refresh_publication, which
                    # checksums meta.json.
                    if meta.get("graph_pending") != store.load_meta().get("graph_pending"):
                        store.save_meta(meta)
                    _patch_file_merkle(store, root, old, touch)
                    chunk_merkle = store.load_chunk_merkle()
                    for file in touch_set:
                        recs = new_by_file.get(file, [])
                        if recs:
                            chunk_merkle[file] = {
                                chunk_key(c): chunk_digest(c) for c in recs
                            }
                        else:
                            chunk_merkle.pop(file, None)
                    store.save_chunk_merkle(chunk_merkle)
                    _refresh_publication(store)
                except Exception as merkle_exc:  # noqa: BLE001
                    warnings.append(f"no_delta_merkle: {merkle_exc}")
            try:
                fixed = reconcile_vector_store(store, meta=meta)
                backfilled = int(fixed.get("embedded") or 0) + int(
                    fixed.get("dropped") or 0
                )
            except Exception as bf_exc:  # noqa: BLE001
                warnings.append(f"vector_reconcile: {bf_exc}")
            if backfilled:
                from pipeline.engine import clear_engines

                clear_engines()
            print(
                f"[sync] no chunk delta files={len(touch)} "
                f"paths={','.join(touch[:8])}{'…' if len(touch) > 8 else ''} "
                f"reconciled={backfilled} ms={(time.perf_counter() - t0) * 1000:.0f}",
                file=sys.stderr,
                flush=True,
            )
            return IncrementalResult(
                refreshed=backfilled > 0,
                files=touch,
                chunks_upserted=backfilled,
                chunks_removed=0,
                ms=(time.perf_counter() - t0) * 1000,
                strategy="none",
                warnings=warnings or None,
            )

        chunk_count = 0
        hot_delta: HotDelta | None = None
        vector_flush = None
        if named_delta:
            # Vectors first, chunk lines second. A crash between the two writes
            # then leaves orphan *vectors* (harmless — unreferenced ids are
            # ignored) instead of orphan *chunks*, which dense can never rank.
            t_write = time.perf_counter()
            col_delta = store.get_collection()
            stages["vec_open_ms"] = (time.perf_counter() - t_write) * 1000
            dim_delta = int(
                meta.get("dim")
                or (matrix.shape[1] if matrix is not None and getattr(matrix, "size", 0) else 768)
            )
            vector_flush = _upsert_named_vectors(
                store,
                col_delta,
                embed_records,
                matrix,
                removed_ids,
                dim=dim_delta,
                bits=int(meta.get("bits") or bits),
                hot_lane=hot_lane,
                stages=stages,
                defer_save=hot_lane,
            )
            stages["vectors_ms"] = (time.perf_counter() - t_write) * 1000
            t_chunks = time.perf_counter()
            _write_sliced_chunks(store, kept_lines or [], new_records)
            stages["chunkfile_ms"] = (time.perf_counter() - t_chunks) * 1000
            # Hand the publisher exactly what it needs to append to the live
            # binder: the appended records, the rows we just embedded for them,
            # and the corpus size they were appended to. Row i belongs to
            # records[i] only when every appended record was embedded in order.
            coverage = [int(r.id) for r in embed_records] == [
                int(r.id) for r in new_records
            ]
            if (
                matrix is not None
                and getattr(matrix, "size", 0)
                and int(getattr(matrix, "shape", (0,))[0]) != len(embed_records)
            ):
                coverage = False
            hot_delta = HotDelta(
                records=list(new_records),
                matrix=matrix,
                removed_ids=[int(i) for i in removed_ids],
                dim=dim_delta,
                full_embed_coverage=bool(coverage),
                base_chunk_count=len(kept_lines or []),
            )
            stages["write_ms"] = (time.perf_counter() - t_write) * 1000
            t_reconcile = time.perf_counter()
            try:
                reconcile_vector_store(store, meta=meta)
            except Exception as bf_exc:  # noqa: BLE001
                warnings.append(f"vector_reconcile: {bf_exc}")
            stages["reconcile_ms"] = (time.perf_counter() - t_reconcile) * 1000
            _patch_file_merkle(store, root, old, touch)
            chunk_merkle = store.load_chunk_merkle()
            for file in touch_set:
                recs = new_by_file.get(file, [])
                if recs:
                    chunk_merkle[file] = {chunk_key(c): chunk_digest(c) for c in recs}
                else:
                    chunk_merkle.pop(file, None)
            store.save_chunk_merkle(chunk_merkle)
            merged = new_records
            chunk_count = len(kept_lines or []) + len(new_records)
        else:
            # Merge chunk list. IDs stay durable; gaps after deletion are expected.
            merged = keep + new_records
            store.save_chunks(merged)
            chunk_count = len(merged)

        if not named_delta:
            col = store.get_collection()
        dim = int(meta.get("dim") or (matrix.shape[1] if matrix is not None and matrix.size else 768))
        if named_delta:
            col = "skip"
        bits_i = int(meta.get("bits") or bits)
        if named_delta:
            pass
        elif col is None:
            # create empty then replace — matrix only covers embed_records, not all merged
            import numpy as np

            if not merged:
                full_mat = np.zeros((0, dim), dtype=np.float32)
            elif matrix is not None and int(matrix.shape[0]) == len(merged):
                full_mat = np.asarray(matrix, dtype=np.float32)
            else:
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
                full_mat = embedder.embed_many([c.enriched for c in merged])
            store.upsert_vectors(
                full_mat,
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
                # keep empty or collection empty — never upsert a partial embed batch
                import numpy as np

                if not merged:
                    full_mat = np.zeros((0, dim), dtype=np.float32)
                elif matrix is not None and int(matrix.shape[0]) == len(merged):
                    full_mat = np.asarray(matrix, dtype=np.float32)
                else:
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
                    full_mat = embedder.embed_many([c.enriched for c in merged])
                store.upsert_vectors(
                    full_mat,
                    merged,
                    dim=dim,
                    bits=bits_i,
                )

        if not named_delta:
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
        if report.git_head:
            meta["git_head"] = report.git_head
        meta["chunks"] = chunk_count
        meta["last_incremental_at"] = time.time()
        if graph_error:
            meta["last_graph_error"] = graph_error
        else:
            meta.pop("last_graph_error", None)
        store.save_meta(meta)
        # Incremental sync mutates the same published artifacts as a full
        # index. Refresh the manifest only after all of those writes complete,
        # otherwise readiness will reject every live update as corruption.
        t_publication = time.perf_counter()
        _refresh_publication(store)
        stages["publication_ms"] = (time.perf_counter() - t_publication) * 1000
        t_cards = time.perf_counter()
        try:
            from pipeline.capability import ensure_cards

            if hot_lane and named_delta:
                # Cards are a locate aid over module summaries, not what admits a
                # file into map's pool. Rebuilding them reads and rewrites the
                # whole card file, so a save leaves it to the same catch-up that
                # carries the graph.
                pass
            elif named_delta:
                _patch_capability_cards(root, store, touch)
            else:
                ensure_cards(
                    root,
                    store.base,
                    indexed_files=[c.file for c in merged],
                    force=True,
                )
        except Exception as cap_exc:  # noqa: BLE001
            warnings = list(warnings or [])
            warnings.append(f"capability_cards: {cap_exc}")
        stages["cards_ms"] = (time.perf_counter() - t_cards) * 1000
        from pipeline.engine import clear_engines

        clear_engines()

        upserted = len(embed_records)
        removed_n = len(removed_ids)
        if hot_delta is not None:
            # A full-publish fallback reloads vectors from disk; it must flush first.
            hot_delta.flush = vector_flush
        return IncrementalResult(
            refreshed=upserted > 0 or removed_n > 0,
            files=touch,
            chunks_upserted=upserted,
            chunks_removed=removed_n,
            ms=(time.perf_counter() - t0) * 1000,
            strategy=report.strategy,
            graph_error=graph_error,
            warnings=warnings or None,
            hot_delta=hot_delta if hot_lane else None,
            stages={k: round(v, 1) for k, v in stages.items()},
            graph_pending=graph_pending or None,
            vector_flush=vector_flush,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[sync] failed: {exc}", file=sys.stderr, flush=True)
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
                        quiesce=False,
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
                "(set CTX_ALLOW_BG_FULL=1 or run: scubiee sync . --confirm)",
                file=sys.stderr,
                flush=True,
            )
            note = (
                "full reindex skipped (CTX_ALLOW_BG_FULL=0); "
                "run `scubiee sync . --confirm` if you want to index the large change set"
            )
        out["sync"] = {
            "refreshed": False,
            "strategy": "full",
            "files": (report.diff.changed_files + report.diff.removed)[:50],
            "note": note,
        }
        out["dirty_boost_files"] = report.diff.changed_files[:50]
        return out

    # background: incremental in daemon (single-flight)
    def _bg():
        incremental_sync(root, base_dir=base_dir, vdb=vdb)

    started = _run_single_flight("ctx-incremental", _bg)
    out["sync"] = {
        "refreshed": False,
        "strategy": "background",
        "files": report.diff.changed_files + report.diff.removed,
        "note": (
            "search continues; BM25 hot-patched from disk; dense may lag"
            if started
            else "background sync already running; dense may lag briefly"
        ),
        "single_flight": not started,
    }
    out["dirty_boost_files"] = report.diff.changed_files
    return out
