"""Scubiee map v2 - one `map` tool with 5 configs, as a standalone MCP stdio bridge.

    find     "Where is the code for this?"          query (+ keywords, scope)
    refs     "Where else are these names?"          names (+ kind, scope)
    open     "Show me these pieces of code"         targets (+ margin, budget_chars)
    around   "What's connected to this?"            target (+ want)
    outline  "What's in this directory / file?"     path (+ query)

Design: docs/scubiee-map-configs.md. Hard limit: 5 configs.

Self-contained: speaks JSON-RPC 2.0 over stdio and talks to the already-running
Scubiee engine over its HTTP API (/v1/search, /v1/grep, /v1/outline, /health).
It imports nothing from Scubiee's own mcp_* modules and does not change the
engine. File text for spans is read from disk under MINI_REPO.

Env:
  MINI_ENGINE_URL   default http://127.0.0.1:8765
  MINI_REPO         repo root (the indexed repo)
  MINI_PROJECT_ID   echoed by gate()

Defaults shared by every config: line numbers on every code line, a hard
character budget, "already shown" marking per session, code before tests/docs,
a confidence level (find), and suggestions instead of empty results.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

# Production reads CTX_* (set by the MCP launch); the benchmarked harness used
# MINI_*. Prefer MINI_* when present (exact benchmarked behavior), else fall back
# to the production CTX_* names so no env remap is needed in prod.
ENGINE_URL = (
    os.environ.get("MINI_ENGINE_URL")
    or os.environ.get("CTX_ENGINE_URL")
    or "http://127.0.0.1:8765"
).rstrip("/")
REPO = Path(
    os.environ.get("MINI_REPO")
    or os.environ.get("CTX_REPO")
    or "."
).resolve()
PROJECT_ID = os.environ.get("MINI_PROJECT_ID") or os.environ.get("CTX_PROJECT_ID") or ""

CONFIGS = ("find", "refs", "view")
# Budgets are deliberately generous. Measured cost model: tokens ~= context x
# model-calls, and each extra call re-reads the whole transcript (~35-40k tokens
# in our runs). So returning a few thousand extra chars in ONE call is far
# cheaper than a lean result that forces another round-trip. Prefer a complete
# answer now over a small answer plus a follow-up.
# Budgets are generous on purpose: a bigger single response that lets the agent
# finish in ONE call is far cheaper than a lean one that forces another call
# (each call re-reads the whole transcript, ~35k tokens). find's budget is large
# enough to carry several clustered symbol bodies at once.
DEFAULT_BUDGET = {"find": 14000, "refs": 6000, "view": 12000,
                  # internal (view/refs route into these):
                  "open": 12000, "around": 6000, "outline": 6000}
BODY_CAP = 5000           # max chars for a single inline body in find
SKIP_DIRS = {".git", ".scubiee", ".ab_workspaces", "node_modules", "__pycache__", ".pytest_cache",
             "vendor", "models", "graphify-out", ".worktrees", "research", "web-info", "nvidia",
             "dist", "build", "out", ".embed_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vscode"}
SOURCE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".cs",
              ".c", ".cc", ".cpp", ".h", ".hpp", ".swift", ".php", ".scala", ".sh"}
DOC_EXT = {".md", ".rst", ".txt", ".adoc"}
STOP = set("""a an the and or of to in on for with from by at is are be this that these those how where
what which who when why does do it its into as via not no use uses used using code file files function
functions class method methods""".split())
PY_KEYWORDS = set("""if elif else for while return yield with try except finally raise assert def class
lambda and or not in is None True False print len str int float dict list set tuple isinstance getattr
setattr hasattr super range enumerate zip sorted min max sum any all open type map filter repr round abs
bool bytes format iter next object vars id hash""".split())

SERVER_INSTRUCTIONS = """\
Scubiee map = code locate. One tool `map`, three configs; pick by what you know:
- Don't know where it is ...... map config=find query=<short intent> keywords=[names you know]
    returns ranked locations AND the top result's code inline.
- Know a name, want its places . map config=refs names=[...] kind=all
    kind: def|uses|imports|callers|callees|tests|siblings|all (every definition, use, and relation).
- Want to see code/structure .. map config=view targets=["file::symbol","file:line",...]  (shows code;
    pass several) OR  map config=view path=<dir-or-file> [query=<name>]  (shows the outline).
Exact string/regex -> Grep. History -> git.
find returns the top code inline: if it's the place you need, EDIT - don't view it again.
Act on the first good answer; don't call the other configs just to look around."""

# ---------------------------------------------------------------------------
# engine + filesystem helpers
# ---------------------------------------------------------------------------


_OPENER = None


def _opener():
    """Lazily built opener with an EMPTY ProxyHandler. The engine is always loopback
    (127.0.0.1), so proxies are never wanted; an empty ProxyHandler skips urllib's
    default proxy lookup (on Windows that reads WinINET registry settings). Built once
    on the first request (not at import) so the ~350ms one-time urllib opener-init cost
    stays off the worker spawn / initialize critical path and is hidden by the
    background _warm thread. See scripts/perf/probe_proxy_ab.py / probe_firstcall.py."""
    global _OPENER
    if _OPENER is None:
        _OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return _OPENER


def _http(path: str, payload: dict | None = None, timeout: float = 90.0) -> dict:
    url = ENGINE_URL + path
    data = None if payload is None else json.dumps(payload).encode()
    headers = {} if payload is None else {"Content-Type": "application/json"}
    last = None
    opener = _opener()
    for _ in range(2):  # retry once: cold bridges sometimes drop the first request
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with opener.open(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.3)
    raise RuntimeError(f"engine {path} failed: {type(last).__name__}: {last}")


def _search(query: str, top_k: int) -> list[dict]:
    # lean=True: we only read `hits`; this drops the ~4.4KB keeper block (65% of
    # the response body) that the engine would otherwise build/serialize/send and
    # we would parse then discard. Behavior of `hits` is unchanged.
    r = _http("/v1/search", {"query": query, "top_k": top_k, "path": str(REPO), "lean": True})
    return r.get("hits") or []


def _grep_one(pattern: str, max_hits: int, glob: str) -> tuple[list[dict], bool]:
    r = _http("/v1/grep", {"pattern": pattern, "glob": glob, "max_hits": max_hits, "path": str(REPO)})
    hits = [h for h in (r.get("hits") or []) if not _skipped(h.get("path", ""))]
    return hits, bool(r.get("truncated") or r.get("has_more"))


def _source_globs() -> list[str]:
    """Globs for the repo's main source languages, most common first."""
    counts: dict[str, int] = {}
    for f in _repo_files():
        suf = Path(f).suffix.lower()
        if suf in SOURCE_EXT:
            counts[suf] = counts.get(suf, 0) + 1
    exts = [e for e, n in sorted(counts.items(), key=lambda x: -x[1]) if n >= 3][:4] or [".py"]
    return [f"**/*{e}" for e in exts]


_GREP_EXT = SOURCE_EXT | DOC_EXT | {".json", ".toml", ".yaml", ".yml"}


_ESCAPE_SEQ_RE = re.compile(r"\\.")  # \b \s \w \( etc. — drop before literal scan
_LITERAL_GROUPS_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _pattern_prefilter(pattern: str):
    """Cheap required-substring filter for a regex, so the hot grep can skip files
    with a C-level ``in`` test before paying for ``re.search`` over 28 MB of text.

    Returns a predicate ``keep(text_lower) -> bool`` that is a *necessary* (never
    over-strict) condition for the regex to match. The nearly-universal grep shapes
    here — ``\\bNAME\\b``, ``NAME\\s*\\(``, ``def NAME``, ``(a|b|c)`` — all require at
    least one fixed identifier of length >= 3 to be present somewhere in the file.
    If we cannot prove such a requirement, we keep the file (fall back to the regex),
    so correctness is preserved; we only ever skip files that provably cannot match.
    """
    ci = pattern.startswith("(?i)")
    body = pattern[4:] if ci else pattern
    # Escape-strip FIRST so escaped literals like "\(" and classes like "\s" become
    # spaces and are not mistaken for regex group syntax or required text.
    stripped = _ESCAPE_SEQ_RE.sub(" ", body)
    # Drop OPTIONAL groups entirely — "(?:async )?" / "(group)?" are not required,
    # so their contents must not count as required idents.
    stripped = re.sub(r"\((?:\?:)?[^()]*\)\s*\?", " ", stripped)
    # Neutralise group *syntax* (parens, "?:") but KEEP the identifiers inside an
    # alternation so they contribute to the OR requirement below.
    stripped = stripped.replace("(?:", " ").replace("(", " ").replace(")", " ")
    # Bail when unsafe features remain that could make a required-substring claim
    # wrong: char classes, wildcard '.', leftover escapes, or a quantified literal.
    if any(tok in stripped for tok in ("[", "]", "{", "}", ".", "\\")):
        return None
    if re.search(r"[A-Za-z0-9_][*?]", stripped):
        return None
    idents = _LITERAL_GROUPS_RE.findall(stripped)
    noise = {"async", "def", "class", "function", "func", "fn"}
    req = [i for i in idents if i.lower() not in noise]
    if not req:
        return None
    uniq = list(dict.fromkeys((i.lower() if ci else i) for i in req))
    # OR semantics everywhere: the predicate is only ever a *necessary* condition
    # (if the regex matches, at least one of its fixed identifiers is present), so
    # requiring "any ident present" never over-filters. The only shapes that reach
    # here are plain literals, word-boundary idents, "NAME\s*\(", "def NAME", and
    # single/alternation groups — all satisfy this. Anything riskier bailed above.
    def keep(t: str) -> bool:
        return any(u in t for u in uniq)

    return (keep, ci)


_GREP_SCOPE_FILES: dict[tuple, list[str]] = {}


def _grep_scope_files(scope: str) -> list[str]:
    """Filtered + sorted file list for a grep ``scope``, memoized per repo file set.

    The walk/filter/sort recomputes ``_kind_of`` for ~5k files on every grep and the
    result is identical within a session, so it dominated a warm grep (~117ms of
    ~145ms). Keyed on the identity+length of ``_repo_files()`` so it invalidates
    automatically whenever the file list is rebuilt. Output is byte-identical to the
    inline build it replaces, so grep results are unchanged."""
    files = _repo_files()
    key = (scope, id(files), len(files))
    hit = _GREP_SCOPE_FILES.get(key)
    if hit is not None:
        return hit
    want = {"code": ("code", "tests"), "tests": ("tests",), "docs": ("docs",),
            "all": ("code", "tests", "docs", "other")}.get(scope, ("code", "tests"))
    sel = [f for f in files if Path(f).suffix.lower() in _GREP_EXT and _kind_of(f) in want]
    order = {"code": 0, "tests": 1, "docs": 2, "other": 3}
    sel.sort(key=lambda f: (order[_kind_of(f)], f))
    _GREP_SCOPE_FILES.clear()  # one scope's list is all we keep; cheap to rebuild on scope change
    _GREP_SCOPE_FILES[key] = sel
    return sel


def _grep(pattern: str, max_hits: int = 300, scope: str = "code") -> tuple[list[dict], bool]:
    """Line grep over the repo, code files first, docs only when scope asks.

    Done in the bridge (live disk, per-file cache keyed on mtime) instead of the
    engine's /v1/grep: that route walks files alphabetically and stops at its hit
    cap, so docs/ crowded out packages/, and each call took ~2 s. Same rules as
    the engine: skip vendored/build dirs, binaries and files over 2 MB.

    Fast path: a required-substring prefilter skips files that provably cannot match
    (C-level ``in``) before the per-file regex, cutting a whole-repo identifier grep
    from ~1 s to ~100 ms on this corpus without changing results."""
    try:
        rx = re.compile(pattern)
        rx_file = re.compile(pattern, re.MULTILINE)  # same pattern, ^/$ per line, for the whole-file check
    except re.error:
        rx = re.compile(re.escape(pattern))
        rx_file = rx
    pf = _pattern_prefilter(pattern)
    keep, keep_ci = (pf if pf else (None, False))
    files = _grep_scope_files(scope)
    out, truncated = [], False
    for f in files:
        text = _text_cached_fast(f)  # TTL-cached: avoids a stat() per file on bursts
        if len(text) > 2_000_000:
            continue
        if keep is not None:
            # C-level `in` prefilter: skip files that provably cannot match before
            # paying for re.search. Case-insensitive patterns use a cached lower().
            if keep_ci:
                probe = _TEXT_LOWER.get(f)
                probe = probe[1] if (probe and probe[0] == _TEXT.get(f, (0.0,))[0]) else text.lower()
            else:
                probe = text
            if not keep(probe):
                continue
        if not rx_file.search(text):  # whole-file pre-check: most files have no hit
            continue
        for i, line in enumerate(_lines(f), 1):
            if rx.search(line):
                out.append({"path": f, "line": i, "text": line.strip()[:200]})
                if len(out) >= max_hits:
                    return out, True
    return out, truncated


_STRING_RE = re.compile(r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')')
_COMMENT_RE = re.compile(r"(#[^\n]*|//[^\n]*)")


def _code_only(text: str) -> str:
    """Drop string literals and comments so a name mentioned in an example string
    or a comment does not count as the code using it."""
    return _COMMENT_RE.sub(" ", _STRING_RE.sub(" ", text))


_OUTLINE: dict[str, tuple[float, list[dict]]] = {}
_LINES: dict[str, tuple[float, list[str]]] = {}
_TEXT: dict[str, tuple[float, str]] = {}
_TEXT_LOWER: dict[str, tuple[float, str]] = {}
_FILES: list[str] | None = None


def _norm(p: str) -> str:
    return str(p or "").replace("\\", "/").lstrip("./")


def _skipped(rel: str) -> bool:
    parts = _norm(rel).split("/")
    return any(p in SKIP_DIRS or p.startswith(".venv") for p in parts[:-1])


def _abs(rel: str) -> Path:
    return REPO / _norm(rel)


def _mtime(rel: str) -> float:
    try:
        return _abs(rel).stat().st_mtime
    except OSError:
        return 0.0


def _lines(rel: str) -> list[str]:
    rel = _norm(rel)
    m = _mtime(rel)
    hit = _LINES.get(rel)
    if hit and hit[0] == m:
        return hit[1]
    try:
        text = _abs(rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    lines = text.splitlines()
    _LINES[rel] = (m, lines)
    _TEXT[rel] = (m, text)
    return lines


def _text(rel: str) -> str:
    rel = _norm(rel)
    hit = _TEXT.get(rel)
    if hit and hit[0] == _mtime(rel):
        return hit[1]
    _lines(rel)
    return _TEXT.get(rel, (0.0, ""))[1]


def _text_lower(rel: str) -> str:
    """mtime-cached lowercased file text, for case-insensitive grep prefilters."""
    rel = _norm(rel)
    m = _mtime(rel)
    hit = _TEXT_LOWER.get(rel)
    if hit and hit[0] == m:
        return hit[1]
    low = _text(rel).lower()
    _TEXT_LOWER[rel] = (m, low)
    return low


# A whole-repo grep validates every file's mtime (one stat() each ~= 300ms over
# ~5k files). Back-to-back locate calls do not need a fresh stat per file every
# time — the engine's own sync debounce is ~1s. So within a short window we reuse
# the cached text without re-stat'ing. Edits are still reflected within TTL, and a
# changed file only risks a slightly stale line number for <=TTL, self-correcting.
_GREP_STAT_TTL_S = 10.0
# Effective stat-TTL. The idle keepalive raises this to cover its pulse interval so
# the whole warmed set stays "validated" across an idle gap (the keepalive re-stamps
# every file each pulse, so a file is only ever trusted for one interval between
# physical re-stats — edits still self-correct within one keepalive interval).
_STAT_TTL_EFFECTIVE_S = 10.0
_TEXT_VALIDATED_AT: dict[str, float] = {}


def _text_cached_fast(rel: str) -> str:
    """Return file text, skipping the per-file stat() when it was validated within
    the TTL. Falls back to the normal mtime-checked read on a cold/expired entry."""
    rel = _norm(rel)
    now = time.time()
    seen = _TEXT_VALIDATED_AT.get(rel)
    if seen is not None and (now - seen) < _STAT_TTL_EFFECTIVE_S:
        hit = _TEXT.get(rel)
        if hit is not None:
            return hit[1]
    text = _text(rel)  # does the mtime stat + (re)read if changed
    _TEXT_VALIDATED_AT[rel] = now
    return text


def _py_outline(rel: str) -> list[dict]:
    """Functions/classes/methods with line ranges, from Python's own AST.
    Same data the engine's /v1/outline returns (it is Python-AST only too), but
    local: no HTTP round-trip per file."""
    import ast
    try:
        # Strip a leading UTF-8 BOM: _text() reads as plain utf-8, so a BOM
        # survives as U+FEFF at offset 0, which ast.parse rejects
        # ("invalid non-printable character U+FEFF") -> empty outline -> focus
        # cannot resolve ANY symbol in that file while find still works. Dropping
        # the single BOM char keeps every line number identical.
        tree = ast.parse(_text(rel).lstrip("\ufeff"))
    except (SyntaxError, ValueError):
        return []
    out: list[dict] = []

    def walk(node, prefix: str, in_class: bool):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{ch.name}"
                kind = "class" if isinstance(ch, ast.ClassDef) else ("method" if in_class else "function")
                start = min([ch.lineno] + [d.lineno for d in getattr(ch, "decorator_list", [])])
                out.append({"kind": kind, "symbol": name, "line": start,
                            "end_line": getattr(ch, "end_lineno", ch.lineno) or ch.lineno})
                if isinstance(ch, ast.ClassDef):
                    walk(ch, name + ".", True)

    walk(tree, "", False)
    out.sort(key=lambda s: s["line"])
    return out


def _outline(rel: str) -> list[dict]:
    rel = _norm(rel)
    m = _mtime(rel)
    hit = _OUTLINE.get(rel)
    if hit and hit[0] == m:
        return hit[1]
    syms: list[dict] = []
    suf = Path(rel).suffix.lower()
    if suf in (".py", ".pyi"):
        syms = _py_outline(rel)
    elif _lang_outline_supports(suf):
        # Tree-sitter outline for TS/JS/Go/Rust/Java/C/C++/Ruby/C# etc. — the
        # same grammars Scubiee indexes with. Without this, focus could resolve
        # symbols ONLY in Python (the engine /v1/outline is Python-AST-only and
        # reports language_unsupported for everything else).
        try:
            from pipeline.map_lang_outline import outline_text
            syms = outline_text(suf, _text(rel))
        except Exception:  # noqa: BLE001
            syms = []
        if not syms:
            # grammar missing or parse failed -> fall back to the engine route
            # (also Python-only, but harmless) so behavior is never worse.
            try:
                r = _http("/v1/outline", {"file": rel, "root": str(REPO)}, timeout=30)
                syms = [s for s in (r.get("symbols") or []) if s.get("line")]
            except Exception:  # noqa: BLE001
                syms = []
    elif suf in SOURCE_EXT:
        try:  # engine route for any supported ext without a bundled grammar
            r = _http("/v1/outline", {"file": rel, "root": str(REPO)}, timeout=30)
            syms = [s for s in (r.get("symbols") or []) if s.get("line")]
        except Exception:  # noqa: BLE001
            syms = []
    _OUTLINE[rel] = (m, syms)
    return syms


def _lang_outline_supports(suf: str) -> bool:
    try:
        from pipeline.map_lang_outline import supports
        return supports(suf)
    except Exception:  # noqa: BLE001
        return False


_NONCODE: dict[str, tuple[float, dict[int, list[tuple[int, int]]]]] = {}


def _noncode_spans(rel: str) -> dict[int, list[tuple[int, int]]]:
    """line -> [(col_start, col_end)] covered by string literals or comments.
    Python files use the tokenizer; other languages get a per-line regex."""
    rel = _norm(rel)
    m = _mtime(rel)
    hit = _NONCODE.get(rel)
    if hit and hit[0] == m:
        return hit[1]
    spans: dict[int, list[tuple[int, int]]] = {}
    src = _lines(rel)

    def add(r0, c0, r1, c1):
        for r in range(r0, r1 + 1):
            a = c0 if r == r0 else 0
            b = c1 if r == r1 else len(src[r - 1]) if r - 1 < len(src) else 10 ** 6
            spans.setdefault(r, []).append((a, b))

    if Path(rel).suffix.lower() in (".py", ".pyi"):
        import io
        import token
        import tokenize
        noncode = {token.STRING, token.COMMENT}
        for nm in ("FSTRING_MIDDLE", "FSTRING_START", "FSTRING_END"):
            if hasattr(token, nm):
                noncode.add(getattr(token, nm))
        try:
            for tok in tokenize.generate_tokens(io.StringIO(_text(rel)).readline):
                if tok.type in noncode:
                    add(tok.start[0], tok.start[1], tok.end[0], tok.end[1])
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
    else:
        for i, line in enumerate(src, 1):
            for mm in list(_STRING_RE.finditer(line)) + list(_COMMENT_RE.finditer(line)):
                add(i, mm.start(), i, mm.end())
    _NONCODE[rel] = (m, spans)
    return spans


def _uses_in_code(rel: str, line_no: int, name: str) -> bool:
    """True if `name` appears on this line outside strings and comments."""
    src = _lines(rel)
    if not (0 < line_no <= len(src)):
        return False
    line = src[line_no - 1]
    spans = _noncode_spans(rel).get(line_no, [])
    for mm in re.finditer(rf"\b{re.escape(name)}\b", line):
        if not any(a <= mm.start() < b for a, b in spans):
            return True
    return False


def _code_text(rel: str, a: int, b: int) -> str:
    """Lines a..b with strings and comments blanked out."""
    src = _lines(rel)
    spans = _noncode_spans(rel)
    out = []
    for n in range(max(1, a), min(len(src), b) + 1):
        chars = list(src[n - 1])
        for s, e in spans.get(n, []):
            for k in range(s, min(e, len(chars))):
                chars[k] = " "
        out.append("".join(chars))
    return "\n".join(out)


def _repo_files() -> list[str]:
    global _FILES
    if _FILES is None:
        # os.scandir recursion instead of os.walk + relpath/join per file: the
        # dirent type is read from the directory entry (no extra stat), and the
        # relative path is a slice of the already-known absolute path. Output is
        # byte-identical to the old walk (same _norm, same sort) — see
        # scripts/perf/probe_repowalk_ab.py — at roughly half the time (~290ms→~130ms
        # for ~8k files), which shrinks the first-call/warm-thread startup tax.
        root = str(REPO)
        base = len(root) + 1
        out: list[str] = []
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.is_dir(follow_symlinks=False):
                            nm = e.name
                            if nm in SKIP_DIRS or nm.startswith(".venv"):
                                continue
                            stack.append(e.path)
                        else:
                            out.append(_norm(e.path[base:]))
            except OSError:
                continue
        _FILES = sorted(out)
    return _FILES


def _kind_of(rel: str) -> str:
    rel = _norm(rel)
    name = rel.rsplit("/", 1)[-1]
    suf = Path(rel).suffix.lower()
    if ("/tests/" in f"/{rel}" or rel.startswith("tests/") or name.startswith("test_")
            or name.endswith(("_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js", "_test.go"))):
        return "tests"
    if suf in DOC_EXT or rel.startswith("docs/"):
        return "docs"
    if suf in SOURCE_EXT:
        return "code"
    return "other"


def _in_scope(rel: str, scope: str) -> bool:
    k = _kind_of(rel)
    if scope == "all":
        return k != "other" or Path(rel).suffix.lower() in {".json", ".toml", ".yaml", ".yml"}
    return k == scope


def _enclosing(rel: str, line: int) -> dict | None:
    """Smallest symbol whose range contains `line`."""
    best = None
    for s in _outline(rel):
        a, b = int(s.get("line") or 0), int(s.get("end_line") or s.get("line") or 0)
        if a <= line <= b and (best is None or (b - a) < (best["end_line"] - best["line"])):
            best = {"symbol": s.get("symbol"), "kind": s.get("kind"), "line": a, "end_line": b}
    return best


def _resolve_file(given: str) -> tuple[str | None, list[str]]:
    g = _norm(given)
    if g and _abs(g).is_file():
        return g, []
    files = _repo_files()
    cands = [f for f in files if f.endswith("/" + g) or f == g]
    if not cands:
        base = g.rsplit("/", 1)[-1]
        cands = [f for f in files if f.rsplit("/", 1)[-1] == base]
    if not cands:
        names = [f.rsplit("/", 1)[-1] for f in files]
        close = difflib.get_close_matches(g.rsplit("/", 1)[-1], names, n=5, cutoff=0.6)
        return None, [f for f in files if f.rsplit("/", 1)[-1] in close][:5]
    cands.sort(key=lambda f: (_kind_of(f) != "code", len(f)))
    return cands[0], cands[1:4]


# ---------------------------------------------------------------------------
# output helpers (budget, line numbers, seen marking)
# ---------------------------------------------------------------------------


class Out:
    def __init__(self, budget: int):
        self.budget = max(500, int(budget))
        self.lines: list[str] = []
        self.used = 0
        self.dropped = 0

    def add(self, line: str = "", force: bool = False) -> bool:
        cost = len(line) + 1
        if not force and self.used + cost > self.budget:
            self.dropped += 1
            return False
        self.lines.append(line)
        self.used += cost
        return True

    def room(self) -> int:
        return self.budget - self.used

    def text(self) -> str:
        if self.dropped:
            self.lines.append(f"[budget {self.budget} chars reached: {self.dropped} more lines not shown]")
        return "\n".join(self.lines)


def _numbered(rel: str, a: int, b: int, limit_chars: int) -> tuple[list[str], int]:
    """Lines a..b (1-based, inclusive) with line numbers; returns (lines, last_line_shown)."""
    src = _lines(rel)
    a, b = max(1, a), min(len(src), b)
    out, used, last = [], 0, a - 1
    for n in range(a, b + 1):
        row = f"{n}: {src[n - 1].rstrip()}"
        if used + len(row) + 1 > limit_chars:
            break
        out.append(row)
        used += len(row) + 1
        last = n
    return out, last


_SEEN: dict[str, list[tuple[int, int, float, int]]] = {}
_CALL_NO = [0]


def _seen_check(rel: str, a: int, b: int) -> int | None:
    m = _mtime(rel)
    for sa, sb, sm, call in _SEEN.get(rel, []):
        if sm == m and sa <= a and b <= sb:
            return call
    return None


def _seen_mark(rel: str, a: int, b: int) -> None:
    _SEEN.setdefault(rel, []).append((a, b, _mtime(rel), _CALL_NO[0]))


def _seen_upto(rel: str, a: int) -> tuple[int, int | None]:
    """Last line already shown contiguously from line `a` (a-1 if none), and the
    call that showed it. Lets a repeated request continue instead of restarting."""
    m = _mtime(rel)
    upto, call = a - 1, None
    changed = True
    while changed:
        changed = False
        for sa, sb, sm, c in _SEEN.get(rel, []):
            if sm == m and sa <= upto + 1 <= sb and sb > upto:
                upto, call, changed = sb, c, True
    return upto, call


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text or "") if w.lower() not in STOP]


def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[,\n]", v) if x.strip()]
    return [str(x).strip() for x in v if str(x).strip()]


# ---------------------------------------------------------------------------
# config: find
# ---------------------------------------------------------------------------


def cfg_find(a: dict) -> str:
    query = str(a.get("query") or "").strip()
    keywords = _as_list(a.get("keywords"))
    if not query and not keywords:
        return "error: find needs query (short intent), e.g. map config=find query=\"where X is computed\" keywords=[\"name\"]"
    scope = str(a.get("scope") or "code")
    k = max(1, min(20, int(a.get("k") or 8)))
    w = float(a.get("keyword_weight") if a.get("keyword_weight") is not None else 0.6) if keywords else 0.0
    out = Out(int(a.get("budget_chars") or DEFAULT_BUDGET["find"]))

    sem_q = (query + " " + " ".join(keywords)).strip()
    hits = _search(sem_q, top_k=max(24, 3 * k))
    max_score = max([float(h.get("score") or 0) for h in hits] or [1.0]) or 1.0
    kw_l = [x.lower() for x in keywords]
    # Lexical signal: the caller's keywords (exact names, weight w), or, without
    # keywords, the content words of the query (weight 0.3) as a light tie-breaker
    # on the engine's semantic rank.
    qwords = sorted({x.lower() for x in _words(query) if len(x) >= 4})
    wq = 0.3 if (not keywords and qwords) else 0.0

    cands: dict[tuple, dict] = {}

    def add_cand(rel: str, a_: int, b_: int, sem: float, src: str):
        rel = _norm(rel)
        enc = _enclosing(rel, a_)
        if enc and enc["end_line"] - enc["line"] <= 400:
            key = (rel, enc["line"])
            sym, kind, sa, sb = enc["symbol"], enc["kind"], enc["line"], enc["end_line"]
        else:
            key = (rel, a_)
            sym, kind, sa, sb = None, None, a_, b_
        if key in cands and cands[key]["sem"] >= sem:
            return
        code = _code_text(rel, sa, sb).lower()
        present = [kw for kw in kw_l if re.search(rf"\b{re.escape(kw)}\b", code)]
        cov = (len(present) / len(kw_l)) if kw_l else 0.0
        defhit = bool(sym) and any(sym.split(".")[-1].lower() == kw for kw in kw_l)
        full = "\n".join(_lines(rel)[max(0, sa - 1):sb]).lower()
        qcov = (sum(1 for q in qwords if q in full) / len(qwords)) if qwords else 0.0
        if keywords:
            score = (1 - w) * sem + w * min(1.0, cov + (0.25 if defhit else 0.0))
        else:
            score = (1 - wq) * sem + wq * qcov
        if sym and qwords:
            # query words that appear in the symbol's own name (faiss_import_ok for
            # "...faiss imports...") are strong evidence the symbol is the answer
            parts = set(re.split(r"[_.]+", sym.lower()))
            name_hit = sum(1 for q in qwords if any(p and (p.startswith(q[:5]) or q.startswith(p[:5]))
                                                    for p in parts if len(p) >= 3))
            score += 0.08 * min(3, name_hit)
        if sym is None and (sb - sa) <= 3:
            score *= 0.7  # a bare module docstring line carries little code
        cands[key] = {"file": rel, "symbol": sym, "kind": kind, "start": sa, "end": sb,
                      "hit_start": a_, "hit_end": b_, "sem": sem, "cov": cov, "defhit": defhit,
                      "score": score, "src": src, "raw": sem * max_score}

    for h in hits:
        add_cand(h.get("path") or h.get("file"), int(h.get("start_line") or 1),
                 int(h.get("end_line") or h.get("start_line") or 1),
                 float(h.get("score") or 0) / max_score, "semantic")
    if keywords:
        pat = r"(?i)\b(" + "|".join(re.escape(x) for x in keywords[:6]) + r")\b"
        try:
            ghits, _ = _grep(pat, max_hits=200, scope="code" if scope in ("code", "tests") else scope)
        except Exception:  # noqa: BLE001
            ghits = []
        for gh in ghits:
            ln = int(gh.get("line") or 1)
            rel = _norm(gh.get("path"))
            # a name that only shows up in a string or comment is not the code
            if _kind_of(rel) in ("code", "tests") and not any(_uses_in_code(rel, ln, kw) for kw in keywords):
                continue
            add_cand(rel, ln, ln, 0.0, "keyword")

    all_c = sorted(cands.values(), key=lambda c: -c["score"])
    in_scope = [c for c in all_c if _in_scope(c["file"], scope)]
    tests = [c for c in all_c if _kind_of(c["file"]) == "tests"] if scope == "code" else []
    top = in_scope[:k]

    # confidence (heuristic; the reason is shown so the agent can judge)
    conf, reason = "low", "weak or scattered matches"
    if top:
        s1 = top[0]["score"]
        s2 = top[1]["score"] if len(top) > 1 else 0.0
        if keywords and top[0]["cov"] >= 0.999 and top[0]["symbol"] and (top[0]["defhit"] or s1 - s2 >= 0.1):
            conf, reason = "high", "all keywords match in " + _label(top[0])
        elif not keywords and top[0]["symbol"] and (s1 - s2) >= 0.15:
            conf, reason = "high", "top result clearly ahead of the rest"
        elif s1 >= 0.5:
            conf, reason = "medium", "top result plausible; check the lines below"
    if not top or (conf == "low" and keywords and all(c["cov"] == 0 for c in top[:3])):
        return _no_match(out, query, keywords, hits, scope)

    out.add(f"find: {len(top)} results  confidence: {conf} - {reason}", force=True)
    terms = kw_l or qwords
    for i, c in enumerate(top, 1):
        tag = "keyword+semantic" if (c["cov"] > 0 and c["sem"] > 0) else ("keyword" if c["cov"] > 0 else "semantic")
        if not out.add(f"{i}. {c['file']}:{c['start']}-{c['end']}  {c['symbol'] or '(module)'}  [{tag}]"):
            break
        for ln_no, ln_txt in _match_lines(c, terms, 2):
            out.add(f"   {ln_no}: {ln_txt}")
    # Attach BODIES on high/medium confidence. Spend characters to save calls:
    # a body paid once (a few k chars) is far cheaper than the follow-up call it
    # saves (~35k tokens re-paid every later turn). When the relevant hits
    # CLUSTER in the top file, return ALL of their bodies in this one call, so a
    # multi-symbol edit needs no view/refs follow-up at all. Only `low` holds
    # back, where a wrong file would mislead.
    if conf in ("high", "medium") and top[0]["symbol"]:
        c0 = top[0]
        # the hot symbols to show: the top result + any other in-scope result in
        # the SAME file (that is the "whole relevant region" an edit usually
        # touches), de-duplicated and in file order.
        # A2: callers may widen the cluster to the top N files when the top hits
        # span more than one tightly-scored file (a cross-file edit). cluster_files
        # defaults to 1 so the newmap arm is unchanged; map_v3 passes 2.
        n_cluster_files = max(1, int(a.get("cluster_files") or 1))
        cluster_files_set = []
        for c in top:
            if c.get("symbol") and c["file"] not in cluster_files_set:
                # only add a 2nd file if its best hit is close to the top score
                if not cluster_files_set or c["score"] >= top[0]["score"] * 0.75:
                    cluster_files_set.append(c["file"])
            if len(cluster_files_set) >= n_cluster_files:
                break
        cluster = [c for c in top if c.get("symbol") and c["file"] in cluster_files_set]
        seen_keys = set()
        bodies = []
        for c in cluster:
            key = (c["file"], c["start"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            bodies.append(c)
        if len(bodies) > 1:
            _bfiles = list(dict.fromkeys(c["file"] for c in bodies))
            _where = c0["file"] if len(_bfiles) == 1 else f"{len(_bfiles)} files"
            out.add(f"-- bodies: {len(bodies)} relevant symbols in {_where} (edit from these; no follow-up needed) --", force=True)
        for c in bodies:
            if out.room() < 400:
                out.add(f"   (+{len(bodies) - bodies.index(c)} more symbols: map config=view targets=[...])")
                break
            seen = _seen_check(c["file"], c["start"], c["end"])
            if seen:
                out.add(f"-- {_label(c)}: already shown in call #{seen} --")
                continue
            # per-body cap: share the budget across the cluster, floor so each
            # body is substantial; whole budget for a single body.
            cap = BODY_CAP if len(bodies) == 1 else max(900, (out.room() - 300) // max(1, len(bodies) - bodies.index(c)))
            room = min(cap, out.room() - 200)
            if room <= 300:
                break
            out.add(f"-- body of {_label(c)} --", force=True)
            body, last = _numbered(c["file"], c["start"], c["end"], room)
            for row in body:
                out.add(row, force=True)
            if last < c["end"]:
                out.add(f"... +{c['end'] - last} lines: map config=view targets=[\"{c['file']}:{last + 1}-{c['end']}\"]", force=True)
            _seen_mark(c["file"], c["start"], last)
        # how the top symbol connects, so one find answers "where AND how wired".
        # B1: do this on medium too (not just high) so the body always carries the
        # wiring + the no-refocus note - the medium case is where the agent most
        # often made a wasted follow-up focus/refs call.
        if conf in ("high", "medium") and out.room() > 400:
            _append_connections(out, c0)
    if tests:
        tl = []
        for t in tests[:3]:
            tl.append(f"{t['file']}::{t['symbol']}" if t["symbol"] else f"{t['file']}:{t['start']}")
        out.add("related tests: " + ", ".join(tl))
    nxt = {"high": "the bodies above are the code to change - EDIT from them; no further locate call needed",
           "medium": "the bodies above are the likely code - if right, EDIT from them; else refine the query",
           "low": "rewrite the query, or map config=refs names=[...] if you know a name"}[conf]
    out.add(f"next: {nxt}")
    return out.text()


def _label(c: dict) -> str:
    return f"{c['file']}::{c['symbol']}" if c.get("symbol") else f"{c['file']}:{c['start']}"


def _append_connections(out: "Out", c: dict) -> None:
    """Compact 'connections' block for find's top symbol: direct callers and the
    repo-defined functions it calls, one line each, small cap. Lets a single find
    answer where+how-wired so the agent skips a follow-up refs/view call."""
    rel, sym = c["file"], c["symbol"]
    name = str(sym).split(".")[-1]
    # callers: other code that calls this name (not its own body, not defs)
    callers = []
    try:
        hits, _ = _grep(rf"\b{re.escape(name)}\s*\(", max_hits=60, scope="code")
    except Exception:  # noqa: BLE001
        hits = []
    for h in hits:
        hrel, ln = _norm(h.get("path")), int(h.get("line") or 0)
        if hrel == rel and c["start"] <= ln <= c["end"]:
            continue
        if _def_re(name).search(str(h.get("text") or "")):
            continue
        if not _uses_in_code(hrel, ln, name):
            continue
        enc = _enclosing(hrel, ln)
        callers.append(f"{hrel}:{ln}" + (f" {enc['symbol']}" if enc else ""))
        if len(callers) >= 4:
            break
    # callees: functions THIS body calls that are defined in the repo
    callees = []
    body = _code_text(rel, c["start"] + 1, c["end"])
    local = {str(s.get("symbol") or "").split(".")[-1]: s for s in _outline(rel)}
    seen_c = set()
    for m in re.finditer(r"(?<![\w.])(?:(?:self|cls)\.)?([A-Za-z_][A-Za-z0-9_]*)\s*\(", body):
        nm = m.group(1)
        if nm in (name,) or nm in PY_KEYWORDS or nm in seen_c:
            continue
        seen_c.add(nm)
        if nm in local:
            callees.append(f"{rel}:{local[nm]['line']} {nm}")
        if len(callees) >= 4:
            break
    if callers or callees:
        out.add("-- connections --")
        if callers:
            out.add("  callers: " + "; ".join(callers))
        if callees:
            out.add("  calls (same file): " + "; ".join(callees))
        # B1/T3: the wiring is HERE - steer away from the reflex follow-up locate
        # call (refs in map_v2, focus in map_v3) that sessions showed was the #1
        # wasted turn. Only re-locate for a rename needing EVERY use site.
        out.add("  (you already have this symbol's code AND wiring - do NOT focus/refs/grep it "
                "again; only re-locate for a rename that must touch EVERY use site)")


def _match_lines(c: dict, terms: list[str], n: int) -> list[tuple[int, str]]:
    src = _lines(c["file"])
    scored = []
    for ln in range(c["start"], min(c["end"], len(src)) + 1):
        t = src[ln - 1]
        low = t.lower()
        sc = sum(1 for term in terms if term in low)
        if sc:
            scored.append((sc, ln, t.strip()[:140]))
    if not scored:
        ln = max(c["start"], c["hit_start"])
        if 1 <= ln <= len(src):
            return [(ln, src[ln - 1].strip()[:140])]
        return []
    scored.sort(key=lambda x: (-x[0], x[1]))
    return sorted([(ln, t) for _, ln, t in scored[:n]])


def _no_match(out: Out, query: str, keywords: list[str], hits: list[dict], scope: str) -> str:
    out.add(f"find: no confident match in scope={scope}", force=True)
    names = set()
    for h in hits[:10]:
        for s in _outline(h.get("path") or ""):
            names.add(str(s.get("symbol") or "").split(".")[-1])
    sugg = []
    for kw in keywords:
        sugg += difflib.get_close_matches(kw, sorted(names), n=3, cutoff=0.5)
    if sugg:
        out.add("similar names that exist: " + ", ".join(dict.fromkeys(sugg)))
    words = [x.lower() for x in _words(query + " " + " ".join(keywords)) if len(x) >= 4]
    files = [f for f in _repo_files() if any(wd in f.rsplit("/", 1)[-1].lower() for wd in words)]
    files.sort(key=lambda f: (_kind_of(f) != "code", len(f)))
    if files:
        out.add("files with matching names: " + ", ".join(files[:5]))
    if hits:
        h = hits[0]
        out.add(f"closest semantic hit (outside scope or weak): {_norm(h.get('path'))}:{h.get('start_line')}-{h.get('end_line')}")
    alt = " ".join(_words(query)[:5])
    out.add(f"next: try map config=find query=\"{alt}\" scope=all, or map config=view path=<dir> query=<name>")
    return out.text()


# ---------------------------------------------------------------------------
# config: refs
# ---------------------------------------------------------------------------


def _def_re(name: str) -> re.Pattern:
    n = re.escape(name)
    return re.compile(
        rf"^\s*(?:export\s+)?(?:public\s+|private\s+|static\s+)*(?:async\s+)?"
        rf"(?:def|class|function|func|fn|interface|type|struct|enum|trait)\s+(?:\([^)]*\)\s*)?{n}\b"
        rf"|^\s*(?:export\s+)?(?:const|let|var)\s+{n}\s*="
        rf"|^{n}\s*(?::[^=]+)?=(?!=)")


def _classify(rel: str, line_no: int, text: str, name: str) -> str:
    if _kind_of(rel) in ("code", "tests") and not _uses_in_code(rel, line_no, name):
        return "mention"  # only inside a string literal or a comment
    if _def_re(name).search(text):
        return "def"
    if re.search(r"\bimport\b|\brequire\(|\buse\s", text):
        return "imports"
    stripped = text.strip()
    if re.fullmatch(rf"{re.escape(name)}(\s+as\s+\w+)?,?", stripped):
        src = _lines(rel)
        for back in range(line_no - 1, max(0, line_no - 40), -1):
            prev = src[back - 1]
            if re.search(r"\bimport\s*[({]", prev) or re.search(r"^\s*from\s+\S+\s+import\s*\($", prev):
                return "imports"
            if ")" in prev or "}" in prev:
                break
    return "uses"


def cfg_refs(a: dict) -> str:
    raw_names = _as_list(a.get("names") or a.get("keywords") or a.get("target"))
    # accept file::symbol or file:line and reduce to the bare identifier for the
    # occurrence grep (refs looks up a NAME across the repo, not a located span)
    names = []
    for nm in raw_names:
        if "::" in nm:
            nm = nm.split("::", 1)[1]
        nm = nm.split(".")[-1].strip()
        nm = re.split(r"[:\s(]", nm)[0]
        if nm and nm not in names:
            names.append(nm)
    if not names:
        return "error: refs needs names, e.g. map config=refs names=[\"git_dirty_files\"] kind=uses"
    kind = str(a.get("kind") or "all")
    scope = str(a.get("scope") or "code")   # code = source + tests; docs counted, not listed
    out = Out(int(a.get("budget_chars") or DEFAULT_BUDGET["refs"]))
    pat = r"\b(" + "|".join(re.escape(n) for n in names[:8]) + r")\b"
    hits, truncated = _grep(pat, max_hits=800, scope="all")
    list_areas = {"code": ("code", "tests"), "tests": ("tests",), "docs": ("docs",),
                  "all": ("code", "tests", "docs", "other")}.get(scope, ("code", "tests"))

    rows = []
    for h in hits:
        rel = _norm(h.get("path"))
        text = str(h.get("text") or "")
        nm = next((n for n in names if re.search(rf"\b{re.escape(n)}\b", text)), names[0])
        ln = int(h.get("line") or 0)
        rows.append({"file": rel, "line": ln, "text": text.strip()[:140], "name": nm,
                     "kind": _classify(rel, ln, text, nm), "area": _kind_of(rel)})
    if kind != "all":
        want = {"def": "def", "defs": "def", "uses": "uses", "use": "uses", "imports": "imports", "import": "imports"}.get(kind, kind)
        rows_k = [r for r in rows if r["kind"] == want]
    else:
        rows_k = list(rows)
    rows_k = [r for r in rows_k if r["area"] in list_areas]

    for n in names:
        mine = [r for r in rows if r["name"] == n]
        c = {kk: sum(1 for r in mine if r["kind"] == kk) for kk in ("def", "uses", "imports", "mention")}
        areas = {ar: sum(1 for r in mine if r["area"] == ar and r["kind"] != "mention")
                 for ar in ("code", "tests", "docs")}
        out.add(f"{n} - {c['def']} def, {c['uses']} uses, {c['imports']} imports "
                f"({c['def'] + c['uses'] + c['imports']} total: code {areas['code']}, tests {areas['tests']}, docs {areas['docs']}"
                + (f"; {c['mention']} more only in strings/comments" if c["mention"] else "") + ")"
                + ("  [search capped: more exist]" if truncated else ""), force=True)
    rows_k = [r for r in rows_k if r["kind"] != "mention"]
    want_kind = None if kind == "all" else {"defs": "def", "use": "uses", "import": "imports"}.get(kind, kind)
    hidden = sum(1 for r in rows if r["kind"] != "mention" and r["area"] not in list_areas
                 and (want_kind is None or r["kind"] == want_kind))
    if hidden:
        if rows_k:
            out.add(f"(listing scope={scope}; {hidden} more in docs/other: scope=all to list them)")
        else:
            out.add(f"no {want_kind or 'occurrences'} in scope={scope}; {hidden} in docs/other - scope=all to list them")
    if not any(r["kind"] != "mention" for r in rows):
        alts = []
        for n in names:
            syms = set()
            for f in _repo_files():
                if _kind_of(f) == "code" and n[:4].lower() in f.lower():
                    for s in _outline(f)[:50]:
                        syms.add(str(s.get("symbol") or "").split(".")[-1])
            alts += difflib.get_close_matches(n, sorted(syms), n=3, cutoff=0.5)
        if alts:
            out.add("no occurrences. similar names: " + ", ".join(dict.fromkeys(alts)))
        out.add("next: map config=find query=<what it does> if you're not sure of the name")
        return out.text()

    order = {"code": 0, "tests": 1, "docs": 2, "other": 3}
    kind_order = {"def": 0, "imports": 1, "uses": 2, "mention": 3}
    rows_k.sort(key=lambda r: (kind_order[r["kind"]], order[r["area"]], r["file"], r["line"]))
    shown = 0
    cur = None
    for r in rows_k:
        head = f"{r['kind']}" + ("" if r["area"] == "code" else f" ({r['area']})")
        if head != cur:
            if not out.add(f"{head}:"):
                break
            cur = head
        enc = _enclosing(r["file"], r["line"]) if r["kind"] == "uses" else None
        where = f"  in {enc['symbol']}" if enc else ""
        if not out.add(f"  {r['file']}:{r['line']}{where}  {r['text']}"):
            break
        shown += 1
    if shown < len(rows_k):
        out.add(f"showing {shown} of {len(rows_k)} - narrow with kind= or scope=code|tests|docs")
    return out.text()


# ---------------------------------------------------------------------------
# config: open
# ---------------------------------------------------------------------------


def _parse_target(t: str) -> tuple[str, str | None, int | None, int | None]:
    t = t.strip().strip("`")
    if "::" in t:
        f, sym = t.split("::", 1)
        return f, sym.strip(), None, None
    m = re.match(r"^(.*?):(\d+)(?:-(\d+))?$", t)
    if m:
        return m.group(1), None, int(m.group(2)), int(m.group(3)) if m.group(3) else None
    return t, None, None, None


def _resolve_symbol_name(name: str) -> dict | None:
    """Find where a BARE symbol name (no file path) is defined, so relation kinds
    like `refs kind=callers names=["git_dirty_files"]` work without the caller
    knowing the file. Prefer a real def site in code/packages; fall back to the
    top semantic hit's enclosing symbol."""
    ident = name.split(".")[-1].strip()
    if not ident or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", ident):
        return None
    esc = re.escape(ident)
    # Keyword-led definitions (Python def/class, JS/TS function/class, Go func,
    # Rust fn/struct/enum/trait/impl, Ruby def/class/module, Kotlin fun, etc.).
    kw = (r"^\s*(?:(?:pub|public|private|protected|internal|static|final|async|"
          r"export|default|abstract|override|open|suspend|inline|const)\s+)*"
          r"(?:def|class|function|func|fn|struct|enum|trait|impl|interface|module|"
          r"type|object|record|val|var|fun)\s+" + esc + r"\b")
    # Keyword-LESS definitions: Java/C/C++/C# methods `... NAME(` where NAME is
    # immediately followed by `(` (declaration), and type-y `... NAME {`.
    nodecl = r"\b" + esc + r"\s*[(<]"
    patterns = [kw, nodecl]
    hits: list[dict] = []
    seen_lines: set = set()
    for pat in patterns:
        try:
            hs, _ = _grep(pat, max_hits=60, scope="code")
        except Exception:  # noqa: BLE001
            hs = []
        for h in hs:
            key = (_norm(h.get("path")), int(h.get("line") or 0))
            if key not in seen_lines:
                seen_lines.add(key)
                hits.append(h)
    # Rank candidates: real code first, then tests, then docs/other — but do NOT
    # drop tests. A symbol that lives ONLY in a test file (a test class/helper
    # like CacheTest, or Go's *_test.go helpers) must still resolve by bare name;
    # hard-filtering to kind=="code" made focus report "could not resolve" for
    # every test-only symbol. Keep the code-first preference via the sort key.
    _kind_rank = {"code": 0, "tests": 1, "docs": 2, "other": 3}

    def _rank(h: dict) -> tuple:
        rel = _norm(h.get("path"))
        return (
            _kind_rank.get(_kind_of(rel), 3),
            0 if rel.startswith("packages/") else 1,
            len(rel),
        )

    hits = [h for h in hits if _kind_of(_norm(h.get("path"))) in _kind_rank]
    hits.sort(key=_rank)
    # A hit confirms ONLY when the file's (now multi-language) outline agrees that
    # a symbol with this leaf name actually encloses that line — this is what
    # makes resolution correct across languages, not just a lucky grep.
    for h in hits:
        rel = _norm(h.get("path"))
        enc = _enclosing(rel, int(h.get("line") or 1))
        if enc and str(enc["symbol"]).split(".")[-1] == ident:
            return {"file": rel, "symbol": enc["symbol"], "start": enc["line"],
                    "end": enc["end_line"], "note": "(resolved bare name to its definition)"}
    # Direct outline scan: for languages/shapes the grep patterns above miss, ask
    # each candidate file's outline directly for a symbol with this leaf name.
    for h in hits[:12]:
        rel = _norm(h.get("path"))
        for s in _outline(rel):
            if str(s.get("symbol") or "").split(".")[-1] == ident:
                return {"file": rel, "symbol": s["symbol"], "start": int(s["line"]),
                        "end": int(s.get("end_line") or s["line"]),
                        "note": "(resolved bare name via outline)"}
    # Plain-identifier fallback: the keyword/decl patterns miss some real
    # definition shapes (C `struct __attribute__((packed)) Name`, Rust `mod x;`,
    # macro-wrapped decls). Grep for the bare word, then let each file's outline
    # confirm — the outline is authoritative, so this adds recall without false
    # positives. Ranked code-first, tests included (same as above).
    try:
        plain_hits, _ = _grep(r"\b" + esc + r"\b", max_hits=80, scope="code")
    except Exception:  # noqa: BLE001
        plain_hits = []
    seen_files: set = set()
    plain_rels = []
    for h in sorted(plain_hits, key=_rank):
        rel = _norm(h.get("path"))
        if rel not in seen_files:
            seen_files.add(rel)
            plain_rels.append(rel)
    for rel in plain_rels[:20]:
        for s in _outline(rel):
            if str(s.get("symbol") or "").split(".")[-1] == ident:
                return {"file": rel, "symbol": s["symbol"], "start": int(s["line"]),
                        "end": int(s.get("end_line") or s["line"]),
                        "note": "(resolved bare name via outline scan)"}
    # fall back to semantic search's best enclosing symbol. Guard the engine
    # call: _search hits /v1/search over HTTP, which raises if the engine is
    # down or still warming. Bare-name resolution must degrade to None in that
    # case (the grep+outline passes above are engine-free), never propagate an
    # exception up through focus.
    try:
        sem_hits = _search(ident, top_k=8)
    except Exception:  # noqa: BLE001
        sem_hits = []
    for sh in sem_hits:
        rel = _norm(sh.get("path") or sh.get("file"))
        enc = _enclosing(rel, int(sh.get("start_line") or 1))
        if enc and str(enc["symbol"]).split(".")[-1] == ident:
            return {"file": rel, "symbol": enc["symbol"], "start": enc["line"],
                    "end": enc["end_line"], "note": "(resolved bare name via search)"}
    return None


def _locate_target(t: str) -> dict:
    fgiven, sym, a, b = _parse_target(t)
    rel, others = _resolve_file(fgiven)
    if rel is None:
        # bare symbol name (no path, no line) -> resolve to its definition so
        # relation kinds work with just a name. (Fixes: refs kind=callers
        # names=["bare_name"] -> "file not found".)
        if sym is None and a is None and "/" not in fgiven and "." not in fgiven.rstrip():
            res = _resolve_symbol_name(fgiven)
            if res:
                return res
        return {"error": f"file not found: {fgiven}" + (f" (did you mean: {', '.join(others)})" if others else "")}
    note = f"(also matches: {', '.join(others)})" if others else ""
    syms = _outline(rel)
    if sym:
        exact = [s for s in syms if s.get("symbol") == sym]
        tail = [s for s in syms if str(s.get("symbol") or "").split(".")[-1] == sym.split(".")[-1]]
        pick = (exact or tail)
        if not pick:
            close = difflib.get_close_matches(sym, [str(s.get("symbol")) for s in syms], n=3, cutoff=0.5)
            return {"error": f"symbol {sym} not in {rel}" + (f" (close: {', '.join(close)})" if close else "")}
        s = pick[0]
        more = [str(x.get("symbol")) for x in pick[1:3]]
        return {"file": rel, "symbol": s.get("symbol"), "start": int(s["line"]),
                "end": int(s.get("end_line") or s["line"]),
                "note": " ".join(x for x in (note, f"(also: {', '.join(more)})" if more else "") if x)}
    if a is not None and b is not None:
        return {"file": rel, "symbol": None, "start": a, "end": b, "note": note}
    if a is not None:
        enc = _enclosing(rel, a)
        if enc:
            return {"file": rel, "symbol": enc["symbol"], "start": enc["line"], "end": enc["end_line"], "note": note}
        return {"file": rel, "symbol": None, "start": max(1, a - 15), "end": a + 15, "note": note}
    return {"file": rel, "symbol": None, "start": None, "end": None, "note": note}


def cfg_open(a: dict) -> str:
    targets = _as_list(a.get("targets") or a.get("target"))
    if not targets:
        return "error: view needs targets, e.g. map config=view targets=[\"freshness.py::git_dirty_files\", \"server.py:791\"]"
    margin = max(0, min(60, int(a.get("margin") if a.get("margin") is not None else 10)))
    out = Out(int(a.get("budget_chars") or DEFAULT_BUDGET["open"]))
    per = max(800, out.budget // max(1, len(targets)))
    for t in targets[:10]:
        loc = _locate_target(t)
        if "error" in loc:
            out.add(f"== {t}: {loc['error']}", force=True)
            continue
        rel = loc["file"]
        if loc["start"] is None:  # whole file requested -> outline instead of the whole body
            out.add(f"== {rel}: file outline (ask for file::symbol or file:start-end to get code)", force=True)
            for row in _outline_file_rows(rel)[:40]:
                if not out.add("  " + row):
                    break
            continue
        # Start at the symbol (decorators included), plus any comment lines that
        # sit directly above it; the margin goes after, where agents read on.
        src = _lines(rel)
        a_ = max(1, loc["start"])
        while a_ > 1 and src[a_ - 2].strip().startswith(("#", "//", "@")):
            a_ -= 1
        b_ = min(len(src), loc["end"] + margin)
        label = f"{rel}::{loc['symbol']}" if loc["symbol"] else f"{rel}:{loc['start']}-{loc['end']}"
        upto, seen = _seen_upto(rel, loc["start"])
        if seen and upto >= loc["end"]:
            out.add(f"== {label}  lines {loc['start']}-{loc['end']}: already shown in call #{seen} (unchanged)", force=True)
            continue
        if seen and upto >= loc["start"]:
            out.add(f"== {label}  lines {loc['start']}-{upto} already shown in call #{seen}; continuing", force=True)
            a_ = upto + 1
        out.add(f"== {label}  lines {a_}-{b_} {loc['note']}".rstrip(), force=True)
        body, last = _numbered(rel, a_, b_, min(per, max(300, out.room())))
        for row in body:
            out.add(row, force=True)
        if last < b_:
            out.add(f"... +{b_ - last} lines: map config=view targets=[\"{rel}:{last + 1}-{b_}\"]", force=True)
        _seen_mark(rel, a_, last)
    return out.text()


# ---------------------------------------------------------------------------
# config: around
# ---------------------------------------------------------------------------


def cfg_around(a: dict) -> str:
    target = str(a.get("target") or (_as_list(a.get("targets")) or [""])[0]).strip()
    if not target:
        return "error: refs needs a name, e.g. map config=refs names=[\"token_meter.py::compare_queries\"] kind=callers"
    want = set(_as_list(a.get("want")) or ["callers", "callees", "tests"])
    out = Out(int(a.get("budget_chars") or DEFAULT_BUDGET["around"]))
    loc = _locate_target(target)
    if "error" in loc:
        return f"around: {loc['error']}"
    if not loc.get("symbol"):
        return "around: target must name a symbol (file::symbol or file:line inside a function)"
    rel, sym = loc["file"], str(loc["symbol"])
    name = sym.split(".")[-1]
    out.add(f"around {rel}::{sym}  (lines {loc['start']}-{loc['end']})", force=True)

    if want & {"callers", "tests"}:
        hits, truncated = _grep(rf"\b{re.escape(name)}\b", max_hits=400, scope="code")
        callers, tests, other = {}, {}, 0
        for h in hits:
            hrel, ln = _norm(h.get("path")), int(h.get("line") or 0)
            if hrel == rel and loc["start"] <= ln <= loc["end"]:
                continue
            text = str(h.get("text") or "")
            if _def_re(name).search(text):
                continue
            if not _uses_in_code(hrel, ln, name):
                other += 1  # mentioned only in a string or comment
                continue
            area = _kind_of(hrel)
            enc = _enclosing(hrel, ln)
            key = (hrel, enc["symbol"] if enc else ln)
            entry = f"{hrel}:{ln}" + (f"  in {enc['symbol']}" if enc else "") + f"  {text.strip()[:100]}"
            if area == "tests":
                tests.setdefault(key, entry)
            elif area == "code" and re.search(rf"\b{re.escape(name)}\s*\(|\.{re.escape(name)}\b", text):
                callers.setdefault(key, entry)
            else:
                other += 1
        if "callers" in want:
            out.add(f"callers ({len(callers)}):")
            for e in list(callers.values())[:15]:
                if not out.add("  " + e):
                    break
        if "tests" in want:
            out.add(f"tests ({len(tests)}):")
            for e in list(tests.values())[:8]:
                if not out.add("  " + e):
                    break
        if other:
            out.add(f"other references (docs/config/strings): {other} - map config=refs names=[\"{name}\"] for all")

    if "callees" in want:
        # Bare calls f(...) and self./cls. calls only, on code with strings and
        # comments removed. obj.method(...) on other objects is almost always a
        # library call (str.split, list.append, ...), so it isn't resolved.
        body = _code_text(rel, loc["start"] + 1, loc["end"])
        called = []
        for m in re.finditer(r"(?<![\w.])(?:(?:self|cls)\.)?([A-Za-z_][A-Za-z0-9_]*)\s*\(", body):
            nm = m.group(1)
            if nm and nm != name and nm not in PY_KEYWORDS and nm not in called:
                called.append(nm)
        local = {str(s.get("symbol") or "").split(".")[-1]: s for s in _outline(rel)}
        rows, remote = [], []
        for nm in called[:25]:
            if nm in local:
                s = local[nm]
                rows.append(f"  {rel}:{s['line']}  {s.get('symbol')}  (same file)")
            else:
                remote.append(nm)
        if remote:
            pat = r"^\s*(?:async\s+)?(?:def|class|function|func|fn)\s+(" + "|".join(re.escape(x) for x in remote[:20]) + r")\b"
            try:
                dh, _ = _grep(pat, max_hits=200, scope="code")
            except Exception:  # noqa: BLE001
                dh = []
            # prefer the definition the target file imports, then packages/, then the rest
            imports_txt = _text(rel)
            dh.sort(key=lambda h: (0 if _norm(h.get("path")).rsplit("/", 1)[-1][:-3] in imports_txt else 1,
                                   0 if _norm(h.get("path")).startswith("packages/") else 1))
            found = set()
            for h in dh:
                hrel = _norm(h.get("path"))
                if _kind_of(hrel) != "code":
                    continue
                m = re.search(pat, str(h.get("text") or ""))
                nm = m.group(1) if m else None
                if nm and nm not in found:
                    found.add(nm)
                    rows.append(f"  {hrel}:{h.get('line')}  {nm}")
            unresolved = [x for x in remote if x not in found]
        else:
            unresolved = []
        out.add(f"callees ({len(rows)} resolved in repo):")
        for r_ in rows:
            if not out.add(r_):
                break
        if unresolved:
            out.add("  not defined in repo (library/builtin): " + ", ".join(unresolved[:12]))

    if "siblings" in want:
        sib = [s for s in _outline(rel) if s.get("symbol") != sym and "." not in str(s.get("symbol"))]
        out.add(f"same-file symbols ({len(sib)}):")
        for s in sib[:15]:
            if not out.add(f"  {rel}:{s['line']}-{s.get('end_line')}  {s.get('kind')} {s.get('symbol')}"):
                break
    out.add("next: map config=view targets=[...] with the places you need to read (batch them)")
    return out.text()


# ---------------------------------------------------------------------------
# config: outline
# ---------------------------------------------------------------------------


def _signature(rel: str, s: dict) -> str:
    """The def/class line of a symbol (skipping decorators above it)."""
    src = _lines(rel)
    a, b = int(s["line"]), int(s.get("end_line") or s["line"])
    for n in range(a, min(b, a + 12) + 1):
        t = src[n - 1].strip() if 0 < n <= len(src) else ""
        if t and not t.startswith("@"):
            return t[:100]
    return f"{s.get('kind')} {s.get('symbol')}"


def _outline_file_rows(rel: str) -> list[str]:
    rows = []
    for s in _outline(rel):
        indent = "  " * str(s.get("symbol") or "").count(".")
        rows.append(f"{indent}{s['line']}-{s.get('end_line')}  {_signature(rel, s)}")
    return rows


def _doc_line(rel: str) -> str:
    src = _lines(rel)[:12]
    for i, ln in enumerate(src):
        t = ln.strip()
        if t.startswith(('"""', "'''")):
            body = t.strip('"\' ')
            if body:
                return body[:90]
            if i + 1 < len(src):
                return src[i + 1].strip()[:90]
        if t.startswith(("//", "#")) and len(t) > 3 and not t.startswith("#!"):
            return t.lstrip("/# ")[:90]
    return ""


def cfg_outline(a: dict) -> str:
    path = str(a.get("path") or ".").strip() or "."
    query = str(a.get("query") or "").strip()
    out = Out(int(a.get("budget_chars") or DEFAULT_BUDGET["outline"]))
    p = _abs(path)
    if not p.exists():
        rel, others = _resolve_file(path)
        if rel is None:
            return f"outline: {path} not found" + (f" (did you mean: {', '.join(others)})" if others else "")
        p = _abs(rel)
    rel_p = _norm(os.path.relpath(p, REPO)) if p != REPO else "."

    if p.is_file():
        rows = _outline_file_rows(rel_p)
        out.add(f"outline {rel_p}  ({len(_lines(rel_p))} lines, {len(rows)} symbols)", force=True)
        doc = _doc_line(rel_p)
        if doc:
            out.add(f"  {doc}")
        for r_ in rows:
            if query and query.lower() not in r_.lower():
                continue
            if not out.add("  " + r_):
                break
        return out.text()

    prefix = "" if rel_p == "." else rel_p + "/"
    files = [f for f in _repo_files() if f.startswith(prefix)]
    if query:
        ql = query.lower()
        hits = [f for f in files if ql in f.lower()]
        if not hits:
            names = [f.rsplit("/", 1)[-1] for f in files]
            close = set(difflib.get_close_matches(query, names, n=8, cutoff=0.55))
            hits = [f for f in files if f.rsplit("/", 1)[-1] in close]
        sym_hits = []
        if len(hits) < 3 and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", query):
            try:
                dh, _ = _grep(rf"^\s*(?:async\s+)?(?:def|class|function|func|fn)\s+\w*{re.escape(query)}\w*",
                              max_hits=20, scope="code")
                sym_hits = [f"{_norm(h['path'])}:{h['line']}  {str(h.get('text') or '').strip()[:80]}"
                            for h in dh if _norm(h["path"]).startswith(prefix)]
            except Exception:  # noqa: BLE001
                sym_hits = []
        hits.sort(key=lambda f: (_kind_of(f) != "code", len(f)))
        out.add(f"outline {rel_p}  query={query}: {len(hits)} files match" +
                (f", {len(sym_hits)} symbol definitions match" if sym_hits else ""), force=True)
        for f in hits[:25]:
            tops = [str(s.get("symbol")) for s in _outline(f) if "." not in str(s.get("symbol"))][:6]
            if not out.add(f"  {f}" + (f"  - {', '.join(tops)}" if tops else "")):
                break
        for s in sym_hits[:10]:
            if not out.add(f"  def {s}"):
                break
        return out.text()

    depth = max(1, min(3, int(a.get("depth") or 1)))
    subdirs: dict[str, int] = {}
    here = []
    for f in files:
        rest = f[len(prefix):]
        parts = rest.split("/")
        if len(parts) > depth:
            d = "/".join(parts[:depth])
            subdirs[d] = subdirs.get(d, 0) + 1
        else:
            here.append(f)
    out.add(f"outline {rel_p}/  ({len(files)} files below, {len(subdirs)} subdirs)", force=True)
    for d, n in sorted(subdirs.items())[:30]:
        out.add(f"  {d}/  ({n} files)")
    here.sort(key=lambda f: (_kind_of(f) != "code", f))
    if len(here) <= 25:
        # Small directory: each file with its summary line and top-level symbols.
        for f in here:
            name = f.rsplit("/", 1)[-1]
            line = f"  {name}"
            if _kind_of(f) == "code":
                doc = _doc_line(f)
                line += f" - {doc}" if doc else ""
                tops = [str(s.get("symbol")) for s in _outline(f) if "." not in str(s.get("symbol"))]
                if tops:
                    line += f"\n      {', '.join(tops[:8])}" + (f" +{len(tops) - 8}" if len(tops) > 8 else "")
            if not out.add(line):
                break
        return out.text()

    # Large directory: every file name first (so nothing is missing, like ls),
    # then one-line summaries for as many code files as the budget allows.
    names = [f.rsplit("/", 1)[-1] for f in here]
    row, rows = "", []
    for nm in names:
        if row and len(row) + len(nm) + 2 > 110:
            rows.append(row)
            row = ""
        row = f"{row}, {nm}" if row else nm
    if row:
        rows.append(row)
    out.add(f"  files ({len(names)}):", force=True)
    for r_ in rows:
        out.add("    " + r_, force=True)
    code = [f for f in here if _kind_of(f) == "code"]
    out.add("  summaries:")
    shown = 0
    for f in code:
        doc = _doc_line(f)
        if not doc:
            continue
        if not out.add(f"    {f.rsplit('/', 1)[-1]} - {doc[:70]}"):
            break
        shown += 1
    left = sum(1 for f in code if _doc_line(f)) - shown
    if left > 0:
        out.dropped = 0
        out.add(f"    ... {left} more summaries - map config=view path=<file> for one file, or query=<name> to filter",
                force=True)
    return out.text()


# ---------------------------------------------------------------------------
# dispatcher, gate/status, MCP stdio loop
# ---------------------------------------------------------------------------

# The public surface is THREE configs. refs and view route into the internal
# implementations (around/open/outline) by what the agent asked for, so no
# capability is lost.
_RELATION_KINDS = {"callers", "callees", "tests", "siblings", "around"}


def cfg_refs_router(a: dict) -> str:
    """refs = everything about a name. Occurrence kinds (def/uses/imports/all)
    run the occurrence lister; relation kinds (callers/callees/tests/siblings)
    run the one-hop relation walk. 'all' with a single symbol target also appends
    the relation summary so one call answers 'where and how is this connected'."""
    kinds = _as_list(a.get("kind")) or ["all"]
    kset = {k.lower() for k in kinds}
    names = _as_list(a.get("names") or a.get("target"))
    rel_kinds = kset & _RELATION_KINDS
    occ_kinds = kset - _RELATION_KINDS

    # Pure relation request -> around on the single named symbol.
    if rel_kinds and not occ_kinds:
        target = a.get("target") or (names[0] if names else "")
        want = [k for k in ("callers", "callees", "tests", "siblings") if k in rel_kinds] or \
               ["callers", "callees", "tests"]
        return cfg_around({**a, "target": target, "want": want})

    out_occ = cfg_refs(a)
    # 'all' on a single symbol under a known file -> also show the relations,
    # since "all" means "everything about this name".
    if "all" in occ_kinds and len(names) == 1 and ("::" in names[0] or ":" in names[0]):
        rel = cfg_around({**a, "target": names[0], "want": ["callers", "callees", "tests"]})
        return out_occ + "\n\n" + rel
    return out_occ


def cfg_view_router(a: dict) -> str:
    """view = show me this. Targets (file::symbol / file:line) -> code (open).
    A path (dir or bare file) -> structure (outline). If both are given, targets win."""
    targets = _as_list(a.get("targets") or a.get("target"))
    path = str(a.get("path") or "").strip()
    if targets:
        return cfg_open({**a, "targets": targets})
    if path:
        return cfg_outline(a)
    return ("error: view needs either targets=[\"file::symbol\", \"file:line\", ...] to show code, "
            "or path=<dir-or-file> to show structure")


HANDLERS = {"find": cfg_find, "refs": cfg_refs_router, "view": cfg_view_router}


def tool_map(args: dict) -> str:
    cfg = str(args.get("config") or "find").strip().lower()
    _CALL_NO[0] += 1
    try:
        # tolerate the old 5-config names so nothing breaks mid-migration, but
        # tell the agent to use the 3 real configs so it stops reaching for the
        # retired names (sessions showed open/around still fired as if distinct).
        if cfg == "open" or cfg == "outline":
            notice = f"note: `{cfg}` is folded into `view` - there are 3 configs (find, refs, view); use `view` next time.\n"
            return notice + cfg_view_router(args)
        if cfg == "around":
            notice = "note: `around` is folded into `refs` - there are 3 configs (find, refs, view); use `refs` next time.\n"
            return notice + cfg_around(args)
        if cfg not in HANDLERS:
            return f"error: config must be one of {', '.join(CONFIGS)}"
        return HANDLERS[cfg](args)
    except Exception as e:  # noqa: BLE001
        return f"map {cfg} failed: {type(e).__name__}: {e}"


def tool_gate(_a: dict) -> str:
    try:
        ok = bool(_http("/health", timeout=10).get("ok"))
    except Exception:  # noqa: BLE001
        ok = False
    return (f"1:{PROJECT_ID}" if PROJECT_ID else "1") if ok else "0"


def tool_status(_a: dict) -> str:
    try:
        h = _http("/health", timeout=10)
    except Exception as e:  # noqa: BLE001
        return f"status: engine unreachable ({e})"
    line = (f"ok={h.get('ok')} warm={h.get('warm_ready')} dense={h.get('dense_ready')} "
            f"phase={h.get('warm_phase')} chunks={h.get('chunks')} version={h.get('version')}")
    # Surface pending work ONLY when it is substantial (reconcile/interrupted).
    # Small incremental catch-up stays silent; search_usable means the current
    # index still serves while the catch-up finishes.
    pending = h.get("pending")
    if isinstance(pending, dict) and pending.get("substantial"):
        state = pending.get("state") or "reconciling"
        reason = pending.get("reason") or ""
        secs = pending.get("estimated_seconds")
        usable = pending.get("search_usable", True)
        line += f" pending={state}"
        if reason:
            line += f"({reason})"
        if isinstance(secs, (int, float)) and secs > 0:
            line += f" ~{int(secs)}s"
        line += f" search_usable={str(bool(usable)).lower()}"
        action = pending.get("action")
        if action:
            line += f" action='{action}'"
    return line


MAP_SCHEMA = {
    "type": "object",
    "properties": {
        "config": {"type": "string", "enum": list(CONFIGS),
                   "description": "find (where is the code) | refs (a name's defs/uses/relations) | "
                                  "view (show code or structure)"},
        "query": {"type": "string", "description": "find: short plain-language intent"},
        "keywords": {"type": "array", "items": {"type": "string"},
                     "description": "find: exact names you know; weighted in ranking"},
        "names": {"type": "array", "items": {"type": "string"},
                  "description": "refs: identifier(s) to look up (e.g. [\"compare_queries\"])"},
        "kind": {"type": "string",
                 "enum": ["all", "def", "uses", "imports", "callers", "callees", "tests", "siblings"],
                 "description": "refs: def/uses/imports = occurrences; callers/callees/tests/siblings = "
                                "relations; all = occurrences (+ relations for a single file::symbol)"},
        "targets": {"type": "array", "items": {"type": "string"},
                    "description": "view: show code of these - \"file::symbol\" | \"file:line\" | "
                                   "\"file:start-end\" (pass several at once)"},
        "path": {"type": "string",
                 "description": "view: show structure of this directory or file"},
        "scope": {"type": "string", "enum": ["code", "tests", "docs", "all"],
                  "description": "find/refs: default code"},
        "k": {"type": "integer", "description": "find: max results (default 8)"},
        "margin": {"type": "integer", "description": "view: context lines after each symbol (default 10)"},
        "budget_chars": {"type": "integer", "description": "hard cap on response size"},
    },
    "required": ["config"],
}

TOOLS = {
    "map": {"fn": tool_map, "schema": MAP_SCHEMA,
            "description": ("Locate and read code. Three configs: "
                            "find = where is the code for X (returns ranked locations + the top "
                            "result's code inline); "
                            "refs = a name's definitions, uses, imports, and relations "
                            "(callers/callees/tests/siblings); "
                            "view = show the code of named targets (file::symbol / file:line, several "
                            "at once) OR the structure of a directory/file.")},
    "gate": {"fn": tool_gate, "schema": {"type": "object", "properties": {}},
             "description": "Health/managed signal only (not for finding code)."},
    "status": {"fn": tool_status, "schema": {"type": "object", "properties": {}},
               "description": "Engine health only; not for finding code."},
}


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _warm() -> None:
    """Load the file list and source text in the background so the first
    find/refs call doesn't pay for walking and reading the whole repo.

    Also stamps the grep stat-TTL so the FIRST real grep skips the ~300ms
    per-file stat() storm (the warm pass already validated every mtime), and builds
    the HTTP opener here so the one-time ~350ms urllib opener-init is paid on this
    background thread instead of on the user's first search."""
    try:
        # Pay urllib's one-time first-request init (~350ms on Windows, mostly the
        # first opener build + first socket op) here on the background thread with a
        # throwaway /health, so the user's first real search doesn't wear it.
        _http("/health", None, 8)
    except Exception:  # noqa: BLE001
        pass
    try:
        warmed = []
        for f in _repo_files():
            if Path(f).suffix.lower() in _GREP_EXT and _kind_of(f) in ("code", "tests"):
                _lines(f)
                warmed.append(_norm(f))
        # Stamp at the END so the whole warmed set shares one fresh validation time
        # (warm takes ~1.8s; stamping per-file would expire the earliest entries).
        now = time.time()
        for rel in warmed:
            _TEXT_VALIDATED_AT[rel] = now
    except Exception:  # noqa: BLE001
        pass


def _keepalive_tick() -> None:
    """One cheap idle re-warm pulse — keeps the worker ms-fast across idle gaps.

    The expensive engine/embedder residency is handled engine-side (CTX_ENGINE_IDLE_S
    / CTX_EMBED_IDLE_DEMOTE_S). This handles the WORKER-process costs that a long idle
    would otherwise let decay, so the first user call after a break is still warm:
      1) keep urllib's opener + a live socket to the engine paid (tiny /health),
      2) re-stamp the grep stat-TTL (10s) so the next grep skips the per-file stat
         storm instead of re-stat'ing ~5k files on the first post-idle call.
    Pure warm-touch: reads nothing new, changes no tool output. Best-effort; any
    failure is swallowed so the pulse never disturbs a real call."""
    try:
        _http("/health", None, 8)  # opener/socket stays warm; also nudges engine idle timer
    except Exception:  # noqa: BLE001
        pass
    try:
        # Re-stamp the grep stat-TTL for every already-cached file so _text_cached_fast
        # keeps skipping the per-file stat() storm right through the idle window. Pure
        # dict writes over the warmed set — no disk I/O (files are already in _TEXT from
        # the initial _warm), so a pulse is ~1ms, not a repo re-read.
        now = time.time()
        for rel in list(_TEXT.keys()):
            _TEXT_VALIDATED_AT[rel] = now
    except Exception:  # noqa: BLE001
        pass


def _keepalive_loop(interval_s: float) -> None:
    """Daemon loop: pulse _keepalive_tick every ``interval_s`` while idle.
    Skips the pulse if a real tool call ran within the last interval (no need to
    warm something that's already hot, and never contend with an in-flight call)."""
    # Extend the effective stat-TTL to cover a full pulse interval (+50% margin) so a
    # file stamped by one pulse is still trusted when the next call lands mid-interval.
    # Each pulse physically re-stamps the whole set, so trust never outlives one
    # interval between actual re-stats.
    global _STAT_TTL_EFFECTIVE_S
    _STAT_TTL_EFFECTIVE_S = max(_GREP_STAT_TTL_S, interval_s * 1.5)
    _keepalive_tick()  # stamp once immediately so the window is live before the first sleep
    while True:
        try:
            time.sleep(interval_s)
            # Skip if a real call touched the worker within the last interval.
            if (time.time() - _LAST_CALL_AT[0]) < interval_s:
                continue
            _keepalive_tick()
        except Exception:  # noqa: BLE001
            # Never let the keepalive thread die on a transient error.
            try:
                time.sleep(interval_s)
            except Exception:  # noqa: BLE001
                return


# Updated by map_v3_server on every tools/call so the keepalive loop can tell idle
# from active (list wrapper = cheap mutable shared cell, no lock needed for a float).
_LAST_CALL_AT: list[float] = [0.0]


def main() -> int:
    import threading
    threading.Thread(target=_warm, name="map-v2-warm", daemon=True).start()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        method, rid = msg.get("method"), msg.get("id")
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "scubiee-map-v2", "version": "2.0.0"},
                "instructions": SERVER_INSTRUCTIONS}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [
                {"name": n, "description": t["description"], "inputSchema": t["schema"]}
                for n, t in TOOLS.items()]}})
        elif method == "tools/call":
            p = msg.get("params") or {}
            tool = TOOLS.get(p.get("name"))
            if not tool:
                _send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown tool {p.get('name')}"}})
                continue
            text = tool["fn"](p.get("arguments") or {})
            _send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}]}})
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif rid is not None:
            _send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
