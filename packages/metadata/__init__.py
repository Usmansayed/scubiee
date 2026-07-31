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


def _file_symbol_id(ir: RepoIR, file_path: str) -> str | None:
    for sid, sym in ir.symbols.items():
        if sym.kind == "file" and sym.file == file_path:
            return sid
    return None


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


def _related_siblings(ir: RepoIR, file_path: str, *, limit: int = 8) -> list[str]:
    folder = _folder_name(file_path)
    siblings = [
        p
        for p in ir.files
        if p != file_path and _folder_name(p) == folder
    ]
    return sorted(siblings)[:limit]


def _immediate_dependents(ir: RepoIR, file_path: str, *, limit: int = 8) -> list[str]:
    """Files that import this file or its symbols (one hop)."""
    file_sid = _file_symbol_id(ir, file_path)
    owned = {sid for sid, s in ir.symbols.items() if s.file == file_path}
    if file_sid:
        owned.add(file_sid)

    deps: set[str] = set()
    for edge in ir.edges:
        if edge.relation not in {"imports", "imports_from"}:
            continue
        if edge.target not in owned:
            continue
        src = ir.symbols.get(edge.source)
        if src and src.file and src.file != file_path:
            deps.add(src.file)
    return sorted(deps)[:limit]


def _functions_in_span(
    ir: RepoIR,
    file_path: str,
    start_line: int | None,
    end_line: int | None,
) -> list[str]:
    names: list[str] = []
    for sym in ir.symbols.values():
        if sym.file != file_path:
            continue
        if sym.kind not in {"function", "class", "method"}:
            continue
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
    return ChunkMeta(
        repository=_repo_name(ir.root),
        module=_module_name(file_path),
        folder=_folder_name(file_path),
        file=file_path,
        functions=tuple(_functions_in_span(ir, file_path, start_line, end_line)),
        imports=tuple(_import_labels(ir, file_ir)),
        exports=tuple(sorted(set(file_ir.exports))),
        related_files=tuple(_related_siblings(ir, file_path)),
        dependents=tuple(_immediate_dependents(ir, file_path)),
    )
