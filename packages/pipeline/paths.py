"""Shared index path collection (optional directory scope)."""

from __future__ import annotations

import os
from pathlib import Path

from graphify.extract import collect_files
from pipeline.merkle import DEFAULT_EXTENSIONS

# Optional scope when --roots / CTX_INDEX_ROOTS / legacy CTX_FAST_ROOTS is set.
# Do NOT include testdata/ — fixture trees flood the index with duplicates.
_DEFAULT_SCOPE_ROOTS = (
    "src/",
    "lib/",
    "app/",
    "apps/",
    "server/",
    "client/",
    "backend/",
    "frontend/",
    "packages/",
    "execution_layer/",
    "coordination_layer/",
    "pipeline/",
    "conductor/",
    "scripts/",
    "tools/",
    "tests/",
    "test/",
)

_SKIP_SUBSTRINGS = (
    "/vendor/",
    "node_modules",
    "/dist/",
    "__pycache__",
    ".venv",
    "venv-proof",
    ".venv-proof",
    "site-packages",
    "graphify-out",
    "/sandbox/",
    "/references/",
    "/research/",
    "/experiments/",
    "/testdata/",
    "/design_benchmarks/",
    "/.git/",
    "/out/",
    "/.ab_workspaces/",
    # IDE / agent tooling trees — merkle already skips dotdirs; indexer must
    # match or root_probe treats every *.md under these as permanent "added"
    # and the keeper never converges (same class as #3182).
    "/.cursor/",
    "/.kiro/",
    "/.codex/",
    "/.cline/",
    "/.roo/",
    "/.amp/",
    "/.continue/",
    "/.claude/",
    "/.config/",
    "/.copilot/",
    "/.pi/",
    "/scubiee-0.",
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


def collect_index_paths(
    root: Path,
    *,
    fast: bool = False,
    fast_roots: list[str] | tuple[str, ...] | None = None,
) -> list[Path]:
    """Collect indexable source files under *root*.

    Always includes every language in ``DEFAULT_EXTENSIONS`` (``.py``, ``.ts``,
    ``.go``, …). When ``fast`` is true (legacy name = scoped), only paths under
    ``fast_roots`` / default scope roots are kept — never Python-only.
    """
    root = root.resolve()
    paths = collect_files(root, root=root)
    roots = fast_roots_from_env(list(fast_roots) if fast_roots else None)
    out: list[Path] = []
    for p in paths:
        rel = p.relative_to(root).as_posix().lower()
        # Compare against "/rel" so patterns written as "/out/" also match a
        # top-level out/ directory, not just a nested one.
        if any(x in f"/{rel}" for x in _SKIP_SUBSTRINGS):
            continue
        if p.suffix.lower() not in DEFAULT_EXTENSIONS:
            continue
        if fast:
            # Prefix-anchored: matching a root anywhere in the path pulls in
            # vendored or copied trees (e.g. testdata/<copy>/packages/...).
            if not any(rel.startswith(fr) for fr in roots):
                continue
        out.append(p)
    return out


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
