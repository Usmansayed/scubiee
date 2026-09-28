"""Issue 3: what makes up the engine's ~4GB commit (private bytes)?

Replays the engine's load order in a fresh interpreter and prints private
bytes (commit) and RSS after each step. Run with the uv-tool python while the
real engine is stopped or idle (it loads its own model + index copy):

    python scripts/engine_commit_breakdown.py <repo> [--no-index]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import psutil

_P = psutil.Process()
_ROWS: list[tuple[str, int, int, float]] = []
_T0 = time.perf_counter()


def mark(label: str) -> None:
    mi = _P.memory_info()
    _ROWS.append((label, int(getattr(mi, "private", 0) / 2**20), int(mi.rss / 2**20), time.perf_counter() - _T0))
    prev = _ROWS[-2][1] if len(_ROWS) > 1 else 0
    print(
        f"{label:<44} private={_ROWS[-1][1]:>6} MB (+{_ROWS[-1][1] - prev:>5})  rss={_ROWS[-1][2]:>6} MB  t={_ROWS[-1][3]:.1f}s",
        flush=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--no-index", action="store_true")
    args = ap.parse_args()
    os.environ.setdefault("CTX_REPO", str(Path(args.repo).resolve()))
    mark("interpreter")
    import numpy  # noqa: F401

    mark("import numpy")
    import onnxruntime as ort

    mark(f"import onnxruntime {ort.__version__}")
    import pipeline.engine as eng

    mark("import pipeline.engine (+conductor, graphify)")
    try:
        import fastembed  # noqa: F401

        mark("import fastembed")
    except Exception as exc:  # noqa: BLE001
        print(f"fastembed import failed: {exc}")
    if not args.no_index:
        engine = eng.load_engine(Path(args.repo).resolve())
        mark(f"load_engine (index {len(engine.texts)} chunks)")
        emb = engine.embedder
    else:
        from pipeline.engine import _get_embedder  # type: ignore[attr-defined]

        emb = _get_embedder()
    emb.embed_one("scubiee commit probe", is_query=True)
    mark("embedder loaded + first query encode (ORT session)")
    for n in (16, 44):
        emb.embed_many([f"def f{i}(x):\n    return x + {i}  # commit probe" * 8 for i in range(n)])
        mark(f"embed_many {n} docs (hot-save size)")
    if not args.no_index:
        q = "retrieve_D_channel_best FastEmbed embed_one keepalive"
        engine.search(q, top_k=8, skip_freshness=True)
        mark("one D-channel search")
    print("\nSUMMARY (MB private / rss):")
    for label, priv, rss, _t in _ROWS:
        print(f"  {priv:>6} / {rss:>6}  {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
