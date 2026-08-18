"""Embedding backends: CodeRankEmbed via FastEmbed (primary) or SentenceTransformers.

CodeRankEmbed (nomic-ai/CodeRankEmbed) is the production code retriever.
Hardware profile from ``pipeline.accel`` (cuda / dml / cpu).

Query prefix (required by CodeRankEmbed):
  \"Represent this query for searching relevant code: \"
Documents / code chunks: no prefix.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

QUERY_PREFIX = "Represent this query for searching relevant code: "
CODERANK_MODEL = "nomic-ai/CodeRankEmbed"
DEFAULT_MODEL = os.environ.get("CTX_EMBED_MODEL", CODERANK_MODEL)


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pick_device(explicit: str | None = None) -> str:
    """Legacy ST device picker: auto → cuda > mps > cpu. Respect CTX_EMBED_DEVICE."""
    if explicit:
        return explicit
    env = os.environ.get("CTX_EMBED_DEVICE", "").strip().lower()
    if env and env != "auto":
        return env
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


def _tune_cpu_threads() -> None:
    try:
        import torch

        n = int(os.environ.get("CTX_TORCH_THREADS", "0")) or (os.cpu_count() or 4)
        torch.set_num_threads(max(1, n))
        torch.set_num_interop_threads(max(1, min(4, n // 2 or 1)))
    except Exception:  # noqa: BLE001
        pass


def _accel_wants_fastembed() -> bool:
    """Saved/hardware profile prefers FastEmbed unless explicitly overridden."""
    try:
        from pipeline.accel import resolve_runtime

        prof = resolve_runtime()
        return str(getattr(prof, "backend", "fastembed") or "fastembed") == "fastembed"
    except Exception:  # noqa: BLE001
        return True


def _fastembed_available() -> bool:
    try:
        import fastembed  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _choose_backend(model: str, backend: str | None) -> str:
    """Pick embed backend. Hardware accel (FastEmbed+ORT) wins over silent ST/CPU.

    Production path is always accel.json / detect → FastEmbed. SentenceTransformers
    is an explicit opt-in only (CTX_EMBED_BACKEND=st|coderank), never a quiet fallback.
    """
    if backend:
        chosen = backend
    else:
        env = os.environ.get("CTX_EMBED_BACKEND", "").strip().lower()
        if env in {"fastembed", "coderank", "sentence-transformers", "st", "ollama"}:
            chosen = "coderank" if env in {"st", "sentence-transformers"} else env
        else:
            name = (model or "").lower()
            if name.startswith("ollama:") or name in {"nomic-embed-text"}:
                chosen = "ollama"
            elif _accel_wants_fastembed():
                chosen = "fastembed"
            elif _fastembed_available():
                chosen = "fastembed"
            else:
                chosen = "coderank"

    if chosen == "fastembed" and not _fastembed_available():
        from pipeline.preflight import CapabilityError

        raise CapabilityError(
            "Context Engine accel profile requires FastEmbed + ONNX Runtime, but "
            "fastembed is not installed in this Python. Run: python -m pipeline setup "
            "(or pip install -e \".[dml|cuda|coreml|cpu]\"). Refusing silent PyTorch/CPU fallback."
        )
    return chosen


class Embedder:
    """Unified embedder. Prefer ``backend='fastembed'`` (ORT cuda/dml/cpu)."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        backend: str | None = None,
        dim: int | None = None,
        cache_path: Path | None = None,
        batch_size: int | None = None,
        max_seq_length: int = 512,
        device: str | None = None,
        cache_flush_every: int = 256,
        quiet: bool = False,
    ):
        self.model = model
        self.quiet = quiet
        self.max_seq_length = max_seq_length
        self.dim = dim
        self.cache_path = cache_path
        self.cache: dict[str, list[float]] = {}
        self._st_model = None
        self._fe_model = None
        self._cpu_backup_model = None
        self._cache_dirty: list[tuple[str, list[float]]] = []
        self.cache_flush_every = max(32, int(cache_flush_every))
        self._last_stats: dict = {}

        self._accel = None
        try:
            from pipeline.accel import resolve_runtime

            self._accel = resolve_runtime()
        except Exception:  # noqa: BLE001
            self._accel = None

        from pipeline.runtime_profile import (
            RuntimeProfileState,
            get_runtime_profile_state,
            set_runtime_profile_state,
        )

        preferred_profile = self._accel.profile if self._accel else "cpu"
        current_state = get_runtime_profile_state()
        if current_state.preferred_profile != preferred_profile:
            current_state = RuntimeProfileState(preferred_profile, preferred_profile)
            set_runtime_profile_state(current_state)

        # Resolve backend after accel so missing FastEmbed fails closed with profile context.
        self.backend = _choose_backend(model, backend)
        if self.backend == "ollama":
            self.model = model.replace("ollama:", "")

        if self.backend == "fastembed" and self._accel:
            self.device = self._accel.profile
            # Honor hardware-tuned batch (DML-safe 16, CUDA 32, CPU 8) — never invent 64+.
            default_batch = max(1, int(self._accel.batch_size or 16))
        else:
            self.device = pick_device(device)
            if self.device == "cpu":
                _tune_cpu_threads()
            default_batch = 32 if self.device == "cuda" else 16

        if batch_size is not None:
            self.batch_size = int(batch_size)
        elif "CTX_EMBED_BATCH" in os.environ:
            self.batch_size = int(os.environ["CTX_EMBED_BATCH"])
        else:
            self.batch_size = default_batch

        if not self.quiet:
            print(
                f"[embed] plan backend={self.backend} device={self.device} "
                f"batch={self.batch_size} model={self.model}"
                + (
                    f" accel={self._accel.profile}@{self._accel.texts_per_sec}t/s"
                    if self._accel
                    else ""
                ),
                file=sys.stderr,
                flush=True,
            )

        if cache_path and cache_path.exists():
            self._load_cache()

    @property
    def runtime_state(self):
        """Read synchronized process-wide profile state."""

        from pipeline.runtime_profile import get_runtime_profile_state

        return get_runtime_profile_state()

    def _load_cache(self) -> None:
        assert self.cache_path is not None
        npz = self.cache_path.with_suffix(".npz")
        if npz.exists():
            try:
                data = np.load(npz, allow_pickle=True)
                keys = data["keys"].tolist()
                vecs = data["vecs"]
                for i, k in enumerate(keys):
                    self.cache[str(k)] = vecs[i].astype(np.float32).tolist()
                return
            except Exception:  # noqa: BLE001
                pass
        for line in self.cache_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = row.get("key")
            emb = row.get("embedding")
            if key is None or emb is None:
                continue
            self.cache[str(key)] = emb

    def _queue_cache(self, key: str, emb: list[float]) -> None:
        if not self.cache_path:
            return
        self._cache_dirty.append((key, emb))
        if len(self._cache_dirty) >= self.cache_flush_every:
            self.flush_cache()

    def flush_cache(self) -> None:
        if not self.cache_path or not self._cache_dirty:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("a", encoding="utf-8") as f:
            for key, emb in self._cache_dirty:
                f.write(json.dumps({"key": key, "embedding": emb}) + "\n")
        self._cache_dirty.clear()

    def save_cache_npz(self) -> Path | None:
        if not self.cache_path or not self.cache:
            return None
        npz = self.cache_path.with_suffix(".npz")
        keys = list(self.cache.keys())
        vecs = np.asarray([self.cache[k] for k in keys], dtype=np.float32)
        np.savez_compressed(npz, keys=np.asarray(keys, dtype=object), vecs=vecs)
        return npz

    def _ensure_fastembed(self):
        if self._fe_model is not None:
            return self._fe_model
        from pipeline.accel import register_coderank, resolve_runtime

        register_coderank()
        from fastembed import TextEmbedding

        prof = self._accel or resolve_runtime()
        providers = prof.providers()
        model_name = self.model if self.model else CODERANK_MODEL
        if prof.profile == "coreml":
            from pipeline.coreml_mac import coreml_model_name

            model_name = coreml_model_name(model_name)
        print(
            f"[embed] loading FastEmbed {model_name} profile={prof.profile} "
            f"batch={self.batch_size} providers={providers[0] if providers else '?'}",
            file=sys.stderr,
            flush=True,
        )
        t0 = time.perf_counter()
        self._fe_model = TextEmbedding(
            model_name=model_name,
            threads=1,
            providers=providers,
            lazy_load=True,
        )
        from pipeline.coreml_mac import pad_embed_batch, static_embed_batch_size

        warm_bs = 1
        warm = ["warmup"]
        if prof.profile == "coreml":
            warm_bs = static_embed_batch_size(prof, self.batch_size)
            warm = pad_embed_batch(warm, warm_bs)
        list(self._fe_model.embed(warm, batch_size=warm_bs, parallel=None))
        print(
            f"[embed] FastEmbed ready in {(time.perf_counter()-t0)*1000:.0f}ms",
            file=sys.stderr,
            flush=True,
        )
        return self._fe_model

    def _ensure_coderank(self):
        if self._st_model is not None:
            return self._st_model
        from sentence_transformers import SentenceTransformer

        print(
            f"[embed] loading ST {self.model} on {self.device} "
            f"(batch={self.batch_size}, seq={self.max_seq_length})",
            file=sys.stderr,
            flush=True,
        )
        t0 = time.perf_counter()
        self._st_model = SentenceTransformer(
            self.model,
            trust_remote_code=True,
            device=self.device,
        )
        try:
            self._st_model.max_seq_length = int(self.max_seq_length)
        except Exception:  # noqa: BLE001
            pass
        print(
            f"[embed] model ready in {(time.perf_counter()-t0)*1000:.0f}ms device={self.device}",
            file=sys.stderr,
            flush=True,
        )
        return self._st_model

    def _embed_cpu_backup(self, batch: list[str], *, batch_size: int) -> np.ndarray:
        """Embed one operation on CPU without changing the installed profile."""

        if self._cpu_backup_model is None:
            from fastembed import TextEmbedding

            self._cpu_backup_model = TextEmbedding(
                model_name=self.model if self.model else CODERANK_MODEL,
                threads=1,
                providers=["CPUExecutionProvider"],
                lazy_load=True,
            )
        vecs = list(
            self._cpu_backup_model.embed(
                batch,
                batch_size=batch_size,
                parallel=None,
            )
        )
        return np.asarray(vecs, dtype=np.float32)

    def _cpu_backup_batch_ceiling(self) -> int:
        ceiling = int(self.batch_size)
        if self._accel:
            try:
                ceiling = min(
                    ceiling,
                    int((self._accel.envelope or {}).get("batch_ceiling", ceiling)),
                )
            except (TypeError, ValueError):
                pass
        return max(1, ceiling // 2)

    def format_query(self, query: str) -> str:
        if self.backend in {"coderank", "fastembed"} and not query.startswith(QUERY_PREFIX):
            return QUERY_PREFIX + query
        return query

    def _encode_batch(self, batch: list[str]) -> np.ndarray:
        if self.backend == "fastembed":
            backup_batch = self._cpu_backup_batch_ceiling()
            runtime_state = self.runtime_state
            prof = self._accel
            gpu_only_coreml = False
            if prof and prof.profile == "coreml":
                from pipeline.coreml_mac import mac_gpu_only

                gpu_only_coreml = mac_gpu_only()
            if (
                runtime_state.active_profile == "cpu"
                and runtime_state.preferred_profile != "cpu"
                and not gpu_only_coreml
            ):
                self.device = "cpu"
                return self._embed_cpu_backup(batch, batch_size=backup_batch)
            try:
                model = self._ensure_fastembed()
                ort_bs = len(batch)
                payload = batch
                if prof and prof.profile == "coreml":
                    from pipeline.coreml_mac import pad_embed_batch, static_embed_batch_size

                    ort_bs = static_embed_batch_size(prof, self.batch_size)
                    payload = pad_embed_batch(batch, ort_bs)
                vecs = list(model.embed(payload, batch_size=ort_bs, parallel=None))
                arr = np.asarray(vecs[: len(batch)], dtype=np.float32)
                return arr
            except Exception as primary_exc:
                if runtime_state.preferred_profile == "cpu" or gpu_only_coreml:
                    raise
                from pipeline.runtime_profile import (
                    activate_cpu_backup,
                    set_runtime_profile_state,
                )

                try:
                    result = self._embed_cpu_backup(
                        batch,
                        batch_size=backup_batch,
                    )
                except Exception as backup_exc:
                    self.device = runtime_state.preferred_profile
                    raise primary_exc from backup_exc
                set_runtime_profile_state(
                    activate_cpu_backup(runtime_state, str(primary_exc))
                )
                self.device = "cpu"
                return result
        model = self._ensure_coderank()
        return model.encode(
            batch,
            batch_size=len(batch),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).astype(np.float32)

    def embed_one(self, text: str, *, is_query: bool = False) -> np.ndarray:
        payload = self.format_query(text) if is_query else text
        key = text_key(("q:" if is_query else "d:") + payload)
        if key in self.cache:
            vec = np.asarray(self.cache[key], dtype=np.float32)
            if self.dim is None:
                self.dim = int(vec.shape[0])
            return vec
        if self.backend in {"coderank", "fastembed"}:
            arr = self._encode_batch([payload])
            emb = arr[0].astype(np.float32).tolist()
        else:
            emb = self._ollama_embed(payload)
        self.cache[key] = emb
        self._queue_cache(key, emb)
        self.flush_cache()
        vec = np.asarray(emb, dtype=np.float32)
        if self.dim is None:
            self.dim = int(vec.shape[0])
        return vec

    def embed_many(
        self,
        texts: list[str],
        progress=None,
        *,
        is_query: bool = False,
    ) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim or 0), dtype=np.float32)

        if self.backend == "ollama":
            rows = []
            for i, t in enumerate(texts):
                rows.append(self.embed_one(t, is_query=is_query))
                if progress and (i + 1) % 25 == 0:
                    progress(i + 1, len(texts))
            self.flush_cache()
            return np.stack(rows, axis=0)

        pending_idx: list[int] = []
        pending_text: list[str] = []
        encoded: dict[int, np.ndarray] = {}

        for i, t in enumerate(texts):
            payload = self.format_query(t) if is_query else t
            key = text_key(("q:" if is_query else "d:") + payload)
            if key in self.cache:
                encoded[i] = np.asarray(self.cache[key], dtype=np.float32)
            else:
                pending_idx.append(i)
                pending_text.append(payload)

        bs = max(1, int(self.batch_size))
        t_all = time.perf_counter()
        done_new = 0
        # Adaptive batching via Resource Manager
        try:
            from pipeline.resources import get_resource_manager

            rm = get_resource_manager()
            rm.refresh_base_from_accel()
        except Exception:  # noqa: BLE001
            rm = None

        start = 0
        # Floor: never thrash below the hardware-tuned batch on healthy systems.
        # Adaptive RM may raise (idle boost) or cut on busy/critical only.
        configured_bs = max(1, int(self.batch_size))
        while start < len(pending_text):
            if rm is not None:
                budget = rm.wait_for_capacity(
                    "embed",
                    timeout_s=180.0,
                    on_wait=lambda b: print(
                        f"[resources] embed waiting pressure={b.pressure} {b.reason}",
                        file=sys.stderr,
                        flush=True,
                    ),
                )
                if budget.pressure in {"idle", "normal"}:
                    bs = max(configured_bs, int(budget.batch_size))
                elif budget.pressure == "busy":
                    bs = max(max(1, configured_bs // 2), 1)
                else:
                    bs = 1 if not budget.allow else max(1, min(int(budget.batch_size), configured_bs))
                bs = max(1, min(bs, len(pending_text) - start))
                if not budget.allow and budget.pressure == "critical":
                    bs = 1
                    print(
                        f"[resources] embed proceeding minimally: {budget.reason}",
                        file=sys.stderr,
                        flush=True,
                    )
            else:
                bs = max(1, min(configured_bs, len(pending_text) - start))
            t_batch = time.perf_counter()
            batch = pending_text[start : start + bs]
            idxs = pending_idx[start : start + bs]
            arr = self._encode_batch(batch)
            for j, idx in enumerate(idxs):
                vec = arr[j].astype(np.float32)
                encoded[idx] = vec
                key = text_key(("q:" if is_query else "d:") + batch[j])
                emb = vec.tolist()
                self.cache[key] = emb
                self._queue_cache(key, emb)
            done_new += len(batch)
            batch_ms = (time.perf_counter() - t_batch) * 1000
            rate = len(batch) / max(batch_ms / 1000.0, 1e-6)
            if progress:
                progress(min(start + bs, len(pending_text)), len(texts))
            if not progress and (
                start == 0
                or (start // max(bs, 1)) % 5 == 0
                or start + bs >= len(pending_text)
            ):
                print(
                    f"[embed] {done_new}/{len(pending_text)} new "
                    f"(+{len(encoded)-done_new} cached) "
                    f"{rate:.1f} chunk/s batch_ms={batch_ms:.0f} bs={bs} device={self.device}",
                    file=sys.stderr,
                    flush=True,
                )
            if rm is not None:
                try:
                    rm.apply_pause(rm.budget("embed"))
                except Exception:  # noqa: BLE001
                    pass
            start += len(batch)

        self.flush_cache()
        try:
            self.save_cache_npz()
        except Exception:  # noqa: BLE001
            pass

        rows = [encoded[i] for i in range(len(texts))]
        matrix = np.stack(rows, axis=0)
        self.dim = int(matrix.shape[1])
        elapsed = time.perf_counter() - t_all
        self._last_stats = {
            "total": len(texts),
            "cached": len(texts) - len(pending_text),
            "embedded": len(pending_text),
            "seconds": round(elapsed, 2),
            "chunk_per_s": round(len(pending_text) / max(elapsed, 1e-6), 2),
            "device": self.device,
            "batch_size": bs,
            "backend": self.backend,
        }
        if not progress:
            print(
                f"[embed] done: {self._last_stats['embedded']} new / {self._last_stats['cached']} cached "
                f"in {elapsed:.1f}s ({self._last_stats['chunk_per_s']:.1f} chunk/s) on {self.device}",
                file=sys.stderr,
                flush=True,
            )
        return matrix

    def _ollama_embed(self, text: str) -> list[float]:
        import requests

        endpoint = os.environ.get("CTX_OLLAMA_EMBED", "http://localhost:11434/api/embed")
        payload = {"model": self.model, "input": text}
        try:
            r = requests.post(endpoint, json=payload, timeout=120)
            r.raise_for_status()
            data = r.json()
        except Exception:
            alt = endpoint.replace("/api/embed", "/api/embeddings")
            r = requests.post(alt, json={"model": self.model, "prompt": text}, timeout=120)
            r.raise_for_status()
            data = r.json()
        if "embeddings" in data:
            return list(data["embeddings"][0])
        return list(data["embedding"])
