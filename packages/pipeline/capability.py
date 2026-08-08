"""Capability cards — deterministic intent index (no LLM).

Built from module docstrings, public symbols, path stems, and light
concept→phrase expansions when those concepts appear in the docstring.
Locate is BM25 over card text — pointer results only.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from conductor.bm25_index import BM25Index, tokenize
from pipeline.merkle import _is_ignored_dir_name, is_junk_rel

_DOC_FIRST = re.compile(r"^\s*[\"']{3}(.*?)[\"']{3}", re.DOTALL)
_INTENT_LINE = re.compile(
    r"(?im)^\s*(?:#\s*)?(?:intent|capability)\s*:\s*(.+)$"
)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?", re.MULTILINE)


@dataclass
class CapabilityCard:
    id: str
    path: str
    symbol: str
    kind: str  # module | function | class
    summary: str
    intents: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)

    def blob(self) -> str:
        parts = [
            self.path,
            self.symbol,
            self.summary,
            " ".join(self.intents),
            " ".join(self.terms),
        ]
        return "\n".join(p for p in parts if p)


@dataclass
class LocateHit:
    path: str
    symbol: str
    why: str
    score: float
    card_id: str
    source: str = "capability"


def _norm_path(rel: str) -> str:
    return rel.replace("\\", "/").lstrip("./")


def _module_doc(source: str) -> str:
    m = _DOC_FIRST.match(source)
    if m:
        return " ".join(m.group(1).split())
    try:
        tree = ast.parse(source)
        d = ast.get_docstring(tree)
        if d:
            return " ".join(d.split())
    except SyntaxError:
        pass
    return ""


def _intent_lines(source: str, doc: str) -> list[str]:
    found = [g.strip() for g in _INTENT_LINE.findall(source)]
    found += [g.strip() for g in _INTENT_LINE.findall(doc)]
    # unique preserve order
    out: list[str] = []
    for x in found:
        if x and x not in out:
            out.append(x)
    return out


def _first_sentences(doc: str, n: int = 2) -> list[str]:
    if not doc:
        return []
    out: list[str] = []
    for m in _SENTENCE.finditer(doc):
        s = " ".join(m.group(0).split()).strip()
        if len(s) < 12:
            continue
        out.append(s)
        if len(out) >= n:
            break
    return out


def _public_symbols(source: str) -> list[tuple[str, str, int]]:
    """Return (kind, name, lineno) for top-level public defs/classes."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[tuple[str, str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_") and not node.name.startswith("__"):
                continue
            out.append(("function", node.name, getattr(node, "lineno", 1) or 1))
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            out.append(("class", node.name, getattr(node, "lineno", 1) or 1))
    return out[:24]


def _concept_intents(doc: str, path: str, symbols: list[str]) -> list[str]:
    """Deterministic expansions only when cue words exist in docstring/path/symbols."""
    blob = f"{doc} {path} {' '.join(symbols)}".lower()
    intents: list[str] = []

    def has(*words: str) -> bool:
        return all(w in blob for w in words)

    def has_any(*words: str) -> bool:
        return any(w in blob for w in words)

    if has_any("merkle", "root hash", "root_hash", "root probe", "root_probe"):
        intents.append("detect whether the repository changed via root hash")
        intents.append("file synchronizer root hash diff for incremental index")
        if has_any("cheap", "idle", "gate", "clean", "skip", "without", "no embed"):
            intents.append("notice repo changes without full scan or re-embed")
            intents.append("cheap dirty check before incremental sync")
        elif "merkle" in blob or "root_probe" in blob or "root_hash" in blob:
            # Merkle core still answers "did anything change?" even without "cheap"
            intents.append("notice when repo files changed for sync")
    if has_any("hot_patch", "hot-patch", "hot patch") or (
        "hot" in blob and "patch" in blob
    ):
        intents.append("keep search usable while index is catching up")
        intents.append("patch bm25 from disk without waiting for embed")
    if has_any("directml", "dml", "cuda", "execution provider") and has_any(
        "embed", "onnx", "provider"
    ):
        intents.append("pick gpu or directml path for embedding")
    if has_any("background", "keeper", "sync_loop", "session keeper") and has_any(
        "fresh", "sync", "interval", "probe"
    ):
        intents.append("background loop that keeps the index fresh")
    if has_any("venv", "site-packages", ".venv") and has_any(
        "ignore", "skip", "junk", "noise", "never", "prune"
    ):
        intents.append("exclude venv and site-packages from project indexing")
        intents.append("avoid walking virtualenv directories that melt the laptop")
    if "mcp" in blob and has_any("search_code", "tool", "fastmcp"):
        intents.append("mcp tool an agent calls to find code")
    if has_any("turboquant", "turbo quant", "compress") and has_any(
        "faiss", "vector", "quant"
    ):
        intents.append("compress vectors before faiss")
    if has_any("incremental", "new file") and has_any("reindex", "re-embed", "upsert"):
        intents.append("pick up a new file without a full reindex")
    if has_any("final_check", "set_repo", "close", "exit") and has_any(
        "keeper", "sync", "probe"
    ):
        intents.append("last index check when closing or switching folders")
    if has_any("lock", "contention", "dml", "hang", "block") and has_any(
        "embed", "search", "background"
    ):
        intents.append("search hang while re-embedding in the background")

    # path-stem soft anchors
    stem = Path(path).stem.lower()
    if stem in {"merkle", "root_probe", "freshness"}:
        intents.append("file change detection for the index universe")
    if stem in {"hot_patch"}:
        intents.append("usable search during index catch-up")

    out: list[str] = []
    for x in intents:
        if x not in out:
            out.append(x)
    return out


def card_from_source(rel: str, source: str) -> list[CapabilityCard]:
    rel = _norm_path(rel)
    if not rel.endswith(".py") or is_junk_rel(rel):
        return []
    doc = _module_doc(source)
    symbols = _public_symbols(source)
    sym_names = [n for _, n, _ in symbols]
    # Head of file for concept cues (ignore-lists, constants) — not full RAG text
    cue = doc + "\n" + "\n".join(source.splitlines()[:100])
    intents = _intent_lines(source, doc) + _first_sentences(doc) + _concept_intents(
        cue, rel, sym_names
    )
    # dedupe intents
    uniq_i: list[str] = []
    for i in intents:
        if i and i not in uniq_i:
            uniq_i.append(i)
    terms = sorted(
        set(tokenize(doc))
        | set(tokenize(rel.replace("/", " ").replace("_", " ")))
        | set(tokenize(" ".join(sym_names)))
    )
    stem = Path(rel).stem
    mod_id = rel.replace("/", ".").removesuffix(".py")
    cards = [
        CapabilityCard(
            id=mod_id,
            path=rel,
            symbol=stem,
            kind="module",
            summary=(doc[:240] if doc else f"module {stem}"),
            intents=uniq_i[:16],
            terms=terms[:64],
        )
    ]
    for kind, name, _lineno in symbols[:12]:
        cards.append(
            CapabilityCard(
                id=f"{mod_id}.{name}",
                path=rel,
                symbol=name,
                kind=kind,
                summary=f"{kind} {name} in {rel}" + (f" — {doc[:120]}" if doc else ""),
                intents=uniq_i[:8],
                terms=sorted(set(terms) | set(tokenize(name)))[:64],
            )
        )
    return cards


def iter_py_files(root: Path, *, rels: Iterable[str] | None = None) -> list[str]:
    if rels is not None:
        return sorted({_norm_path(r) for r in rels if str(r).endswith(".py")})
    out: list[str] = []
    for dirpath, dirnames, filenames in os_walk_safe(root):
        dirnames[:] = [d for d in dirnames if not _is_ignored_dir_name(d)]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            p = Path(dirpath) / fname
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                continue
            if is_junk_rel(rel):
                continue
            out.append(rel)
    return sorted(out)


def os_walk_safe(root: Path):
    import os

    return os.walk(root, topdown=True)


def build_cards(
    root: Path,
    *,
    rels: Iterable[str] | None = None,
) -> list[CapabilityCard]:
    root = root.resolve()
    cards: list[CapabilityCard] = []
    for rel in iter_py_files(root, rels=rels):
        path = root / rel
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        cards.extend(card_from_source(rel, source))
    return cards


def cards_path(store_base: Path) -> Path:
    return store_base / "capability_cards.json"


def save_cards(store_base: Path, cards: list[CapabilityCard]) -> Path:
    path = cards_path(store_base)
    path.write_text(
        json.dumps([asdict(c) for c in cards], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def load_cards(store_base: Path) -> list[CapabilityCard]:
    path = cards_path(store_base)
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [CapabilityCard(**row) for row in rows]


def ensure_cards(
    root: Path,
    store_base: Path,
    *,
    indexed_files: Iterable[str] | None = None,
    force: bool = False,
) -> list[CapabilityCard]:
    """Load cards or rebuild from indexed .py files (fast, no embed)."""
    if not force:
        existing = load_cards(store_base)
        if existing:
            return existing
    rels = None
    if indexed_files is not None:
        rels = sorted({_norm_path(f) for f in indexed_files if str(f).endswith(".py")})
    cards = build_cards(root, rels=rels)
    save_cards(store_base, cards)
    return cards


class CapabilityIndex:
    """In-memory BM25 over capability cards."""

    def __init__(self, cards: list[CapabilityCard]):
        self.cards = cards
        self._bm25 = BM25Index([c.blob() for c in cards]) if cards else None

    def locate(self, query: str, top_k: int = 5) -> list[LocateHit]:
        if not self.cards or self._bm25 is None:
            return []
        raw = self._bm25.search(query, top_k=max(top_k * 4, 20))
        # Prefer module cards; collapse by path keeping best score
        by_path: dict[str, LocateHit] = {}
        for idx, score in raw:
            c = self.cards[idx]
            why = c.intents[0] if c.intents else c.summary[:160]
            hit = LocateHit(
                path=c.path,
                symbol=c.symbol,
                why=why,
                score=float(score),
                card_id=c.id,
            )
            # module kind slight boost for soft English
            if c.kind == "module":
                hit.score *= 1.08
            prev = by_path.get(c.path)
            if prev is None or hit.score > prev.score:
                by_path[c.path] = hit
        ordered = sorted(by_path.values(), key=lambda h: -h.score)
        return ordered[:top_k]

    def strong_hit(self, hits: list[LocateHit], *, min_score: float = 2.5) -> bool:
        if not hits:
            return False
        if hits[0].score < min_score:
            return False
        if len(hits) == 1:
            return True
        return (hits[0].score / (hits[1].score + 1e-9)) >= 1.12


def grep_code(
    root: Path,
    pattern: str,
    *,
    glob: str = "*.py",
    max_hits: int = 20,
) -> list[dict[str, Any]]:
    """Cheap line grep over the repo (no LLM)."""
    import fnmatch

    try:
        rx = re.compile(pattern)
    except re.error:
        rx = re.compile(re.escape(pattern))
    hits: list[dict[str, Any]] = []
    for rel in iter_py_files(root):
        if glob and not fnmatch.fnmatch(Path(rel).name, glob.replace("**/", "")):
            if not fnmatch.fnmatch(rel, glob):
                continue
        path = root / rel
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if rx.search(line):
                hits.append(
                    {
                        "path": rel,
                        "line": i,
                        "text": line.strip()[:200],
                    }
                )
                if len(hits) >= max_hits:
                    return hits
    return hits


def file_outline(root: Path, rel: str) -> list[dict[str, Any]]:
    """Symbol outline for one file — no bodies."""
    rel = _norm_path(rel)
    path = root / rel
    if not path.is_file():
        return []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []
    out: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(
                {
                    "kind": "function",
                    "symbol": node.name,
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                }
            )
        elif isinstance(node, ast.ClassDef):
            out.append(
                {
                    "kind": "class",
                    "symbol": node.name,
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                }
            )
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(
                        {
                            "kind": "method",
                            "symbol": f"{node.name}.{child.name}",
                            "line": child.lineno,
                            "end_line": getattr(child, "end_lineno", child.lineno),
                        }
                    )
    return out
