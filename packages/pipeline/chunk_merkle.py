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


# File-wide summary lines repeated in every chunk of a file. Adding one import or
# function rewrites them everywhere, which re-embedded the whole file per edit.
_FILE_WIDE_PREFIXES = ("Imports:", "Exports:", "Functions:", "Dependents:")


# Prefix of the raw chunk text that is hashed. Every text cap the indexer has
# used (compress 512, plain 1200) is at least this long, so chunks stored by an
# older build hash the same as a fresh re-parse of unchanged code.
_DIGEST_TEXT_CHARS = 512


def chunk_digest(chunk: ChunkRecord) -> str:
    """Hash the chunk's own source text; fall back to its own enriched lines.

    Issue 5: hashing ``enriched`` (even without the file-wide lines) was not
    stable. The body is capped *after* the file-wide Imports/Exports/Functions
    lines are prepended, so adding one function moved where every chunk's own
    code was cut off, and an enrichment-format change between builds did the
    same once for every stored chunk. Measured on this repo: 47/114 chunks of
    an unedited mcp_locate.py and 55/95 of cli_ui.py read as changed. The raw
    ``text`` does not depend on the rest of the file.
    """
    raw = (chunk.text or "").lstrip("\ufeff")
    if raw.strip():
        own_text = raw[:_DIGEST_TEXT_CHARS].rstrip()
        return hashlib.sha256(own_text.encode("utf-8", errors="replace")).hexdigest()
    own = "\n".join(
        line
        for line in (chunk.enriched or "").splitlines()
        if not line.startswith(_FILE_WIDE_PREFIXES)
    )
    return hashlib.sha256(own.encode("utf-8", errors="replace")).hexdigest()


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
