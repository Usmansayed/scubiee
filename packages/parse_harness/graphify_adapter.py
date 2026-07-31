"""Convert Graphify extraction output into canonical RepoIR."""

from __future__ import annotations

import re
import time
from pathlib import Path

from repo_ir import Edge, FileIR, RepoIR, Symbol


_FUNC_LABEL = re.compile(r"^(.+?)\(\)$")


def _norm_path(path: str | Path, root: Path) -> str:
    p = Path(path)
    try:
        rel = p.resolve().relative_to(root.resolve())
    except ValueError:
        # Graphify sometimes emits paths already relative to CWD
        rel = Path(path)
        if rel.is_absolute():
            try:
                rel = rel.relative_to(root.resolve())
            except ValueError:
                pass
    return rel.as_posix()


def _infer_kind(label: str, node: dict) -> str:
    if node.get("_callable_class"):
        return "class"
    if node.get("_callable") or label.endswith("()"):
        return "function"
    # File nodes usually equal the filename
    if label.endswith((".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs")):
        return "file"
    if "/" in str(node.get("source_file", "")) and label == Path(str(node.get("source_file"))).name:
        return "file"
    return "other"


def _symbol_name(label: str) -> str:
    m = _FUNC_LABEL.match(label)
    return m.group(1) if m else label


def _parse_line(loc: str | None) -> int | None:
    if not loc:
        return None
    m = re.search(r"L(\d+)", str(loc))
    return int(m.group(1)) if m else None


def graphify_to_repo_ir(
    extraction: dict,
    *,
    root: Path,
    elapsed_ms: float,
    file_count: int,
) -> RepoIR:
    root = root.resolve()
    symbols: dict[str, Symbol] = {}
    files: dict[str, FileIR] = {}

    for node in extraction.get("nodes", []):
        sid = str(node["id"])
        label = str(node.get("label") or sid)
        src = _norm_path(node.get("source_file") or "", root)
        kind = _infer_kind(label, node)
        if kind == "file" or src.endswith(label):
            kind = "file"
            files.setdefault(src, FileIR(path=src))
        name = _symbol_name(label)
        # Prefer callable-shaped labels over bare export aliases when colliding ids
        existing = symbols.get(sid)
        if existing is None or (existing.kind == "other" and kind == "function"):
            symbols[sid] = Symbol(
                id=sid,
                name=name,
                kind=kind,
                file=src,
                line=_parse_line(node.get("source_location")),
            )
        if kind == "file":
            files.setdefault(src, FileIR(path=src))

    edges: list[Edge] = []
    for raw in extraction.get("edges", []):
        rel = str(raw.get("relation") or "")
        edge = Edge(
            source=str(raw["source"]),
            target=str(raw["target"]),
            relation=rel,
            confidence=str(raw.get("confidence") or "EXTRACTED"),
            file=_norm_path(raw["source_file"], root) if raw.get("source_file") else None,
        )
        edges.append(edge)

        # Attach file-level summaries
        src_sym = symbols.get(edge.source)
        tgt_sym = symbols.get(edge.target)
        if src_sym and src_sym.kind == "file":
            file_ir = files.setdefault(src_sym.file, FileIR(path=src_sym.file))
            if rel == "contains" and tgt_sym:
                if tgt_sym.name not in file_ir.symbols:
                    file_ir.symbols.append(tgt_sym.name)
                if tgt_sym.kind in {"function", "class", "method"} and tgt_sym.name not in file_ir.exports:
                    # exported/callable symbols defined in file (approximation)
                    file_ir.exports.append(tgt_sym.name)
            elif rel in {"imports", "imports_from"} and tgt_sym:
                target_name = tgt_sym.name if rel == "imports" else tgt_sym.file
                if target_name not in file_ir.imports:
                    file_ir.imports.append(target_name)
            elif rel == "calls" and tgt_sym:
                if tgt_sym.name not in file_ir.calls:
                    file_ir.calls.append(tgt_sym.name)

    # Ensure every file path seen on symbols exists
    for sym in symbols.values():
        if sym.file:
            files.setdefault(sym.file, FileIR(path=sym.file))

    for fir in files.values():
        fir.symbols = sorted(set(fir.symbols))
        fir.imports = sorted(set(fir.imports))
        fir.exports = sorted(set(fir.exports))
        fir.calls = sorted(set(fir.calls))

    callable_count = sum(1 for s in symbols.values() if s.kind in {"function", "class", "method"})
    return RepoIR(
        root=str(root),
        parser="graphify-tree-sitter",
        files=files,
        symbols=symbols,
        edges=edges,
        stats={
            "file_count": file_count,
            "symbol_count": len(symbols),
            "callable_count": callable_count,
            "edge_count": len(edges),
            "elapsed_ms": round(elapsed_ms, 2),
            "relation_counts": _count_relations(edges),
        },
    )


def _count_relations(edges: list[Edge]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in edges:
        counts[e.relation] = counts.get(e.relation, 0) + 1
    return dict(sorted(counts.items()))


def parse_with_graphify(repo_root: Path, *, parallel: bool = False) -> RepoIR:
    """Single parse pass: Graphify AST → RepoIR."""
    from graphify.extract import collect_files, extract

    repo_root = repo_root.resolve()
    paths = collect_files(repo_root, root=repo_root)
    t0 = time.perf_counter()
    extraction = extract(paths, root=repo_root, cache_root=repo_root, parallel=parallel)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return graphify_to_repo_ir(
        extraction,
        root=repo_root,
        elapsed_ms=elapsed_ms,
        file_count=len(paths),
    )
