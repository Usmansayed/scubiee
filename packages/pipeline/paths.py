"""Shared index path collection (fast roots configurable)."""

from __future__ import annotations

import os
from pathlib import Path

from graphify.extract import collect_files
from pipeline.merkle import DEFAULT_EXTENSIONS

# Broader than before; override with CTX_FAST_ROOTS=src,lib,app,packages
# Do NOT include testdata/ — fixture trees (frontend-mcp copies, workdirs)
# are thousands of .py files and hang chunk/embed when indexing this repo.
# Point CTX_REPO at a fixture root when you intentionally want that corpus.
_DEFAULT_FAST_ROOTS = (
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
    # Harness and test code answers "how do we run/verify X".
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


def fast_roots_from_env(meta_roots: list[str] | None = None) -> tuple[str, ...]:
    if meta_roots:
        return tuple(r if r.endswith("/") else f"{r}/" for r in meta_roots)
    raw = os.environ.get("CTX_FAST_ROOTS", "").strip()
    if raw:
        parts = [p.strip().replace("\\", "/").lower() for p in raw.split(",") if p.strip()]
        return tuple(p if p.endswith("/") else f"{p}/" for p in parts)
    return _DEFAULT_FAST_ROOTS


def collect_index_paths(
    root: Path,
    *,
    fast: bool = False,
    fast_roots: list[str] | tuple[str, ...] | None = None,
) -> list[Path]:
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
        if fast:
            if p.suffix.lower() != ".py":
                continue
            # Prefix-anchored: matching a root anywhere in the path pulls in
            # vendored or copied trees (e.g. testdata/<copy>/packages/...),
            # which floods the index with duplicates of the real source.
            if not any(rel.startswith(fr) for fr in roots):
                continue
        elif p.suffix.lower() not in DEFAULT_EXTENSIONS:
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
