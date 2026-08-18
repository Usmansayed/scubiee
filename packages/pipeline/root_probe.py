"""Cheap Merkle root probe — Cursor-style idle gate.

Idle tick answers one question first: did the root hash of the *indexed
universe* change? Clean ⇒ no embed / no graphify. Dirty ⇒ caller runs
incremental_sync.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from pipeline.merkle import file_sha256, is_junk_rel, root_hash
from pipeline.paths import collect_index_relpaths
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
    """Mtime-gated rehash of indexed leaves (+ optional indexable newcomers)."""
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
    if discover_newcomers:
        universe = collect_index_relpaths(
            root, fast=bool(meta.get("fast")), fast_roots=meta.get("fast_roots")
        )
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
