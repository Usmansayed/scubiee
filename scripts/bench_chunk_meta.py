"""Measure enrichment cost per chunk: indexed lookups vs the old inline scans.

Usage: python scripts/bench_chunk_meta.py [subdir]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))

from enrich import chunk_repo_from_ir  # noqa: E402
from graphify.extract import extract  # noqa: E402
from parse_harness.graphify_adapter import graphify_to_repo_ir  # noqa: E402
from metadata import ChunkMeta, _folder_name, _import_labels, _module_name  # noqa: E402
from metadata import _repo_name, build_chunk_meta  # noqa: E402
from repo_ir import FileIR, RepoIR  # noqa: E402


def naive_chunk_meta(ir: RepoIR, file_path: str, start_line, end_line) -> ChunkMeta:
    """The implementation as it stood before the index was introduced."""
    file_ir = ir.files.get(file_path) or FileIR(path=file_path)

    folder = _folder_name(file_path)
    siblings = sorted(
        p for p in ir.files if p != file_path and _folder_name(p) == folder
    )[:8]

    owned = {sid for sid, s in ir.symbols.items() if s.file == file_path}
    deps: set[str] = set()
    for edge in ir.edges:
        if edge.relation not in {"imports", "imports_from"}:
            continue
        if edge.target not in owned:
            continue
        src = ir.symbols.get(edge.source)
        if src and src.file and src.file != file_path:
            deps.add(src.file)

    names: list[str] = []
    for sym in ir.symbols.values():
        if sym.file != file_path or sym.kind not in {"function", "class", "method"}:
            continue
        if start_line is not None and sym.line is not None and sym.line < start_line:
            continue
        if end_line is not None and sym.line is not None and sym.line > end_line:
            continue
        if sym.name not in names:
            names.append(sym.name)
    if not names:
        names = list(file_ir.symbols)

    return ChunkMeta(
        repository=_repo_name(ir.root),
        module=_module_name(file_path),
        folder=folder,
        file=file_path,
        functions=tuple(sorted(names)),
        imports=tuple(_import_labels(ir, file_ir)),
        exports=tuple(sorted(set(file_ir.exports))),
        related_files=tuple(siblings),
        dependents=tuple(sorted(deps)[:8]),
    )


def main() -> int:
    if len(sys.argv) > 1:
        target = REPO / sys.argv[1]
        paths = sorted(p for p in target.rglob("*.py") if p.is_file())
        label = f"{target.name}/"
    else:
        # The set `scubiee init` actually indexes - honours ignores, so it will
        # not wander into .venv or the vendored model directories.
        from pipeline.paths import collect_index_paths

        paths = sorted(collect_index_paths(REPO))
        label = "the indexed set"
    print(f"extracting IR from {len(paths)} files ({label}) ...")

    raw = extract(paths, root=REPO)
    ir = graphify_to_repo_ir(raw, root=REPO, elapsed_ms=0.0, file_count=len(paths))
    chunks = chunk_repo_from_ir(ir, REPO)
    print(
        f"IR: {len(ir.files)} files, {len(ir.symbols)} symbols, "
        f"{len(ir.edges)} edges -> {len(chunks)} chunks\n"
    )

    t0 = time.perf_counter()
    for ch in chunks:
        naive_chunk_meta(ir, ch.file, ch.start_line, ch.end_line)
    old = time.perf_counter() - t0

    if hasattr(ir, "_chunk_meta_index"):
        delattr(ir, "_chunk_meta_index")
    t0 = time.perf_counter()
    for ch in chunks:
        build_chunk_meta(ir, ch.file, start_line=ch.start_line, end_line=ch.end_line)
    new = time.perf_counter() - t0

    print(f"  inline scans : {old:8.2f}s  ({old / len(chunks) * 1000:.3f} ms/chunk)")
    print(f"  indexed      : {new:8.2f}s  ({new / len(chunks) * 1000:.3f} ms/chunk)")
    print(f"  speedup      : {old / new:8.1f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
