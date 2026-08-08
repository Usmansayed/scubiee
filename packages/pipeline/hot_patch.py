"""Cursor-style query-time freshness: disk text + BM25 hot-patch without re-embed."""

from __future__ import annotations

from pathlib import Path

from conductor.bm25_index import BM25Index
from pipeline.store import ChunkRecord


def read_lines(path: Path, start_line: int, end_line: int) -> str:
    """Read inclusive 1-based line range from disk (Cursor: vectors are pointers)."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    lo = max(0, int(start_line) - 1)
    hi = max(lo, int(end_line))
    return "\n".join(lines[lo:hi])


def disk_preview(
    root: Path,
    file: str,
    start_line: int,
    end_line: int,
    *,
    max_chars: int = 240,
) -> str:
    body = read_lines(root / file, start_line, end_line)
    return " ".join(body.split())[:max_chars]


def hot_patch_texts(
    root: Path,
    chunks: list[ChunkRecord],
    texts: list[str],
    dirty_files: list[str],
) -> tuple[list[str], list[int]]:
    """Overwrite in-memory chunk texts for dirty files from live disk.

    Dense vectors may still lag; BM25/graph lexical path sees fresh tokens immediately.
    """
    dirty = {f.replace("\\", "/") for f in dirty_files}
    if not dirty:
        return texts, []
    patched: list[str] = list(texts)
    touched: list[int] = []
    for c in chunks:
        f = c.file.replace("\\", "/")
        if f not in dirty:
            continue
        live = read_lines(root / f, c.start_line, c.end_line)
        if not live:
            continue
        if 0 <= c.id < len(patched):
            patched[c.id] = live
            touched.append(c.id)
    return patched, touched


def rebuild_bm25(texts: list[str]) -> BM25Index:
    return BM25Index(texts)
