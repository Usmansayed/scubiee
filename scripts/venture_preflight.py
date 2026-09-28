"""Preflight: refuse venture bakeoffs unless embed + (optional) FAISS are live."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def preflight(*, fixture_root: Path, require_faiss: bool = True) -> dict[str, Any]:
    import onnxruntime as ort
    from pipeline.accel import resolve_runtime
    from pipeline.embedder import Embedder
    from trace_lab.embed_field import EmbedField
    from trace_lab.corpus import extract_nodes
    from trace_lab.semantic_venture import product_faiss_ok

    providers = list(ort.get_available_providers())
    accel = resolve_runtime()
    emb = Embedder(quiet=True)
    mat = emb.embed_many(["def ping():\n  return 1"], is_query=False)
    embed_ok = (
        emb.backend == "fastembed"
        and str(getattr(mat, "shape", [0])[-1]) in {"768", "768"}
        and int(mat.shape[0]) == 1
        and emb.device in {"dml", "cuda", "cpu", "gpu"}
    )
    # Prefer DML/CUDA; CPU allowed but flagged
    accel_ok = accel.provider in providers or accel.profile == "cpu"

    nodes = extract_nodes(fixture_root)
    cache = fixture_root / ".embed_cache" / "coderank.jsonl"
    field = EmbedField(nodes, cache_path=cache, require_real=True, quiet=True)
    field_ok = str(field.backend).startswith("real:") and int(field.dim) >= 384

    # Gate on PRODUCT repo FAISS only. Never search_repo(fixture): fixture shares
    # the parent git project_id and can overwrite / contaminate the product store.
    faiss_prod = product_faiss_ok(ROOT)
    faiss_gate = faiss_prod if require_faiss else {"ok": True, "skipped": True}

    report = {
        "ort_providers": providers,
        "accel_profile": accel.profile,
        "accel_provider": accel.provider,
        "accel_batch": accel.batch_size,
        "embed_backend": emb.backend,
        "embed_device": emb.device,
        "embed_ok": embed_ok,
        "accel_ok": accel_ok,
        "field_backend": field.backend,
        "field_dim": field.dim,
        "field_n": len(field.ids),
        "field_ok": field_ok,
        "faiss_fixture": {"ok": False, "skipped": True, "reason": "do_not_search_fixture_under_product_project"},
        "faiss_product_repo": faiss_prod,
        "faiss_gate_ok": bool(faiss_gate.get("ok")),
        "dml_live": "DmlExecutionProvider" in providers and emb.device == "dml",
    }
    report["blockers"] = []
    if not embed_ok:
        report["blockers"].append("Embedder smoke failed")
    if not field_ok:
        report["blockers"].append(f"EmbedField not real CodeRank (backend={field.backend})")
    if require_faiss and not faiss_prod.get("ok"):
        report["blockers"].append(
            f"Product FAISS unhealthy on {ROOT}: {faiss_prod.get('error') or '0 hits'} "
            f"(meta_root={faiss_prod.get('meta_root')})"
        )
    if "DmlExecutionProvider" not in providers:
        report["blockers"].append("DmlExecutionProvider missing from ORT")
    if emb.device != "dml" and "DmlExecutionProvider" in providers:
        report["blockers"].append(f"ORT has DML but Embedder device={emb.device}")
    report["ok"] = len(report["blockers"]) == 0
    return report


def main() -> int:
    from trace_lab.cases import default_fixture_root

    require_faiss = "--no-faiss" not in sys.argv
    # Default: require FAISS on fixture so venture A1 is actually testing product vectors.
    # Pass --no-faiss only for embed-field-only ablations (must be labeled).
    rep = preflight(fixture_root=default_fixture_root().resolve(), require_faiss=require_faiss)
    out = ROOT / "docs/superpowers/plans/2026-09-06-venture-preflight.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(json.dumps(rep, indent=2))
    if not rep["ok"]:
        print("PREFLIGHT FAIL:", "; ".join(rep["blockers"]), file=sys.stderr)
        return 2
    print("PREFLIGHT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
