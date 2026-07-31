"""Production retrieval engine: pure Graphify vs D_rerank side-by-side.

Loads the frontend-mcp corpus once, then serves search/compare for API + MCP.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from conductor.architectures import MultiArchConductor
from conductor.bm25_index import BM25Index
from conductor.conductor import ConductorConfig, Hit
from conductor.dense_index import DenseIndex, load_cache, text_key
from conductor.graphify_retriever import ChunkSpan, GraphifyChunkRetriever, load_or_build_graph
from enrich import chunk_repo_from_ir
from graphify.extract import collect_files, extract
from parse_harness.graphify_adapter import graphify_to_repo_ir

Mode = Literal["graphify", "d_rerank", "d_floor", "r_gated", "both", "both_rg"]

DEFAULT_REPO = Path(os.environ.get("CONDUCTOR_REPO", str(ROOT / "testdata" / "frontend-mcp")))
DEFAULT_EMBED_CACHE = Path(
    os.environ.get("CONDUCTOR_EMBED_CACHE", str(ROOT / "out" / "embed_cache_frontend_mcp_nomic768.jsonl"))
)
DEFAULT_GRAPH = Path(
    os.environ.get("CONDUCTOR_GRAPH", str(DEFAULT_REPO / "graphify-out" / "graph.json"))
)
OLLAMA_EMBED = os.environ.get("CONDUCTOR_OLLAMA_EMBED", "http://localhost:11434/api/embed")
EMBED_MODEL = os.environ.get("CONDUCTOR_EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = int(os.environ.get("CONDUCTOR_EMBED_DIM", "768"))


@dataclass
class SearchHit:
    rank: int
    file: str
    score: float
    source: str
    chunk_id: int
    graph: float = 0.0
    bm25: float = 0.0
    dense: float = 0.0
    preview: str = ""


def _collect_py_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for name in ("src", "packages", "execution_layer", "coordination_layer"):
        d = root / name
        if d.exists():
            paths.extend(collect_files(d, root=root))
    out = []
    for p in paths:
        s = p.as_posix().lower()
        if p.suffix != ".py":
            continue
        if any(x in s for x in ["/vendor/", "node_modules", "/dist/", "__pycache__"]):
            continue
        out.append(p)
    return out


def _unique_file_hits(hits: list[Hit], texts: list[str], top_k: int) -> list[SearchHit]:
    out: list[SearchHit] = []
    seen: set[str] = set()
    for h in hits:
        f = h.file.replace("\\", "/")
        if f in seen:
            continue
        seen.add(f)
        preview = ""
        if 0 <= h.chunk_id < len(texts):
            preview = " ".join(texts[h.chunk_id].split())[:240]
        out.append(
            SearchHit(
                rank=len(out) + 1,
                file=f,
                score=float(h.score),
                source=h.source or "",
                chunk_id=int(h.chunk_id),
                graph=float(h.graph),
                bm25=float(h.bm25),
                dense=float(h.dense),
                preview=preview,
            )
        )
        if len(out) >= top_k:
            break
    return out


class ConductorEngine:
    """Thread-safe lazy-loaded retrieval stack."""

    def __init__(
        self,
        repo: Path = DEFAULT_REPO,
        embed_cache: Path = DEFAULT_EMBED_CACHE,
        graph_json: Path = DEFAULT_GRAPH,
    ) -> None:
        self.repo = repo.resolve()
        self.embed_cache = embed_cache
        self.graph_json = graph_json
        self._lock = threading.Lock()
        self._ready = False
        self._cond: MultiArchConductor | None = None
        self._texts: list[str] = []
        self._cache: dict[str, list[float]] = {}
        self._load_ms = 0.0
        self._n_chunks = 0
        self._n_files = 0

    @property
    def ready(self) -> bool:
        return self._ready

    def ensure_loaded(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            t0 = time.perf_counter()
            root = self.repo
            paths = _collect_py_paths(root)
            extraction = extract(paths, root=root, cache_root=root, parallel=True)
            ir = graphify_to_repo_ir(
                extraction,
                root=root,
                elapsed_ms=(time.perf_counter() - t0) * 1000,
                file_count=len(paths),
            )
            chunks = chunk_repo_from_ir(ir, root)
            texts = [c.content for c in chunks]
            files = [c.file.replace("\\", "/") for c in chunks]
            G = load_or_build_graph(extraction, root, self.graph_json)
            spans = [
                ChunkSpan(index=i, file=files[i], start_line=c.start_line, end_line=c.end_line)
                for i, c in enumerate(chunks)
            ]
            cache = load_cache(self.embed_cache)
            cond = MultiArchConductor(
                files=files,
                bm25=BM25Index(texts),
                dense=DenseIndex.from_texts_and_cache(texts, cache),
                graph=GraphifyChunkRetriever(G, spans, depth=2),
                config=ConductorConfig(),
            )
            self._cond = cond
            self._texts = texts
            self._cache = cache
            self._n_chunks = len(chunks)
            self._n_files = len(set(files))
            self._load_ms = (time.perf_counter() - t0) * 1000
            self._ready = True

    def _embed(self, query: str) -> np.ndarray:
        k = text_key(query)
        if k in self._cache:
            return np.asarray(self._cache[k], dtype=np.float32)
        resp = requests.post(
            OLLAMA_EMBED, json={"model": EMBED_MODEL, "input": [query]}, timeout=120
        )
        resp.raise_for_status()
        emb = resp.json()["embeddings"][0]
        if len(emb) != EMBED_DIM:
            raise RuntimeError(f"bad embed dim {len(emb)} expected {EMBED_DIM}")
        self.embed_cache.parent.mkdir(parents=True, exist_ok=True)
        with self.embed_cache.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": k, "embedding": emb}) + "\n")
        self._cache[k] = emb
        return np.asarray(emb, dtype=np.float32)

    def status(self) -> dict[str, Any]:
        return {
            "ready": self._ready,
            "repo": str(self.repo),
            "n_chunks": self._n_chunks,
            "n_files": self._n_files,
            "load_ms": round(self._load_ms, 1),
            "embed_model": EMBED_MODEL,
            "modes": ["graphify", "d_rerank", "d_floor", "r_gated", "both", "both_rg"],
            "production_default": "d_rerank",
            "final_architecture": "D_rerank",
            "soft_experimental": "r_gated",
            "note": "FINAL: ship D_rerank. r_gated rejected for default after OpenCode soft A/B (lexical noise).",
            "compare_endpoints": {
                "both": "graphify vs d_rerank",
                "both_rg": "d_rerank vs r_gated (research only)",
            },
        }

    def search(self, query: str, mode: Mode = "both", top_k: int = 8) -> dict[str, Any]:
        self.ensure_loaded()
        assert self._cond is not None
        top_k = max(1, min(int(top_k), 30))
        t0 = time.perf_counter()
        need_embed = mode in ("d_rerank", "d_floor", "r_gated", "both", "both_rg")
        qvec = self._embed(query) if need_embed else None
        results: dict[str, Any] = {"query": query, "top_k": top_k, "modes": {}}

        if mode in ("graphify", "both"):
            t1 = time.perf_counter()
            hits = self._cond.retrieve_graphify(query, top_k=top_k * 3)
            results["modes"]["graphify"] = {
                "latency_ms": round((time.perf_counter() - t1) * 1000, 2),
                "hits": [asdict(h) for h in _unique_file_hits(hits, self._texts, top_k)],
            }

        if mode in ("d_rerank", "both", "both_rg"):
            assert qvec is not None
            t1 = time.perf_counter()
            hits = self._cond.retrieve_D_rerank(query, qvec, top_k=top_k * 3)
            results["modes"]["d_rerank"] = {
                "latency_ms": round((time.perf_counter() - t1) * 1000, 2),
                "hits": [asdict(h) for h in _unique_file_hits(hits, self._texts, top_k)],
            }

        if mode == "d_floor":
            assert qvec is not None
            t1 = time.perf_counter()
            hits = self._cond.retrieve_D_floor(query, qvec, top_k=top_k * 3)
            results["modes"]["d_floor"] = {
                "latency_ms": round((time.perf_counter() - t1) * 1000, 2),
                "hits": [asdict(h) for h in _unique_file_hits(hits, self._texts, top_k)],
                "note": "always-on floor — soft ACCEPT; consistency REJECT",
            }

        if mode in ("r_gated", "both_rg"):
            assert qvec is not None
            t1 = time.perf_counter()
            hits = self._cond.retrieve_R_gated_floor(query, qvec, top_k=top_k * 3)
            results["modes"]["r_gated"] = {
                "latency_ms": round((time.perf_counter() - t1) * 1000, 2),
                "hits": [asdict(h) for h in _unique_file_hits(hits, self._texts, top_k)],
                "note": "R&D#5 router — soft ACCEPT; consistency REJECT vs D — experimental",
            }

        if mode == "both":
            g_files = [h["file"] for h in results["modes"]["graphify"]["hits"]]
            d_files = [h["file"] for h in results["modes"]["d_rerank"]["hits"]]
            results["agreement"] = {
                "same_top1": bool(g_files and d_files and g_files[0] == d_files[0]),
                "jaccard_top_k": round(
                    len(set(g_files) & set(d_files)) / max(len(set(g_files) | set(d_files)), 1), 4
                ),
                "graphify_only": [f for f in g_files if f not in set(d_files)],
                "d_rerank_only": [f for f in d_files if f not in set(g_files)],
            }

        if mode == "both_rg":
            d_files = [h["file"] for h in results["modes"]["d_rerank"]["hits"]]
            r_files = [h["file"] for h in results["modes"]["r_gated"]["hits"]]
            results["agreement"] = {
                "pair": "d_rerank_vs_r_gated",
                "same_top1": bool(d_files and r_files and d_files[0] == r_files[0]),
                "jaccard_top_k": round(
                    len(set(d_files) & set(r_files)) / max(len(set(d_files) | set(r_files)), 1), 4
                ),
                "d_rerank_only": [f for f in d_files if f not in set(r_files)],
                "r_gated_only": [f for f in r_files if f not in set(d_files)],
            }

        results["total_latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return results


_ENGINE: ConductorEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_engine() -> ConductorEngine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = ConductorEngine()
        return _ENGINE
