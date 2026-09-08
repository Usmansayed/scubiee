"""Symbol-level corpus for the tracing sim (Python AST, no engine/daemon)."""

from __future__ import annotations

import ast
import hashlib
import os
import pickle
import time
from pathlib import Path

from trace_lab.types import TraceNode, node_id

_SKIP_DIRS = {
    "__pycache__",
    ".git",
    "cases",
    "graphify-out",
    ".context-engine",
    ".scubiee",
    ".venv",
    "venv",
    "node_modules",
    ".tox",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
    "site-packages",
    "testdata",
    "out",
    ".ab_workspaces",
    ".worktrees",
    "vendor",
    ".venv-cli-test",
    "research",
    # Do NOT skip bare "models" — that drops app/models (ORM/domain). Weight dumps
    # live under research/ or are skipped via other junk dirs.
    "fixtures",
}

_CACHE_VERSION = 2


def iter_python_files(root: Path) -> list[Path]:
    """List project ``*.py`` files, pruning junk trees during the walk (not after)."""
    root = root.resolve()
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        # Prune before descending — critical for speed (rglob still walks skipped trees).
        pruned: list[str] = []
        for d in dirnames:
            if d in _SKIP_DIRS or d.startswith("."):
                continue
            pruned.append(d)
        dirnames[:] = pruned
        rel_parts = Path(dirpath).resolve().relative_to(root).parts
        under_packages = "packages" in rel_parts
        if "tests" in rel_parts and not under_packages:
            dirnames[:] = []
            continue
        for name in filenames:
            if not name.endswith(".py"):
                continue
            if name.startswith("test_") and not under_packages:
                continue
            out.append(Path(dirpath) / name)
    out.sort()
    return out


def rel_posix(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def module_name_for(rel: str) -> str:
    if rel.endswith("/__init__.py"):
        return rel[: -len("/__init__.py")].replace("/", ".")
    if rel.endswith(".py"):
        return rel[: -len(".py")].replace("/", ".")
    return rel.replace("/", ".")


def _end_lineno(node: ast.AST, fallback: int) -> int:
    end = getattr(node, "end_lineno", None)
    return int(end) if end else fallback


def _slice(lines: list[str], start: int, end: int) -> str:
    s = max(1, start)
    e = max(s, end)
    return "\n".join(lines[s - 1 : e])


def _fingerprint(root: Path, files: list[Path]) -> str:
    h = hashlib.sha1()
    h.update(str(_CACHE_VERSION).encode())
    for path in files:
        try:
            st = path.stat()
            rel = path.resolve().relative_to(root).as_posix().encode()
            h.update(rel)
            h.update(str(int(st.st_mtime_ns)).encode())
            h.update(str(int(st.st_size)).encode())
        except OSError:
            h.update(b"?")
    return h.hexdigest()


def _cache_path(root: Path) -> Path:
    return root / ".scubiee" / "cache" / f"trace_nodes_v{_CACHE_VERSION}.pkl"


def _load_cached_nodes(root: Path, fingerprint: str) -> dict[str, TraceNode] | None:
    path = _cache_path(root)
    if not path.is_file():
        return None
    try:
        raw = pickle.loads(path.read_bytes())
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("fingerprint") != fingerprint:
        return None
    nodes = raw.get("nodes")
    return nodes if isinstance(nodes, dict) else None


def _store_cached_nodes(root: Path, fingerprint: str, nodes: dict[str, TraceNode]) -> None:
    path = _cache_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".pkl.tmp")
        tmp.write_bytes(
            pickle.dumps(
                {"fingerprint": fingerprint, "nodes": nodes, "saved_at": time.time()},
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        )
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        pass


def extract_nodes(root: Path) -> dict[str, TraceNode]:
    """One node per function, method, class, and ALL_CAPS module constant."""
    root = root.resolve()
    files = iter_python_files(root)
    fp = _fingerprint(root, files)
    cached = _load_cached_nodes(root, fp)
    if cached is not None:
        return cached

    nodes: dict[str, TraceNode] = {}
    for path in files:
        rel = rel_posix(root, path)
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        doc = ast.get_docstring(tree) or ""
        _walk_body(rel, tree.body, lines, nodes, class_name="", file_doc=doc)
    _store_cached_nodes(root, fp, nodes)
    return nodes


def corpus_fingerprint(root: Path) -> str:
    """Stable content fingerprint for disk caches that depend on the Python corpus."""
    root = root.resolve()
    return _fingerprint(root, iter_python_files(root))


def _walk_body(
    rel: str,
    body: list[ast.stmt],
    lines: list[str],
    nodes: dict[str, TraceNode],
    *,
    class_name: str,
    file_doc: str,
) -> None:
    prefix = (file_doc.strip() + "\n") if file_doc.strip() else ""
    for stmt in body:
        if isinstance(stmt, ast.ClassDef):
            qual = stmt.name
            nid = node_id(rel, qual)
            start = int(stmt.lineno)
            end = _end_lineno(stmt, start)
            body_txt = _slice(lines, start, end)
            nodes[nid] = TraceNode(
                id=nid,
                file=rel,
                symbol=qual,
                kind="class",
                start_line=start,
                end_line=end,
                text=body_txt,
                lex_text=prefix + body_txt,
            )
            _walk_body(rel, stmt.body, lines, nodes, class_name=stmt.name, file_doc=file_doc)
            continue
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qual = f"{class_name}.{stmt.name}" if class_name else stmt.name
            nid = node_id(rel, qual)
            start = int(stmt.lineno)
            end = _end_lineno(stmt, start)
            kind = "method" if class_name else "function"
            body_txt = _slice(lines, start, end)
            nodes[nid] = TraceNode(
                id=nid,
                file=rel,
                symbol=qual,
                kind=kind,
                start_line=start,
                end_line=end,
                text=body_txt,
                lex_text=prefix + body_txt,
            )
            continue
        if class_name:
            continue
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    nid = node_id(rel, t.id)
                    start = int(stmt.lineno)
                    end = _end_lineno(stmt, start)
                    body_txt = _slice(lines, start, end)
                    nodes[nid] = TraceNode(
                        id=nid,
                        file=rel,
                        symbol=t.id,
                        kind="const",
                        start_line=start,
                        end_line=end,
                        text=body_txt,
                        lex_text=prefix + body_txt,
                    )
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if stmt.target.id.isupper():
                nid = node_id(rel, stmt.target.id)
                start = int(stmt.lineno)
                end = _end_lineno(stmt, start)
                body_txt = _slice(lines, start, end)
                nodes[nid] = TraceNode(
                    id=nid,
                    file=rel,
                    symbol=stmt.target.id,
                    kind="const",
                    start_line=start,
                    end_line=end,
                    text=body_txt,
                    lex_text=prefix + body_txt,
                )
