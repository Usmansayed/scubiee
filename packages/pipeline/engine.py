"""Warm long-lived search engine (embedder + conductor cached in-process)."""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from conductor.architectures import MultiArchConductor
from conductor.bm25_index import BM25Index
from conductor.conductor import ConductorConfig
from conductor.graphify_retriever import ChunkSpan, GraphifyChunkRetriever
from graphify.serve import _load_graph

from pipeline.capability import CapabilityIndex, LocateHit, ensure_cards
from pipeline.embedder import Embedder
from pipeline.hot_patch import disk_preview, hot_patch_texts, rebuild_bm25
from pipeline.searcher import FaissDenseAdapter, SearchResult
from pipeline.store import ChunkRecord, PipelineStore
from pipeline.vectordb import VectorDatabase


def _verify_gpu_provider(embedder: Embedder) -> None:
    """Warn if the configured GPU profile silently fell back to CPU at runtime.

    Called after the warm-up embed_one. Checks the accel profile vs what ORT
    actually loaded. Logs a clear warning so users know they're on CPU.
    """
    try:
        from pipeline.accel import load_accel, ort_available_providers

        profile = load_accel()
        if not profile or profile.profile in {"cpu", "mlx"}:
            return  # CPU or MLX — no ORT provider concern

        want_provider = {
            "cuda": "CUDAExecutionProvider",
            "dml": "DmlExecutionProvider",
            "coreml": "CoreMLExecutionProvider",
        }.get(profile.profile)

        if not want_provider:
            return

        available = ort_available_providers()
        if want_provider in available:
            return  # All good — GPU provider loaded

        print(
            f"[engine] WARNING: profile={profile.profile} but {want_provider} not in "
            f"available providers {available}. Embedding is running on CPU. "
            f"Run `scubiee setup --repair` to fix GPU acceleration.",
            file=sys.stderr,
            flush=True,
        )
    except Exception:  # noqa: BLE001
        pass  # Don't crash the warm-up over a diagnostic check

_LOCK = threading.RLock()
_ENGINES: dict[str, "WarmSearchEngine"] = {}
_EMBEDDERS: dict[str, Embedder] = {}

# Most capability cards a SOFT query may promote ahead of RAG hits.
CAP_MERGE_MAX = int(os.environ.get("CTX_CAPABILITY_MAX_PROMOTED", "2"))
CAP_MERGE_MIN_SCORE = 2.0


def promotable_cards(
    capability: "CapabilityIndex | None",
    cap_hits: list[LocateHit],
    top_k: int,
    *,
    max_promoted: int | None = None,
) -> list[LocateHit]:
    """Capability cards allowed ahead of RAG hits for a SOFT query.

    Cards are BM25 over module summaries, so a bare score floor matches almost
    any English query. Require a decisive leader (``strong_hit``) and cap the
    count, otherwise cards fill the whole window and evict the real hits.
    """
    if capability is None or not cap_hits or not capability.strong_hit(cap_hits):
        return []
    limit = CAP_MERGE_MAX if max_promoted is None else max_promoted
    keep = min(top_k, max(1, limit))
    return [h for h in cap_hits if h.score >= CAP_MERGE_MIN_SCORE][:keep]


def _engine_key(root: Path, base_dir: Path | None) -> str:
    return f"{root.resolve()}::{base_dir.resolve() if base_dir else ''}"


def _store_generation_mtime(store: PipelineStore) -> float:
    """Newest published artifact mtime — used to drop a stale in-process engine."""
    latest = 0.0
    for path in (store.meta_path, store.chunks_path, store.merkle_path):
        try:
            if path.is_file():
                latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return latest


class _LazyEmbedder:
    """Defer model weights until the first semantic query (locate_only tier)."""

    def __init__(self, model: str, *, dim: int | None, cache_path: Path | None) -> None:
        self.model = model
        self.dim = dim
        self.cache_path = cache_path
        self.backend = "lazy"
        self._inner: Embedder | None = None

    def _ensure(self) -> Embedder:
        if self._inner is None:
            self._inner = get_embedder(
                self.model,
                dim=self.dim,
                cache_path=self.cache_path,
                eager=True,
            )
            self.backend = self._inner.backend
            try:
                from pipeline.memory_governor import get_governor

                get_governor().note_embedder_loaded()
            except Exception:  # noqa: BLE001
                pass
        return self._inner

    def unload(self) -> None:
        self._inner = None
        self.backend = "lazy"

    def embed_one(self, *args: Any, **kwargs: Any) -> Any:
        try:
            from pipeline.memory_governor import get_governor

            get_governor().note_semantic_activity()
        except Exception:  # noqa: BLE001
            pass
        return self._ensure().embed_one(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ensure(), name)


def get_embedder(
    model: str,
    *,
    dim: int | None,
    cache_path: Path | None,
    eager: bool = True,
) -> Embedder:
    """Process-wide CodeRank/Ollama embedder cache (load weights once)."""
    key = f"{model}|{dim}|{cache_path}"
    with _LOCK:
        if key not in _EMBEDDERS:
            emb = Embedder(model=model, dim=dim, cache_path=cache_path)
            if eager:
                if emb.backend == "coderank":
                    emb._ensure_coderank()
                elif emb.backend == "mlx":
                    emb._ensure_mlx()
            _EMBEDDERS[key] = emb
        return _EMBEDDERS[key]


def release_embedders() -> int:
    """Unload cached embedder weights; lazy wrappers drop their inner reference."""
    with _LOCK:
        for eng in _ENGINES.values():
            emb = eng.embedder
            if isinstance(emb, _LazyEmbedder):
                emb.unload()
        count = len(_EMBEDDERS)
        _EMBEDDERS.clear()
        try:
            from pipeline.memory_governor import get_governor

            get_governor().note_embedder_unloaded()
        except Exception:  # noqa: BLE001
            pass
        return count


def embedder_is_loaded() -> bool:
    with _LOCK:
        return bool(_EMBEDDERS)


@dataclass
class WarmSearchEngine:
    root: Path
    store: PipelineStore
    chunks: list[ChunkRecord]
    texts: list[str]
    files: list[str]
    conductor: MultiArchConductor
    embedder: Embedder
    load_ms: float
    loaded_at: float
    capability: CapabilityIndex | None = None

    def locate_capability(self, query: str, top_k: int = 5) -> list[LocateHit]:
        idx = self.capability
        if idx is None:
            return []
        return idx.locate(query, top_k=top_k)

    def _best_chunk_id(self, rel: str) -> int:
        rel = rel.replace("\\", "/")
        best_id, best_len = -1, -1
        for c in self.chunks:
            f = c.file.replace("\\", "/")
            if f == rel or f.endswith("/" + rel) or rel.endswith("/" + f):
                n = len(c.text or "")
                if n > best_len:
                    best_len, best_id = n, int(c.id)
        return best_id

    def _cap_results(self, caps: list[LocateHit], top_k: int) -> list[SearchResult]:
        out: list[SearchResult] = []
        for i, h in enumerate(caps[:top_k], 1):
            cid = self._best_chunk_id(h.path)
            out.append(
                SearchResult(
                    rank=i,
                    file=h.path.replace("\\", "/"),
                    score=float(h.score),
                    chunk_id=cid if cid >= 0 else 0,
                    preview=h.why[:240],
                    source=f"capability:{h.symbol}",
                )
            )
        return out

    def search(
        self,
        query: str,
        top_k: int = 8,
        *,
        skip_freshness: bool = False,
    ) -> list[SearchResult]:
        gate: dict[str, Any] = {"freshness": {"strategy": "skipped"}, "sync": None}
        if not skip_freshness:
            gen = _store_generation_mtime(self.store)
            if gen > self.loaded_at + 0.05:
                clear_engines()
                fresh = load_engine(self.root, force_reload=True)
                return fresh.search(query, top_k=top_k, skip_freshness=False)

            from pipeline.incremental import ensure_fresh_for_search

            gate = ensure_fresh_for_search(self.root) or {}
            sync = gate.get("sync") or {}
            if sync.get("refreshed"):
                clear_engines()
                fresh = load_engine(self.root, force_reload=True)
                return fresh.search(query, top_k=top_k, skip_freshness=True)

            # Cursor-style: while dense lags, hot-patch BM25 from disk (no embed wait)
            dirty = list(gate.get("dirty_boost_files") or [])
            strat = (gate.get("freshness") or {}).get("strategy")
            if dirty and strat in {"background", "full", "incremental"}:
                patched, touched = hot_patch_texts(self.root, self.chunks, self.texts, dirty)
                if touched:
                    self.texts = patched
                    self.conductor.bm25 = rebuild_bm25(self.texts)
                    gate["hot_patched_chunks"] = len(touched)

        try:
            from conductor.query_router import query_state, path_likeness

            qstate = query_state(query)
            plike = path_likeness(query)
        except Exception:  # noqa: BLE001
            qstate, plike = None, None

        # SOFT: cheap capability locate (no LLM). Prefer exclusive cards only when
        # CTX_CAPABILITY=exclusive; default merges cards ahead of RAG so we don't
        # drop good R_plan hits.
        cap_ms = 0.0
        cap_hits: list[LocateHit] = []
        cap_mode = (os.environ.get("CTX_CAPABILITY") or "merge").strip().lower()
        if (
            qstate == "SOFT"
            and self.capability is not None
            and cap_mode not in {"0", "false", "off"}
        ):
            t_cap = time.perf_counter()
            cap_hits = self.capability.locate(query, top_k=max(top_k, 5))
            cap_ms = (time.perf_counter() - t_cap) * 1000

        if (
            cap_mode in {"exclusive", "only"}
            and cap_hits
            and self.capability is not None
            and self.capability.strong_hit(cap_hits)
        ):
            out = self._cap_results(cap_hits, top_k)
            self._last_timings = {
                "embed_ms": 0.0,
                "retrieve_ms": round(cap_ms, 1),
                "capability_ms": round(cap_ms, 1),
                "total_ms": round(cap_ms, 1),
                "freshness": gate.get("freshness", {}).get("strategy"),
                "detection": gate.get("freshness", {}).get("detection"),
                "hot_patched_chunks": gate.get("hot_patched_chunks", 0),
                "retrieve_mode": "capability",
                "query_state": qstate,
                "path_likeness": round(plike, 3) if plike is not None else None,
                "hit_source": out[0].source if out else None,
            }
            self._last_gate = gate
            return out

        t0 = time.perf_counter()
        # Cap query size (huge prompts can OOM/orphan ORT on laptop GPUs) and
        # single-flight the embed — DirectML/ORT is not safe under ThreadingHTTPServer.
        max_q = int(os.environ.get("CTX_QUERY_MAX_CHARS", "2000") or "2000")
        q_embed = (query or "")[: max(64, max_q)]
        try:
            from pipeline.fair_schedule import get_embed_scheduler

            with get_embed_scheduler().hold(
                "query-embed", priority="active", timeout_s=90.0
            ) as acquired:
                if not acquired:
                    raise TimeoutError("embed scheduler busy")
                qvec = self.embedder.embed_one(q_embed, is_query=True)
        except Exception:
            import hashlib

            h = hashlib.sha256(q_embed.encode("utf-8")).digest()
            rng = np.random.default_rng(int.from_bytes(h[:8], "little"))
            dim = int(self.embedder.dim or 768)
            qvec = rng.normal(size=dim).astype(np.float32)
            qvec /= max(float(np.linalg.norm(qvec)), 1e-12)
        embed_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        # One production retrieve path. Research arches stay on MultiArchConductor
        # for bakeoffs; the engine does not select them.
        retrieve_fn = self.conductor.retrieve_D_channel_best
        route = "D_channel_best"
        hits = retrieve_fn(query, qvec, top_k=top_k)
        retrieve_ms = (time.perf_counter() - t1) * 1000

        dirty_set = set(gate.get("dirty_boost_files") or [])
        if dirty_set:

            def _boost(h: Any) -> tuple:
                f = h.file.replace("\\", "/")
                return (0 if f in dirty_set else 1, -h.score)

            hits = sorted(hits, key=_boost)

        by_id = {c.id: c for c in self.chunks}
        out: list[SearchResult] = []
        for i, h in enumerate(hits, 1):
            # Cursor: read live disk for the span (vectors are pointers)
            preview = ""
            cid = int(h.chunk_id)
            if 0 <= cid < len(self.chunks):
                c = self.chunks[cid]
            else:
                c = by_id.get(cid)
            if c is not None:
                preview = disk_preview(self.root, c.file, c.start_line, c.end_line)
            if not preview and 0 <= cid < len(self.texts):
                preview = " ".join(self.texts[cid].split())[:240]
            out.append(
                SearchResult(
                    rank=i,
                    file=h.file.replace("\\", "/"),
                    score=float(h.score),
                    chunk_id=int(c.id) if c is not None else cid,
                    preview=preview,
                    source=h.source or "D_channel_best",
                    start_line=int(c.start_line) if c is not None else None,
                    end_line=int(c.end_line) if c is not None else None,
                )
            )

        # Soft merge: a few capability pointers first, RAG fills the rest (deduped).
        if qstate == "SOFT" and cap_hits and cap_mode not in {"0", "false", "off"}:
            promotable = promotable_cards(self.capability, cap_hits, top_k)
            cap_out = self._cap_results(promotable, len(promotable))
            if cap_out:
                seen: set[str] = set()
                merged: list[SearchResult] = []
                for r in cap_out + out:
                    f = r.file.replace("\\", "/")
                    if f in seen:
                        continue
                    seen.add(f)
                    merged.append(r)
                out = merged[:top_k]
                for i, r in enumerate(out, 1):
                    r.rank = i
                route = route + "+cap"

        self._last_timings = {
            "embed_ms": round(embed_ms, 1),
            "retrieve_ms": round(retrieve_ms, 1),
            "capability_ms": round(cap_ms, 1),
            "total_ms": round(embed_ms + retrieve_ms + cap_ms, 1),
            "freshness": gate.get("freshness", {}).get("strategy"),
            "detection": gate.get("freshness", {}).get("detection"),
            "hot_patched_chunks": gate.get("hot_patched_chunks", 0),
            "retrieve_mode": route,
            "query_state": qstate,
            "path_likeness": round(plike, 3) if plike is not None else None,
            "hit_source": out[0].source if out else None,
        }
        self._last_gate = gate
        return out

    def status(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "chunks": len(self.texts),
            "capability_cards": len(self.capability.cards) if self.capability else 0,
            "load_ms": round(self.load_ms, 1),
            "loaded_at": self.loaded_at,
            "embed_model": self.embedder.model,
            "embed_backend": self.embedder.backend,
            "warm": True,
        }


def load_engine(
    root: Path,
    *,
    base_dir: Path | None = None,
    vdb: VectorDatabase | None = None,
    force_reload: bool = False,
) -> WarmSearchEngine:
    root = root.resolve()
    key = _engine_key(root, base_dir)
    with _LOCK:
        if not force_reload and key in _ENGINES:
            return _ENGINES[key]

        t0 = time.perf_counter()
        store = PipelineStore(root, base_dir=base_dir, vdb=vdb)
        from pipeline.project_id import index_is_usable

        if not index_is_usable(store.base):
            raise RuntimeError(
                "Index publication is missing or checksum-invalid; refusing mixed generation."
            )
        chunks = store.load_chunks()
        if not chunks:
            raise RuntimeError("No index found. Run: python -m pipeline index <repo>")
        col = store.get_collection()
        if col is None:
            raise RuntimeError("Vector collection missing. Re-run index.")
        graph_json = store.base / "graph.json"
        if not graph_json.exists():
            raise RuntimeError("graph.json missing. Re-run index.")

        texts = [c.text for c in chunks]
        files = [c.file.replace("\\", "/") for c in chunks]
        G = _load_graph(str(graph_json))
        spans = [
            ChunkSpan(index=i, file=files[i], start_line=c.start_line, end_line=c.end_line)
            for i, c in enumerate(chunks)
        ]
        graph = GraphifyChunkRetriever(G, spans, depth=2)
        bm25 = BM25Index(texts)
        dense = FaissDenseAdapter(col, n_chunks=len(chunks))
        conductor = MultiArchConductor(
            files=files,
            bm25=bm25,
            dense=dense,
            graph=graph,
            config=ConductorConfig(),
        )
        meta = store.load_meta()
        model = str(meta.get("embed_model") or "nomic-ai/CodeRankEmbed")
        try:
            from pipeline.memory_governor import (
                current_serve_tier,
                get_governor,
                should_lazy_embedder,
            )

            tier = current_serve_tier()
            cfg = get_governor().config(tier)
            lazy = should_lazy_embedder() or not cfg.load_embedder
        except Exception:  # noqa: BLE001
            lazy = os.environ.get("CTX_CE_LAZY_EMBEDDER", "").strip().lower() in {
                "1",
                "true",
                "yes",
            }
            cfg = None  # type: ignore[assignment]

        if lazy:
            embedder: Embedder | _LazyEmbedder = _LazyEmbedder(
                model,
                dim=col.meta.dim,
                cache_path=store.embed_cache,
            )
        else:
            embedder = get_embedder(
                model,
                dim=col.meta.dim,
                cache_path=store.embed_cache,
                eager=True,
            )
            try:
                if cfg is None or cfg.warmup_embedder:
                    embedder.embed_one("warmup", is_query=True)
            except Exception:
                pass
            _verify_gpu_provider(embedder)

        # Rebuild cards on force_reload so docstring/intent updates apply without re-embed.
        cards = ensure_cards(
            root,
            store.base,
            indexed_files=files,
            force=force_reload or not (store.base / "capability_cards.json").exists(),
        )
        eng = WarmSearchEngine(
            root=root,
            store=store,
            chunks=chunks,
            texts=texts,
            files=files,
            conductor=conductor,
            embedder=embedder,
            load_ms=(time.perf_counter() - t0) * 1000,
            loaded_at=time.time(),
            capability=CapabilityIndex(cards),
        )
        _ENGINES[key] = eng
        return eng


def drop_engine(root: Path, *, base_dir: Path | None = None) -> bool:
    """Drop one repository's cached WarmSearchEngine without touching others."""
    key = _engine_key(root.resolve(), base_dir)
    with _LOCK:
        return _ENGINES.pop(key, None) is not None


def clear_engines() -> None:
    with _LOCK:
        _ENGINES.clear()
