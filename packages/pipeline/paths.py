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
    return not fast or any(rel.lower().startswith(fr) for fr in roots)


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
