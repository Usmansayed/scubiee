"""Shared index path collection (optional directory scope)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from graphify.detect import _is_ignored, _load_graphifyignore
from graphify.extract import collect_files
from pipeline.ignore import (
    INDEX_WRITE_HINT_ROOTS,
    IgnoreRules,
    load_scubiee_ignore,
    should_index_rel,
)
from pipeline.merkle import DEFAULT_EXTENSIONS

# Optional scope when --roots / CTX_INDEX_ROOTS / legacy CTX_FAST_ROOTS is set.
# Do NOT include testdata/ — fixture trees flood the index with duplicates
# (list them in ``.scubieeignore`` instead; they are not builtin ignores).
_DEFAULT_SCOPE_ROOTS = INDEX_WRITE_HINT_ROOTS + (
    "execution_layer/",
    "coordination_layer/",
    "conductor/",
)

# Back-compat alias for older call sites / env docs.
_DEFAULT_FAST_ROOTS = _DEFAULT_SCOPE_ROOTS


def fast_roots_from_env(meta_roots: list[str] | None = None) -> tuple[str, ...]:
    """Directory prefixes used when scoped indexing is on (``fast=True`` / ``--roots``)."""
    if meta_roots:
        return tuple(r if r.endswith("/") else f"{r}/" for r in meta_roots)
    raw = (
        os.environ.get("CTX_INDEX_ROOTS", "").strip()
        or os.environ.get("CTX_FAST_ROOTS", "").strip()
    )
    if raw:
        parts = [p.strip().replace("\\", "/").lower() for p in raw.split(",") if p.strip()]
        return tuple(p if p.endswith("/") else f"{p}/" for p in parts)
    return _DEFAULT_SCOPE_ROOTS


# Bytes to sniff when deciding whether a file is real text. A NUL byte in the
# head is the classic binary signal (git uses the same heuristic); a head that
# is not valid UTF-8 means the downstream extractor's strict utf-8 read would
# raise and — before this guard — abort indexing for the WHOLE repo. We probe
# only the head so the cost is one small read per already-eligible file.
_TEXT_SNIFF_BYTES = 8192


def _is_probably_text(abs_path: Path) -> bool:
    """True if the file looks like decodable text (not a binary / bad-encoding).

    A file can carry a source extension yet contain binary bytes (a blob saved as
    ``data.py``) or non-UTF-8 legacy encoding. The index extractor reads with a
    STRICT utf-8 decode, so a single such file used to raise and fail the entire
    ``init``. Excluding it at collection keeps one bad file from blocking the
    whole project index. One-line minified blobs are rejected too. Best-effort:
    on any read error we keep the file (the downstream path is itself guarded).
    """
    from pipeline.ignore import content_indexable

    return content_indexable(abs_path)


# Root-level .gitignore/.graphifyignore (+ .git/info/exclude), the same set the
# full-index walker (graphify ``collect_files``) applies. Reloaded every few
# seconds so an edited .gitignore takes effect without a restart.
_GITIGNORE_TTL_S = 5.0
_gitignore_cache: dict[str, tuple[float, Path, list, dict]] = {}


def clear_gitignore_cache() -> None:
    _gitignore_cache.clear()


def gitignored(root: Path, rel: str) -> bool:
    """True if *rel* is excluded by the repo's .gitignore/.graphifyignore.

    Folder-only patterns (``build/``) match only folders that exist, so a file
    under a deleted folder is not reported ignored and its removal is still seen.
    """
    key = str(root)
    now = time.monotonic()
    hit = _gitignore_cache.get(key)
    if hit is None or now - hit[0] >= _GITIGNORE_TTL_S:
        try:
            res = Path(root).resolve()
            patterns: list[Any] = _load_graphifyignore(res)
        except OSError:
            return False
        if len(_gitignore_cache) > 16:
            _gitignore_cache.clear()
        hit = (now, res, patterns, {})
        _gitignore_cache[key] = hit
    _, res, patterns, memo = hit
    if not patterns:
        return False
    try:
        return _is_ignored(res / rel, res, patterns, _cache=memo)
    except (OSError, ValueError):
        return False


def index_rel_ok(
    root: Path,
    rel: str,
    *,
    rules: IgnoreRules,
    fast: bool = False,
    roots: tuple[str, ...] = (),
    gitignore: bool = True,
) -> bool:
    """True if the file at posix *rel* belongs in the index.

    ``gitignore=False`` only for callers whose walk already applied it.
    """
    if Path(rel).suffix.lower() not in DEFAULT_EXTENSIONS:
        return False
    if not should_index_rel(root, rel, rules=rules):
        return False
    if gitignore and gitignored(root, rel):
        return False
    # Prefix-anchored: matching a root anywhere in the path pulls in
    # vendored or copied trees (e.g. testdata/<copy>/packages/...).
    if fast and not any(rel.lower().startswith(fr) for fr in roots):
        return False
    # Final gate: a source-extension file that is actually binary / non-UTF-8
    # must not reach the strict-utf-8 extractor (it would abort the whole index).
    return _is_probably_text(root / rel)


def index_dir_pruner(root: Path, rules: IgnoreRules):
    """Return ``prune(dir) -> bool``: True when no file under *dir* can pass ``should_index_rel``.

    Builtin denials are never negatable. Custom ``.scubieeignore`` matches cover
    every descendant, but a ``!`` rule may re-include one, so custom pruning is
    only applied when the rules contain no negation.
    """
    from pipeline.ignore import _custom_matches, builtin_ignores_rel

    root_s = str(root)
    prefix_len = len(root_s.rstrip("\\/")) + 1
    custom_ok = bool(rules.patterns) and not any(p.negated for p in rules.patterns)

    def prune(d: Path) -> bool:
        s = str(d)
        if not s.startswith(root_s) or len(s) <= prefix_len:
            return False
        rel = s[prefix_len:].replace("\\", "/")
        if builtin_ignores_rel(rel + "/_", root):
            return True
        return custom_ok and _custom_matches(rules, rel, is_dir=True) is True

    return prune


def collect_index_paths(
    root: Path,
    *,
    fast: bool = False,
    fast_roots: list[str] | tuple[str, ...] | None = None,
    under: Path | None = None,
    rules: IgnoreRules | None = None,
) -> list[Path]:
    """Collect indexable source files under *root* (or only its *under* subtree).

    Always includes every language in ``DEFAULT_EXTENSIONS`` (``.py``, ``.ts``,
    ``.go``, …). When ``fast`` is true (legacy name = scoped), only paths under
    ``fast_roots`` / default scope roots are kept — never Python-only.
    """
    root = root.resolve()
    if rules is None:
        rules = load_scubiee_ignore(root)
    paths = collect_files(
        under if under is not None else root,
        root=root,
        prune_dir=index_dir_pruner(root, rules),
    )
    roots = fast_roots_from_env(list(fast_roots) if fast_roots else None)
    return [
        p
        for p in paths
        if index_rel_ok(
            root, p.relative_to(root).as_posix(), rules=rules, fast=fast, roots=roots, gitignore=False
        )
    ]


def collect_index_relpaths(
    root: Path,
    *,
    fast: bool = False,
    fast_roots: list[str] | tuple[str, ...] | None = None,
) -> set[str]:
    """Repo-relative paths currently eligible for indexing."""
    root = root.resolve()
    return {
        p.relative_to(root).as_posix()
        for p in collect_index_paths(root, fast=fast, fast_roots=fast_roots)
    }


def exceeds_index_cap(root: Path, cap: int) -> bool:
    """Fast, bounded check: does *root* hold MORE than *cap* indexable files?

    The full ``collect_index_relpaths`` materialises every candidate path AND
    reads the first 8 KB of each (the text sniff) just to produce a count — on a
    broad root (home dir, drive root) that is hundreds of thousands of files and
    minutes of silent work (the "init looks hung" trap). This does a pruned
    ``os.walk`` that skips builtin-ignored dirs (``node_modules``, ``.venv``,
    ``.git``, dotdirs, …) and returns ``True`` as soon as the extension-matching
    count exceeds *cap* — no per-file content read, early exit. Approximate by
    design: it may slightly over-count vs the full filter (it skips the text
    sniff and custom ``.scubieeignore``), but for a "is this absurdly large?"
    gate that is exactly right and bounded.
    """
    from pipeline.ignore import is_builtin_ignored_dir_name

    root = root.resolve()
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored dirs in place so os.walk never descends into them.
        dirnames[:] = [d for d in dirnames if not is_builtin_ignored_dir_name(d)]
        for fn in filenames:
            if Path(fn).suffix.lower() in DEFAULT_EXTENSIONS:
                n += 1
                if n > cap:
                    return True
    return False
