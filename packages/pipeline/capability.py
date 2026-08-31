"""Capability cards — deterministic intent index (no LLM).

Built from module docstrings, public symbols, path stems, and light
concept→phrase expansions when those concepts appear in the docstring.
Locate is BM25 over card text — pointer results only.
"""

from __future__ import annotations

import ast
import json
import os
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
    """Normalize repo-relative paths; preserve dotfiles like ``.env``."""
    rel = rel.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")


def _explicit_dot_dirs_in_pattern(pattern: str) -> set[str]:
    """Dot-directory names explicitly named in a glob (e.g. ``.scubiee/**``)."""
    out: set[str] = set()
    for part in (pattern or "").replace("\\", "/").split("/"):
        if part.startswith(".") and part not in {".", ".."}:
            head = part.split("*", 1)[0].split("{", 1)[0].split("[", 1)[0]
            if head:
                out.add(head)
    return out


def _should_skip_glob_dir(name: str, glob_pat: str) -> bool:
    if name in _explicit_dot_dirs_in_pattern(glob_pat):
        return False
    return _is_ignored_dir_name(name)


def glob_to_regex(patt: str) -> re.Pattern[str]:
    """Glob with ``**`` path segments (not fnmatch's flattened ``*``)."""
    i, n = 0, len(patt)
    parts: list[str] = []
    while i < n:
        if patt.startswith("**/", i):
            parts.append("(?:.*/)?")
            i += 3
            continue
        if patt.startswith("**", i):
            parts.append(".*")
            i += 2
            continue
        ch = patt[i]
        if ch == "*":
            parts.append("[^/]*")
        elif ch == "?":
            parts.append("[^/]")
        else:
            parts.append(re.escape(ch))
        i += 1
    flags = re.IGNORECASE if os.name == "nt" else 0
    return re.compile("^" + "".join(parts) + "$", flags)


def expand_brace_glob(pattern: str) -> list[str]:
    """Expand ``{a,b}`` groups (one level at a time, nested OK)."""
    patt = (pattern or "**/*").replace("\\", "/").strip() or "**/*"
    start = patt.find("{")
    if start < 0:
        return [patt]
    end = patt.find("}", start)
    if end < 0:
        return [patt]
    inner = patt[start + 1 : end]
    prefix = patt[:start]
    suffix = patt[end + 1 :]
    out: list[str] = []
    for alt in inner.split(","):
        out.extend(expand_brace_glob(prefix + alt.strip() + suffix))
    return out


def _path_glob_match_one(rel_n: str, glob_pat: str) -> bool:
    name = rel_n.rsplit("/", 1)[-1]
    patt = (glob_pat or "**/*").replace("\\", "/").strip() or "**/*"
    if patt in {"*", "**", "**/*"}:
        return True
    rx = glob_to_regex(patt)
    return rx.fullmatch(rel_n) is not None or rx.fullmatch(name) is not None


def path_glob_match(rel: str, glob_pat: str) -> bool:
    rel_n = _norm_path(rel)
    for expanded in expand_brace_glob(glob_pat):
        if _path_glob_match_one(rel_n, expanded):
            return True
    return False


def iter_glob_files(root: Path, glob_pat: str = "**/*") -> list[str]:
    """Repo-relative files matching ``glob_pat``, skipping junk dirs."""
    root = root.resolve()
    out: list[str] = []
    for dirpath, dirnames, filenames in os_walk_safe(root):
        dirnames[:] = [d for d in dirnames if not _should_skip_glob_dir(d, glob_pat)]
        for fname in filenames:
            p = Path(dirpath) / fname
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                continue
            if is_junk_rel(rel):
                continue
            if not path_glob_match(rel, glob_pat):
                continue
            out.append(rel)
    return sorted(out)


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


def _grep_via_rg(
    root: Path,
    pattern: str,
    *,
    glob: str,
    max_hits: int,
) -> dict[str, Any] | None:
    """Fast path via ripgrep when available (native-like speed and glob semantics)."""
    import shutil
    import subprocess

    rg = shutil.which("rg")
    if not rg:
        return None
    glob_pat = (glob or "**/*").replace("\\", "/").strip() or "**/*"
    cap = max(1, int(max_hits or 200))
    timeout_s = float(os.environ.get("CTX_GREP_TIMEOUT_S", "15"))
    args = [
        rg,
        "--line-number",
        "--no-heading",
        "--color=never",
        "--hidden",
        "--max-count",
        str(cap + 1),
        "-e",
        pattern,
        "--glob",
        glob_pat,
        ".",
    ]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(root.resolve()),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1):
        return None
    hits: list[dict[str, Any]] = []
    root_resolved = root.resolve()
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        fpath, lno_s, text = parts[0], parts[1], parts[2]
        try:
            rel = (root_resolved / fpath).resolve().relative_to(root_resolved).as_posix()
        except ValueError:
            rel = _norm_path(fpath)
        try:
            line_no = int(lno_s)
        except ValueError:
            continue
        hits.append(
            {
                "path": rel,
                "file": rel,
                "line": line_no,
                "text": text.strip()[:200],
            }
        )
    truncated = len(hits) > cap
    if truncated:
        hits = hits[:cap]
    return {
        "hits": hits,
        "truncated": truncated,
        "has_more": truncated,
        "glob": glob_pat,
        "max_hits": cap,
        "count": len(hits),
        "backend": "rg",
    }


def grep_scan(
    root: Path,
    pattern: str,
    *,
    glob: str = "**/*",
    max_hits: int = 200,
) -> dict[str, Any]:
    """Live-disk line grep. ``truncated`` means the hit cap or scan budget fired — not absence."""
    import time as _time

    glob_pat = (glob or "**/*").replace("\\", "/").strip() or "**/*"
    cap = max(1, int(max_hits or 200))
    rg_report = _grep_via_rg(root, pattern, glob=glob_pat, max_hits=cap)
    if rg_report is not None:
        return rg_report

    max_lines = int(os.environ.get("CTX_GREP_MAX_LINES", "250000"))
    deadline = _time.monotonic() + float(os.environ.get("CTX_GREP_TIMEOUT_S", "15"))
    try:
        rx = re.compile(pattern)
    except re.error:
        rx = re.compile(re.escape(pattern))
    hits: list[dict[str, Any]] = []
    truncated = False
    lines_scanned = 0
    for rel in iter_glob_files(root, glob_pat):
        if _time.monotonic() > deadline:
            truncated = True
            break
        path = root / rel
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if len(raw) > 2_000_000:
            continue
        if b"\0" in raw[:8192]:
            continue
        try:
            lines = raw.decode("utf-8", errors="replace").splitlines()
        except Exception:  # noqa: BLE001
            continue
        for i, line in enumerate(lines, 1):
            lines_scanned += 1
            if lines_scanned > max_lines:
                truncated = True
                break
            if _time.monotonic() > deadline:
                truncated = True
                break
            if not rx.search(line):
                continue
            if len(hits) >= cap:
                truncated = True
                break
            hits.append(
                {
                    "path": rel,
                    "file": rel,
                    "line": i,
                    "text": line.strip()[:200],
                }
            )
        if truncated:
            break
    out: dict[str, Any] = {
        "hits": hits,
        "truncated": truncated,
        "has_more": truncated,
        "glob": glob_pat,
        "max_hits": cap,
        "count": len(hits),
        "backend": "python",
    }
    if truncated and not hits:
        out["scan_incomplete"] = True
    return out


def grep_code(
    root: Path,
    pattern: str,
    *,
    glob: str = "**/*",
    max_hits: int = 200,
) -> list[dict[str, Any]]:
    """Cheap line grep over the repo (no LLM). Honors ``glob`` (not Python-only)."""
    return list(grep_scan(root, pattern, glob=glob, max_hits=max_hits)["hits"])


def read_python_source(path: Path) -> str:
    """Read Python source, stripping UTF-8 BOM so ast.parse succeeds."""
    return path.read_text(encoding="utf-8-sig", errors="replace").lstrip("\ufeff")


def truncation_meta(
    full_text: str,
    *,
    start_line: int,
    end_line: int,
    lines_total: int,
    max_chars: int,
    path: str = "",
    handle: str = "",
    budget: str = "cap",
    line_truncated: bool = False,
) -> dict[str, Any]:
    """Pagination hints when span text exceeds line or char budget."""
    char_truncated = len(full_text) > max_chars
    body = full_text[:max_chars] if char_truncated else full_text
    chars_returned = len(body)
    lines_returned_end = end_line
    next_start_line: int | None = None
    if char_truncated and body:
        lines_in_body = body.count("\n") + 1
        lines_returned_end = min(end_line, start_line + max(0, lines_in_body - 1))
        next_start_line = min(end_line + 1, lines_returned_end + 1)
        if next_start_line <= start_line:
            next_start_line = start_line + 1
    elif line_truncated and end_line < lines_total:
        next_start_line = end_line + 1
    truncated = char_truncated or line_truncated
    truncated_by: str | None = None
    if char_truncated and line_truncated:
        truncated_by = "lines" if line_truncated and end_line < lines_total else "chars"
    elif char_truncated:
        truncated_by = "chars"
    elif line_truncated:
        truncated_by = "lines"
    meta: dict[str, Any] = {
        "truncated": truncated,
        "truncated_by": truncated_by,
        "chars_returned": chars_returned,
        "lines_total": lines_total,
        "lines_returned": f"{start_line}-{lines_returned_end} of {lines_total}",
    }
    if truncated and next_start_line is not None:
        meta["next_start_line"] = next_start_line
        if path:
            meta["next"] = (
                f"focus(path={path!r}, start_line={next_start_line}, "
                f"budget={budget!r}, max_chars={max_chars})"
            )
        elif handle:
            meta["next"] = f"expand(handle={handle!r}, max_chars={max_chars})"
    return meta


def file_outline(root: Path, rel: str) -> list[dict[str, Any]]:
    """Symbol outline for one file — no bodies."""
    rel = _norm_path(rel)
    path = root / rel
    if not path.is_file():
        return []
    try:
        source = read_python_source(path)
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
