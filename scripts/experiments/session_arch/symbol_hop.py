"""Import-follow + identifier BM25/grep hops (LSP replacement)."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from pipeline.capability import grep_code
from pipeline.engine import WarmSearchEngine

from .core import (
    SessionState,
    bm25_confirm_score,
    norm,
    query_state,
    query_terms,
    soft_rewrite_queries,
)
from .hop_utils import pack_file_line_span, pick_outline_symbols, soft_demote

# Names that often mark "wiring" targets worth following from imports
_WIRING_HINTS = (
    "registry",
    "dispatch",
    "handler",
    "manager",
    "executor",
    "runtime",
    "store",
    "bridge",
    "router",
    "catalog",
)


def _confirm_query(query: str) -> str:
    """Query + soft rewrites → richer terms for confirm / ident search."""
    parts = [query, *soft_rewrite_queries(query)]
    return " ".join(parts)


def parse_imports(root: Path, file_rel: str) -> list[dict[str, Any]]:
    """Parse import statements → module + names + lineno."""
    path = root / file_rel
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []
    out: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [a.name for a in (node.names or []) if a.name and a.name != "*"]
            out.append(
                {
                    "module": node.module,
                    "names": names,
                    "lineno": int(getattr(node, "lineno", 1) or 1),
                    "level": int(node.level or 0),
                }
            )
        elif isinstance(node, ast.Import):
            for a in node.names or []:
                if a.name:
                    out.append(
                        {
                            "module": a.name,
                            "names": [a.name.split(".")[-1]],
                            "lineno": int(getattr(node, "lineno", 1) or 1),
                            "level": 0,
                        }
                    )
    return out


def resolve_module_file(root: Path, module: str, *, from_file: str = "") -> str | None:
    """Map dotted module to a repo-relative .py path if it exists."""
    if not module:
        return None
    parts = module.split(".")
    rel_py = Path(*parts).with_suffix(".py")
    rel_init = Path(*parts) / "__init__.py"
    bases = [root / "src", root]
    # Prefer package root matching from_file (e.g. already under src/)
    if from_file.startswith("src/"):
        bases = [root / "src", root]
    for base in bases:
        for cand in (base / rel_py, base / rel_init):
            try:
                if cand.is_file():
                    return norm(str(cand.resolve().relative_to(root.resolve())))
            except Exception:  # noqa: BLE001
                continue
    return None


def _import_score(imp: dict[str, Any], query: str) -> float:
    terms = set(query_terms(_confirm_query(query)))
    names = list(imp.get("names") or [])
    blob = " ".join([str(imp.get("module") or ""), *names]).lower()
    score = 0.0
    for t in terms:
        if t in blob:
            score += 2.0
    for h in _WIRING_HINTS:
        if h in blob:
            score += 1.5
        if any(h in t for t in terms):
            # query mentions registry/manager → boost matching imports
            if h in blob:
                score += 2.0
    # Prefer non-dunder, non-typing noise
    if any(n in ("annotations", "Any", "Optional") for n in names):
        score -= 1.0
    return score


def import_hop_from_seeds(
    engine: WarmSearchEngine,
    st: SessionState,
    query: str,
    seed_files: list[str],
    *,
    max_chars: int,
    already: list[str],
    keep: int = 6,
) -> list[str]:
    """Follow high-value imports from seed files (goto-def without LSP)."""
    opened: list[str] = []
    opened_set = {norm(x) for x in already}
    soft = query_state(query) == "SOFT"
    cq = _confirm_query(query)
    scored: list[tuple[float, str, int, str]] = []

    for f in seed_files[:8]:
        rel = norm(f)
        abs_path = engine.root / rel
        if not abs_path.is_file():
            continue
        for imp in parse_imports(engine.root, rel):
            target = resolve_module_file(
                engine.root, str(imp["module"]), from_file=rel
            )
            if not target or target in opened_set:
                continue
            if soft and soft_demote(target):
                continue
            sc = _import_score(imp, query) + bm25_confirm_score(engine, cq, target)
            names = imp.get("names") or []
            sym = names[0] if names else Path(target).stem
            scored.append((sc, target, int(imp["lineno"]), str(sym)))

    scored.sort(key=lambda x: -x[0])
    for sc, target, _ln, sym in scored[:keep]:
        # Prefer span at class/def of imported name if present
        line = 1
        outline = pick_outline_symbols(engine, target, sym, limit=1)
        st.ops.outlines += 1
        if outline:
            line = int(outline[0].get("line") or 1)
        if pack_file_line_span(
            engine,
            st,
            target,
            line,
            max_chars=max_chars,
            label="import_hop",
            symbol=sym,
        ):
            opened.append(target)
            opened_set.add(target)
    return opened


def ident_bm25_grep_hop(
    engine: WarmSearchEngine,
    st: SessionState,
    query: str,
    seed_files: list[str],
    *,
    max_chars: int,
    already: list[str],
    keep: int = 4,
) -> list[str]:
    """Pick identifiers from seed outlines / query; BM25 + grep to related files."""
    opened: list[str] = []
    opened_set = {norm(x) for x in already}
    soft = query_state(query) == "SOFT"
    cq = _confirm_query(query)
    idents: list[str] = []

    # From query terms that look like symbols
    for t in query_terms(query):
        if t[0].isupper() or "_" in t or t.endswith(("registry", "manager", "handler")):
            idents.append(t)
    # From seed outlines overlapping query
    for f in seed_files[:5]:
        st.ops.outlines += 1
        for row in pick_outline_symbols(engine, norm(f), query, limit=3):
            leaf = str(row.get("symbol") or "").split(".")[-1]
            if leaf and leaf not in idents:
                idents.append(leaf)
    # From import names on seeds (even if resolve failed)
    for f in seed_files[:5]:
        for imp in parse_imports(engine.root, norm(f)):
            for n in imp.get("names") or []:
                if n not in idents and n[0].isupper():
                    idents.append(n)

    idents = idents[:8]
    candidates: list[tuple[float, str, int, str]] = []

    for ident in idents:
        st.ops.greps += 1
        # Definition-ish patterns
        pat = rf"(class|def)\s+{re.escape(ident)}\b|{re.escape(ident)}\s*="
        hits = grep_code(engine.root, pat, glob="*.py", max_hits=12)
        for h in hits:
            rel = norm(str(h["path"]))
            if rel in opened_set:
                continue
            if soft and soft_demote(rel):
                continue
            sc = bm25_confirm_score(engine, f"{ident} {cq}", rel) + 3.0
            candidates.append((sc, rel, int(h["line"]), ident))

        # BM25 mass on identifier alone across files (via score_all best per file)
        try:
            scores = engine.conductor.bm25.score_all(ident)
            st.ops.searches += 1
            by_file: dict[str, float] = {}
            for c in engine.chunks:
                cid = int(c.id)
                if 0 <= cid < len(scores):
                    f = norm(c.file)
                    by_file[f] = max(by_file.get(f, 0.0), float(scores[cid]))
            for f, sc in sorted(by_file.items(), key=lambda x: -x[1])[:6]:
                if f in opened_set or sc <= 0:
                    continue
                if soft and soft_demote(f):
                    continue
                candidates.append(
                    (sc + bm25_confirm_score(engine, cq, f), f, 1, ident)
                )
        except Exception:  # noqa: BLE001
            pass

    candidates.sort(key=lambda x: -x[0])
    seen: set[str] = set()
    for sc, rel, line, ident in candidates:
        if rel in seen or rel in opened_set:
            continue
        seen.add(rel)
        if pack_file_line_span(
            engine,
            st,
            rel,
            line,
            max_chars=max_chars,
            label="ident_hop",
            symbol=ident,
        ):
            opened.append(rel)
            opened_set.add(rel)
            if len(opened) >= keep:
                break
    return opened
