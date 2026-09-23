"""Warm long-lived search engine (embedder + conductor cached in-process)."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from conductor.architectures import MultiArchConductor
from conductor.bm25_index import BM25Index
from conductor.conductor import ConductorConfig
from conductor.graphify_retriever import ChunkSpan, GraphifyChunkRetriever
from graphify.serve import _load_graph

from pipeline.capability import CapabilityIndex, LocateHit, ensure_cards
from pipeline.embedder import Embedder
from pipeline.hot_patch import disk_preview, hot_patch_texts, rebuild_bm25
from pipeline.searcher import FaissDenseAdapter, SearchResult
from pipeline.store import ChunkRecord, PipelineStore
from pipeline.vectordb import VectorDatabase

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# All ORT/DML encodes run on ONE dedicated thread. Concurrent DirectML from
# ThreadingHTTPServer workers + keepalive wedged the engine (map hung forever).
_EMBED_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scubiee-embed")
_EMBED_INFER_LOCK = threading.RLock()  # retained for tests / status; executor is authority
_EMBED_WORKER_LOCAL = threading.local()
_EMBED_BUSY = threading.Event()


def try_embed_infer_lock(*, blocking: bool = True, timeout: float = -1.0) -> bool:
    if blocking and timeout < 0:
        return bool(_EMBED_INFER_LOCK.acquire(blocking=True))
    return bool(_EMBED_INFER_LOCK.acquire(blocking=blocking, timeout=timeout))


def release_embed_infer_lock() -> None:
    try:
        _EMBED_INFER_LOCK.release()
    except RuntimeError:
        pass


_ABORT_EMBED = object()


def run_embed_infer(
    fn, *, timeout_s: float | None = 120.0, abort_if_search: bool = False
):
    """Run ``fn`` on the single embed worker. ``timeout_s=None`` waits forever.

    Re-entrant: if already on the embed worker (e.g. search submitted a job that
    calls ``_LazyEmbedder.embed_one`` → another ``run_embed_infer``), run inline.
    Nested submit on ``max_workers=1`` would otherwise deadlock forever.

    ``abort_if_search``: keepalive ticks only — if a real map/search set
    ``_SEARCH_IN_FLIGHT`` before this job starts, skip encode so locate is not
    queued behind a dummy tick.
    """
    if getattr(_EMBED_WORKER_LOCAL, "inside", False):
        return fn()

    def _wrap():
        if abort_if_search and _SEARCH_IN_FLIGHT.is_set():
            return _ABORT_EMBED
        _EMBED_WORKER_LOCAL.inside = True
        _EMBED_BUSY.set()
        try:
            return fn()
        finally:
            _EMBED_WORKER_LOCAL.inside = False
            _EMBED_BUSY.clear()

    fut = _EMBED_EXECUTOR.submit(_wrap)
    return fut.result(timeout=timeout_s)


def _verify_gpu_provider(embedder: Embedder) -> None:
    """Warn if the configured GPU profile silently fell back to CPU at runtime.

    Called after the warm-up embed_one. Checks the accel profile vs what ORT
    actually loaded. Logs a clear warning so users know they're on CPU.
    """
    try:
        from pipeline.accel import load_accel, ort_available_providers

        profile = load_accel()
        if not profile or profile.profile in {"cpu", "mlx"}:
            return  # CPU or MLX — no ORT provider concern

        want_provider = {
            "cuda": "CUDAExecutionProvider",
            "dml": "DmlExecutionProvider",
            "coreml": "CoreMLExecutionProvider",
        }.get(profile.profile)

        if not want_provider:
            return

        available = ort_available_providers()
        if want_provider in available:
            return  # All good — GPU provider loaded

        print(
            f"[engine] WARNING: profile={profile.profile} but {want_provider} not in "
            f"available providers {available}. Embedding is running on CPU. "
            f"Run `scubiee setup --repair` to fix GPU acceleration.",
            file=sys.stderr,
            flush=True,
        )
    except Exception:  # noqa: BLE001
        pass  # Don't crash the warm-up over a diagnostic check

_LOCK = threading.RLock()
_ENGINES: dict[str, "WarmSearchEngine"] = {}
_EMBEDDERS: dict[str, Embedder] = {}

# Most capability cards a SOFT query may promote ahead of RAG hits.
CAP_MERGE_MAX = int(os.environ.get("CTX_CAPABILITY_MAX_PROMOTED", "2"))
CAP_MERGE_MIN_SCORE = 2.0


def promotable_cards(
    capability: "CapabilityIndex | None",
    cap_hits: list[LocateHit],
    top_k: int,
    *,
    max_promoted: int | None = None,
) -> list[LocateHit]:
    """Capability cards allowed ahead of RAG hits for a SOFT query.

    Cards are BM25 over module summaries, so a bare score floor matches almost
    any English query. Require a decisive leader (``strong_hit``) and cap the
    count, otherwise cards fill the whole window and evict the real hits.
    """
    if capability is None or not cap_hits or not capability.strong_hit(cap_hits):
        return []
    limit = CAP_MERGE_MAX if max_promoted is None else max_promoted
    keep = min(top_k, max(1, limit))
    return [h for h in cap_hits if h.score >= CAP_MERGE_MIN_SCORE][:keep]


def _engine_key(root: Path, base_dir: Path | None) -> str:
    return f"{root.resolve()}::{base_dir.resolve() if base_dir else ''}"


def _store_generation_mtime(store: PipelineStore) -> float:
    """Newest published artifact mtime — used to drop a stale in-process engine."""
    latest = 0.0
    for path in (store.meta_path, store.chunks_path, store.merkle_path):
        try:
            if path.is_file():
                latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return latest


class _LazyEmbedder:
    """Defer model weights until the first semantic query (locate_only tier)."""

    def __init__(self, model: str, *, dim: int | None, cache_path: Path | None) -> None:
        self.model = model
        self.dim = dim
        self.cache_path = cache_path
        self.backend = "lazy"
        self._inner: Embedder | None = None

    def _ensure(self) -> Embedder:
        if self._inner is None:
            self._inner = get_embedder(
                self.model,
                dim=self.dim,
                cache_path=self.cache_path,
                eager=True,
            )
            self.backend = self._inner.backend
            try:
                from pipeline.memory_governor import get_governor

                get_governor().note_embedder_loaded()
            except Exception:  # noqa: BLE001
                pass
        return self._inner

    def unload(self) -> None:
        self._inner = None
        self.backend = "lazy"

    def embed_one(self, *args: Any, **kwargs: Any) -> Any:
        try:
            from pipeline.memory_governor import get_governor

            get_governor().note_semantic_activity()
        except Exception:  # noqa: BLE001
            pass

        def _call() -> Any:
            return self._ensure().embed_one(*args, **kwargs)

        return run_embed_infer(_call, timeout_s=120.0)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ensure(), name)


def get_embedder(
    model: str,
    *,
    dim: int | None,
    cache_path: Path | None,
    eager: bool = True,
) -> Embedder:
    """Process-wide CodeRank/Ollama embedder cache (load weights once).

    Heavy ORT/MLX session creation runs **outside** ``_LOCK`` so ``/health``
    (``embedder_is_loaded``) stays responsive during cold prewarm.
    """
    key = f"{model}|{dim}|{cache_path}"
    with _LOCK:
        existing = _EMBEDDERS.get(key)
        if existing is not None:
            return existing
    emb = Embedder(model=model, dim=dim, cache_path=cache_path)
    if eager:
        if emb.backend == "coderank":
            emb._ensure_coderank()
        elif emb.backend == "mlx":
            emb._ensure_mlx()
    with _LOCK:
        # Another thread may have won the race; prefer the cached instance.
        cached = _EMBEDDERS.get(key)
        if cached is not None:
            return cached
        _EMBEDDERS[key] = emb
        return emb


def release_embedders() -> int:
    """Unload cached embedder weights; lazy wrappers drop their inner reference."""
    try:
        stop_embed_keepalive_loop()
    except Exception:  # noqa: BLE001
        pass
    with _LOCK:
        for eng in _ENGINES.values():
            emb = eng.embedder
            if isinstance(emb, _LazyEmbedder):
                emb.unload()
        count = len(_EMBEDDERS)
        _EMBEDDERS.clear()
        try:
            from pipeline.memory_governor import get_governor

            get_governor().note_embedder_unloaded()
        except Exception:  # noqa: BLE001
            pass
        with _PREWARM_LOCK:
            _PREWARM_STATE.update(
                {"running": False, "done": False, "error": None, "ms": None}
            )
        return count


def embedder_is_loaded() -> bool:
    with _LOCK:
        return bool(_EMBEDDERS)


_PREWARM_LOCK = threading.Lock()
_PREWARM_STATE: dict[str, Any] = {
    "running": False,
    "done": False,
    "error": None,
    "ms": None,
}


def prewarm_status() -> dict[str, Any]:
    with _PREWARM_LOCK:
        return {
            "running": bool(_PREWARM_STATE.get("running")),
            "done": bool(_PREWARM_STATE.get("done")),
            "error": _PREWARM_STATE.get("error"),
            "ms": _PREWARM_STATE.get("ms"),
            "embedder_loaded": embedder_is_loaded(),
            "prime_done": bool(_PREWARM_STATE.get("prime_done")) or prime_dense_ready(),
            "priming": bool(_PREWARM_STATE.get("priming")),
            "prime_dense": dict(_PREWARM_STATE.get("prime_dense") or {}),
        }


def _prime_done_path() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home() / "embed_prime.done"


def _mark_prime_done(ok: bool, payload: dict[str, Any] | None = None) -> None:
    path = _prime_done_path()
    try:
        if not ok:
            if path.is_file():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = {"ok": True, "at": time.time(), **(payload or {})}
        path.write_text(json.dumps(blob, default=str), encoding="utf-8")
    except OSError:
        pass


def prime_dense_ready(*, max_age_s: float = 3600.0) -> bool:
    """True after warmup paid the first D-channel encode (side-channel, not /health)."""
    path = _prime_done_path()
    try:
        if not path.is_file():
            return False
        age = time.time() - path.stat().st_mtime
        return 0.0 <= age < float(max_age_s)
    except OSError:
        return False


def _prewarm_enabled() -> bool:
    raw = (os.environ.get("CTX_EMBED_PREWARM") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _prewarm_busy_path() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home() / "embed_prewarm.busy"


def _mark_prewarm_busy(busy: bool) -> None:
    """Side-channel for watchdog: /health can time out while ORT holds the GIL."""
    path = _prewarm_busy_path()
    try:
        if busy:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(time.time()), encoding="utf-8")
        elif path.is_file():
            path.unlink()
    except OSError:
        pass


def prewarm_busy_stamp_active(*, max_age_s: float | None = None) -> bool:
    """True when a dense prewarm is in flight (file stamp; no HTTP)."""
    path = _prewarm_busy_path()
    try:
        if not path.is_file():
            return False
        age = time.time() - float((path.read_text(encoding="utf-8") or "0").strip() or 0)
        if max_age_s is None:
            from pipeline.warm_autoload import DEFAULT_PREWARM_MAX_AGE_S

            limit = float(DEFAULT_PREWARM_MAX_AGE_S)
        else:
            limit = max(1.0, float(max_age_s))
        return 0.0 <= age < limit
    except (OSError, ValueError):
        return False


# Representative map-shaped query so the first *real* DML encode + D-channel
# retrieve is paid during the ~40s warmup, not on the user's first map.
_PRIME_DENSE_QUERY = (
    "retrieve_D_channel_best FastEmbed embed_one DmlExecutionProvider "
    "pack_context expand_context map_result_cache mcp_locate map_impl "
    "packages/pipeline/engine.py::search packages/pipeline/mcp_locate.py::map_impl "
    "dense_embed_required keepalive CTX_EMBED_KEEPALIVE_S "
    "enforce_mcp_warm_contract disconnect debounce lifecycle_runtime"
)


def prime_dense_search(eng: Any) -> dict[str, Any]:
    """Run one D_channel_best search so later maps skip the ~2s first-encode tax."""
    q = (os.environ.get("CTX_EMBED_PRIME_QUERY") or _PRIME_DENSE_QUERY).strip()
    t0 = time.perf_counter()
    hits = eng.search(q, top_k=8, skip_freshness=True)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    n = len(hits) if hits is not None else 0
    timings = dict(getattr(eng, "_last_timings", None) or {})
    return {"ok": True, "ms": ms, "hits": n, "timings": timings}


def _prime_with_timeout(eng: Any, *, timeout_s: float = 15.0) -> dict[str, Any]:
    """Best-effort prime; never block warmup longer than ``timeout_s``."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["prime"] = prime_dense_search(eng)
        except Exception as exc:  # noqa: BLE001
            box["prime"] = {"ok": False, "error": str(exc)}

    with _PREWARM_LOCK:
        _PREWARM_STATE["priming"] = True
    t = threading.Thread(target=_run, name="scubiee-prime-dense", daemon=True)
    t.start()
    t.join(max(3.0, float(timeout_s)))
    with _PREWARM_LOCK:
        _PREWARM_STATE["priming"] = False
    if t.is_alive():
        return {"ok": False, "error": "timeout", "timeout_s": timeout_s}
    return box.get("prime") or {"ok": False, "error": "empty"}


def prewarm_embedder(root: Path | str | None = None) -> dict[str, Any]:
    """Synchronously load FastEmbed weights (first ORT/DML session)."""
    t0 = time.perf_counter()
    try:
        from pipeline.warm_autoload import begin_prewarm

        begin_prewarm()
    except Exception:  # noqa: BLE001
        _mark_prewarm_busy(True)
    try:
        try:
            from pipeline.memory_governor import get_governor

            get_governor().ensure_semantic_tier()
        except Exception:  # noqa: BLE001
            pass
        root_p = Path(root or os.environ.get("CTX_REPO") or ".").resolve()
        eng = load_engine(root_p)
        emb = eng.embedder
        # Forces _LazyEmbedder → real FastEmbed/ORT session creation.
        # ORT session init holds the GIL — /health will time out until this returns.
        emb.embed_one("scubiee prewarm", is_query=True)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        with _PREWARM_LOCK:
            _PREWARM_STATE.update({"running": False, "done": True, "error": None, "ms": ms})
        try:
            from pipeline.warm_autoload import end_prewarm

            end_prewarm(ok=True)
        except Exception:  # noqa: BLE001
            _mark_prewarm_busy(False)
        # Prime the first real D-channel search BEFORE keepalive. Cap at 15s so
        # a stuck retrieve cannot hide behind settle_join forever.
        prime: dict[str, Any] = {"ok": False, "skipped": True}
        try:
            prime = _prime_with_timeout(eng, timeout_s=15.0)
        except Exception as exc:  # noqa: BLE001
            prime = {"ok": False, "error": str(exc)}
        with _PREWARM_LOCK:
            _PREWARM_STATE["prime_dense"] = prime
            _PREWARM_STATE["prime_done"] = True
        # Stamp even on timeout — DML session exists; first map may still be ≤3s.
        _mark_prime_done(True, prime)
        try:
            ensure_embed_keepalive_loop(root_p)
        except Exception:  # noqa: BLE001
            pass
        try:
            embed_keepalive(root_p)
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True,
            "ms": ms,
            "embedder_loaded": True,
            "prime_dense": prime,
        }
    except Exception as exc:
        try:
            from pipeline.warm_autoload import end_prewarm

            end_prewarm(ok=False, error=str(exc))
        except Exception:  # noqa: BLE001
            _mark_prewarm_busy(False)
        with _PREWARM_LOCK:
            _PREWARM_STATE.update(
                {"running": False, "done": False, "error": str(exc), "ms": None}
            )
        raise


_KEEPALIVE_LOCK = threading.RLock()
_KEEPALIVE_STOP: threading.Event | None = None
_KEEPALIVE_THREAD: threading.Thread | None = None
_SEARCH_IN_FLIGHT = threading.Event()
_LAST_SEARCH_DONE_AT = 0.0
_KEEPALIVE_STATE: dict[str, Any] = {
    "running": False,
    "last_ms": None,
    "last_at": None,
    "last_error": None,
    "last_retrieve_ok": None,
    "ticks": 0,
}


def embed_keepalive_enabled() -> bool:
    # Default on — single-thread embed executor makes background ticks safe.
    raw = (os.environ.get("CTX_EMBED_KEEPALIVE") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def embed_keepalive_interval_s() -> float:
    """Seconds between dummy encode+retrieve ticks while MCP clients are connected.

    Default **8s** — Windows/AMD DirectML often drops to D3 ~10s after last GPU
    work (ORT idle thread-pool/cache goes cold). 15s was longer than that window.
    Override with ``CTX_EMBED_KEEPALIVE_S`` (5–120).
    """
    raw = (os.environ.get("CTX_EMBED_KEEPALIVE_S") or "8").strip()
    try:
        return max(5.0, min(120.0, float(raw)))
    except ValueError:
        return 8.0


def embed_keepalive_timeout_s() -> float:
    """Hard cap for a keepalive tick so a stuck DML call cannot block map forever."""
    raw = (os.environ.get("CTX_EMBED_KEEPALIVE_TIMEOUT_S") or "8").strip()
    try:
        return max(1.0, min(60.0, float(raw)))
    except ValueError:
        return 8.0


def embed_keepalive_status() -> dict[str, Any]:
    with _KEEPALIVE_LOCK:
        return {
            "enabled": embed_keepalive_enabled(),
            "interval_s": embed_keepalive_interval_s(),
            "running": bool(_KEEPALIVE_STATE.get("running")),
            "last_ms": _KEEPALIVE_STATE.get("last_ms"),
            "last_at": _KEEPALIVE_STATE.get("last_at"),
            "last_error": _KEEPALIVE_STATE.get("last_error"),
            "last_retrieve_ok": _KEEPALIVE_STATE.get("last_retrieve_ok"),
            "ticks": int(_KEEPALIVE_STATE.get("ticks") or 0),
            "embedder_loaded": embedder_is_loaded(),
        }


def _keepalive_index_touch(eng: Any, query: str, qvec: np.ndarray) -> None:
    """Keep retrieve channels hot without a full D-channel BFS on the HTTP path.

    Dense+BM25 are numpy (GIL-light). Graph BFS is capped so keepalive cannot
    starve ThreadingHTTPServer the way retrieve_D_channel_best did. Abort early
    if a real map/search starts mid-touch (dual MCP clients + host-sim).
    """
    if _SEARCH_IN_FLIGHT.is_set() or _EMBED_BUSY.is_set():
        return
    cond = getattr(eng, "conductor", None)
    if cond is None:
        raise RuntimeError("no_conductor")
    try:
        n = int(getattr(cond, "_n", 0) or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        try:
            n = int(np.asarray(qvec).size)
        except Exception:  # noqa: BLE001
            n = 1
    try:
        from conductor.channel_pool import channel_pool

        pool = channel_pool()
        for _ in range(3):
            pool.submit(lambda: None)
    except Exception:  # noqa: BLE001
        pass
    if _SEARCH_IN_FLIGHT.is_set():
        return
    dense = getattr(cond, "dense", None)
    score_dense = getattr(dense, "score_all", None) if dense is not None else None
    if score_dense is None:
        raise RuntimeError("no_dense")
    score_dense(qvec)
    if _SEARCH_IN_FLIGHT.is_set():
        return
    bm25 = getattr(cond, "bm25", None)
    score_bm25 = getattr(bm25, "score_all", None) if bm25 is not None else None
    if score_bm25 is not None:
        score_bm25(query)
    if _SEARCH_IN_FLIGHT.is_set():
        return
    graph = getattr(cond, "graph", None)
    aff = getattr(graph, "affinity_scores", None) if graph is not None else None
    if aff is not None:
        # 64 visits keeps graph pages warm without 1–2s GIL stalls under dual MCP.
        aff(query, max(n, 1), max_visit=64)


def _keepalive_qvec(arr: Any) -> np.ndarray | None:
    try:
        vec = np.asarray(arr, dtype=np.float32)
        if vec.ndim == 2 and vec.shape[0] >= 1:
            vec = vec[0]
        vec = np.reshape(vec, -1)
        if vec.size == 0:
            return None
        return vec
    except Exception:  # noqa: BLE001
        return None


def embed_keepalive(root: Path | str | None = None) -> dict[str, Any]:
    """Dummy encode + D-channel retrieve to keep ORT/DML and retrieve indexes warm.

    Encode runs on the single embed worker (never nest). Retrieve runs on the
    keepalive thread so graph/BM25/dense pages stay hot without queuing behind
    the next map encode. No-op when the embedder is not loaded.
    """
    if not embedder_is_loaded():
        return {"ok": True, "skipped": True, "reason": "embedder_not_loaded"}
    if _SEARCH_IN_FLIGHT.is_set() or _EMBED_BUSY.is_set():
        return {
            "ok": True,
            "skipped": True,
            "reason": "search_in_flight" if _SEARCH_IN_FLIGHT.is_set() else "embed_busy",
        }
    # Do not steal the embed worker between consecutive maps/pack (host-sim
    # map_second was paying ~2.5s behind a keepalive encode).
    try:
        cooldown = float((os.environ.get("CTX_EMBED_KEEPALIVE_SEARCH_COOLDOWN_S") or "4").strip())
    except ValueError:
        cooldown = 4.0
    cooldown = max(0.0, min(30.0, cooldown))
    if cooldown > 0.0 and _LAST_SEARCH_DONE_AT > 0.0:
        if (time.time() - float(_LAST_SEARCH_DONE_AT)) < cooldown:
            return {"ok": True, "skipped": True, "reason": "recent_search"}
    try:
        st = prewarm_status() or {}
        if bool(st.get("running")) or bool(st.get("priming")):
            return {"ok": True, "skipped": True, "reason": "prewarm_running"}
    except Exception:  # noqa: BLE001
        pass
    if not prime_dense_ready():
        try:
            root_p = Path(root or os.environ.get("CTX_REPO") or ".").resolve()
            prime = _prime_with_timeout(load_engine(root_p), timeout_s=15.0)
            with _PREWARM_LOCK:
                _PREWARM_STATE["prime_dense"] = prime
                _PREWARM_STATE["prime_done"] = True
            _mark_prime_done(True, prime)
        except Exception as exc:  # noqa: BLE001
            _mark_prime_done(True, {"ok": False, "error": str(exc)})
    t0 = time.perf_counter()
    try:
        root_p = Path(root or os.environ.get("CTX_REPO") or ".").resolve()

        def _tick() -> tuple[Any, Any]:
            eng = load_engine(root_p)
            emb = eng.embedder
            # Must call the real Embedder while already on the embed worker —
            # LazyEmbedder.embed_one would re-submit to the same executor and deadlock.
            real = emb._ensure() if hasattr(emb, "_ensure") else emb
            # Bypass embedder.cache — a fixed dummy string skips DML after the
            # first tick and GPU clocks drop (post-idle map paid ~3s again).
            payload = real.format_query(f"scubiee keepalive {time.time_ns()}")
            arr = real._encode_batch([payload])
            return eng, arr

        out = run_embed_infer(
            _tick,
            timeout_s=embed_keepalive_timeout_s(),
            abort_if_search=True,
        )
        if out is _ABORT_EMBED:
            return {"ok": True, "skipped": True, "reason": "search_in_flight"}
        eng, arr = out
        retrieve_ok = False
        retrieve_error: str | None = None
        qvec = _keepalive_qvec(arr)
        if qvec is None:
            retrieve_error = "no_qvec"
        else:
            try:
                _keepalive_index_touch(eng, "scubiee keepalive retrieve", qvec)
                retrieve_ok = True
            except Exception as exc:  # noqa: BLE001
                retrieve_error = str(exc)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        with _KEEPALIVE_LOCK:
            _KEEPALIVE_STATE.update(
                {
                    "last_ms": ms,
                    "last_at": time.time(),
                    "last_error": None,
                    "last_retrieve_ok": retrieve_ok,
                    "ticks": int(_KEEPALIVE_STATE.get("ticks") or 0) + 1,
                }
            )
        out: dict[str, Any] = {
            "ok": True,
            "ms": ms,
            "embedder_loaded": True,
            "retrieve_ok": retrieve_ok,
        }
        if retrieve_error:
            out["retrieve_error"] = retrieve_error
        return out
    except FuturesTimeoutError:
        with _KEEPALIVE_LOCK:
            _KEEPALIVE_STATE["last_error"] = "timeout"
        return {"ok": True, "skipped": True, "reason": "timeout"}
    except Exception as exc:  # noqa: BLE001
        with _KEEPALIVE_LOCK:
            _KEEPALIVE_STATE["last_error"] = str(exc)
        return {"ok": False, "error": str(exc)}


def stop_embed_keepalive_loop() -> None:
    global _KEEPALIVE_STOP, _KEEPALIVE_THREAD
    with _KEEPALIVE_LOCK:
        if _KEEPALIVE_STOP is not None:
            _KEEPALIVE_STOP.set()
        _KEEPALIVE_STOP = None
        _KEEPALIVE_THREAD = None
        _KEEPALIVE_STATE["running"] = False


def ensure_embed_keepalive_loop(root: Path | str | None = None) -> dict[str, Any]:
    """Start engine-side dummy-encode loop while MCP/IDE clients are registered.

    Lives in the engine process (where DML is). MCP client/touch heartbeats are
    a backup; this is the primary anti-idle path for map <1s after minutes idle.
    """
    if not embed_keepalive_enabled():
        return {"ok": True, "skipped": True, "reason": "CTX_EMBED_KEEPALIVE=0"}
    root_s = str(Path(root or os.environ.get("CTX_REPO") or ".").resolve())
    with _KEEPALIVE_LOCK:
        global _KEEPALIVE_STOP, _KEEPALIVE_THREAD
        if _KEEPALIVE_THREAD is not None and _KEEPALIVE_THREAD.is_alive():
            return {"ok": True, "already_running": True, **embed_keepalive_status()}
        stop = threading.Event()
        _KEEPALIVE_STOP = stop
        _KEEPALIVE_STATE["running"] = True

        def _loop() -> None:
            # Tiny yield so HTTP ``ensure_embed_keepalive_loop`` can return
            # before the first DML tick (ORT GIL would otherwise starve /health).
            if stop.wait(0.05):
                return
            while True:
                try:
                    from pipeline.lifecycle_runtime import active_client_count

                    clients = int(active_client_count())
                except Exception:  # noqa: BLE001
                    clients = 0
                wait_s = embed_keepalive_interval_s()
                if clients > 0:
                    if embedder_is_loaded():
                        embed_keepalive(root_s)
                    # Do not kick prewarm from keepalive. Attach kicks once;
                    # a 2s retry loop re-entered ORT while the first load held
                    # the GIL and refreshed the hung-prewarm clock.
                if stop.wait(wait_s):
                    break

        t = threading.Thread(target=_loop, name="scubiee-embed-keepalive", daemon=True)
        _KEEPALIVE_THREAD = t
        t.start()
    return {"ok": True, "started": True, **embed_keepalive_status()}


def prewarm_embedder_async(root: Path | str | None = None) -> dict[str, Any]:
    """Background FastEmbed load so the next map/search is not a ~30s cold start.

    Index ``warm_state=ready`` only means BM25/FAISS are up — CodeRankEmbed/ORT
    still lazy-loads on first semantic query unless this runs first.
    """
    if not _prewarm_enabled():
        return {"ok": True, "skipped": True, "reason": "CTX_EMBED_PREWARM=0"}
    if embedder_is_loaded():
        with _PREWARM_LOCK:
            _PREWARM_STATE["done"] = True
        if not prime_dense_ready():
            try:
                root_p = Path(root or os.environ.get("CTX_REPO") or ".").resolve()
                prime = _prime_with_timeout(load_engine(root_p), timeout_s=15.0)
                with _PREWARM_LOCK:
                    _PREWARM_STATE["prime_dense"] = prime
                    _PREWARM_STATE["prime_done"] = True
                _mark_prime_done(True, prime)
            except Exception as exc:  # noqa: BLE001
                _mark_prime_done(True, {"ok": False, "error": str(exc)})
        return {"ok": True, "already_warm": True, **prewarm_status()}
    with _PREWARM_LOCK:
        if _PREWARM_STATE.get("running"):
            return {"ok": True, "already_running": True, **prewarm_status()}
        _PREWARM_STATE.update({"running": True, "error": None})
    try:
        from pipeline.warm_autoload import begin_prewarm

        begin_prewarm()
    except Exception:  # noqa: BLE001
        _mark_prewarm_busy(True)

    root_s = str(Path(root).resolve()) if root else None

    def _run() -> None:
        try:
            prewarm_embedder(root_s)
        except Exception as exc:  # noqa: BLE001
            with _PREWARM_LOCK:
                _PREWARM_STATE.update(
                    {
                        "running": False,
                        "done": False,
                        "error": str(exc),
                        "ms": None,
                    }
                )
            try:
                from pipeline.warm_autoload import end_prewarm

                end_prewarm(ok=False, error=str(exc))
            except Exception:  # noqa: BLE001
                _mark_prewarm_busy(False)

    threading.Thread(target=_run, name="scubiee-embed-prewarm", daemon=True).start()
    return {"ok": True, "started": True, **prewarm_status()}


def prewarm_wait_seconds() -> float:
    """Max seconds MCP/daemon will block to finish FastEmbed load before tools run."""
    raw = (os.environ.get("CTX_EMBED_PREWARM_WAIT_S") or "120").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 120.0


def warming_response(*, warm_state: str = "warming") -> dict[str, Any]:
    """Immediate agent-facing payload: engine is coming up, retry the same tool."""
    return {
        "ok": False,
        "status": "warming",
        "error": "engine_warming",
        "warming": True,
        "should_retry": True,
        "retry_after_s": 3,
        "warm_state": warm_state or "warming",
        "ready": False,
        "agent_ready": "no",
        "hint": (
            "Engine is warming. Wait ~3s and retry this same tool once. "
            "Do not poll status() in a loop."
        ),
    }


def is_dense_d_channel_result(
    payload: dict[str, Any] | None = None,
    *,
    timings: dict[str, Any] | None = None,
) -> bool:
    """True when map/search used real FastEmbed → D_channel_best (not BM25/pseudo/cap-only)."""
    blob = payload if isinstance(payload, dict) else {}
    t = timings if isinstance(timings, dict) else (blob.get("timings") if isinstance(blob.get("timings"), dict) else {})
    if blob.get("warming") or blob.get("ok") is False:
        return False
    err = str(blob.get("error") or "").lower()
    if err in {"dense_embed_loading", "engine_warming", "dense_embed_required"}:
        return False
    mode = str(t.get("retrieve_mode") or blob.get("retrieve_mode") or "")
    if "pseudo" in mode or mode == "capability":
        return False
    if t.get("dense") is True or blob.get("dense") is True:
        return (not mode) or ("D_channel" in mode)
    rows: list[Any] = []
    for key in ("cards", "results", "hits"):
        chunk = blob.get(key)
        if isinstance(chunk, list):
            rows.extend(chunk)
    for row in rows:
        if not isinstance(row, dict):
            continue
        src = str(row.get("source") or "")
        if "D_channel_best" in src and "pseudo" not in src:
            return True
    return False


def ensure_embedder_ready(
    root: Path | str | None = None,
    *,
    wait_s: float | None = None,
) -> dict[str, Any]:
    """Block until CodeRankEmbed/ORT is loaded (join in-flight prewarm, or load now).

    Call this on MCP connect and before dense map/search so the first user query
    does not pay cold ORT/DML session creation.
    """
    if embedder_is_loaded():
        return {"ok": True, "already_warm": True, **prewarm_status()}
    if not _prewarm_enabled():
        # Still load once when a caller explicitly asks to be ready.
        return prewarm_embedder(root)

    limit = prewarm_wait_seconds() if wait_s is None else max(0.0, float(wait_s))
    started = prewarm_embedder_async(root)
    if embedder_is_loaded():
        return {"ok": True, "already_warm": True, **prewarm_status(), "kick": started}

    t0 = time.perf_counter()
    # Join the background thread instead of starting a second cold load.
    while (time.perf_counter() - t0) < limit:
        if embedder_is_loaded():
            return {
                "ok": True,
                "waited_ms": round((time.perf_counter() - t0) * 1000, 1),
                **prewarm_status(),
            }
        st = prewarm_status()
        if st.get("error"):
            return {"ok": False, "error": st.get("error"), **st}
        if not st.get("running") and not embedder_is_loaded():
            # Background died without loading — do it inline.
            return prewarm_embedder(root)
        time.sleep(0.05)

    # Timeout: finish synchronously so the caller still gets a warm model.
    out = prewarm_embedder(root)
    out["waited_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    out["timed_out_then_sync"] = True
    return out


@dataclass
class WarmSearchEngine:
    root: Path
    store: PipelineStore
    chunks: list[ChunkRecord]
    texts: list[str]
    files: list[str]
    conductor: MultiArchConductor
    embedder: Embedder
    load_ms: float
    loaded_at: float
    capability: CapabilityIndex | None = None

    def locate_capability(self, query: str, top_k: int = 5) -> list[LocateHit]:
        idx = self.capability
        if idx is None:
            return []
        return idx.locate(query, top_k=top_k)

    def _best_chunk_id(self, rel: str) -> int:
        rel = rel.replace("\\", "/")
        best_id, best_len = -1, -1
        for c in self.chunks:
            f = c.file.replace("\\", "/")
            if f == rel or f.endswith("/" + rel) or rel.endswith("/" + f):
                n = len(c.text or "")
                if n > best_len:
                    best_len, best_id = n, int(c.id)
        return best_id

    def _cap_results(self, caps: list[LocateHit], top_k: int) -> list[SearchResult]:
        out: list[SearchResult] = []
        for i, h in enumerate(caps[:top_k], 1):
            cid = self._best_chunk_id(h.path)
            out.append(
                SearchResult(
                    rank=i,
                    file=h.path.replace("\\", "/"),
                    score=float(h.score),
                    chunk_id=cid if cid >= 0 else 0,
                    preview=h.why[:240],
                    source=f"capability:{h.symbol}",
                )
            )
        return out

    def search(
        self,
        query: str,
        top_k: int = 8,
        *,
        skip_freshness: bool = False,
    ) -> list[SearchResult]:
        global _LAST_SEARCH_DONE_AT
        gate: dict[str, Any] = {"freshness": {"strategy": "skipped"}, "sync": None}
        if not skip_freshness:
            gen = _store_generation_mtime(self.store)
            if gen > self.loaded_at + 0.05:
                clear_engines()
                fresh = load_engine(self.root, force_reload=True)
                return fresh.search(query, top_k=top_k, skip_freshness=False)

            from pipeline.incremental import ensure_fresh_for_search

            gate = ensure_fresh_for_search(self.root) or {}
            sync = gate.get("sync") or {}
            if sync.get("refreshed"):
                clear_engines()
                fresh = load_engine(self.root, force_reload=True)
                return fresh.search(query, top_k=top_k, skip_freshness=True)

            # Cursor-style: while dense lags, hot-patch BM25 from disk (no embed wait)
            dirty = list(gate.get("dirty_boost_files") or [])
            strat = (gate.get("freshness") or {}).get("strategy")
            if dirty and strat in {"background", "full", "incremental"}:
                patched, touched = hot_patch_texts(self.root, self.chunks, self.texts, dirty)
                if touched:
                    self.texts = patched
                    self.conductor.bm25 = rebuild_bm25(self.texts)
                    gate["hot_patched_chunks"] = len(touched)

        try:
            from conductor.query_router import query_state, path_likeness

            qstate = query_state(query)
            plike = path_likeness(query)
        except Exception:  # noqa: BLE001
            qstate, plike = None, None

        # SOFT: cheap capability locate (no LLM). Prefer exclusive cards only when
        # CTX_CAPABILITY=exclusive; default merges cards ahead of RAG so we don't
        # drop good R_plan hits.
        cap_ms = 0.0
        cap_hits: list[LocateHit] = []
        cap_mode = (os.environ.get("CTX_CAPABILITY") or "merge").strip().lower()
        if (
            qstate == "SOFT"
            and self.capability is not None
            and cap_mode not in {"0", "false", "off"}
        ):
            t_cap = time.perf_counter()
            cap_hits = self.capability.locate(query, top_k=max(top_k, 5))
            cap_ms = (time.perf_counter() - t_cap) * 1000

        if (
            cap_mode in {"exclusive", "only"}
            and cap_hits
            and self.capability is not None
            and self.capability.strong_hit(cap_hits)
        ):
            out = self._cap_results(cap_hits, top_k)
            self._last_timings = {
                "embed_ms": 0.0,
                "retrieve_ms": round(cap_ms, 1),
                "capability_ms": round(cap_ms, 1),
                "total_ms": round(cap_ms, 1),
                "freshness": gate.get("freshness", {}).get("strategy"),
                "detection": gate.get("freshness", {}).get("detection"),
                "hot_patched_chunks": gate.get("hot_patched_chunks", 0),
                "retrieve_mode": "capability",
                "query_state": qstate,
                "path_likeness": round(plike, 3) if plike is not None else None,
                "hit_source": out[0].source if out else None,
            }
            self._last_gate = gate
            return out

        t0 = time.perf_counter()
        # Cap query size (huge prompts can OOM/orphan ORT on laptop GPUs) and
        # single-flight the embed — DirectML/ORT is not safe under ThreadingHTTPServer.
        max_q = int(os.environ.get("CTX_QUERY_MAX_CHARS", "2000") or "2000")
        q_embed = (query or "")[: max(64, max_q)]
        # Map/search always use real FastEmbed → D_channel_best (dense shortlist).
        # Never skip dense for skip_freshness. Never park the HTTP worker on a
        # full sync cold load (that GIL-starved /health and failed Lane A settle).
        # Kick async + brief join; if still cold → dense_embed_required (retry).
        allow_pseudo = (os.environ.get("CTX_ALLOW_PSEUDO_DENSE") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        dense_ready = False
        try:
            wait_raw = (os.environ.get("CTX_EMBED_SEARCH_WAIT_S") or "0").strip()
            wait_s = max(0.0, min(30.0, float(wait_raw)))
        except ValueError:
            wait_s = 0.0
        _SEARCH_IN_FLIGHT.set()
        try:
            if not embedder_is_loaded():
                prewarm_embedder_async(self.root)
                deadline = time.time() + wait_s
                while time.time() < deadline and not embedder_is_loaded():
                    st = prewarm_status() or {}
                    if st.get("error"):
                        raise RuntimeError(str(st.get("error")))
                    time.sleep(0.05)
                if not embedder_is_loaded():
                    raise RuntimeError(
                        "dense_embed_required: FastEmbed still loading for "
                        "D_channel_best map/search — retry in ~3s"
                    )
            elif bool((prewarm_status() or {}).get("running")):
                # Join brief; do not fall back to hash.
                deadline = time.time() + min(wait_s, 5.0)
                while time.time() < deadline and bool(
                    (prewarm_status() or {}).get("running")
                ):
                    time.sleep(0.05)
                if not embedder_is_loaded():
                    raise RuntimeError(
                        "dense_embed_required: FastEmbed prewarm in flight — retry"
                    )
            # All DML/ORT on the single embed worker (same as keepalive).
            # Never encode on the HTTP thread — concurrent DirectML wedges map.
            # Unwrap _LazyEmbedder so we do not nest run_embed_infer (deadlock).
            def _embed_query() -> Any:
                emb = self.embedder
                real = emb._ensure() if hasattr(emb, "_ensure") else emb
                return real.embed_one(q_embed, is_query=True)

            qvec = run_embed_infer(
                _embed_query,
                timeout_s=max(5.0, min(25.0, embed_keepalive_timeout_s() + 5.0)),
            )
            dense_ready = True
        except Exception:
            if not allow_pseudo:
                _LAST_SEARCH_DONE_AT = time.time()
                _SEARCH_IN_FLIGHT.clear()
                raise RuntimeError(
                    "dense_embed_required: FastEmbed not ready for map/search "
                    "(D_channel_best). Retry after embedder loads, or run "
                    "scubiee engine ensure . / POST /v1/embed/prewarm."
                )
            import hashlib

            h = hashlib.sha256(q_embed.encode("utf-8")).digest()
            rng = np.random.default_rng(int.from_bytes(h[:8], "little"))
            dim = int(self.embedder.dim or 768)
            qvec = rng.normal(size=dim).astype(np.float32)
            qvec /= max(float(np.linalg.norm(qvec)), 1e-12)
        try:
            embed_ms = (time.perf_counter() - t0) * 1000

            t1 = time.perf_counter()
            # One production retrieve path. Research arches stay on MultiArchConductor
            # for bakeoffs; the engine does not select them.
            retrieve_fn = self.conductor.retrieve_D_channel_best
            route = "D_channel_best" if dense_ready else "D_channel_best:pseudo"
            hits = retrieve_fn(query, qvec, top_k=top_k)
            retrieve_ms = (time.perf_counter() - t1) * 1000
        finally:
            _LAST_SEARCH_DONE_AT = time.time()
            _SEARCH_IN_FLIGHT.clear()

        dirty_set = set(gate.get("dirty_boost_files") or [])
        if dirty_set:

            def _boost(h: Any) -> tuple:
                f = h.file.replace("\\", "/")
                return (0 if f in dirty_set else 1, -h.score)

            hits = sorted(hits, key=_boost)

        by_id = {c.id: c for c in self.chunks}
        out: list[SearchResult] = []
        # Map/pack soft locate (skip_freshness) must stay sub-second — prefer
        # in-memory chunk text over N disk reads for the why/preview field.
        prefer_memory_preview = bool(skip_freshness)
        for i, h in enumerate(hits, 1):
            preview = ""
            cid = int(h.chunk_id)
            if 0 <= cid < len(self.chunks):
                c = self.chunks[cid]
            else:
                c = by_id.get(cid)
            if prefer_memory_preview and 0 <= cid < len(self.texts):
                preview = " ".join(self.texts[cid].split())[:240]
            elif c is not None:
                preview = disk_preview(self.root, c.file, c.start_line, c.end_line)
            if not preview and 0 <= cid < len(self.texts):
                preview = " ".join(self.texts[cid].split())[:240]
            out.append(
                SearchResult(
                    rank=i,
                    file=h.file.replace("\\", "/"),
                    score=float(h.score),
                    chunk_id=int(c.id) if c is not None else cid,
                    preview=preview,
                    source=h.source or "D_channel_best",
                    start_line=int(c.start_line) if c is not None else None,
                    end_line=int(c.end_line) if c is not None else None,
                )
            )

        # Soft merge: a few capability pointers first, RAG fills the rest (deduped).
        if qstate == "SOFT" and cap_hits and cap_mode not in {"0", "false", "off"}:
            promotable = promotable_cards(self.capability, cap_hits, top_k)
            cap_out = self._cap_results(promotable, len(promotable))
            if cap_out:
                seen: set[str] = set()
                merged: list[SearchResult] = []
                for r in cap_out + out:
                    f = r.file.replace("\\", "/")
                    if f in seen:
                        continue
                    seen.add(f)
                    merged.append(r)
                out = merged[:top_k]
                for i, r in enumerate(out, 1):
                    r.rank = i
                route = route + "+cap"

        self._last_timings = {
            "embed_ms": round(embed_ms, 1),
            "retrieve_ms": round(retrieve_ms, 1),
            "capability_ms": round(cap_ms, 1),
            "total_ms": round(embed_ms + retrieve_ms + cap_ms, 1),
            "freshness": gate.get("freshness", {}).get("strategy"),
            "detection": gate.get("freshness", {}).get("detection"),
            "hot_patched_chunks": gate.get("hot_patched_chunks", 0),
            "retrieve_mode": route,
            "dense": bool(dense_ready),
            "query_state": qstate,
            "path_likeness": round(plike, 3) if plike is not None else None,
            "hit_source": out[0].source if out else None,
        }
        self._last_gate = gate
        return out

    def status(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "chunks": len(self.texts),
            "capability_cards": len(self.capability.cards) if self.capability else 0,
            "load_ms": round(self.load_ms, 1),
            "loaded_at": self.loaded_at,
            "embed_model": self.embedder.model,
            "embed_backend": self.embedder.backend,
            "warm": True,
        }


def load_engine(
    root: Path,
    *,
    base_dir: Path | None = None,
    vdb: VectorDatabase | None = None,
    force_reload: bool = False,
) -> WarmSearchEngine:
    """Load WarmSearchEngine without holding ``_LOCK`` across disk/ORT work.

    Holding the process lock for the whole open starved ``/health`` (via
    ``embedder_is_loaded``) for tens of seconds and made MCP warm look dead.
    """
    root = root.resolve()
    key = _engine_key(root, base_dir)
    with _LOCK:
        if not force_reload and key in _ENGINES:
            return _ENGINES[key]

    t0 = time.perf_counter()
    store = PipelineStore(root, base_dir=base_dir, vdb=vdb)
    from pipeline.project_id import index_is_usable

    if not index_is_usable(store.base):
        from pipeline.artifact_guard import MANIFEST_NAME, heal_checksum_mismatch, validate_manifest

        if (store.base / MANIFEST_NAME).is_file():
            report = validate_manifest(store.base)
            if str(report.get("reason") or "") in {
                "checksum_mismatch",
                "artifact_missing",
                "manifest_invalid",
            }:
                heal = heal_checksum_mismatch(store.base, root=root)
                if heal.get("ok") and index_is_usable(store.base):
                    pass  # rebuilt; continue load
                else:
                    raise RuntimeError(
                        "Index publication is missing or checksum-invalid; refusing mixed generation."
                    )
        if not index_is_usable(store.base):
            raise RuntimeError(
                "Index publication is missing or checksum-invalid; refusing mixed generation."
            )
    chunks = store.load_chunks()
    if not chunks:
        raise RuntimeError("No index found. Run: python -m pipeline index <repo>")
    col = store.get_collection()
    if col is None:
        raise RuntimeError("Vector collection missing. Re-run index.")
    graph_json = store.base / "graph.json"
    if not graph_json.exists():
        raise RuntimeError("graph.json missing. Re-run index.")

    texts = [c.text for c in chunks]
    files = [c.file.replace("\\", "/") for c in chunks]
    spans = [
        ChunkSpan(index=i, file=files[i], start_line=c.start_line, end_line=c.end_line)
        for i, c in enumerate(chunks)
    ]

    from concurrent.futures import ThreadPoolExecutor

    from pipeline.bm25_cache import load_or_build_bm25

    # Independent disk/CPU work — overlap graph parse, BM25, and cards.
    def _build_graph() -> GraphifyChunkRetriever:
        G = _load_graph(str(graph_json))
        return GraphifyChunkRetriever(G, spans, depth=2)

    def _build_bm25() -> BM25Index:
        bm25, _meta = load_or_build_bm25(store.base, texts)
        return bm25

    def _build_cards():
        return ensure_cards(
            root,
            store.base,
            indexed_files=files,
            force=not (store.base / "capability_cards.json").exists(),
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_graph = pool.submit(_build_graph)
        f_bm25 = pool.submit(_build_bm25)
        f_cards = pool.submit(_build_cards)
        dense = FaissDenseAdapter(col, n_chunks=len(chunks))
        graph = f_graph.result()
        bm25 = f_bm25.result()
        cards = f_cards.result()

    conductor = MultiArchConductor(
        files=files,
        bm25=bm25,
        dense=dense,
        graph=graph,
        config=ConductorConfig(),
    )
    meta = store.load_meta()
    model = str(meta.get("embed_model") or "nomic-ai/CodeRankEmbed")
    try:
        from pipeline.memory_governor import (
            current_serve_tier,
            get_governor,
            should_lazy_embedder,
        )

        tier = current_serve_tier()
        cfg = get_governor().config(tier)
        lazy = should_lazy_embedder() or not cfg.load_embedder
    except Exception:  # noqa: BLE001
        lazy = os.environ.get("CTX_CE_LAZY_EMBEDDER", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        cfg = None  # type: ignore[assignment]

    if lazy:
        embedder: Embedder | _LazyEmbedder = _LazyEmbedder(
            model,
            dim=col.meta.dim,
            cache_path=store.embed_cache,
        )
    else:
        embedder = get_embedder(
            model,
            dim=col.meta.dim,
            cache_path=store.embed_cache,
            eager=True,
        )
        try:
            if cfg is None or cfg.warmup_embedder:
                embedder.embed_one("warmup", is_query=True)
        except Exception:
            pass
        _verify_gpu_provider(embedder)
    eng = WarmSearchEngine(
        root=root,
        store=store,
        chunks=chunks,
        texts=texts,
        files=files,
        conductor=conductor,
        embedder=embedder,
        load_ms=(time.perf_counter() - t0) * 1000,
        loaded_at=time.time(),
        capability=CapabilityIndex(cards),
    )
    with _LOCK:
        if not force_reload and key in _ENGINES:
            return _ENGINES[key]
        _ENGINES[key] = eng
        return eng


def drop_engine(root: Path, *, base_dir: Path | None = None) -> bool:
    """Drop one repository's cached WarmSearchEngine without touching others."""
    key = _engine_key(root.resolve(), base_dir)
    with _LOCK:
        return _ENGINES.pop(key, None) is not None


def clear_engines() -> None:
    with _LOCK:
        _ENGINES.clear()
