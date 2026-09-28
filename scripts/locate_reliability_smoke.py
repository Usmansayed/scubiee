#!/usr/bin/env python3
"""Pre-bump locate reliability smoke (expand / broad / seed / collect).

No publish. Exit 0 only when all checks pass.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

os.environ.setdefault("CTX_TRACE_PARALLEL", "1")
os.environ.setdefault("CTX_TRACE_ENGINE", "composite_v1")
os.environ.setdefault("CTX_TRUST_ID_FILE", "1")


def _ok(name: str, cond: bool, detail: str = "") -> dict[str, Any]:
    row = {"check": name, "ok": bool(cond), "detail": detail}
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return row


def main() -> int:
    from pipeline.context_trace import (
        finalize_suggested_seed,
        pick_suggested_seed,
        run_collect_hot,
        run_expand_context,
        run_pack_context,
    )

    t0 = time.perf_counter()
    results: list[dict[str, Any]] = []

    # 1) Expand after dense pack — callers should surface real call sites
    q_embed = "index_repo engine callers embed_many encode batch"
    pack = run_pack_context(
        ROOT,
        q_embed,
        seed_file="packages/pipeline/embedder.py",
        seed_symbol="embed_many",
        mode="lean",
        policy="strict",
        include_bodies=False,
        k=12,
    )
    pack_ids = {
        str(c.get("id") or "")
        for c in (pack.get("heatmap") or pack.get("cards") or [])
        if isinstance(c, dict) and c.get("id")
    }
    results.append(
        _ok("pack_embed_many", pack.get("ok") is True, f"count={pack.get('count')}")
    )

    for direction in ("callers", "callees", "effects"):
        exp = run_expand_context(
            ROOT,
            node=str((pack.get("seed") or {}).get("id") or "packages/pipeline/embedder.py::embed_many"),
            direction=direction,
            query=q_embed,
            prior_ids=set(),
            pack_seen_ids=pack_ids,
            k=12,
        )
        n = int(exp.get("count") or 0)
        if direction == "callers":
            syms = [str(c.get("symbol") or "") for c in (exp.get("delta") or [])]
            has_up = any("index_repo" in s or "incremental_sync" in s for s in syms)
            results.append(
                _ok(
                    "expand_callers_upward",
                    exp.get("ok") is True and n >= 1 and has_up,
                    f"count={n} top={syms[:4]}",
                )
            )
        elif direction == "effects":
            results.append(
                _ok(
                    f"expand_{direction}",
                    exp.get("ok") is True,
                    f"count={n} (sparse OK)",
                )
            )
        else:
            results.append(
                _ok(f"expand_{direction}", exp.get("ok") is True and n >= 1, f"count={n}")
            )

    # Conductor → MultiArch hop
    cond = run_pack_context(
        ROOT,
        "Conductor retrieve_conductor MultiArch hybrid graphify BM25",
        seed_file="packages/conductor/conductor.py",
        seed_symbol="Conductor",
        mode="lean",
        include_bodies=False,
        k=12,
    )
    cond_seed = str((cond.get("seed") or {}).get("symbol") or "")
    cond_files = " ".join(
        str(c.get("file") or "") for c in (cond.get("heatmap") or [])
    )
    results.append(
        _ok(
            "conductor_multiarch_hop",
            cond.get("ok") is True
            and (
                "MultiArch" in cond_seed
                or "architectures.py" in cond_files
                or bool(cond.get("seed_promoted"))
            ),
            f"seed={cond_seed} promoted={cond.get('seed_promoted')} count={cond.get('count')}",
        )
    )

    # 2) Broad honesty on thin leaf
    leaf = run_pack_context(
        ROOT,
        "TurboQuant to_float32 compressed embedding decode",
        seed_file="packages/pipeline/turbo_quant.py",
        seed_symbol="to_float32",
        mode="lean",
        policy="broad",
        include_bodies=False,
        k=12,
    )
    helped = leaf.get("escape_helped")
    results.append(
        _ok(
            "broad_escape_helped_present",
            leaf.get("ok") is True and "escape_helped" in leaf,
            f"escape_helped={helped} thin={leaf.get('thin')} count={leaf.get('count')}",
        )
    )
    if helped is False:
        nxt = str(leaf.get("next") or "").lower()
        results.append(
            _ok(
                "broad_honest_next",
                "expand" in nxt or "read" in nxt,
                nxt[:120],
            )
        )
    else:
        results.append(_ok("broad_densified_or_usable", True, "escape_helped=true"))

    # 3) Map-style empty seed finalize → non-empty symbol
    cards = [
        {
            "file": "packages/pipeline/vectordb.py",
            "symbol": "",
            "kind": "chunk",
            "role": "other",
            "score": 20.0,
            "start_line": 1,
            "end_line": 1,
            "loc": "packages/pipeline/vectordb.py:1-1",
        },
        {
            "file": "packages/pipeline/vectordb.py",
            "symbol": "FaissCollection",
            "kind": "class",
            "role": "class",
            "score": 18.0,
            "start_line": 104,
            "end_line": 369,
            "loc": "packages/pipeline/vectordb.py:104-369",
        },
    ]
    picked = pick_suggested_seed(
        cards, query="vector database FAISS embeddings search add load save"
    )
    finalized = finalize_suggested_seed(ROOT, picked)
    sym = str((finalized or {}).get("symbol") or "")
    results.append(
        _ok(
            "suggested_seed_nonempty",
            bool(sym) and not (finalized or {}).get("seed_incomplete"),
            f"symbol={sym!r}",
        )
    )

    # 4) Collect after lean (no packed_ids poison)
    lean = run_pack_context(
        ROOT,
        q_embed,
        seed_file="packages/pipeline/embedder.py",
        seed_symbol="embed_many",
        mode="lean",
        include_bodies=False,
        k=8,
    )
    persist = lean.get("_persist") or {}
    heat = lean.get("heatmap") or []
    only = {str(c.get("id")) for c in heat[:3] if isinstance(c, dict) and c.get("id")}
    collected = run_collect_hot(
        ROOT,
        heat,
        threshold=0.45,
        skip_ids=set(persist.get("packed_ids") or []),
        max_bodies=3,
        only_ids=only or None,
    )
    results.append(
        _ok(
            "collect_after_lean",
            collected.get("count", 0) >= 1 and not collected.get("empty_bodies"),
            f"count={collected.get('count')} packed_ids={persist.get('packed_ids')}",
        )
    )

    elapsed = round(time.perf_counter() - t0, 1)
    failed = [r for r in results if not r["ok"]]
    summary = {
        "ok": not failed,
        "elapsed_s": elapsed,
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
    }
    out_path = ROOT / "docs" / "superpowers" / "plans" / "locate-reliability-smoke-latest.json"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"wrote {out_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"warn: could not write summary: {exc}")

    print(
        f"\nBattery: {summary['passed']}/{len(results)} passed in {elapsed}s — "
        f"{'GREEN' if summary['ok'] else 'RED (no bump)'}"
    )
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
