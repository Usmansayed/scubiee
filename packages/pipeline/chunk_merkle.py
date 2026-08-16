"""Chunk-level Merkle helpers used only after a file is marked dirty.

File hashes decide *which files* need work.  These digests decide *which
chunks inside those files* need a new embedding.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Iterable

from pipeline.store import ChunkRecord


def chunk_key(chunk: ChunkRecord) -> str:
    """Stable identity: symbols survive line shifts; anonymous chunks use range."""
    if chunk.symbol:
        return str(chunk.symbol)
    return f"@{chunk.start_line}:{chunk.end_line}"


def chunk_digest(chunk: ChunkRecord) -> str:
    """Hash the actual embedding input, not presentation line coordinates."""
    return hashlib.sha256(chunk.enriched.encode("utf-8", errors="replace")).hexdigest()


@dataclass(frozen=True)
class ChunkDiff:
    unchanged: set[str]
    changed: set[str]
    removed: set[str]


def diff_chunk_records(
    old: Iterable[ChunkRecord],
    new: Iterable[ChunkRecord],
) -> ChunkDiff:
    old_hashes = {chunk_key(chunk): chunk_digest(chunk) for chunk in old}
    new_hashes = {chunk_key(chunk): chunk_digest(chunk) for chunk in new}
    return ChunkDiff(
        unchanged={key for key in new_hashes if old_hashes.get(key) == new_hashes[key]},
        changed={key for key in new_hashes if old_hashes.get(key) != new_hashes[key]},
        removed=set(old_hashes) - set(new_hashes),
    )
