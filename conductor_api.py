"""HTTP API for Conductor retrieval A/B.

Surfaces:
  GET  /health
  POST /search         {query, top_k, mode}
  POST /compare        graphify vs d_rerank
  POST /compare_rgated d_rerank vs r_gated  (soft-router test)

Modes: graphify | d_rerank | d_floor | r_gated | both | both_rg

Usage:
  .\\.venv\\Scripts\\python -u conductor_api.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT))

from conductor.service import get_engine  # noqa: E402

app = FastAPI(
    title="Conductor A/B API",
    description=(
        "Retrieval A/B on testdata/frontend-mcp. "
        "Production default: d_rerank. Soft router experiment: r_gated."
    ),
    version="0.2.0",
)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(8, ge=1, le=30)
    mode: Literal[
        "graphify", "d_rerank", "d_floor", "r_gated", "both", "both_rg"
    ] = "both"


class CompareRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=30)


@app.on_event("startup")
def _startup() -> None:
    get_engine().ensure_loaded()


@app.get("/health")
def health():
    eng = get_engine()
    if not eng.ready:
        eng.ensure_loaded()
    return {"ok": True, **eng.status()}


@app.post("/search")
def search(req: SearchRequest):
    try:
        return get_engine().search(req.query, mode=req.mode, top_k=req.top_k)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/compare")
def compare(req: CompareRequest):
    """Graphify vs D_rerank (+ agreement)."""
    try:
        return get_engine().search(req.query, mode="both", top_k=req.top_k)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/compare_rgated")
def compare_rgated(req: CompareRequest):
    """D_rerank vs R_gated soft router (+ agreement). Primary OpenCode soft A/B."""
    try:
        return get_engine().search(req.query, mode="both_rg", top_k=req.top_k)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


def main() -> None:
    host = "127.0.0.1"
    port = 8765
    print(f"Conductor A/B API on http://{host}:{port}", flush=True)
    print("  POST /compare         graphify vs d_rerank", flush=True)
    print("  POST /compare_rgated  d_rerank vs r_gated", flush=True)
    print(
        "  POST /search          mode: graphify|d_rerank|d_floor|r_gated|both|both_rg",
        flush=True,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
