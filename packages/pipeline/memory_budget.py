"""Cross-platform Context Engine memory budgets.

CPU and RAM budgets are always coupled — heavy work gets both, light work gets neither.

Bootstrap (first complete index / init): 800 MB RAM + 30% CPU.

Background reindex (incremental sync): 500 MB RAM + 15% CPU. Invisible during coding.
Serve / live MCP: soft advisory tree budget **800 MB**; **full-warm while Cursor connected**
(engine + locate AST + bridge, embedder held) commonly lands near **0.9–1.2 GB** and is
accepted for &lt;1s first-tool availability — do not auto-demote on soft overage.
Large reindex / bulk index / bulk sync: total ≤ **1 GB** OK.
Engine soft RSS cap remains tiered (520–800 MB); FastEmbed loads only in the engine.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Literal

from pipeline.store import PipelineStore

MemoryMode = Literal["bootstrap", "background", "large_reindex"]

BOOTSTRAP_RSS_CAP_MB = 800
BACKGROUND_RSS_CAP_MB = 500  # Light sync: 1-5 files, stay invisible
LARGE_REINDEX_RSS_CAP_MB = 1000
LARGE_REINDEX_CHUNK_THRESHOLD = 6000


@dataclass(frozen=True)
class IndexMemoryBudget:
    mode: MemoryMode
    rss_cap_mb: int
    mlx_cache_mb: int
    mlx_batch: int
    embed_batch_ceiling: int
    aggressive_unload: bool
    # CPU thread budget as percentage of os.cpu_count(). On CPU-only profiles
    # (no GPU), this controls how much CPU the embedding phase uses.
    # Heavy work (800MB–1GB) is capped at 30% CPU; light sync (500MB) at 15%.
    # The Windows engine job also hard-caps at CTX_ENGINE_CPU_CAP_PCT (default 30).
    cpu_thread_pct: float = 0.30


def bootstrap_budget() -> IndexMemoryBudget:
    return IndexMemoryBudget(
        mode="bootstrap",
        rss_cap_mb=BOOTSTRAP_RSS_CAP_MB,
        mlx_cache_mb=256,
        mlx_batch=48,
        embed_batch_ceiling=48,
        aggressive_unload=False,
        cpu_thread_pct=0.30,
    )


def background_budget() -> IndexMemoryBudget:
    return IndexMemoryBudget(
        mode="background",
        rss_cap_mb=BACKGROUND_RSS_CAP_MB,
        mlx_cache_mb=128,
        mlx_batch=24,
        embed_batch_ceiling=24,
        aggressive_unload=True,
        cpu_thread_pct=0.15,
    )


def large_reindex_budget() -> IndexMemoryBudget:
    return IndexMemoryBudget(
        mode="large_reindex",
        rss_cap_mb=LARGE_REINDEX_RSS_CAP_MB,
        mlx_cache_mb=512,
        mlx_batch=64,
        embed_batch_ceiling=64,
        aggressive_unload=False,
        cpu_thread_pct=0.30,
    )


def is_bootstrap_index(store: PipelineStore) -> bool:
    """True when this repo has never completed a full index."""
    try:
        if not store.chunks_path.is_file():
            return True
        if store.chunks_path.stat().st_size <= 2:
            return True
    except OSError:
        return True
    meta = store.load_meta()
    if int(meta.get("chunks") or 0) <= 0:
        return True
    if meta.get("indexed_at") is None and meta.get("root_hash") is None:
        return True
    return False


def indexed_chunk_count(store: PipelineStore) -> int:
    meta = store.load_meta()
    n = int(meta.get("chunks") or 0)
    if n > 0:
        return n
    try:
        return len(store.load_chunks())
    except Exception:  # noqa: BLE001
        return 0


def resolve_index_memory_budget(
    *,
    background: bool = False,
    store: PipelineStore | None = None,
) -> IndexMemoryBudget:
    if store is not None and not is_bootstrap_index(store):
        if indexed_chunk_count(store) > LARGE_REINDEX_CHUNK_THRESHOLD:
            return large_reindex_budget()
        if background:
            return background_budget()
        # Force/full reindex of an existing modest corpus: same weight as bootstrap
        # (800MB RAM + 30% CPU) since it processes all chunks, not just a few.
        return bootstrap_budget()
    if background:
        return background_budget()
    return bootstrap_budget()


def apply_index_memory_budget(budget: IndexMemoryBudget) -> None:
    """Apply budget as env defaults (never override explicit caller env)."""
    os.environ.setdefault("CTX_CE_MEMORY_MODE", budget.mode)
    os.environ.setdefault("CTX_CE_RSS_CAP_MB", str(budget.rss_cap_mb))
    # CPU thread budget for CPU-only embedding (INT8 on laptops without GPU).
    # DML/CUDA/MLX profiles ignore this — GPU handles the compute.
    # Bootstrap guarantees at least 2 threads (except on single-core) so that
    # 4-core laptops don't get stuck at single-threaded.
    cores = os.cpu_count() or 4
    raw_threads = round(cores * budget.cpu_thread_pct)
    if budget.mode in ("bootstrap", "large_reindex"):
        cpu_threads = max(min(2, cores), raw_threads)
    else:
        cpu_threads = max(1, raw_threads)
    os.environ.setdefault("CTX_CPU_EMBED_THREADS", str(cpu_threads))
    os.environ["CTX_MLX_DTYPE"] = "float16"
    os.environ.setdefault("CTX_MLX_FAST_ATTN", "1")
    os.environ.setdefault("CTX_MLX_FAST_LN", "1")
    os.environ.setdefault("CTX_MLX_EVAL", "output")
    if "CTX_MLX_CACHE_MB" not in os.environ:
        os.environ["CTX_MLX_CACHE_MB"] = str(budget.mlx_cache_mb)
    mlx = os.environ.get("CTX_EMBED_BACKEND", "").strip().lower() == "mlx"
    if not mlx:
        try:
            from pipeline.accel import load_accel

            prof = load_accel()
            mlx = bool(prof and (prof.profile == "mlx" or prof.backend == "mlx"))
        except Exception:  # noqa: BLE001
            mlx = False
    if mlx and "CTX_EMBED_BATCH" not in os.environ:
        os.environ["CTX_EMBED_BATCH"] = str(budget.mlx_batch)
    if budget.aggressive_unload:
        os.environ.setdefault("CTX_CE_AGGRESSIVE_UNLOAD", "1")
    if "CTX_CE_EMB_BATCH_CEILING" not in os.environ:
        os.environ["CTX_CE_EMB_BATCH_CEILING"] = str(budget.embed_batch_ceiling)


def force_apply_memory_budget(budget: IndexMemoryBudget) -> None:
    """Unconditionally override memory budget env vars.

    Used after a bulk operation finishes to restore the conservative background
    budget so the daemon doesn't keep running at elevated resources for
    subsequent small live edits.
    """
    os.environ["CTX_CE_MEMORY_MODE"] = budget.mode
    os.environ["CTX_CE_RSS_CAP_MB"] = str(budget.rss_cap_mb)
    # Sync CPU thread budget with the new RAM budget
    cores = os.cpu_count() or 4
    raw_threads = round(cores * budget.cpu_thread_pct)
    if budget.mode in ("bootstrap", "large_reindex"):
        cpu_threads = max(min(2, cores), raw_threads)
    else:
        cpu_threads = max(1, raw_threads)
    os.environ["CTX_CPU_EMBED_THREADS"] = str(cpu_threads)
    os.environ["CTX_MLX_CACHE_MB"] = str(budget.mlx_cache_mb)
    os.environ["CTX_CE_EMB_BATCH_CEILING"] = str(budget.embed_batch_ceiling)
    mlx = os.environ.get("CTX_EMBED_BACKEND", "").strip().lower() == "mlx"
    if not mlx:
        try:
            from pipeline.accel import load_accel

            prof = load_accel()
            mlx = bool(prof and (prof.profile == "mlx" or prof.backend == "mlx"))
        except Exception:  # noqa: BLE001
            mlx = False
    if mlx:
        os.environ["CTX_EMBED_BATCH"] = str(budget.mlx_batch)
    if budget.aggressive_unload:
        os.environ["CTX_CE_AGGRESSIVE_UNLOAD"] = "1"
    else:
        os.environ.pop("CTX_CE_AGGRESSIVE_UNLOAD", None)


def _rusage_rss_mb() -> float | None:
    """Unix ``resource`` module; missing on Windows."""
    try:
        import resource
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak = int(usage.ru_maxrss)
    if sys.platform == "darwin":
        return peak / (1024 * 1024)
    return peak / 1024


def process_rss_mb() -> float | None:
    try:
        import psutil  # type: ignore

        return float(psutil.Process().memory_info().rss) / (1024 * 1024)
    except Exception:  # noqa: BLE001
        pass
    return _rusage_rss_mb()


def scubiee_tree_rss_mb() -> dict[str, Any]:
    """Sum RSS for engine / bridge / locate / watchdog processes (best-effort)."""
    rows: list[dict[str, Any]] = []
    total = 0.0
    try:
        import psutil  # type: ignore

        markers = (
            "pipeline engine",
            "pipeline.mcp_bridge",
            "pipeline.mcp_locate",
            "mcp_bridge",
            "mcp_locate",
            "engine watchdog",
            "engine run",
        )
        for proc in psutil.process_iter(["pid", "name", "memory_info", "cmdline"]):
            try:
                cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
                blob = cmd.lower()
                if not any(m in blob for m in markers):
                    continue
                rss = float(proc.info["memory_info"].rss) / (1024 * 1024)
                role = "other"
                if "mcp_bridge" in blob or "pipeline.mcp_bridge" in blob:
                    role = "bridge"
                elif "mcp_locate" in blob or "pipeline.mcp_locate" in blob:
                    role = "locate"
                elif "watchdog" in blob:
                    role = "watchdog"
                elif "engine run" in blob or "pipeline engine" in blob:
                    role = "engine"
                rows.append(
                    {
                        "pid": int(proc.info["pid"]),
                        "role": role,
                        "rss_mb": round(rss, 1),
                        "cmd": cmd[:160],
                    }
                )
                total += rss
            except (psutil.Error, TypeError, ValueError, KeyError):
                continue
    except Exception:  # noqa: BLE001
        return {"ok": False, "total_rss_mb": None, "processes": []}
    rows.sort(key=lambda r: float(r.get("rss_mb") or 0.0), reverse=True)
    return {
        "ok": True,
        "total_rss_mb": round(total, 1),
        "process_count": len(rows),
        "processes": rows[:12],
    }


def process_rss_peak_mb() -> float | None:
    try:
        import psutil  # type: ignore

        info = psutil.Process().memory_info()
        peak = getattr(info, "peak_wset", None) or info.rss
        return float(peak) / (1024 * 1024)
    except Exception:  # noqa: BLE001
        pass
    return _rusage_rss_mb()


def rss_cap_mb() -> int | None:
    raw = os.environ.get("CTX_CE_RSS_CAP_MB", "").strip()
    if not raw:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def mlx_compute_summary(timings: dict[str, float] | None) -> dict[str, float]:
    """Extract model-side compute from embedder timing breakdown."""
    timings = timings or {}
    infer = float(timings.get("mlx_inference") or timings.get("ort_inference") or 0.0)
    tokenize = float(timings.get("tokenization") or 0.0)
    prep = float(timings.get("batch_prep") or 0.0)
    return {
        "model_inference_s": round(infer, 3),
        "model_tokenize_s": round(tokenize, 3),
        "model_batch_prep_s": round(prep, 3),
        "model_compute_s": round(infer + prep, 3),
    }
