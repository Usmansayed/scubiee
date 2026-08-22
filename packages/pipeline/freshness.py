"""Freshness: Merkle + git change detection (industry patterns).

Aligned with:
- Claude Context: Merkle root + file hash diff
- Cursor: async dense, disk is source of truth at query time
- hybrid-code-rag-mcp: git HEAD / diff / mtime fast paths

IMPORTANT: git porcelain alone is NOT enough — gitignored indexed files
won't appear in status. Always verify Merkle leaves (mtime then hash).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.merkle import (
    SyncDiff,
    diff_hashes,
    file_sha256,
    is_junk_rel,
    root_hash,
    scan_file_hashes,
)

FULL_FRACTION = float(os.environ.get("CTX_FULL_REINDEX_FRACTION", "0.5"))
INCREMENTAL_MAX = int(os.environ.get("CTX_INCREMENTAL_MAX", "40"))
BACKGROUND_MAX = int(os.environ.get("CTX_BACKGROUND_MAX", "500"))


@dataclass
class FreshnessReport:
    clean: bool
    root: str
    diff: SyncDiff
    git_available: bool = False
    git_dirty: list[str] = field(default_factory=list)
    git_head: str | None = None
    indexed_head: str | None = None
    strategy: str = "none"  # none | incremental | background | full
    reason: str = ""
    detection: str = "merkle"  # git_fast | git_diff | merkle | mtime | merkle_verify

    @property
    def changed_count(self) -> int:
        return len(self.diff.changed_files) + len(self.diff.removed)

    def to_dict(self) -> dict:
        # Cap path lists — dumping tens of thousands of site-packages paths
        # previously OOM'd / froze the machine when MCP serialized freshness.
        cap = 50
        return {
            "clean": self.clean,
            "root": self.root,
            "changed_count": self.changed_count,
            "added": self.diff.added[:cap],
            "modified": self.diff.modified[:cap],
            "removed": self.diff.removed[:cap],
            "added_truncated": len(self.diff.added) > cap,
            "modified_truncated": len(self.diff.modified) > cap,
            "removed_truncated": len(self.diff.removed) > cap,
            "git_available": self.git_available,
            "git_dirty": self.git_dirty[:cap],
            "git_head": self.git_head,
            "indexed_head": self.indexed_head,
            "strategy": self.strategy,
            "reason": self.reason,
            "detection": self.detection,
        }


def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if r.returncode != 0:
            return None
        return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_head(root: Path) -> str | None:
    return _git(root, "rev-parse", "HEAD")


def git_dirty_files(root: Path) -> list[str]:
    """Tracked+untracked paths (porcelain). Does NOT include gitignored files.

    Filters venv/site-packages noise — an unignored ``.venv-proof`` previously
    injected 7k+ paths into freshness and triggered a full reindex storm.
    """
    # -uno: tracked changes only. Untracked newcomers are discovered via fast_roots
    # walk — `git status -u` on a dirty tree with thousands of files hung MCP status.
    out = _git(root, "status", "--porcelain", "-uno")
    if out is None:
        return []
    files: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.replace("\\", "/").strip('"')
        if is_junk_rel(path):
            continue
        files.append(path)
    return files


def git_diff_names(root: Path, old_rev: str, new_rev: str = "HEAD") -> list[str]:
    out = _git(root, "diff", "--name-only", f"{old_rev}..{new_rev}")
    if out is None:
        return []
    return [p.replace("\\", "/") for p in out.splitlines() if p.strip()]


def choose_strategy(
    changed_count: int,
    *,
    corpus_size: int = 0,
    incremental_max: int = INCREMENTAL_MAX,
    background_max: int = BACKGROUND_MAX,
    full_fraction: float = FULL_FRACTION,
) -> tuple[str, str]:
    if changed_count <= 0:
        return "none", "index matches working tree"
    if changed_count <= incremental_max:
        return "incremental", f"{changed_count} files <= {incremental_max}: sync before search"
    if corpus_size > 0 and (changed_count / corpus_size) >= full_fraction:
        return (
            "full",
            f"{changed_count}/{corpus_size} files >= {full_fraction:.0%}: full reindex in background",
        )
    if changed_count <= background_max:
        return "background", f"{changed_count} files: search with hybrid boost, refresh in background"
    return "background", f"{changed_count} files large: background refresh, prefer BM25/graph until done"


def _empty_diff(hashes: dict[str, str]) -> SyncDiff:
    return SyncDiff(
        added=[],
        modified=[],
        removed=[],
        root_hash=root_hash(hashes) if hashes else "",
        unchanged=True,
    )


def verify_merkle_leaves(
    root: Path,
    merkle_snapshot: dict[str, str],
    *,
    file_mtimes: dict[str, float] | None = None,
) -> SyncDiff:
    """Verify every indexed path (catches gitignored edits porcelain misses).

    Cheap path: stat mtime vs snapshot; hash only suspects + missing/new.
    """
    root = root.resolve()
    suspects: list[str] = []
    current = dict(merkle_snapshot)

    for rel, old_hash in merkle_snapshot.items():
        p = root / rel
        if not p.is_file():
            current.pop(rel, None)
            continue
        if file_mtimes and rel in file_mtimes:
            try:
                if p.stat().st_mtime == file_mtimes[rel]:
                    continue  # mtime match → skip hash
            except OSError:
                pass
            suspects.append(rel)
        else:
            suspects.append(rel)

    for rel in suspects:
        p = root / rel
        if p.is_file():
            current[rel] = file_sha256(p)
        else:
            current.pop(rel, None)

    return diff_hashes(merkle_snapshot, current)


def check_freshness(
    root: Path,
    merkle_snapshot: dict[str, str],
    *,
    indexed_head: str | None = None,
    extensions: set[str] | None = None,
    fast_paths: list[Path] | None = None,
    file_mtimes: dict[str, float] | None = None,
    indexed_universe_only: bool = True,
) -> FreshnessReport:
    """Detect drift. Merkle leaves are always verified — git is a speed hint only."""
    root = root.resolve()
    head = git_head(root)
    dirty = git_dirty_files(root) if head else []
    corpus = len(merkle_snapshot) or 1

    def _finish(diff: SyncDiff, detection: str, suffix: str = "") -> FreshnessReport:
        strategy, reason = choose_strategy(
            0 if diff.unchanged else len(diff.changed_files) + len(diff.removed),
            corpus_size=corpus,
        )
        return FreshnessReport(
            clean=diff.unchanged,
            root=str(root),
            diff=diff,
            git_available=head is not None,
            git_dirty=dirty,
            git_head=head,
            indexed_head=indexed_head,
            strategy=strategy,
            reason=reason + suffix,
            detection=detection,
        )

    # --- Path A: same HEAD + clean porcelain → still VERIFY merkle leaves ---
    # (gitignored indexed files never show in porcelain — Cursor/Claude use content hashes)
    if (
        head
        and indexed_head
        and head == indexed_head
        and not dirty
        and merkle_snapshot
        and fast_paths is None
    ):
        diff = verify_merkle_leaves(root, merkle_snapshot, file_mtimes=file_mtimes)
        if diff.unchanged:
            return _finish(diff, "git_fast", " [HEAD match + merkle leaves OK]")
        return _finish(diff, "merkle_verify", " [porcelain clean but merkle leaf drifted]")

    # --- Path B: HEAD advanced — git diff + porcelain + merkle verify of those ---
    if head and indexed_head and head != indexed_head and merkle_snapshot and fast_paths is None:
        committed = git_diff_names(root, indexed_head, head)
        candidates = sorted(set(committed) | set(dirty) | set(merkle_snapshot))
        # Also mtime-suspect any merkle leaf (ignored files edited while commits moved)
        if file_mtimes:
            for rel, old_m in file_mtimes.items():
                p = root / rel
                try:
                    if not p.is_file() or p.stat().st_mtime != old_m:
                        candidates.append(rel)
                except OSError:
                    candidates.append(rel)
        candidates = sorted(set(candidates))
        current = dict(merkle_snapshot)
        for rel in candidates:
            if is_junk_rel(rel):
                continue
            p = root / rel
            if p.is_file():
                # Indexed universe only: never enlarge the corpus from random dirty paths
                # (untracked .venv-proof / .cache used to flood "added" → full reindex).
                if rel in merkle_snapshot or (
                    not indexed_universe_only and (rel in committed or rel in dirty)
                ):
                    current[rel] = file_sha256(p)
            elif rel in current:
                current.pop(rel, None)
        for rel in list(merkle_snapshot):
            if not (root / rel).is_file():
                current.pop(rel, None)
        diff = diff_hashes(merkle_snapshot, current)
        return _finish(diff, "git_diff")

    # --- Path C: mtime prefilter (dirty tree or no indexed_head) ---
    if merkle_snapshot and file_mtimes and fast_paths is None:
        suspects: list[str] = []
        for rel, old_m in file_mtimes.items():
            p = root / rel
            try:
                if not p.is_file() or p.stat().st_mtime != old_m:
                    suspects.append(rel)
            except OSError:
                suspects.append(rel)
        # Dirty paths only matter if already indexed (or universe expansion allowed)
        for rel in dirty:
            if is_junk_rel(rel):
                continue
            if rel in merkle_snapshot or not indexed_universe_only:
                suspects.append(rel)
        suspects = sorted(set(suspects))
        if suspects:
            current = dict(merkle_snapshot)
            for rel in suspects:
                if is_junk_rel(rel):
                    continue
                p = root / rel
                if p.is_file():
                    if rel in merkle_snapshot or not indexed_universe_only:
                        current[rel] = file_sha256(p)
                elif rel in current:
                    current.pop(rel, None)
            # drop deleted merkle entries
            for rel in list(merkle_snapshot):
                if not (root / rel).is_file():
                    current.pop(rel, None)
            diff = diff_hashes(merkle_snapshot, current)
            return _finish(diff, "mtime")

    # --- Path D: full / universe scan ---
    if fast_paths is not None:
        current = {p.relative_to(root).as_posix(): file_sha256(p) for p in fast_paths if p.is_file()}
    elif indexed_universe_only and merkle_snapshot:
        # Only re-hash what we indexed (+ detect deletions). New files need collect_paths elsewhere.
        current = {}
        for rel in merkle_snapshot:
            p = root / rel
            if p.is_file():
                current[rel] = file_sha256(p)
        diff = diff_hashes(merkle_snapshot, current)
        return _finish(diff, "merkle")
    else:
        current = scan_file_hashes(root, extensions=extensions)
    diff = diff_hashes(merkle_snapshot, current)
    return _finish(diff, "merkle")
