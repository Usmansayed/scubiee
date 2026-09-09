"""Lightweight graph-derived metadata for chunk enrichment.

All fields come from RepoIR (one Graphify parse). No LLM. No multi-hop traversal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repo_ir import FileIR, RepoIR, Symbol


@dataclass(frozen=True)
class ChunkMeta:
    repository: str
    module: str
    folder: str
    file: str
    functions: tuple[str, ...]
    imports: tuple[str, ...]
    exports: tuple[str, ...]
    related_files: tuple[str, ...]
    dependents: tuple[str, ...]

    def render(self) -> str:
        lines = [
            f"Repository: {self.repository}",
            f"Module: {self.module}",
            f"Folder: {self.folder}",
            f"File: {self.file}",
            "",
            "Functions:",
        ]
        if self.functions:
            lines.extend(f"- {name}" for name in self.functions)
        else:
            lines.append("- (none)")

        lines.extend(["", "Imports:"])
        if self.imports:
            lines.extend(f"- {name}" for name in self.imports)
        else:
            lines.append("- (none)")

        lines.extend(["", "Exports:"])
        if self.exports:
            lines.extend(f"- {name}" for name in self.exports)
        else:
            lines.append("- (none)")

        lines.extend(["", "Graph Context:", f"- Parent Folder: {self.folder or '.'}/"])
        if self.related_files:
            lines.append("- Related Files:")
            lines.extend(f"    - {p}" for p in self.related_files)
        else:
            lines.append("- Related Files: (none)")

        if self.dependents:
            lines.append("- Immediate Dependents:")
            lines.extend(f"    - {p}" for p in self.dependents)

        lines.extend(["", "--------------------------------", ""])
        return "\n".join(lines)


def _repo_name(root: str | Path) -> str:
    return Path(root).name or str(root)


def _module_name(file_path: str) -> str:
    parts = Path(file_path).parts
    if len(parts) >= 2:
        return parts[0]
    stem = Path(file_path).stem
    return stem or "."


def _folder_name(file_path: str) -> str:
    parent = Path(file_path).parent.as_posix()
    return "" if parent == "." else parent


_CALLABLE_KINDS = frozenset({"function", "class", "method"})
_IMPORT_RELATIONS = frozenset({"imports", "imports_from"})
_INDEX_ATTR = "_chunk_meta_index"


@dataclass(frozen=True)
class _IRIndex:
    """Per-file lookups derived from a single pass over the IR.

    ``build_chunk_meta`` is called once per chunk. Resolving siblings, dependents
    and callables inline meant every chunk walked ``ir.files``, ``ir.edges`` and
    ``ir.symbols`` in full, so a whole-repo index cost
    chunks x (files + symbols + edges).
    """

    fingerprint: tuple[int, int, int]
    folder_files: dict[str, tuple[str, ...]]
    callables: dict[str, tuple[Symbol, ...]]
    dependents: dict[str, tuple[str, ...]]


def _fingerprint(ir: RepoIR) -> tuple[int, int, int]:
    return (len(ir.files), len(ir.symbols), len(ir.edges))


def _build_ir_index(ir: RepoIR) -> _IRIndex:
    folders: dict[str, list[str]] = {}
    for path in ir.files:
        folders.setdefault(_folder_name(path), []).append(path)

    callables: dict[str, list[Symbol]] = {}
    for sym in ir.symbols.values():
        if sym.kind in _CALLABLE_KINDS:
            callables.setdefault(sym.file, []).append(sym)

    # An edge into any symbol owned by a file makes the edge's source file a
    # dependent of it, which is what the per-file ``owned`` set used to express.
    dependents: dict[str, set[str]] = {}
    for edge in ir.edges:
        if edge.relation not in _IMPORT_RELATIONS:
            continue
        target = ir.symbols.get(edge.target)
        if target is None:
            continue
        source = ir.symbols.get(edge.source)
        if source is None or not source.file or source.file == target.file:
            continue
        dependents.setdefault(target.file, set()).add(source.file)

    return _IRIndex(
        fingerprint=_fingerprint(ir),
        folder_files={k: tuple(sorted(v)) for k, v in folders.items()},
        callables={k: tuple(v) for k, v in callables.items()},
        dependents={k: tuple(sorted(v)) for k, v in dependents.items()},
    )


def _ir_index(ir: RepoIR) -> _IRIndex:
    cached = getattr(ir, _INDEX_ATTR, None)
    if isinstance(cached, _IRIndex) and cached.fingerprint == _fingerprint(ir):
        return cached
    index = _build_ir_index(ir)
    try:
        setattr(ir, _INDEX_ATTR, index)
    except (AttributeError, TypeError):
        pass  # __slots__ or frozen IR: correctness never depends on the cache
    return index


def _import_labels(ir: RepoIR, file_ir: FileIR) -> list[str]:
    """Prefer symbol imports; also keep direct module paths."""
    labels: list[str] = []
    for item in file_ir.imports:
        if item.endswith((".ts", ".tsx", ".js", ".jsx", ".py")) or "/" in item:
            # module path — keep basename for brevity unless already short
            labels.append(item)
        else:
            labels.append(item)
    # Stable unique
    return sorted(set(labels))


def _related_siblings(index: _IRIndex, file_path: str, *, limit: int = 8) -> list[str]:
    folder = index.folder_files.get(_folder_name(file_path), ())
    return [p for p in folder if p != file_path][:limit]


def _immediate_dependents(
    index: _IRIndex, file_path: str, *, limit: int = 8
) -> list[str]:
    """Files that import this file or its symbols (one hop)."""
    return list(index.dependents.get(file_path, ())[:limit])


def _functions_in_span(
    ir: RepoIR,
    index: _IRIndex,
    file_path: str,
    start_line: int | None,
    end_line: int | None,
) -> list[str]:
    names: list[str] = []
    for sym in index.callables.get(file_path, ()):
        if start_line is not None and sym.line is not None and sym.line < start_line:
            continue
        if end_line is not None and sym.line is not None and sym.line > end_line:
            continue
        if sym.name not in names:
            names.append(sym.name)
    # Fallback: all file callables if span filter empty but file has symbols
    if not names:
        file_ir = ir.files.get(file_path)
        if file_ir:
            names = list(file_ir.symbols)
    return sorted(names)


def build_chunk_meta(
    ir: RepoIR,
    file_path: str,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
) -> ChunkMeta:
    file_ir = ir.files.get(file_path) or FileIR(path=file_path)
    index = _ir_index(ir)
    return ChunkMeta(
        repository=_repo_name(ir.root),
        module=_module_name(file_path),
        folder=_folder_name(file_path),
        file=file_path,
        functions=tuple(
            _functions_in_span(ir, index, file_path, start_line, end_line)
        ),
        imports=tuple(_import_labels(ir, file_ir)),
        exports=tuple(sorted(set(file_ir.exports))),
        related_files=tuple(_related_siblings(index, file_path)),
        dependents=tuple(_immediate_dependents(index, file_path)),
    )
