"""Chunk derivation + metadata injection without a second AST parse.

Chunks are sliced from source using RepoIR symbol line anchors (from Graphify).
Metadata is prepended; chunk boundaries are unchanged by injection.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from metadata import ChunkMeta, build_chunk_meta
from repo_ir import RepoIR, Symbol


SEPARATOR = "--------------------------------"


@dataclass(frozen=True)
class CodeChunk:
    file: str
    start_line: int
    end_line: int
    content: str
    symbol: str | None = None


@dataclass(frozen=True)
class EnrichedChunk:
    file: str
    start_line: int
    end_line: int
    symbol: str | None
    metadata: ChunkMeta
    original: str
    enriched: str

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "symbol": self.symbol,
            "metadata": asdict(self.metadata),
            "original": self.original,
            "enriched": self.enriched,
            "token_delta_chars": len(self.enriched) - len(self.original),
        }


def _callable_symbols_for_file(ir: RepoIR, file_path: str) -> list[Symbol]:
    found = [
        s
        for s in ir.symbols.values()
        if s.file == file_path and s.kind in {"function", "class", "method"} and s.line
    ]
    # Dedupe by (name, line) preferring function kind already filtered
    by_key: dict[tuple[str, int], Symbol] = {}
    for s in found:
        key = (s.name, s.line or 0)
        by_key[key] = s
    return sorted(by_key.values(), key=lambda s: (s.line or 0, s.name))


def _read_lines(root: Path, file_path: str) -> list[str]:
    text = (root / file_path).read_text(encoding="utf-8")
    return text.splitlines(keepends=True)


def chunk_file_from_ir(ir: RepoIR, root: Path, file_path: str) -> list[CodeChunk]:
    """Slice one file into symbol-span chunks using RepoIR line anchors only."""
    lines = _read_lines(root, file_path)
    if not lines:
        return []

    callables = _callable_symbols_for_file(ir, file_path)
    if not callables:
        content = "".join(lines)
        return [
            CodeChunk(
                file=file_path,
                start_line=1,
                end_line=len(lines),
                content=content,
                symbol=None,
            )
        ]

    chunks: list[CodeChunk] = []
    # Optional preamble before first symbol
    first_line = callables[0].line or 1
    if first_line > 1:
        preamble = "".join(lines[0 : first_line - 1])
        if preamble.strip():
            chunks.append(
                CodeChunk(
                    file=file_path,
                    start_line=1,
                    end_line=first_line - 1,
                    content=preamble,
                    symbol=None,
                )
            )

    for i, sym in enumerate(callables):
        start = sym.line or 1
        if i + 1 < len(callables):
            end = (callables[i + 1].line or start) - 1
        else:
            end = len(lines)
        end = max(end, start)
        content = "".join(lines[start - 1 : end])
        chunks.append(
            CodeChunk(
                file=file_path,
                start_line=start,
                end_line=end,
                content=content,
                symbol=sym.name,
            )
        )
    return chunks


def chunk_repo_from_ir(ir: RepoIR, root: Path | None = None) -> list[CodeChunk]:
    root = Path(root or ir.root)
    chunks: list[CodeChunk] = []
    for file_path in sorted(ir.files):
        abs_path = root / file_path
        if not abs_path.is_file():
            continue
        chunks.extend(chunk_file_from_ir(ir, root, file_path))
    return chunks


def inject_metadata(chunk: CodeChunk, ir: RepoIR) -> EnrichedChunk:
    meta = build_chunk_meta(
        ir,
        chunk.file,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
    )
    enriched = meta.render() + chunk.content
    return EnrichedChunk(
        file=chunk.file,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        symbol=chunk.symbol,
        metadata=meta,
        original=chunk.content,
        enriched=enriched,
    )


def enrich_repo(ir: RepoIR, root: Path | None = None) -> list[EnrichedChunk]:
    return [inject_metadata(c, ir) for c in chunk_repo_from_ir(ir, root)]
