"""Drop Context Engine state for repos that no longer exist on disk.

Every indexed repo leaves a registry entry, a project dir and a FAISS
collection under ``~/.context-engine``. Throwaway roots (pytest tmpdirs, A/B
workspace copies) therefore accumulate forever and there is no built-in GC.

Dry run by default; pass --apply to delete.

    python scripts/prune_engine_state.py
    python scripts/prune_engine_state.py --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))


def _exists(path: str) -> bool:
    try:
        return Path(path).is_dir()
    except OSError:
        return False


def dead_project_ids(registry: dict[str, Any], *, keep: set[str] | None = None) -> list[str]:
    """Project ids whose every recorded path is gone.

    An entry with no paths at all is kept: it carries no evidence that the repo
    was removed, and deleting it would only lose the id mapping.
    """
    keep_norm = {str(Path(k).resolve()) for k in (keep or set())}
    out = []
    for pid, meta in (registry.get("projects") or {}).items():
        if not isinstance(meta, dict):
            continue
        paths = [p for p in (meta.get("paths") or []) if isinstance(p, str)]
        if not paths:
            continue
        if any(str(Path(p).resolve()) in keep_norm for p in paths):
            continue
        if not any(_exists(p) for p in paths):
            out.append(pid)
    return out


def dead_collections(catalog: dict[str, Any], *, keep: set[str] | None = None) -> list[str]:
    """Collection names whose source directory is gone."""
    keep_norm = {str(Path(k).resolve()) for k in (keep or set())}
    out = []
    for entry in catalog.get("collections") or []:
        cwd = entry.get("cwd")
        name = entry.get("name")
        if not name or not isinstance(cwd, str):
            continue
        if str(Path(cwd).resolve()) in keep_norm:
            continue
        if not _exists(cwd):
            out.append(name)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    ap.add_argument(
        "--keep",
        action="append",
        default=[str(ROOT)],
        help="repo path to never prune (repeatable)",
    )
    args = ap.parse_args(argv)

    from pipeline.project_id import load_registry, projects_root, save_registry
    from pipeline.vectordb import VectorDatabase

    keep = set(args.keep)
    registry = load_registry()
    db = VectorDatabase()
    catalog = json.loads(db.catalog_path.read_text(encoding="utf-8"))

    pids = dead_project_ids(registry, keep=keep)
    cols = dead_collections(catalog, keep=keep)

    print(f"registry projects : {len(registry.get('projects') or {})} total, {len(pids)} dead")
    print(f"vector collections: {len(catalog.get('collections') or [])} total, {len(cols)} dead")
    for name in cols:
        print(f"  drop collection {name}")
    for pid in pids:
        print(f"  drop project    {pid}")

    if not args.apply:
        print("\ndry run — pass --apply to delete", file=sys.stderr)
        return 0

    for name in cols:
        db.drop_collection(name)
    projects = registry.setdefault("projects", {})
    proot = projects_root()
    for pid in pids:
        projects.pop(pid, None)
        pdir = proot / pid
        if pdir.is_dir():
            shutil.rmtree(pdir, ignore_errors=True)
    save_registry(registry)

    print(f"\npruned {len(cols)} collections and {len(pids)} projects", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
