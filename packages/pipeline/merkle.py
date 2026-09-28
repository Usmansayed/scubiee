"""Merkle-style file synchronizer (Claude Context–compatible idea).

SHA-256 per file → root hash over sorted (path, hash) pairs.
Diff produces {added, modified, removed} for incremental re-index.
Snapshots live under the store dir as ``merkle.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pipeline.artifact_guard import atomic_write_text
from pipeline.ignore import (
    BUILTIN_IGNORE_DIRS,
    BUILTIN_PATH_MARKERS,
    is_builtin_ignored_dir_name,
    load_scubiee_ignore,
    should_index_rel,
)

# Back-compat: callers that imported DEFAULT_IGNORE_DIRS still see builtins.
# Fixture trees (testdata/, research/, …) live in repo ``.scubieeignore``.
DEFAULT_IGNORE_DIRS = set(BUILTIN_IGNORE_DIRS)

_JUNK_PATH_MARKERS = BUILTIN_PATH_MARKERS

DEFAULT_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".rb",
    ".php",
    ".swift",
    ".md",
}


@dataclass
class SyncDiff:
    added: list[str]
    modified: list[str]
    removed: list[str]
    root_hash: str
    unchanged: bool

    @property
    def changed_files(self) -> list[str]:
        return sorted(set(self.added) | set(self.modified))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _sha256_file(path: Path) -> str:
    return file_sha256(path)


def _is_ignored_dir_name(name: str) -> bool:
    return is_builtin_ignored_dir_name(name)


def is_junk_rel(rel: str, root: Path | str | None = None, *, rules: Any = None) -> bool:
    """True for paths that must never be indexed (builtins + ``.scubieeignore``).

    Pass preloaded ``rules`` in loops: loading them resolves the root and stats
    the ignore file on every call.
    """
    return not should_index_rel(root, rel, rules=rules)


def canonical_relpath(rel: str) -> str:
    """Normalize path keys; case-fold on Windows so renames do not duplicate chunks."""
    norm = rel.replace("\\", "/").strip("/")
    if os.name == "nt":
        return os.path.normcase(norm)
    return norm


def sanitize_file_hashes(
    file_hashes: dict[str, str],
    *,
    root: Path | str | None = None,
) -> dict[str, str]:
    merged: dict[str, str] = {}
    # Load ignore rules once: per-key loading resolved the root and stat'ed the
    # ignore file 1.1k times — ~300ms on every hot save (issue 4, merkle_ms).
    rules = None
    if root is not None:
        try:
            from pipeline.ignore import load_scubiee_ignore

            rules = load_scubiee_ignore(root)
        except Exception:  # noqa: BLE001
            rules = None
    for k, v in file_hashes.items():
        if is_junk_rel(k, root=root, rules=rules):
            continue
        ck = canonical_relpath(k)
        merged[ck] = v
    return merged


def _should_skip(rel: Path, extensions: set[str], *, root: Path | str | None = None) -> bool:
    if is_junk_rel(rel.as_posix(), root=root):
        return True
    if rel.suffix.lower() not in extensions:
        return True
    return False


def scan_file_hashes(
    root: Path,
    *,
    extensions: set[str] | None = None,
) -> dict[str, str]:
    """Hash indexable files. Never descends into venv/node_modules/etc."""
    root = root.resolve()
    exts = extensions or DEFAULT_EXTENSIONS
    rules = load_scubiee_ignore(root)
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dp = Path(dirpath)
        try:
            parent_rel = dp.relative_to(root).as_posix()
            if parent_rel == ".":
                parent_rel = ""
        except ValueError:
            parent_rel = ""

        kept_dirs: list[str] = []
        for d in dirnames:
            child_rel = f"{parent_rel}/{d}" if parent_rel else d
            if should_index_rel(root, child_rel, is_dir=True, rules=rules):
                kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for fname in filenames:
            path = dp / fname
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if _should_skip(rel, exts, root=root):
                continue
            out[canonical_relpath(rel.as_posix())] = _sha256_file(path)
    return out


def root_hash(file_hashes: dict[str, str]) -> str:
    h = hashlib.sha256()
    for path in sorted(file_hashes):
        h.update(path.encode("utf-8"))
        h.update(b"\0")
        h.update(file_hashes[path].encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def diff_hashes(old: dict[str, str], new: dict[str, str]) -> SyncDiff:
    added = sorted(p for p in new if p not in old)
    removed = sorted(p for p in old if p not in new)
    modified = sorted(p for p in new if p in old and old[p] != new[p])
    rh = root_hash(new)
    unchanged = not added and not removed and not modified
    return SyncDiff(
        added=added,
        modified=modified,
        removed=removed,
        root_hash=rh,
        unchanged=unchanged,
    )


def load_snapshot(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    pairs = data.get("file_hashes") or []
    return sanitize_file_hashes({str(k): str(v) for k, v in pairs})


def load_mtimes(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    pairs = data.get("file_mtimes") or []
    return {str(k): float(v) for k, v in pairs}


def save_snapshot(
    path: Path,
    file_hashes: dict[str, str],
    *,
    root: Path | None = None,
    reuse_mtimes: dict[str, float] | None = None,
    restat: Iterable[str] | None = None,
) -> None:
    """Persist a merkle snapshot.

    Keys are canonicalized (``canonical_relpath``) before the root hash is
    computed and stored — ``load_snapshot`` canonicalizes on read via
    ``sanitize_file_hashes``, so writing raw (often posix-style) keys here
    made the persisted ``root_hash`` unreproducible from the loaded snapshot
    on Windows: every probe recomputed a different hash than the one on disk
    and reported a spuriously dirty repo (#3182).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = sanitize_file_hashes(file_hashes, root=root)
    mtimes: list[tuple[str, float]] = []
    restat_c = {canonical_relpath(r) for r in (restat or ())}
    if root is not None:
        for orig_rel in sorted(file_hashes):
            ck = canonical_relpath(orig_rel)
            # A patch only re-hashed ``restat``: keep the mtime recorded next to
            # every other file's (unchanged) hash instead of 1.1k fresh stats.
            if reuse_mtimes is not None and ck not in restat_c and ck in reuse_mtimes:
                mtimes.append((ck, float(reuse_mtimes[ck])))
                continue
            p = root / orig_rel
            try:
                if p.is_file():
                    mtimes.append((ck, p.stat().st_mtime))
            except OSError:
                pass
    payload = {
        "root_hash": root_hash(canonical),
        "file_hashes": sorted(canonical.items()),
        "file_mtimes": mtimes,
    }
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")
