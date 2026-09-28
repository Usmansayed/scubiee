"""Cheap Merkle root probe — Cursor-style idle gate.

Idle tick answers one question first: did the root hash of the *indexed
universe* change? Clean ⇒ no embed / no graphify. Dirty ⇒ caller runs
incremental_sync.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from graphify.detect import _is_noise_dir
from pipeline.ignore import IgnoreRules, load_scubiee_ignore, should_index_rel
from pipeline.merkle import canonical_relpath, file_sha256, is_junk_rel, root_hash
from pipeline.paths import (
    collect_index_paths,
    collect_index_relpaths,
    fast_roots_from_env,
    index_rel_ok,
)
from pipeline.store import PipelineStore
from pipeline.vectordb import VectorDatabase


@dataclass
class RootProbeResult:
    clean: bool
    root: str
    stored_root: str
    ms: float
    added: list[str]
    modified: list[str]
    removed: list[str]
    files_checked: int
    hashed: int

    @property
    def changed_count(self) -> int:
        return len(self.added) + len(self.modified) + len(self.removed)

    def to_dict(self) -> dict:
        return {
            "clean": self.clean,
            "root": self.root,
            "stored_root": self.stored_root,
            "ms": round(self.ms, 2),
            "changed_count": self.changed_count,
            "added": self.added[:50],
            "modified": self.modified[:50],
            "removed": self.removed[:50],
            "files_checked": self.files_checked,
            "hashed": self.hashed,
        }


def _stored_root(store: PipelineStore, snap: dict[str, str]) -> str:
    if store.merkle_path.exists():
        try:
            data = json.loads(store.merkle_path.read_text(encoding="utf-8"))
            rh = data.get("root_hash")
            if rh:
                return str(rh)
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return root_hash(snap) if snap else ""


# merkle.json path -> (stamps, (snap, mtimes, meta, stored_root))
_INPUT_CACHE: dict[str, tuple[tuple, tuple]] = {}


def _probe_inputs(
    store: PipelineStore, root: Path, rules
) -> tuple[dict[str, str], dict[str, float], dict, str]:
    """Junk-filtered Merkle snapshot, mtimes, meta and stored root hash.

    Cached on the (mtime_ns, size) of merkle.json, meta.json and
    .scubieeignore. Between saves the poll ran the same parse + ~1.2k ignore
    matches every second (with merkle.json read twice); under a concurrent
    search each read was a GIL handoff (issue 4). Callers must not mutate.
    """
    from pipeline.fast_stat import fast_stat

    def _stamp(p: Path):
        st = fast_stat(p)
        return None if st is None else (st.st_mtime_ns, st.st_size)

    stamps = (
        _stamp(store.merkle_path),
        _stamp(store.meta_path),
        _stamp(root / ".scubieeignore"),
        str(root),
    )
    key = str(store.merkle_path)
    hit = _INPUT_CACHE.get(key)
    if hit is not None and hit[0] == stamps and stamps[0] is not None:
        return hit[1]  # type: ignore[return-value]
    snap = {
        k: v
        for k, v in store.load_merkle().items()
        if not is_junk_rel(k, root=root, rules=rules)
    }
    mtimes = store.load_mtimes()
    meta = store.load_meta()
    stored = _stored_root(store, snap)
    value = (snap, mtimes, meta, stored)
    if len(_INPUT_CACHE) > 16:
        _INPUT_CACHE.clear()
    _INPUT_CACHE[key] = (stamps, value)
    return value


def _rebuild_universe(
    root: Path,
    snap: dict[str, str],
    mtimes: dict[str, float],
) -> tuple[dict[str, str], int]:
    """Mtime-gated rehash of indexed leaves (``snap`` already junk-filtered).

    Stats go through ``fast_stat``: a plain ``os.stat`` per file hands the GIL
    over and back each time, and with a /v1/search running this loop took 18s
    instead of 78ms (issue 4; see pipeline/fast_stat.py).
    """
    from pipeline.fast_stat import fast_stat

    current: dict[str, str] = {}
    hashed = 0
    for rel, old_h in snap.items():
        p = root / rel
        st = fast_stat(p)
        if st is None or not st.is_file:
            continue
        if mtimes and rel in mtimes and st.st_mtime == mtimes[rel]:
            current[rel] = old_h
            continue
        current[rel] = file_sha256(p)
        hashed += 1
    return current, hashed


@dataclass
class DirWatch:
    """Folder mtimes carried between probes by a long-lived caller."""

    mtimes: dict[str, int] = field(default_factory=dict)
    last_ns: int = 0


def _dir_newcomers(
    root: Path,
    snap: dict[str, str],
    watch: DirWatch,
    *,
    rules: IgnoreRules,
    meta: dict,
) -> list[str]:
    """Indexable files missing from ``snap`` in folders whose mtime moved.

    Creating, deleting or renaming an entry bumps the parent folder's mtime on
    NTFS, APFS and ext4, so statting the folders that hold indexed files (and
    their ancestors) finds new files without walking the repo.
    """
    dirs: set[str] = {""}
    for key in snap:
        d = os.path.dirname(key)
        while d and d not in dirs:
            dirs.add(d)
            d = os.path.dirname(d)
    started = bool(watch.mtimes)
    since = watch.last_ns
    watch.last_ns = time.time_ns()
    from pipeline.fast_stat import fast_stat

    changed: list[tuple[str, int]] = []
    for d in dirs:
        st_d = fast_stat(root / d)
        if st_d is None:
            continue
        m = st_d.st_mtime_ns
        prev = watch.mtimes.get(d)
        watch.mtimes[d] = m
        if started and prev != m:
            # A folder that just joined the watch set may already hold a
            # sibling of the file that brought it in.
            changed.append((d, prev if prev is not None else since))
    for gone in [d for d in watch.mtimes if d not in dirs]:
        del watch.mtimes[gone]
    if not changed:
        return []

    fast = bool(meta.get("fast"))
    roots = fast_roots_from_env(meta.get("fast_roots") or None)
    found: list[str] = []
    for d, prev_ns in changed:
        prefix = d.replace("\\", "/")
        try:
            entries = list(os.scandir(root / d))
        except OSError:
            continue
        for entry in entries:
            rel = f"{prefix}/{entry.name}" if prefix else entry.name
            try:
                if entry.is_file(follow_symlinks=False):
                    if index_rel_ok(root, rel, rules=rules, fast=fast, roots=roots):
                        found.append(rel)
                    continue
                if not entry.is_dir(follow_symlinks=False):
                    continue
                # Only folders touched since we last looked; an old unindexed
                # tree (docs/, testdata/) is the periodic full scan's job.
                if canonical_relpath(rel) in dirs or entry.stat().st_mtime_ns <= prev_ns:
                    continue
            except OSError:
                continue
            if not should_index_rel(root, rel, is_dir=True, rules=rules):
                continue
            sub = root / rel
            if _is_noise_dir(entry.name, sub.parent):
                continue
            found.extend(
                p.relative_to(root).as_posix()
                for p in collect_index_paths(
                    root, fast=fast, fast_roots=meta.get("fast_roots"), under=sub, rules=rules
                )
            )
    return found


def root_probe(
    repo: Path,
    *,
    base_dir: Path | None = None,
    vdb: VectorDatabase | None = None,
    discover_newcomers: bool = True,
    dir_watch: DirWatch | None = None,
    store: PipelineStore | None = None,
) -> RootProbeResult:
    """Mtime-gated rehash of indexed leaves (+ optional indexable newcomers).

    ``store``: a long-lived caller (the keeper polls every second) passes its
    own store so the poll does not re-resolve the project each time.
    """
    from pipeline.fast_stat import cached_resolve

    t0 = time.perf_counter()
    root = cached_resolve(repo)
    rules = load_scubiee_ignore(root)
    if store is None:
        store = PipelineStore(root, base_dir=base_dir, vdb=vdb)
    snap, mtimes, meta, stored = _probe_inputs(store, root, rules)

    if not snap:
        return RootProbeResult(
            clean=False,
            root="",
            stored_root=stored,
            ms=(time.perf_counter() - t0) * 1000,
            added=[],
            modified=[],
            removed=[],
            files_checked=0,
            hashed=0,
        )

    current, hashed = _rebuild_universe(root, snap, mtimes)

    added: list[str] = []
    if discover_newcomers:
        universe = collect_index_relpaths(
            root, fast=bool(meta.get("fast")), fast_roots=meta.get("fast_roots")
        )
        # ``universe`` is posix-style (forward slashes); ``snap``/``current`` keys
        # are ``canonical_relpath`` (backslash + lowercased on Windows). Comparing
        # the raw sets here made every indexed file look "added" on Windows on
        # every probe — the keeper never converged and spun continuously (#3182).
        for rel in sorted(universe, key=canonical_relpath):
            ck = canonical_relpath(rel)
            if ck in snap or ck in current:
                continue
            # The Merkle drops junk paths (``sanitize_file_hashes``), so a junk
            # newcomer can never be recorded: it was re-reported as "added" on
            # every poll and re-synced forever (~7s a cycle on this repo),
            # stalling every save queued behind it.
            if is_junk_rel(rel, root=root, rules=rules) or is_junk_rel(ck, root=root, rules=rules):
                continue
            p = root / rel
            if p.is_file():
                current[ck] = file_sha256(p)
                added.append(ck)
                hashed += 1
    elif dir_watch is not None:
        for rel in _dir_newcomers(root, snap, dir_watch, rules=rules, meta=meta):
            ck = canonical_relpath(rel)
            if ck in snap or ck in current:
                continue
            try:
                current[ck] = file_sha256(root / rel)
            except OSError:
                continue
            added.append(ck)
            hashed += 1

    rh = root_hash(current)
    removed = sorted(p for p in snap if p not in current)
    modified = sorted(
        p for p in current if p in snap and snap[p] != current[p] and p not in added
    )
    # files in current not in snap are added (incl. discoverer)
    all_added = sorted(set(added) | {p for p in current if p not in snap})
    clean = rh == stored and not all_added and not modified and not removed

    # Internal keys are canonical_relpath (backslash + lowercased on Windows)
    # so dict lookups above are correct; the public result always reports
    # posix-style paths since every caller (sync_loop, MCP tools, tests)
    # treats "/" as the wire format.
    def _posix(paths: list[str]) -> list[str]:
        return sorted({p.replace("\\", "/") for p in paths})

    return RootProbeResult(
        clean=clean,
        root=rh,
        stored_root=stored,
        ms=(time.perf_counter() - t0) * 1000,
        added=_posix(all_added),
        modified=_posix(modified),
        removed=_posix(removed),
        files_checked=len(snap),
        hashed=hashed,
    )
