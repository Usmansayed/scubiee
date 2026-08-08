"""Wipe local FAISS/TurboQuant collections + compress-bench indexes.

Keeps bakeoff reports under out/compress_bench/*.md|json.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.vectordb import VectorDatabase, default_vectordb_root  # noqa: E402


def _rm(path: Path) -> None:
    if not path.exists():
        print(f"  skip (missing): {path}")
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    print(f"  removed: {path}")


def main() -> int:
    vdb_root = default_vectordb_root()
    print(f"vectordb_root={vdb_root}")
    vdb = VectorDatabase(root=vdb_root)
    entries = vdb.list_collections()
    names = [e.get("name") for e in entries if e.get("name")]
    print(f"collections={names}")
    for name in names:
        try:
            vdb.drop_collection(name)
            print(f"  dropped collection: {name}")
        except Exception as exc:  # noqa: BLE001
            print(f"  drop failed {name}: {exc}")

    cols = vdb_root / "collections"
    if cols.is_dir():
        for child in list(cols.iterdir()):
            _rm(child)
    catalog = vdb_root / "catalog.json"
    catalog.write_text(json.dumps({"collections": []}, indent=2), encoding="utf-8")
    print(f"  reset catalog: {catalog}")

    indexes = Path.home() / ".context-engine" / "indexes"
    print(f"indexes_home={indexes}")
    if indexes.is_dir():
        for child in list(indexes.iterdir()):
            _rm(child)

    bench = ROOT / "out" / "compress_bench" / "indexes"
    print(f"compress_bench_indexes={bench}")
    _rm(bench)

    for log in (
        ROOT / "out" / "compress_mix_run.log",
        ROOT / "out" / "compress_vs_legacy_run.log",
        ROOT / "out" / "compress_soft_expanded_run.log",
    ):
        _rm(log)

    print("cleanup done (reports kept under out/compress_bench/)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
