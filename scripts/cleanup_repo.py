"""One-shot project cleanup for packing / further product work.

Removes experiment scripts, bench dumps, caches, duplicate clones.
Keeps: packages/, tests/, docs/, fixtures/, vendor/, install/MCP scripts.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Root-level one-off benches / dumps (not part of the product)
ROOT_GLOBS = [
    "ab_test_raw_results.json",
    "benchmark_results.md",
    "final_30_raw.json",
    "rgated_20_raw.json",
    "soft30_raw.json",
    "test_graph_speed_output.json",
    "bedrock_*.py",
    "coderank_*.py",
    "compare_*.py",
    "conductor_*.py",
    "debug_*.py",
    "diagnose_*.py",
    "embed_*.py",
    "embedding_*.py",
    "export_real_chunks.py",
    "fastembed_*.py",
    "frontend_mcp_*_benchmark.py",
    "gemma_*.py",
    "nomic_*.py",
    "ollama_*.py",
    "print_*.py",
    "qwen*.py",
    "rag_*.py",
    "research_embed_recipes_coderank.py",
    "run_20_queries.py",
    "run_final_30.py",
    "run_queries.py",
    "run_rgated_20.py",
    "run_soft_30.py",
    "tei_*.py",
    "test_auto_indexer_dummy.py",
    "test_graph_speed.py",
    "try_bge_*.py",
    "turboquant_*_benchmark.py",
]

# Experiment / one-off scripts (keep install + mcp + cleanup + timed index)
SCRIPTS_REMOVE = [
    "_analyze_hard_v2_misses.py",
    "bench_chunk_compress.py",
    "bench_compress_mix.py",
    "bench_compress_soft.py",
    "bench_compress_soft_expanded.py",
    "bench_compress_vs_legacy.py",
    "bench_retrieve_planner_ab.py",
    "bench_search.py",
    "bench_search_profile.py",
    "bench_soft_tuned_search.py",
    "bench_token_meter.py",
    "clean_package_proof.py",
    "dev_ab_frontend.py",
    "dev_session_ab.py",
    "keeper_session.py",
    "mcp_handshake_smoke.py",
    "run_agent_gather_until_ready.py",
    "run_graphify_vs_d_fastembed.py",
    "run_prod_ab_agent_test.py",
    "run_soft_arch_bakeoff.py",
    "smoke_freshness_e2e.py",
    "timed_sync_probe.py",
]

# Heavy / regenerated dirs
DIRS_REMOVE = [
    "out",
    "graphify-out",
    "build",
    ".venv-proof",
    ".pytest_cache",
    ".cache",
    "__pycache__",
    "packages/context_engine.egg-info",
    "testdata/frontend-mcp-graphify",
]

# Misc files under packages/
MISC_REMOVE = [
    "packages/test_auto_indexer_dummy.py",
]


def _expand(pattern: str) -> list[Path]:
    return sorted(ROOT.glob(pattern))


def _rm(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    print(f"  removed {path.relative_to(ROOT)}")


def main() -> int:
    print(f"cleaning {ROOT}")
    removed = 0

    for pat in ROOT_GLOBS:
        for p in _expand(pat):
            if p.is_file():
                _rm(p)
                removed += 1

    for name in SCRIPTS_REMOVE:
        p = ROOT / "scripts" / name
        if p.exists():
            _rm(p)
            removed += 1

    for rel in DIRS_REMOVE:
        p = ROOT / rel
        if p.exists():
            _rm(p)
            removed += 1

    for rel in MISC_REMOVE:
        p = ROOT / rel
        if p.exists():
            _rm(p)
            removed += 1

    # stray pycaches under packages/tests
    for pyc in ROOT.rglob("__pycache__"):
        if ".venv" in pyc.parts:
            continue
        _rm(pyc)
        removed += 1

    # egg-info anywhere under packages
    for egg in ROOT.glob("*.egg-info"):
        _rm(egg)
        removed += 1
    for egg in (ROOT / "packages").glob("*.egg-info"):
        _rm(egg)
        removed += 1

    print(f"done ({removed} paths touched)")
    print("kept: packages/, tests/, docs/, fixtures/, vendor/, scripts/install*, cleanup, mcp install, index_frontend_timed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
