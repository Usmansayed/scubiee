"""Shared index path collection (optional directory scope)."""

from __future__ import annotations

import os
from pathlib import Path

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
    whole project index. Best-effort: on any read error we keep the file (the
    downstream path is itself guarded), never crash here.
    """
    try:
        with open(abs_path, "rb") as fh:
            head = fh.read(_TEXT_SNIFF_BYTES)
    except OSError:
        return True  # can't probe — let the (guarded) downstream decide
    if not head:
        return True  # empty file is fine
    if b"\x00" in head:
        return False  # NUL byte => binary
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A multibyte char may be split at the 8KB boundary; only reject when the
        # failure is NOT merely a truncated trailing sequence.
        if exc.reason == "unexpected end of data" and exc.start >= len(head) - 4:
            return True
        return False
    return True


def index_rel_ok(
    root: Path,
    rel: str,
    *,
    rules: IgnoreRules,
    fast: bool = False,
    roots: tuple[str, ...] = (),
) -> bool:
    """True if the file at posix *rel* belongs in the index."""
    if Path(rel).suffix.lower() not in DEFAULT_EXTENSIONS:
        return False
    if not should_index_rel(root, rel, rules=rules):
        return False
    # Prefix-anchored: matching a root anywhere in the path pulls in
    # vendored or copied trees (e.g. testdata/<copy>/packages/...).
    if fast and not any(rel.lower().startswith(fr) for fr in roots):
        return False
    # Final gate: a source-extension file that is actually binary / non-UTF-8
    # must not reach the strict-utf-8 extractor (it would abort the whole index).
    return _is_probably_text(root / rel)


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
    paths = collect_files(under if under is not None else root, root=root)
    roots = fast_roots_from_env(list(fast_roots) if fast_roots else None)
    return [
        p
        for p in paths
        if index_rel_ok(root, p.relative_to(root).as_posix(), rules=rules, fast=fast, roots=roots)
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
