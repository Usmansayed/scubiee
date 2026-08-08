"""On-disk pipeline store + FAISS VectorDatabase (collections per project)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pipeline.merkle import load_snapshot, save_snapshot
from pipeline.vectordb import FaissCollection, VectorDatabase, cwd_collection_name


def repo_key(root: Path) -> str:
    """Legacy path-hash key (migration / cleanup only). Prefer project_id."""
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]


@dataclass
class ChunkRecord:
    id: int
    file: str
    start_line: int
    end_line: int
    symbol: str | None
    text: str
    enriched: str


class PipelineStore:
    def __init__(
        self,
        root: Path,
        base_dir: Path | None = None,
        vdb: VectorDatabase | None = None,
        *,
        project_id: str | None = None,
        resolve: bool = True,
    ):
        self.root = root.resolve()
        self.project_id: str | None = project_id
        if base_dir is not None:
            self.base = Path(base_dir).resolve()
            self.base.mkdir(parents=True, exist_ok=True)
            if self.project_id is None:
                from pipeline.project_id import read_id_file

                self.project_id = read_id_file(self.root)
        elif resolve:
            from pipeline.project_id import resolve_project

            ref = resolve_project(self.root)
            self.project_id = ref.project_id
            self.base = ref.store_dir
        else:
            # Tests / callers that want path-hash without side effects
            home = Path.home() / ".context-engine"
            self.base = (home / "indexes" / repo_key(self.root)).resolve()
            self.base.mkdir(parents=True, exist_ok=True)

        self.merkle_path = self.base / "merkle.json"
        self.meta_path = self.base / "meta.json"
        self.chunks_path = self.base / "chunks.jsonl"
        self.graph_path = self.base / "graph_ir.json"
        self.embed_cache = self.base / "embed_cache.jsonl"
        self.vdb = vdb or VectorDatabase()

        meta = self.load_meta() if self.meta_path.exists() else {}
        if meta.get("collection"):
            self.collection_name = str(meta["collection"])
        elif self.project_id:
            from pipeline.project_id import collection_name_for_project

            self.collection_name = collection_name_for_project(self.root, self.project_id)
        else:
            self.collection_name = cwd_collection_name(self.root)

    def load_meta(self) -> dict[str, Any]:
        if not self.meta_path.exists():
            return {}
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def save_meta(self, meta: dict[str, Any]) -> None:
        if self.project_id and "project_id" not in meta:
            meta = {**meta, "project_id": self.project_id}
        self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def load_chunks(self) -> list[ChunkRecord]:
        if not self.chunks_path.exists():
            return []
        out: list[ChunkRecord] = []
        for line in self.chunks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            out.append(ChunkRecord(**row))
        return out

    def save_chunks(self, chunks: list[ChunkRecord]) -> None:
        with self.chunks_path.open("w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")

    def load_merkle(self) -> dict[str, str]:
        return load_snapshot(self.merkle_path)

    def load_mtimes(self) -> dict[str, float]:
        from pipeline.merkle import load_mtimes

        return load_mtimes(self.merkle_path)

    def save_merkle(self, file_hashes: dict[str, str]) -> None:
        save_snapshot(self.merkle_path, file_hashes, root=self.root)

    def get_collection(self) -> FaissCollection | None:
        if self.vdb.has_collection(self.collection_name):
            return self.vdb.get_collection(self.collection_name)
        return None

    def upsert_vectors(
        self,
        vectors,
        chunks: list[ChunkRecord],
        *,
        dim: int,
        bits: int = 8,
    ) -> FaissCollection:
        col = self.vdb.create_collection(
            self.collection_name,
            dim=dim,
            cwd=self.root,
            bits=bits,
            description=f"code chunks for {self.root}",
            overwrite=True,
        )
        payloads = [
            {
                "file": c.file,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "symbol": c.symbol,
                "chunk_id": c.id,
            }
            for c in chunks
        ]
        col.replace_all(vectors, [c.id for c in chunks], payloads)
        self.vdb.save_collection(col.name)
        return col
