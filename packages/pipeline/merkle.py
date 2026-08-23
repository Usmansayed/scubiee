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

from pipeline.artifact_guard import atomic_write_text

DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    ".venv-proof",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".turbo",
    ".next",
    "out",
    "coverage",
    ".context-engine",
    "site-packages",
    # Keep aligned with pipeline.paths._SKIP_SUBSTRINGS: fixture/vendored/
    # experimental trees are never part of the indexed universe. A mismatch
    # here means scan_file_hashes() (merkle snapshot) hashes thousands of
    # files the real indexer never touches, so root_probe() sees them as
    # permanent "newcomers" and the keeper loop never converges (#3182).
    "vendor",
    "testdata",
    "research",
    "sandbox",
    "references",
    "experiments",
    "design_benchmarks",
}

_JUNK_PATH_MARKERS = (
    "/site-packages/",
    "/.venv/",
    "/.venv-",
    "/venv/",
    "/node_modules/",
    "/__pycache__/",
)

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
    if name in DEFAULT_IGNORE_DIRS:
        return True
    if name.startswith(".venv") or name.startswith("venv"):
        return True
    if name.startswith(".") and name not in {".", ".."}:
        return True
    return False


def is_junk_rel(rel: str) -> bool:
    """True for venv / site-packages / cache paths that must never be indexed."""
    norm = "/" + rel.replace("\\", "/").strip("/") + "/"
    if any(m in norm for m in _JUNK_PATH_MARKERS):
        return True
    parts = rel.replace("\\", "/").split("/")
    return any(_is_ignored_dir_name(p) for p in parts[:-1])


def canonical_relpath(rel: str) -> str:
    """Normalize path keys; case-fold on Windows so renames do not duplicate chunks."""
    norm = rel.replace("\\", "/").strip("/")
    if os.name == "nt":
        return os.path.normcase(norm)
    return norm


def sanitize_file_hashes(file_hashes: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for k, v in file_hashes.items():
        if is_junk_rel(k):
            continue
        ck = canonical_relpath(k)
        merged[ck] = v
    return merged


def _should_skip(rel: Path, extensions: set[str]) -> bool:
    if is_junk_rel(rel.as_posix()):
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
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = [d for d in dirnames if not _is_ignored_dir_name(d)]
        dp = Path(dirpath)
        for fname in filenames:
            path = dp / fname
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if _should_skip(rel, exts):
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


def save_snapshot(path: Path, file_hashes: dict[str, str], *, root: Path | None = None) -> None:
    """Persist a merkle snapshot.

    Keys are canonicalized (``canonical_relpath``) before the root hash is
    computed and stored — ``load_snapshot`` canonicalizes on read via
    ``sanitize_file_hashes``, so writing raw (often posix-style) keys here
    made the persisted ``root_hash`` unreproducible from the loaded snapshot
    on Windows: every probe recomputed a different hash than the one on disk
    and reported a spuriously dirty repo (#3182).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = sanitize_file_hashes(file_hashes)
    mtimes: list[tuple[str, float]] = []
    if root is not None:
        for orig_rel in sorted(file_hashes):
            p = root / orig_rel
            try:
                if p.is_file():
                    mtimes.append((canonical_relpath(orig_rel), p.stat().st_mtime))
            except OSError:
                pass
    payload = {
        "root_hash": root_hash(canonical),
        "file_hashes": sorted(canonical.items()),
        "file_mtimes": mtimes,
    }
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")
