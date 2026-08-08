"""Cheap Merkle root probe — Cursor-style idle gate.

Idle tick answers one question first: did the root hash of the *indexed
universe* change? Clean ⇒ no embed / no graphify. Dirty ⇒ caller runs
incremental_sync.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from pipeline.merkle import _is_ignored_dir_name, file_sha256, is_junk_rel, root_hash
from pipeline.paths import fast_roots_from_env
from pipeline.store import PipelineStore
from pipeline.vectordb import VectorDatabase


def _list_fast_py(root: Path, fast_roots: list[str] | tuple[str, ...] | None) -> set[str]:
    """Cheap .py listing under fast roots only (no Graphify whole-tree walk)."""
    roots = fast_roots_from_env(list(fast_roots) if fast_roots else None)
    out: set[str] = set()
    for fr in roots:
        base = root / fr.rstrip("/")
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base, topdown=True):
            dirnames[:] = [d for d in dirnames if not _is_ignored_dir_name(d)]
            dp = Path(dirpath)
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                p = dp / fname
                try:
                    rel = p.relative_to(root).as_posix()
                except ValueError:
                    continue
                if not is_junk_rel(rel):
                    out.add(rel)
    return out


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


def _rebuild_universe(
    root: Path,
    snap: dict[str, str],
    mtimes: dict[str, float],
) -> tuple[dict[str, str], int]:
    """Mtime-gated rehash of indexed leaves. Returns (current_hashes, hashed_count)."""
    current: dict[str, str] = {}
    hashed = 0
    for rel, old_h in snap.items():
        if is_junk_rel(rel):
            continue
        p = root / rel
        if not p.is_file():
            continue
        if mtimes and rel in mtimes:
            try:
                if p.stat().st_mtime == mtimes[rel]:
                    current[rel] = old_h
                    continue
            except OSError:
                pass
        current[rel] = file_sha256(p)
        hashed += 1
    return current, hashed


def root_probe(
    repo: Path,
    *,
    base_dir: Path | None = None,
    vdb: VectorDatabase | None = None,
    discover_newcomers: bool = True,
) -> RootProbeResult:
    """Mtime-gated rehash of indexed leaves (+ optional fast_roots newcomers)."""
    t0 = time.perf_counter()
    root = repo.resolve()
    store = PipelineStore(root, base_dir=base_dir, vdb=vdb)
    snap = {k: v for k, v in store.load_merkle().items() if not is_junk_rel(k)}
    mtimes = store.load_mtimes()
    meta = store.load_meta()
    stored = _stored_root(store, snap)

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
    if discover_newcomers and meta.get("fast"):
        universe = _list_fast_py(root, meta.get("fast_roots"))
        for rel in sorted(universe - set(snap)):
            p = root / rel
            if p.is_file():
                current[rel] = file_sha256(p)
                added.append(rel)
                hashed += 1

    rh = root_hash(current)
    removed = sorted(p for p in snap if p not in current)
    modified = sorted(
        p for p in current if p in snap and snap[p] != current[p] and p not in added
    )
    # files in current not in snap are added (incl. discoverer)
    all_added = sorted(set(added) | {p for p in current if p not in snap})
    clean = rh == stored and not all_added and not modified and not removed

    return RootProbeResult(
        clean=clean,
        root=rh,
        stored_root=stored,
        ms=(time.perf_counter() - t0) * 1000,
        added=all_added,
        modified=modified,
        removed=removed,
        files_checked=len(snap),
        hashed=hashed,
    )
