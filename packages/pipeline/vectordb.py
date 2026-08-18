"""FAISS vector database with TurboQuant compression and named collections.

Layout under ``~/.context-engine/vectordb/`` (override with CTX_VECTORDB_ROOT)::

    catalog.json
    collections/
      <safe_name>/
        meta.json          # name, cwd, dim, bits, ntotal, created_at
        faiss.index        # FAISS IndexIDMap2(IndexFlatIP)
        turboquant.npz     # compressed embedding codes
        ids.npy
        payloads.jsonl     # optional per-id metadata (file, chunk, …)

Collection names are usually derived from the working directory hash so each
repo gets an isolated vector space (like Milvus/Zilliz collections).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from pipeline.turbo_quant import CompressedEmbeddingStore

DEFAULT_ROOT_ENV = "CTX_VECTORDB_ROOT"


def default_vectordb_root() -> Path:
    return Path(
        os.environ.get(DEFAULT_ROOT_ENV, str(Path.home() / ".context-engine" / "vectordb"))
    )


def cwd_collection_name(cwd: Path | str, project_id: str | None = None) -> str:
    """Stable collection id from project_id (preferred) or absolute path hash."""
    if project_id:
        from pipeline.project_id import collection_name_for_project

        return collection_name_for_project(Path(cwd), project_id)
    key = str(Path(cwd).resolve())
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    base = Path(key).name
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", base).strip("_").lower() or "repo"
    return f"{safe}_{digest}"


def _safe_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name).strip("._")
    if not s or s in {".", ".."}:
        raise ValueError(f"invalid collection name: {name!r}")
    return s


@dataclass
class CollectionMeta:
    name: str
    cwd: str
    dim: int
    bits: int = 4
    seed: int = 42
    ntotal: int = 0
    metric: str = "ip"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    description: str = ""
    dead_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CollectionMeta":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class FaissCollection:
    """One FAISS collection: TurboQuant storage + IndexIDMap2 search."""

    def __init__(self, path: Path, meta: CollectionMeta):
        self.path = path
        self.meta = meta
        self.compressed = CompressedEmbeddingStore(
            dim=meta.dim, bits=meta.bits, seed=meta.seed
        )
        self.index = self._new_index()
        self.ids: list[int] = []
        self.payloads: dict[int, dict[str, Any]] = {}

    def _new_index(self) -> faiss.IndexIDMap2:
        return faiss.IndexIDMap2(faiss.IndexFlatIP(self.meta.dim))

    @property
    def name(self) -> str:
        return self.meta.name

    @property
    def ntotal(self) -> int:
        return int(self.index.ntotal)

    @property
    def dead_count(self) -> int:
        return len(self.meta.dead_ids)

    @property
    def live_count(self) -> int:
        return len(self.ids) - self.dead_count

    def _rebuild_faiss_from_compressed(self) -> None:
        self.index = self._new_index()
        dead = set(self.meta.dead_ids)
        live_rows = [row for row, vector_id in enumerate(self.ids) if vector_id not in dead]
        if not live_rows:
            return
        all_vectors = self.compressed.to_float32()
        if all_vectors.shape[0] != len(self.ids):
            raise RuntimeError("compressed rows != ids")
        mat = all_vectors[live_rows].copy()
        live_ids = [self.ids[row] for row in live_rows]
        faiss.normalize_L2(mat)
        self.index.add_with_ids(mat, np.asarray(live_ids, dtype=np.int64))

    def add(
        self,
        vectors: np.ndarray,
        ids: list[int] | np.ndarray,
        payloads: list[dict[str, Any]] | None = None,
    ) -> int:
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        id_list = [int(i) for i in ids]
        if vectors.shape[0] != len(id_list):
            raise ValueError("vectors/ids length mismatch")
        if vectors.shape[1] != self.meta.dim:
            raise ValueError(f"dim mismatch: got {vectors.shape[1]} expected {self.meta.dim}")
        if payloads is not None and len(payloads) != len(id_list):
            raise ValueError("payloads/ids length mismatch")

        # Remove existing ids first (upsert semantics)
        existing = [i for i in id_list if i in self.ids]
        if existing:
            self.delete(existing)
            self.compact()

        self.compressed.add(vectors)
        self.ids.extend(id_list)
        if payloads:
            for i, p in zip(id_list, payloads, strict=True):
                self.payloads[i] = dict(p)
        else:
            for i in id_list:
                self.payloads.setdefault(i, {})

        start = len(self.ids) - len(id_list)
        mat = self.compressed.to_float32()[start:].copy()
        faiss.normalize_L2(mat)
        self.index.add_with_ids(mat, np.asarray(id_list, dtype=np.int64))
        self.meta.ntotal = int(self.index.ntotal)
        self.meta.updated_at = time.time()
        return len(id_list)

    def replace_all(
        self,
        vectors: np.ndarray,
        ids: list[int],
        payloads: list[dict[str, Any]] | None = None,
    ) -> int:
        self.compressed = CompressedEmbeddingStore(
            dim=self.meta.dim, bits=self.meta.bits, seed=self.meta.seed
        )
        self.ids = []
        self.payloads = {}
        self.index = self._new_index()
        self.meta.dead_ids = []
        if len(ids) == 0:
            self.meta.ntotal = 0
            self.meta.updated_at = time.time()
            return 0
        return self.add(vectors, ids, payloads)

    def delete(self, ids: list[int]) -> int:
        """Logically delete vectors without assuming FAISS releases OS memory."""
        drop = set(int(i) for i in ids)
        if not drop:
            return 0
        already_dead = set(self.meta.dead_ids)
        removed = sorted(drop.intersection(self.ids) - already_dead)
        if not removed:
            return 0
        self.index.remove_ids(np.asarray(removed, dtype=np.int64))
        for vector_id in removed:
            self.payloads.pop(vector_id, None)
        self.meta.dead_ids = sorted(already_dead.union(removed))
        self.meta.ntotal = int(self.index.ntotal)
        self.meta.updated_at = time.time()
        return len(removed)

    def compact(self) -> int:
        """Rebuild all vector artifacts from live rows, preserving vector IDs."""
        dead = set(self.meta.dead_ids)
        if not dead:
            self._rebuild_faiss_from_compressed()
            self.meta.ntotal = int(self.index.ntotal)
            self.meta.updated_at = time.time()
            return 0
        keep_idx = [row for row, vector_id in enumerate(self.ids) if vector_id not in dead]
        old_dead_count = len(dead)
        if keep_idx:
            mat = self.compressed.to_float32()[keep_idx].copy()
            new_ids = [self.ids[row] for row in keep_idx]
            new_payloads = [self.payloads.get(vector_id, {}) for vector_id in new_ids]
        else:
            mat = np.zeros((0, self.meta.dim), dtype=np.float32)
            new_ids = []
            new_payloads = []
        self.compressed = CompressedEmbeddingStore(
            dim=self.meta.dim, bits=self.meta.bits, seed=self.meta.seed
        )
        self.ids = []
        self.payloads = {}
        self.index = self._new_index()
        self.meta.dead_ids = []
        if new_ids:
            self.add(mat, new_ids, new_payloads)
        else:
            self.meta.ntotal = 0
            self.meta.updated_at = time.time()
        return old_dead_count

    def search(
        self, query: np.ndarray, top_k: int = 10
    ) -> list[tuple[int, float, dict[str, Any]]]:
        q = np.asarray(query, dtype=np.float32).reshape(1, -1).copy()
        if q.shape[1] != self.meta.dim:
            raise ValueError(f"query dim {q.shape[1]} != collection dim {self.meta.dim}")
        faiss.normalize_L2(q)
        if self.index.ntotal == 0:
            return []
        k = min(top_k, self.index.ntotal)
        scores, labels = self.index.search(q, k)
        out: list[tuple[int, float, dict[str, Any]]] = []
        for score, lab in zip(scores[0], labels[0], strict=False):
            vid = int(lab)
            if vid < 0:
                continue
            out.append((vid, float(score), dict(self.payloads.get(vid, {}))))
        return out

    def get(self, ids: list[int]) -> list[dict[str, Any]]:
        return [{"id": i, "payload": self.payloads.get(int(i), {})} for i in ids]

    def save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        self.meta.ntotal = int(self.index.ntotal)
        self.meta.updated_at = time.time()
        (self.path / "meta.json").write_text(
            json.dumps(self.meta.to_dict(), indent=2), encoding="utf-8"
        )
        self.compressed.save(self.path / "turboquant.npz")
        faiss.write_index(self.index, str(self.path / "faiss.index"))
        np.save(self.path / "ids.npy", np.asarray(self.ids, dtype=np.int64))
        dead = set(self.meta.dead_ids)
        with (self.path / "payloads.jsonl").open("w", encoding="utf-8") as f:
            for vid in self.ids:
                if vid in dead:
                    continue
                f.write(
                    json.dumps({"id": vid, "payload": self.payloads.get(vid, {})})
                    + "\n"
                )

    @classmethod
    def load(cls, path: Path) -> "FaissCollection":
        meta = CollectionMeta.from_dict(
            json.loads((path / "meta.json").read_text(encoding="utf-8"))
        )
        col = cls(path, meta)
        col.compressed = CompressedEmbeddingStore.load(path / "turboquant.npz")
        col.ids = [int(x) for x in np.load(path / "ids.npy").tolist()]
        payloads_path = path / "payloads.jsonl"
        if payloads_path.exists():
            for line in payloads_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                col.payloads[int(row["id"])] = dict(row.get("payload") or {})
        index_path = path / "faiss.index"
        if index_path.exists() and col.ids:
            col.index = faiss.read_index(str(index_path))
            # Integrity: the serialized index contains live rows only.
            if int(col.index.ntotal) != col.live_count:
                col._rebuild_faiss_from_compressed()
        else:
            col._rebuild_faiss_from_compressed()
        col.meta.ntotal = int(col.index.ntotal)
        return col

    def stats(self) -> dict[str, Any]:
        s = self.compressed.memory_stats()
        s.update(
            {
                "name": self.meta.name,
                "cwd": self.meta.cwd,
                "dim": self.meta.dim,
                "faiss_ntotal": int(self.index.ntotal),
                "live_vectors": self.live_count,
                "dead_vectors": self.dead_count,
                "payloads": len(self.payloads),
                "path": str(self.path),
                "metric": self.meta.metric,
            }
        )
        return s


class VectorDatabase:
    """Multi-collection FAISS + TurboQuant manager (cwd-aware)."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root or default_vectordb_root()).resolve()
        self.collections_dir = self.root / "collections"
        self.catalog_path = self.root / "catalog.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.collections_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, FaissCollection] = {}
        self._ensure_catalog()

    def _ensure_catalog(self) -> None:
        if not self.catalog_path.exists():
            self._write_catalog({"collections": []})

    def _read_catalog(self) -> dict[str, Any]:
        return json.loads(self.catalog_path.read_text(encoding="utf-8"))

    def _write_catalog(self, data: dict[str, Any]) -> None:
        self.catalog_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _collection_path(self, name: str) -> Path:
        return self.collections_dir / _safe_name(name)

    def list_collections(self) -> list[dict[str, Any]]:
        cat = self._read_catalog()
        return list(cat.get("collections") or [])

    def has_collection(self, name: str) -> bool:
        return self._collection_path(name).joinpath("meta.json").exists()

    def create_collection(
        self,
        name: str,
        dim: int,
        *,
        cwd: Path | str | None = None,
        bits: int = 4,
        seed: int = 42,
        description: str = "",
        overwrite: bool = False,
    ) -> FaissCollection:
        safe = _safe_name(name)
        path = self._collection_path(safe)
        if path.exists() and not overwrite:
            if self.has_collection(safe):
                return self.get_collection(safe)
        if overwrite and path.exists():
            self.drop_collection(safe)

        cwd_s = str(Path(cwd).resolve()) if cwd else ""
        meta = CollectionMeta(
            name=safe,
            cwd=cwd_s,
            dim=int(dim),
            bits=int(bits),
            seed=int(seed),
            description=description,
        )
        col = FaissCollection(path, meta)
        col.save()
        self._register(meta)
        self._cache[safe] = col
        return col

    def _register(self, meta: CollectionMeta) -> None:
        cat = self._read_catalog()
        cols = [c for c in cat.get("collections") or [] if c.get("name") != meta.name]
        cols.append(
            {
                "name": meta.name,
                "cwd": meta.cwd,
                "dim": meta.dim,
                "bits": meta.bits,
                "ntotal": meta.ntotal,
                "updated_at": meta.updated_at,
            }
        )
        cat["collections"] = cols
        self._write_catalog(cat)

    def get_collection(self, name: str) -> FaissCollection:
        safe = _safe_name(name)
        if safe in self._cache:
            return self._cache[safe]
        path = self._collection_path(safe)
        if not (path / "meta.json").exists():
            raise KeyError(f"collection not found: {name}")
        col = FaissCollection.load(path)
        self._cache[safe] = col
        return col

    def get_or_create_for_cwd(
        self,
        cwd: Path | str,
        dim: int,
        *,
        bits: int = 4,
        name: str | None = None,
    ) -> FaissCollection:
        col_name = name or cwd_collection_name(cwd)
        if self.has_collection(col_name):
            col = self.get_collection(col_name)
            if col.meta.dim != dim:
                raise ValueError(
                    f"collection {col_name} dim={col.meta.dim} != requested {dim}"
                )
            return col
        return self.create_collection(col_name, dim, cwd=cwd, bits=bits)

    def drop_collection(self, name: str) -> None:
        safe = _safe_name(name)
        self._cache.pop(safe, None)
        path = self._collection_path(safe)
        if path.exists():
            import shutil

            shutil.rmtree(path)
        cat = self._read_catalog()
        cat["collections"] = [
            c for c in cat.get("collections") or [] if c.get("name") != safe
        ]
        self._write_catalog(cat)

    def find_by_cwd(self, cwd: Path | str) -> FaissCollection | None:
        target = str(Path(cwd).resolve())
        for entry in self.list_collections():
            if entry.get("cwd") == target:
                return self.get_collection(entry["name"])
        # fallback by naming convention
        guess = cwd_collection_name(cwd)
        if self.has_collection(guess):
            return self.get_collection(guess)
        return None

    def save_collection(self, name: str) -> None:
        col = self.get_collection(name)
        col.save()
        self._register(col.meta)
