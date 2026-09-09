"""``build_chunk_meta`` runs once per chunk, so it must not scan the whole IR.

Enrichment used to rebuild every lookup inline: ``_related_siblings`` walked
``ir.files`` and built a ``Path`` per entry, ``_immediate_dependents`` walked
``ir.edges``, and ``_functions_in_span`` walked ``ir.symbols``. Cost was
chunks x (files + symbols + edges), which is quadratic on a full index and made
``scubiee init`` spend most of its time in metadata rather than embedding.
"""

from __future__ import annotations

from pathlib import Path

import metadata
from metadata import build_chunk_meta
from repo_ir import Edge, FileIR, RepoIR, Symbol


class _CountingList(list):
    """A list that records how many times something iterated it."""

    def __init__(self, *args):
        super().__init__(*args)
        self.scans = 0

    def __iter__(self):
        self.scans += 1
        return super().__iter__()


def _synthetic_ir(*, folders: int = 6, files_per_folder: int = 5) -> RepoIR:
    files: dict[str, FileIR] = {}
    symbols: dict[str, Symbol] = {}
    edges: list[Edge] = []

    paths = [
        f"pkg{f}/mod{i}.py" for f in range(folders) for i in range(files_per_folder)
    ]
    for path in paths:
        files[path] = FileIR(
            path=path,
            symbols=[f"{path}::fallback"],
            imports=[f"{path}-dep.py", "os"],
            exports=[f"{path}::exported"],
        )
        symbols[f"{path}::file"] = Symbol(
            id=f"{path}::file", name=path, kind="file", file=path
        )
        for line in (5, 25, 45):
            sid = f"{path}::fn{line}"
            symbols[sid] = Symbol(
                id=sid, name=f"fn{line}", kind="function", file=path, line=line
            )

    # Each file imports the one before it, so dependents are non-empty.
    for prev, cur in zip(paths, paths[1:]):
        edges.append(
            Edge(source=f"{cur}::fn5", target=f"{prev}::file", relation="imports")
        )
        edges.append(
            Edge(
                source=f"{cur}::fn25",
                target=f"{prev}::fn5",
                relation="imports_from",
            )
        )
    # Noise that must be ignored.
    edges.append(
        Edge(source=f"{paths[0]}::fn5", target=f"{paths[1]}::file", relation="calls")
    )

    return RepoIR(
        root="/repo/demo", parser="test", files=files, symbols=symbols, edges=edges
    )


def _reference_meta(ir: RepoIR, file_path: str, start_line, end_line) -> dict:
    """The original inline implementation, kept as an oracle."""

    def folder_of(p: str) -> str:
        parent = Path(p).parent.as_posix()
        return "" if parent == "." else parent

    siblings = sorted(
        p for p in ir.files if p != file_path and folder_of(p) == folder_of(file_path)
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
        file_ir = ir.files.get(file_path)
        if file_ir:
            names = list(file_ir.symbols)

    return {
        "related_files": tuple(siblings),
        "dependents": tuple(sorted(deps)[:8]),
        "functions": tuple(sorted(names)),
    }


def test_indexed_meta_matches_the_original_implementation() -> None:
    ir = _synthetic_ir()
    spans = [(None, None), (1, 30), (20, 50), (100, 200)]
    for file_path in ir.files:
        for start, end in spans:
            got = build_chunk_meta(ir, file_path, start_line=start, end_line=end)
            want = _reference_meta(ir, file_path, start, end)
            assert got.related_files == want["related_files"], (file_path, start, end)
            assert got.dependents == want["dependents"], (file_path, start, end)
            assert got.functions == want["functions"], (file_path, start, end)


def test_enriching_every_file_scans_the_edge_list_once() -> None:
    ir = _synthetic_ir()
    counting = _CountingList(ir.edges)
    ir.edges = counting

    for file_path in ir.files:
        build_chunk_meta(ir, file_path)

    assert counting.scans <= 1, (
        f"edges rescanned {counting.scans}x for {len(ir.files)} files - "
        "enrichment is quadratic again"
    )


def test_index_is_reused_across_chunks_of_the_same_ir(monkeypatch) -> None:
    ir = _synthetic_ir()
    builds = []
    real = metadata._build_ir_index
    monkeypatch.setattr(
        metadata, "_build_ir_index", lambda i: (builds.append(1), real(i))[1]
    )

    for file_path in ir.files:
        for _ in range(3):
            build_chunk_meta(ir, file_path)

    assert len(builds) == 1


def test_index_is_rebuilt_when_the_ir_changes() -> None:
    ir = _synthetic_ir()
    target = "pkg0/mod0.py"
    assert "pkg0/mod99.py" not in build_chunk_meta(ir, target).related_files

    ir.files["pkg0/mod99.py"] = FileIR(path="pkg0/mod99.py")

    assert "pkg0/mod99.py" in build_chunk_meta(ir, target).related_files


def test_a_second_ir_does_not_inherit_the_first_index() -> None:
    first = _synthetic_ir(folders=1, files_per_folder=2)
    second = _synthetic_ir(folders=1, files_per_folder=4)

    build_chunk_meta(first, "pkg0/mod0.py")
    siblings = build_chunk_meta(second, "pkg0/mod0.py").related_files

    assert siblings == ("pkg0/mod1.py", "pkg0/mod2.py", "pkg0/mod3.py")
