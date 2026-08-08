"""Agent context navigation — post-RAG tools to gather spans without dumping files.

Blind arrow = search_code. These helpers let the agent finish context fast:
  read_span, follow_imports, graph_neighbors, grep_ident, session anchors.
"""

from __future__ import annotations

import ast
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pipeline.capability import file_outline, grep_code
from pipeline.engine import WarmSearchEngine
from pipeline.token_meter import estimate_tokens

_DISTRACTORS = ("/figma_", "/seo_", "/dribbble", "/figma/", "ai_visibility")
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


def norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")


def is_distractor(path: str, extra_avoid: list[str] | None = None) -> bool:
    p = norm(path).lower()
    if any(d in p for d in _DISTRACTORS):
        return True
    for a in extra_avoid or []:
        if a and a.lower() in p:
            return True
    return False


@dataclass
class Anchor:
    file: str
    start_line: int = 1
    end_line: int = 1
    symbol: str | None = None


@dataclass
class SessionNav:
    """Process-local anchors for one repo (agent session memory)."""

    anchors: list[Anchor] = field(default_factory=list)
    known_files: list[str] = field(default_factory=list)

    def remember(
        self,
        file: str,
        *,
        start_line: int = 1,
        end_line: int = 1,
        symbol: str | None = None,
    ) -> None:
        f = norm(file)
        if f not in self.known_files:
            self.known_files.append(f)
        key = (f, symbol)
        if not any((a.file, a.symbol) == key for a in self.anchors):
            self.anchors.append(
                Anchor(file=f, start_line=start_line, end_line=end_line, symbol=symbol)
            )
            if len(self.anchors) > 64:
                self.anchors = self.anchors[-64:]

    def as_dict(self) -> dict[str, Any]:
        return {
            "known_files": self.known_files[:40],
            "anchors": [asdict(a) for a in self.anchors[-30:]],
        }


_SESSIONS: dict[str, SessionNav] = {}


def session_for(root: Path) -> SessionNav:
    key = str(root.resolve())
    if key not in _SESSIONS:
        _SESSIONS[key] = SessionNav()
    return _SESSIONS[key]


def clear_session(root: Path) -> None:
    _SESSIONS.pop(str(root.resolve()), None)


def read_span_text(
    root: Path,
    rel: str,
    start: int,
    end: int,
    *,
    max_chars: int = 700,
) -> str:
    try:
        lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    s = max(0, int(start) - 1)
    e = min(len(lines), max(int(end), s + 1))
    body = "\n".join(lines[s:e])
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return f"# {rel}:{start}-{end}\n{body}"


def chunk_for_line(engine: WarmSearchEngine, rel: str, line: int) -> Any | None:
    rel = norm(rel)
    for c in engine.chunks:
        if norm(c.file) != rel:
            continue
        if int(c.start_line) <= line <= int(c.end_line):
            return c
    for c in engine.chunks:
        if norm(c.file) == rel:
            return c
    return None


def best_chunk(engine: WarmSearchEngine, rel: str) -> Any | None:
    rel = norm(rel)
    for c in engine.chunks:
        if norm(c.file) == rel:
            return c
    return None


def parse_imports(root: Path, file_rel: str) -> list[dict[str, Any]]:
    path = root / file_rel
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
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
                        }
                    )
    return out


def resolve_module_file(root: Path, module: str, *, from_file: str = "") -> str | None:
    if not module:
        return None
    parts = module.split(".")
    rel_py = Path(*parts).with_suffix(".py")
    rel_init = Path(*parts) / "__init__.py"
    bases = [root / "src", root]
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


def _terms(query: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query or "")]


def _import_score(imp: dict[str, Any], query: str) -> float:
    terms = set(_terms(query))
    names = list(imp.get("names") or [])
    blob = " ".join([str(imp.get("module") or ""), *names]).lower()
    score = 0.0
    for t in terms:
        if t in blob:
            score += 2.0
    for h in _WIRING_HINTS:
        if h in blob:
            score += 1.5
        if any(h in t for t in terms) and h in blob:
            score += 2.0
    return score


def bm25_file_score(engine: WarmSearchEngine, query: str, file_rel: str) -> float:
    terms = _terms(query)
    if not terms:
        return 0.0
    rel = norm(file_rel)
    path_l = rel.lower()
    name = Path(rel).stem.lower()
    boost = 0.0
    for t in terms:
        if t in path_l:
            boost += 2.0
        if t in name or name in t:
            boost += 3.0
    try:
        scores = engine.conductor.bm25.score_all(" ".join(terms[:12]))
    except Exception:  # noqa: BLE001
        return boost
    best = 0.0
    for c in engine.chunks:
        if norm(c.file) != rel:
            continue
        cid = int(c.id)
        if 0 <= cid < len(scores):
            best = max(best, float(scores[cid]))
    return best + boost


def pack_span(
    engine: WarmSearchEngine,
    session: SessionNav,
    rel: str,
    line: int = 1,
    *,
    max_chars: int,
    symbol: str | None = None,
    label: str = "span",
) -> dict[str, Any] | None:
    rel = norm(rel)
    c = chunk_for_line(engine, rel, line) or best_chunk(engine, rel)
    if c is None:
        # raw lines fallback
        text = read_span_text(engine.root, rel, line, line + 40, max_chars=max_chars)
        if not text:
            return None
        session.remember(rel, start_line=line, end_line=line + 40, symbol=symbol)
        return {
            "path": rel,
            "start_line": line,
            "end_line": line + 40,
            "symbol": symbol,
            "label": label,
            "text": text,
            "tokens": estimate_tokens(text),
        }
    text = read_span_text(
        engine.root,
        rel,
        int(c.start_line),
        int(c.end_line),
        max_chars=max_chars,
    )
    session.remember(
        rel,
        start_line=int(c.start_line),
        end_line=int(c.end_line),
        symbol=symbol,
    )
    return {
        "path": rel,
        "start_line": int(c.start_line),
        "end_line": int(c.end_line),
        "chunk_id": int(c.id),
        "symbol": symbol,
        "label": label,
        "text": text,
        "tokens": estimate_tokens(text),
    }


# --- Public tool implementations -------------------------------------------------


def tool_read_span(
    engine: WarmSearchEngine,
    path: str,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = 700,
    avoid: list[str] | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    root = engine.root
    session = session_for(root)
    rel = norm(path)
    try:
        if Path(path).is_absolute():
            rel = norm(str(Path(path).resolve().relative_to(root.resolve())))
    except Exception:  # noqa: BLE001
        pass
    if is_distractor(rel, avoid):
        return {"ok": False, "error": "path demoted as distractor", "path": rel}
    if start_line is None or end_line is None:
        c = best_chunk(engine, rel)
        if c is not None:
            start_line = int(c.start_line)
            end_line = int(c.end_line)
        else:
            start_line = start_line or 1
            end_line = end_line or 80
    packed = pack_span(
        engine,
        session,
        rel,
        int(start_line),
        max_chars=max_chars,
        label="read_span",
    )
    return {
        "ok": bool(packed),
        "ms": round((time.perf_counter() - t0) * 1000, 2),
        "span": packed,
        "session": session.as_dict(),
    }


def tool_follow_imports(
    engine: WarmSearchEngine,
    path: str,
    *,
    query: str = "",
    keep: int = 6,
    max_chars: int = 500,
    avoid: list[str] | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    root = engine.root
    session = session_for(root)
    rel = norm(path)
    try:
        if Path(path).is_absolute():
            rel = norm(str(Path(path).resolve().relative_to(root.resolve())))
    except Exception:  # noqa: BLE001
        pass
    scored: list[tuple[float, str, int, str]] = []
    for imp in parse_imports(root, rel):
        target = resolve_module_file(root, str(imp["module"]), from_file=rel)
        if not target or is_distractor(target, avoid):
            continue
        names = imp.get("names") or []
        sym = names[0] if names else Path(target).stem
        sc = _import_score(imp, query) + bm25_file_score(engine, query or sym, target)
        scored.append((sc, target, int(imp["lineno"]), str(sym)))
    scored.sort(key=lambda x: -x[0])
    spans: list[dict[str, Any]] = []
    for _sc, target, _ln, sym in scored[:keep]:
        line = 1
        for row in file_outline(root, target):
            if str(row.get("symbol") or "").split(".")[-1] == sym.split(".")[-1]:
                line = int(row.get("line") or 1)
                break
        packed = pack_span(
            engine,
            session,
            target,
            line,
            max_chars=max_chars,
            symbol=sym,
            label="import",
        )
        if packed:
            spans.append(packed)
    return {
        "ok": True,
        "from": rel,
        "ms": round((time.perf_counter() - t0) * 1000, 2),
        "spans": spans,
        "tokens": sum(int(s.get("tokens") or 0) for s in spans),
        "session": session.as_dict(),
    }


def tool_graph_neighbors(
    engine: WarmSearchEngine,
    paths: list[str],
    *,
    query: str = "",
    cap: int = 16,
    keep: int = 4,
    max_chars: int = 500,
    avoid: list[str] | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    session = session_for(engine.root)
    seeds = [norm(p) for p in paths if p]
    neighbors = engine.conductor.graph.neighbor_files(seeds, cap=cap)
    scored: list[tuple[float, str]] = []
    for nf in neighbors:
        n = norm(nf)
        if is_distractor(n, avoid):
            continue
        if n in seeds:
            continue
        scored.append((bm25_file_score(engine, query or " ".join(seeds), n), n))
    scored.sort(key=lambda x: -x[0])
    spans: list[dict[str, Any]] = []
    for _sc, n in scored[:keep]:
        packed = pack_span(
            engine, session, n, 1, max_chars=max_chars, label="neighbor"
        )
        if packed:
            spans.append(packed)
    return {
        "ok": True,
        "seeds": seeds,
        "ms": round((time.perf_counter() - t0) * 1000, 2),
        "neighbor_candidates": len(neighbors),
        "spans": spans,
        "tokens": sum(int(s.get("tokens") or 0) for s in spans),
        "session": session.as_dict(),
    }


def tool_query_graph(
    engine: WarmSearchEngine,
    question: str,
    *,
    keep: int = 6,
    neighbor_keep: int = 4,
    max_chars: int = 400,
    avoid: list[str] | None = None,
) -> dict[str, Any]:
    """Easy NL graph tool: Graphify affinity seeds → small spans + neighbor paths."""
    t0 = time.perf_counter()
    q = (question or "").strip()
    if not q:
        return {"ok": False, "error": "question required"}
    session = session_for(engine.root)
    cond = engine.conductor
    hits = cond.retrieve_graphify(q, top_k=max(keep, 8))
    seeds: list[str] = []
    spans: list[dict[str, Any]] = []
    for h in hits:
        rel = norm(h.file)
        if is_distractor(rel, avoid) or rel in seeds:
            continue
        seeds.append(rel)
        packed = pack_span(
            engine, session, rel, 1, max_chars=max_chars, label="graph_seed"
        )
        if packed:
            spans.append(packed)
        if len(seeds) >= keep:
            break

    neighbors = cond.graph.neighbor_files(seeds, cap=24)
    neighbor_spans: list[dict[str, Any]] = []
    scored: list[tuple[float, str]] = []
    for nf in neighbors:
        n = norm(nf)
        if is_distractor(n, avoid) or n in seeds:
            continue
        scored.append((bm25_file_score(engine, q, n), n))
    scored.sort(key=lambda x: -x[0])
    for _sc, n in scored[:neighbor_keep]:
        packed = pack_span(
            engine, session, n, 1, max_chars=max_chars, label="graph_neighbor"
        )
        if packed:
            neighbor_spans.append(packed)

    all_spans = spans + neighbor_spans
    return {
        "ok": True,
        "tool": "query_graph",
        "question": q,
        "ms": round((time.perf_counter() - t0) * 1000, 2),
        "seeds": seeds,
        "spans": all_spans,
        "tokens": sum(int(s.get("tokens") or 0) for s in all_spans),
        "hint": "Graph-only path. Follow with grep_ident / read_span / graph_neighbors as needed.",
        "session": session.as_dict(),
    }


def tool_grep_ident(
    engine: WarmSearchEngine,
    ident: str,
    *,
    max_hits: int = 12,
    max_chars: int = 500,
    keep: int = 4,
    avoid: list[str] | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    session = session_for(engine.root)
    ident = ident.strip()
    if not ident:
        return {"ok": False, "error": "ident required"}
    pat = rf"(class|def)\s+{re.escape(ident)}\b"
    hits = grep_code(engine.root, pat, glob="*.py", max_hits=max_hits)
    spans: list[dict[str, Any]] = []
    seen: set[str] = set()
    for h in hits:
        rel = norm(str(h["path"]))
        if rel in seen or is_distractor(rel, avoid):
            continue
        seen.add(rel)
        packed = pack_span(
            engine,
            session,
            rel,
            int(h["line"]),
            max_chars=max_chars,
            symbol=ident,
            label="ident",
        )
        if packed:
            spans.append(packed)
        if len(spans) >= keep:
            break
    return {
        "ok": True,
        "ident": ident,
        "ms": round((time.perf_counter() - t0) * 1000, 2),
        "grep_hits": len(hits),
        "spans": spans,
        "tokens": sum(int(s.get("tokens") or 0) for s in spans),
        "session": session.as_dict(),
    }


def tool_reopen_anchors(
    engine: WarmSearchEngine,
    *,
    prefer: list[str] | None = None,
    avoid: list[str] | None = None,
    max_files: int = 4,
    max_chars: int = 500,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    session = session_for(engine.root)
    prefer_l = [p.lower() for p in (prefer or [])]
    ordered: list[str] = []
    for rel in session.known_files:
        if is_distractor(rel, avoid):
            continue
        if prefer_l and any(p in norm(rel).lower() for p in prefer_l):
            ordered.append(rel)
    for rel in session.known_files:
        if rel not in ordered and not is_distractor(rel, avoid):
            ordered.append(rel)
    spans: list[dict[str, Any]] = []
    for rel in ordered[:max_files]:
        packed = pack_span(
            engine, session, rel, 1, max_chars=max_chars, label="reopen"
        )
        if packed:
            spans.append(packed)
    return {
        "ok": True,
        "ms": round((time.perf_counter() - t0) * 1000, 2),
        "spans": spans,
        "tokens": sum(int(s.get("tokens") or 0) for s in spans),
        "session": session.as_dict(),
    }


def tool_session_status(engine: WarmSearchEngine) -> dict[str, Any]:
    session = session_for(engine.root)
    return {"ok": True, "session": session.as_dict()}
