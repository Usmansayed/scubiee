"""Scubiee index ignore: builtins + repo ``.scubieeignore`` (not ``.gitignore``).

Builtins are only directories we are sure are never product source (deps, build
artefacts, venvs, IDE/agent trees). Project fixtures (``testdata/``,
``research/``, …) belong in ``.scubieeignore``.

Source roots such as ``packages/`` and ``modules/`` are never default-ignored;
they appear on ``index_write_hint`` for agents.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Builtins — sure junk only (no testdata/research/sandbox/…)
# ---------------------------------------------------------------------------

BUILTIN_IGNORE_DIRS: frozenset[str] = frozenset(
    {
        # VCS / engine home
        ".git",
        ".hg",
        ".svn",
        ".scubiee",
        # Dependencies
        "node_modules",
        "jspm_packages",
        "bower_components",
        "site-packages",
        "__pypackages__",
        "vendor",  # Composer / Go module vendor dir — not packages/
        # Virtualenvs
        ".venv",
        "venv",
        ".tox",
        ".nox",
        ".pixi",
        # Bytecode / packaging
        "__pycache__",
        ".eggs",
        # Build / generate
        "dist",
        "build",
        "out",
        "target",
        ".next",
        ".nuxt",
        ".turbo",
        ".angular",
        ".svelte-kit",
        ".output",
        "storybook-static",
        "coverage",
        "lcov-report",
        "graphify-out",
        ".graphify",
        # Tool caches
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".parcel-cache",
        ".terraform",
        ".serverless",
        # IDE / agent trees (#3182 class)
        ".cursor",
        ".kiro",
        ".codex",
        ".cline",
        ".roo",
        ".amp",
        ".continue",
        ".claude",
        ".copilot",
        ".idea",
        ".vscode",
        ".config",
        ".pi",
        ".ab_workspaces",
        ".worktrees",
        ".zed",
    }
)

# Hidden dirs are skipped by default (IDE noise / #3182) except these.
_DOTDIR_INDEX_ALLOWLIST: frozenset[str] = frozenset({".github"})

BUILTIN_PATH_MARKERS: tuple[str, ...] = (
    "/site-packages/",
    "/.venv/",
    "/.venv-",
    "/venv/",
    "/node_modules/",
    "/__pycache__/",
    "/scubiee-0.",
)

# Preferred write/sync roots for agents (never default-ignored).
INDEX_WRITE_HINT_ROOTS: tuple[str, ...] = (
    "packages/",
    "modules/",
    "src/",
    "lib/",
    "app/",
    "apps/",
    "server/",
    "client/",
    "backend/",
    "frontend/",
    "pipeline/",
    "scripts/",
    "tools/",
    "tests/",
    "test/",
)

_IGNORE_FILENAME = ".scubieeignore"
_MAX_IGNORE_LINES = 2000

# (mtime_ns, size, rules) keyed by resolved repo root
_cache: dict[str, tuple[int, int, "IgnoreRules"]] = {}


def normalize_rel(rel: str) -> str:
    s = rel.replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return s.strip("/")


def is_builtin_ignored_dir_name(name: str) -> bool:
    """True if this path segment is a builtin-ignored directory name."""
    if not name or name in {".", ".."}:
        return False
    if name in BUILTIN_IGNORE_DIRS:
        return True
    if name.startswith(".venv") or name.startswith("venv"):
        return True
    if name.endswith("_venv") or name.endswith(".egg-info"):
        return True
    # Unpacked old releases (scubiee-0.2.61/) duplicate packages/ and serve stale code.
    if name.startswith("scubiee-0."):
        return True
    # Blanket hidden dirs except allowlisted source trees (.github).
    if name.startswith(".") and name not in _DOTDIR_INDEX_ALLOWLIST:
        return True
    return False


def builtin_ignores_rel(rel: str) -> bool:
    """True if *rel* is denied by builtin rules (parents or markers)."""
    norm_slash = "/" + normalize_rel(rel) + "/"
    if any(m in norm_slash for m in BUILTIN_PATH_MARKERS):
        return True
    parts = normalize_rel(rel).split("/")
    if not parts or parts == [""]:
        return False
    # Parents only (filename may be e.g. testdata_util.py)
    return any(is_builtin_ignored_dir_name(p) for p in parts[:-1])


@dataclass(frozen=True)
class _Pattern:
    raw: str
    negated: bool
    directory_only: bool
    anchored: bool
    regex: re.Pattern[str]


@dataclass
class IgnoreRules:
    """Compiled ``.scubieeignore`` patterns (root-anchored)."""

    patterns: list[_Pattern] = field(default_factory=list)
    line_count: int = 0
    path: str | None = None

    @property
    def empty(self) -> bool:
        return not self.patterns


def _parse_line(raw: str) -> str | None:
    s = raw.strip()
    if not s or s.startswith("#"):
        return None
    while s.endswith(" ") and not s.endswith("\\ "):
        s = s[:-1]
    s = s.replace("\\ ", " ")
    return s or None


def _glob_to_regex(glob: str) -> str:
    """Translate a gitignore-ish glob (no leading ! or trailing /) to regex body."""
    parts: list[str] = []
    i = 0
    n = len(glob)
    while i < n:
        if glob.startswith("**/", i):
            parts.append("(?:.*/)?")
            i += 3
            continue
        if i + 1 < n and glob[i : i + 2] == "**":
            parts.append(".*")
            i += 2
            continue
        ch = glob[i]
        if ch == "*":
            parts.append("[^/]*")
        elif ch == "?":
            parts.append("[^/]")
        elif ch in ".+^$()[]{}|\\":
            parts.append(re.escape(ch))
        else:
            parts.append(ch)
        i += 1
    return "".join(parts)


def _compile_pattern(line: str) -> _Pattern:
    negated = line.startswith("!")
    if negated:
        line = line[1:]
    directory_only = line.endswith("/")
    if directory_only:
        line = line[:-1]
    anchored = line.startswith("/")
    if anchored:
        line = line[1:]
    body = _glob_to_regex(line)
    if anchored:
        rx = re.compile(f"^{body}(?:/.*)?$")
    else:
        rx = re.compile(f"(?:^|/){body}(?:/.*)?$")
    return _Pattern(
        raw=line,
        negated=negated,
        directory_only=directory_only,
        anchored=anchored,
        regex=rx,
    )


def load_scubiee_ignore(root: Path | str | None) -> IgnoreRules:
    """Load and cache ``{root}/.scubieeignore``."""
    if root is None:
        return IgnoreRules()
    # Called on every change poll: resolve + stat are GIL releases that each
    # cost a timer tick while a search runs (issue 4). See pipeline.fast_stat.
    from pipeline.fast_stat import cached_resolve, fast_stat

    root_p = cached_resolve(root)
    key = str(root_p)
    ignore_path = root_p / _IGNORE_FILENAME
    st = fast_stat(ignore_path)
    if st is None or not st.is_file:
        _cache.pop(key, None)
        return IgnoreRules()
    mtime_ns = int(st.st_mtime_ns)
    size = int(st.st_size)

    cached = _cache.get(key)
    if cached and cached[0] == mtime_ns and cached[1] == size:
        return cached[2]

    try:
        text = ignore_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return IgnoreRules()

    patterns: list[_Pattern] = []
    lines = 0
    for raw in text.splitlines():
        if lines >= _MAX_IGNORE_LINES:
            break
        parsed = _parse_line(raw)
        if parsed is None:
            continue
        lines += 1
        try:
            patterns.append(_compile_pattern(parsed))
        except re.error:
            continue

    rules = IgnoreRules(patterns=patterns, line_count=lines, path=str(ignore_path))
    _cache[key] = (mtime_ns, size, rules)
    return rules


def clear_ignore_cache() -> None:
    _cache.clear()


def _path_or_ancestor_matches(pat: _Pattern, path: str) -> bool:
    """True if *path* or any ancestor directory matches *pat*."""
    # Use search: unanchored patterns may match a mid-path segment.
    if pat.regex.search(path):
        return True
    if not pat.directory_only:
        return False
    parts = path.split("/")
    for i in range(len(parts)):
        prefix = "/".join(parts[: i + 1])
        if pat.regex.search(prefix):
            return True
    return False


def _custom_matches(rules: IgnoreRules, rel: str, *, is_dir: bool = False) -> bool | None:
    """Last-match-wins. Returns True=ignore, False=force-include, None=no match.

    Builtins cannot be negated: callers apply builtins first.
    """
    if rules.empty:
        return None
    path = normalize_rel(rel)
    if is_dir and path and not path.endswith("/"):
        # directory_only patterns match the dir itself
        pass
    result: bool | None = None
    for pat in rules.patterns:
        if _path_or_ancestor_matches(pat, path):
            result = not pat.negated
            continue
        # Basename-only unanchored patterns (e.g. "*.log")
        if not pat.anchored and "/" not in pat.raw:
            base = path.rsplit("/", 1)[-1]
            if pat.regex.match(base) or pat.regex.match(path):
                result = not pat.negated
    return result


def should_index_rel(
    root: Path | str | None,
    rel: str,
    *,
    is_dir: bool = False,
    rules: IgnoreRules | None = None,
) -> bool:
    """True if *rel* may be indexed / dirtied / searched into the corpus."""
    if not str(rel or "").strip():
        return False
    if builtin_ignores_rel(rel):
        return False
    name = normalize_rel(rel).split("/")[-1]
    if is_dir and is_builtin_ignored_dir_name(name):
        return False
    # File whose sole segment is a builtin dir name (e.g. walking into node_modules)
    if not is_dir and "/" not in normalize_rel(rel) and is_builtin_ignored_dir_name(name):
        # Allow regular files at root named oddly; dir names only matter as dirs.
        pass
    r = rules if rules is not None else load_scubiee_ignore(root)
    custom = _custom_matches(r, rel, is_dir=is_dir)
    if custom is True:
        return False
    if custom is False:
        return True
    return True


def filter_dirty_paths(
    root: Path | str | None,
    paths: Iterable[str],
) -> tuple[list[str], list[dict[str, str]]]:
    """Split dirty paths into kept vs dropped (builtin, scubieeignore, or outside-repo)."""
    rules = load_scubiee_ignore(root)
    root_res: Path | None = None
    if root is not None:
        try:
            root_res = Path(root).resolve()
        except (OSError, ValueError):
            root_res = None
    kept: list[str] = []
    dropped: list[dict[str, str]] = []
    for raw in paths:
        p = str(raw or "").replace("\\", "/").strip()
        if not p:
            continue
        # Drop absolute paths that resolve OUTSIDE the repo root. A stray
        # /v1/dirty or an over-eager watcher can mark a sibling/home-dir file;
        # if it slips through, the sync batch's relative_to(root) raises and the
        # whole batch fails forever (permanent "not in the subpath" wedge).
        if root_res is not None:
            cand = Path(p)
            if cand.is_absolute():
                try:
                    cand.resolve().relative_to(root_res)
                except (ValueError, OSError):
                    dropped.append({"path": p, "reason": "outside_repo"})
                    continue
        if builtin_ignores_rel(p):
            dropped.append({"path": p, "reason": "builtin"})
            continue
        custom = _custom_matches(rules, p)
        if custom is True:
            dropped.append({"path": p, "reason": "scubieeignore"})
            continue
        kept.append(p)
    seen: set[str] = set()
    uniq: list[str] = []
    for p in kept:
        key = p.casefold() if os.name == "nt" else p
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq, dropped


def agent_ignore_summary(root: Path | str | None = None) -> dict[str, Any]:
    """Compact fields for gate/status (~30–50 tokens of text when rendered)."""
    rules = load_scubiee_ignore(root)
    n = rules.line_count
    sample = sorted(BUILTIN_IGNORE_DIRS)[:8]
    return {
        "index_skip": (f"builtins+scubieeignore(n={n})" if n else "builtins"),
        "index_skip_sample": sample,
        "index_write_hint": "|".join(INDEX_WRITE_HINT_ROOTS),
        "scubieeignore": rules.path if n else None,
        "scubieeignore_lines": n,
    }


def format_gate_ignore_lines(root: Path | str | None = None) -> str:
    """One–two lines appended to gate() for agents."""
    s = agent_ignore_summary(root)
    return f"index_skip: {s['index_skip']}\nindex_write_hint: {s['index_write_hint']}"


def is_junk_rel(rel: str, root: Path | str | None = None) -> bool:
    """True if path must not be indexed (builtins + optional .scubieeignore)."""
    return not should_index_rel(root, rel)
