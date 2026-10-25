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
import threading
import time
from pathlib import Path

import numpy as np

QUERY_PREFIX = "Represent this query for searching relevant code: "

_MLX_THREAD = threading.local()
CODERANK_MODEL = "nomic-ai/CodeRankEmbed"
DEFAULT_MODEL = os.environ.get("CTX_EMBED_MODEL", CODERANK_MODEL)


def _diag_on() -> bool:
    """``[embed]`` load/throughput diagnostics: on for the engine log, off for CLI front-ends."""
    raw = (os.environ.get("CTX_EMBED_LOG") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _diag(message: str) -> None:
    if _diag_on():
        print(message, file=sys.stderr, flush=True)


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Cache rows that no live chunk references (old chunk text, recent queries).
# Keys are hashes, so queries cannot be told apart from stale chunks; keeping
# the newest few hundred covers repeated searches and quick edit/undo cycles.
CACHE_KEEP_EXTRA = int(os.environ.get("CTX_EMBED_CACHE_KEEP_EXTRA", "1024") or "1024")
CACHE_LOG_COMPACT_BYTES = int(
    float(os.environ.get("CTX_EMBED_LOG_COMPACT_MB", "8") or "8") * 1024 * 1024
)
_CACHE_THREAD_LOCK = threading.RLock()


class _CacheFileLock:
    """Cross-process lock beside ``embed_cache.jsonl``; ``acquired`` may be false."""

    def __init__(self, cache_path: Path, timeout_s: float) -> None:
        self.path = Path(cache_path).with_suffix(".lock")
        self.timeout_s = timeout_s
        self.fd: int | None = None
        self.acquired = False
        self._thread_held = False

    def __enter__(self) -> "_CacheFileLock":
        deadline = time.monotonic() + max(0.0, self.timeout_s)
        if not _CACHE_THREAD_LOCK.acquire(timeout=max(0.0, self.timeout_s)):
            return self
        self._thread_held = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR)
        except OSError:
            self.fd = None
            return self
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    os.lseek(self.fd, 0, os.SEEK_SET)
                    msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    return self
                time.sleep(0.05)

    def __exit__(self, *exc: object) -> None:
        try:
            if self.fd is not None:
                if self.acquired:
                    try:
                        if sys.platform == "win32":
                            import msvcrt

                            os.lseek(self.fd, 0, os.SEEK_SET)
                            msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl

                            fcntl.flock(self.fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                os.close(self.fd)
        finally:
            self.fd = None
            self.acquired = False
            if self._thread_held:
                self._thread_held = False
                _CACHE_THREAD_LOCK.release()


def _file_sig(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (int(st.st_mtime_ns), int(st.st_size))


def _read_cache_npz(npz: Path) -> tuple[list[str], np.ndarray] | None:
    try:
        with np.load(npz, allow_pickle=True) as data:
            keys = [str(k) for k in data["keys"].tolist()]
            vecs = np.ascontiguousarray(data["vecs"], dtype=np.float32)
    except Exception:  # noqa: BLE001
        return None
    if vecs.ndim != 2 or vecs.shape[0] != len(keys):
        return None
    return keys, vecs


def _iter_cache_log(log: Path, known: dict[str, np.ndarray] | None = None):
    """Yield ``(key, float32 vector)`` rows of the append log, skipping known keys.

    Rows are written as json.dumps({"key": ..., "embedding": [...]}): for a
    known key only the leading key is decoded, so its ~16 KB embedding is never
    parsed (full replay of a 150 MB log was seconds of GIL-bound startup work).
    """
    try:
        text = log.read_text(encoding="utf-8")
    except OSError:
        return
    key_prefix = '{"key": '
    decoder = json.JSONDecoder()
    for line in text.splitlines():
        if not line.strip():
            continue
        if known is not None and line.startswith(key_prefix):
            try:
                known_key, _end = decoder.raw_decode(line, len(key_prefix))
            except json.JSONDecodeError:
                known_key = None
            if known_key is not None and str(known_key) in known:
                continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = row.get("key")
        emb = row.get("embedding")
        if key is None or emb is None:
            continue
        try:
            vec = np.asarray(emb, dtype=np.float32)
        except (TypeError, ValueError):
            continue
        if vec.ndim != 1 or vec.size == 0:
            continue
        yield str(key), vec


def _write_npz_atomic(npz: Path, keys: list[str], vecs: np.ndarray) -> bool:
    tmp = npz.with_name(f"{npz.stem}.{os.getpid()}.{threading.get_ident()}.tmp.npz")
    try:
        # Uncompressed: float32 embeddings deflate by only a few percent, and
        # the compressed write cost ~1.5 s per snapshot at 10k rows.
        np.savez(tmp, keys=np.asarray(keys, dtype=str), vecs=vecs)
        for attempt in range(5):
            try:
                os.replace(tmp, npz)
                return True
            except PermissionError:
                # Windows: another process is mid-read of the snapshot.
                time.sleep(0.1 * (attempt + 1))
        return False
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _select_keep(
    keys: list[str], live_keys: set[str] | None, keep_extra: int
) -> list[str]:
    if live_keys is None:
        return keys
    extra = [k for k in keys if k not in live_keys]
    keep_tail = set(extra[-keep_extra:]) if keep_extra > 0 else set()
    return [k for k in keys if k in live_keys or k in keep_tail]


def write_cache_snapshot(
    cache_path: Path,
    cache: dict[str, np.ndarray],
    *,
    npz_sig: tuple[int, int] | None = None,
    live_keys: set[str] | None = None,
    keep_extra: int = CACHE_KEEP_EXTRA,
    lock_timeout_s: float = 10.0,
) -> tuple[int, int] | None:
    """Merge on-disk rows into *cache*, optionally prune, snapshot, truncate the log.

    Other processes share these files, so rows they wrote (snapshot changed
    since *npz_sig*, or appended to the log) are merged in before the snapshot
    replaces theirs. The log is truncated only after the snapshot is safely
    in place, and appends hold the same lock, so no row is dropped. Returns
    the new snapshot signature, or ``None`` when nothing was written.
    """
    cache_path = Path(cache_path)
    npz = cache_path.with_suffix(".npz")
    with _CacheFileLock(cache_path, lock_timeout_s) as lock:
        if not lock.acquired:
            return None
        disk_sig = _file_sig(npz)
        if disk_sig is not None and disk_sig != npz_sig:
            loaded = _read_cache_npz(npz)
            if loaded is not None:
                disk_keys, disk_vecs = loaded
                for i, k in enumerate(disk_keys):
                    if k not in cache:
                        cache[k] = disk_vecs[i]
        if cache_path.exists():
            for k, vec in _iter_cache_log(cache_path, known=cache):
                cache[k] = vec
        if not cache:
            return None
        items = list(cache.items())
        seen_keys = [k for k, _v in items]
        dims = {int(np.asarray(v).shape[-1]) for _k, v in items}
        if len(dims) != 1:
            # Mixed dimensions (model switch mid-cache): keep the majority dim.
            counts: dict[int, int] = {}
            for _k, v in items:
                d = int(np.asarray(v).shape[-1])
                counts[d] = counts.get(d, 0) + 1
            best = max(counts, key=lambda d: counts[d])
            items = [(k, v) for k, v in items if int(np.asarray(v).shape[-1]) == best]
        keys = _select_keep([k for k, _v in items], live_keys, keep_extra)
        keep = set(keys)
        by_key = dict(items)
        vecs = np.ascontiguousarray(
            np.stack([np.asarray(by_key[k], dtype=np.float32) for k in keys], axis=0)
            if keys
            else np.zeros((0, len(next(iter(by_key.values())))), dtype=np.float32)
        )
        if not _write_npz_atomic(npz, keys, vecs):
            return None
        try:
            with cache_path.open("w", encoding="utf-8"):
                pass
        except OSError:
            pass
        # Only rows this snapshot saw: a row another thread added meanwhile is
        # not in the snapshot yet and must stay in RAM (its log append follows).
        for k in seen_keys:
            if k not in keep:
                cache.pop(k, None)
        # Re-point rows at the one contiguous block so merged/old arrays free.
        for i, k in enumerate(keys):
            cache[k] = vecs[i]
        return _file_sig(npz)


def cache_needs_compaction(
    cache_path: Path,
    live_keys: set[str] | None = None,
    *,
    keep_extra: int = CACHE_KEEP_EXTRA,
    log_bytes: int = CACHE_LOG_COMPACT_BYTES,
) -> bool:
    """Cheap check: big append log, or many snapshot rows no live chunk uses."""
    cache_path = Path(cache_path)
    try:
        if cache_path.exists() and cache_path.stat().st_size > max(0, log_bytes):
            return True
    except OSError:
        pass
    if live_keys is None:
        return False
    npz = cache_path.with_suffix(".npz")
    if not npz.exists():
        return False
    try:
        with np.load(npz, allow_pickle=True) as data:
            keys = data["keys"].tolist()
    except Exception:  # noqa: BLE001
        return False
    dead = sum(1 for k in keys if str(k) not in live_keys)
    return dead > max(64, int(keep_extra * 1.5))


_ORT_ARENA_PATCHED = False


def disable_ort_cpu_mem_arena() -> dict[str, object]:
    """Secondary RSS mitigation while the engine process is alive.

    ONNX Runtime arenas are not returned to the OS after session destroy
    (disconnect still **exits the process**). Disabling the CPU mem arena
    reduces sticky RSS for FastEmbed constructs. Safe to call repeatedly.

    Also disables session spinning (CPU busy-wait) so idle warm sessions
    do not burn cores while staying loaded for <1s first map.
    """
    global _ORT_ARENA_PATCHED
    os.environ["ORT_ENABLE_CPU_MEM_ARENA"] = "0"
    os.environ.setdefault("ONNXRUNTIME_DISABLE_CPU_ARENA", "1")
    patched = False
    kwargs_ok = False
    if not _ORT_ARENA_PATCHED:
        try:
            import onnxruntime as ort

            orig = ort.SessionOptions

            class _LeanSessionOptions(orig):  # type: ignore[valid-type,misc]
                def __init__(self, *args: object, **kwargs: object) -> None:
                    super().__init__(*args, **kwargs)
                    try:
                        self.enable_cpu_mem_arena = False
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        # DirectML requires sequential + no mem pattern.
                        self.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        self.enable_mem_pattern = False
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        self.add_session_config_entry(
                            "session.intra_op.allow_spinning", "0"
                        )
                    except Exception:  # noqa: BLE001
                        pass

            ort.SessionOptions = _LeanSessionOptions  # type: ignore[misc]
            ort._scubiee_arena_patched = True  # type: ignore[attr-defined]
            _ORT_ARENA_PATCHED = True
            patched = True
        except Exception:  # noqa: BLE001
            patched = False
    else:
        patched = True
    try:
        import inspect

        from fastembed import TextEmbedding

        kwargs_ok = "enable_cpu_mem_arena" in inspect.signature(TextEmbedding.__init__).parameters
    except Exception:  # noqa: BLE001
        kwargs_ok = False
    return {
        "ok": True,
        "env": "ORT_ENABLE_CPU_MEM_ARENA=0",
        "session_options_patched": patched,
        "textembedding_kwarg": kwargs_ok,
    }


def fastembed_session_kwargs() -> dict[str, object]:
    """Extra TextEmbedding kwargs when the installed FastEmbed accepts them."""
    info = disable_ort_cpu_mem_arena()
    if info.get("textembedding_kwarg"):
        return {"enable_cpu_mem_arena": False}
    return {}


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
    """Set CPU thread limits respecting the memory budget's cpu_thread_pct.

    CTX_CPU_EMBED_THREADS is set by apply_index_memory_budget():
    - bootstrap/large_reindex: 20% of cpu_count (capped; GPU profiles use 1 ORT thread)
    - background sync: 15% of cpu_count (barely noticeable during coding)
    """
    try:
        import torch

        n = int(os.environ.get("CTX_CPU_EMBED_THREADS", "0")) or int(
            os.environ.get("CTX_TORCH_THREADS", "0")
        ) or max(1, int((os.cpu_count() or 4) * 0.20))
        torch.set_num_threads(max(1, n))
        torch.set_num_interop_threads(max(1, min(4, n // 2 or 1)))
    except Exception:  # noqa: BLE001
        pass


def _accel_wants_fastembed() -> bool:
    """Saved/hardware profile prefers FastEmbed unless MLX is the runtime."""
    try:
        from pipeline.accel import resolve_runtime

        prof = resolve_runtime()
        if str(getattr(prof, "profile", "") or "") == "mlx":
            return False
        return str(getattr(prof, "backend", "fastembed") or "fastembed") == "fastembed"
    except Exception:  # noqa: BLE001
        return True


def _runtime_is_mlx() -> bool:
    """True when the resolved accelerator profile is MLX. Cheap: reads the saved
    profile only, never imports fastembed/torch (which is unsafe to do on a
    worker thread while a live MLX Metal context is active)."""
    try:
        from pipeline.accel import resolve_runtime

        prof = resolve_runtime()
        return (str(getattr(prof, "profile", "") or "") == "mlx"
                or str(getattr(prof, "backend", "") or "") == "mlx")
    except Exception:  # noqa: BLE001
        return False


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
        if env in {"fastembed", "coderank", "sentence-transformers", "st", "ollama", "mlx"}:
            chosen = "coderank" if env in {"st", "sentence-transformers"} else env
        else:
            name = (model or "").lower()
            if name.startswith("ollama:") or name in {"nomic-embed-text"}:
                chosen = "ollama"
            elif _accel_wants_fastembed():
                chosen = "fastembed"
            elif _runtime_is_mlx():
                # MLX machine: choose MLX directly. Do NOT probe
                # _fastembed_available() here — that does `import fastembed`
                # (pulling numpy.typing/torch), and when this runs on a worker
                # thread while the eager-prewarm MLX embed holds a live Metal
                # context on another thread, the concurrent heavy native import
                # segfaults the engine on a fresh init (MLX is not thread-safe,
                # ml-explore/mlx#1448). The accel re-check below would flip
                # "fastembed" to "mlx" anyway, so the import was pure risk.
                chosen = "mlx"
            elif _fastembed_available():
                chosen = "fastembed"
            else:
                chosen = "coderank"

        try:
            from pipeline.accel import resolve_runtime

            prof = resolve_runtime()
            if (
                chosen == "fastembed"
                and (prof.profile == "mlx" or prof.backend == "mlx")
                and env not in {"fastembed", "cpu", "coreml"}
            ):
                chosen = "mlx"
        except Exception:  # noqa: BLE001
            pass

    if chosen == "mlx":
        try:
            import mlx.core  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            from pipeline.preflight import CapabilityError

            raise CapabilityError(
                "CTX_EMBED_BACKEND=mlx requires the mlx package on Apple Silicon "
                "(pip install mlx). Refusing FastEmbed/CPU fallback."
            ) from exc
    if chosen == "fastembed" and not _fastembed_available():
        from pipeline.preflight import CapabilityError

        raise CapabilityError(
            "Scubiee accel profile requires FastEmbed + ONNX Runtime, but "
            "fastembed is not installed in this Python. Run: scubiee setup "
            "(reinstall: uv tool install scubiee). Refusing silent PyTorch/CPU fallback."
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
        self.cache: dict[str, np.ndarray] = {}
        self._npz_sig: tuple[int, int] | None = None
        self._st_model = None
        self._fe_model = None
        self._mlx_model = None
        self._mlx_tokenizer = None
        self._mlx_timings: dict[str, float] = {}
        self._cpu_backup_model = None
        self._cache_dirty: list[tuple[str, np.ndarray]] = []
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

        if self.backend == "mlx":
            from pipeline.mlx_mac import require_mlx_gpu

            report = require_mlx_gpu()
            self.device = "gpu"
            self._mlx_device_report = report
            default_batch = max(1, int((self._accel.batch_size if self._accel else 32) or 32))
            # Honor quiet mode: when a progress bar drives updates (quiet=True)
            # the MLX construction banner must not spam stderr, mirroring the
            # `plan` banner guard below.
            if not self.quiet and _diag_on():
                print("[embed] backend=mlx", file=sys.stderr, flush=True)
                print("[embed] device=gpu", file=sys.stderr, flush=True)
                print(
                    f"[embed] metal={'true' if report.get('metal_available') else 'false'}",
                    file=sys.stderr,
                    flush=True,
                )
                print(
                    f"[embed] mlx_device={report.get('default_device')}",
                    file=sys.stderr,
                    flush=True,
                )
        elif self.backend == "fastembed" and self._accel:
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

        if not self.quiet and _diag_on():
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

        skip_cache = os.environ.get("CTX_EMBED_NO_CACHE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._skip_cache = skip_cache
        if skip_cache:
            self.cache_path = None
        elif cache_path and cache_path.exists():
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
            sig = _file_sig(npz)
            loaded = _read_cache_npz(npz)
            if loaded is not None:
                keys, vecs = loaded
                # Row views of one float32 block: ~3 KB per 768-d row instead of
                # ~25 KB as a list of Python floats.
                for i, k in enumerate(keys):
                    self.cache[k] = vecs[i]
                self._npz_sig = sig
                # The .npz is a snapshot; the .jsonl is the append log. Small
                # batches no longer rewrite the snapshot, so rows appended after
                # it would be lost on restart unless the log tail is replayed.
                if (
                    self.cache_path.exists()
                    and self.cache_path.stat().st_mtime > npz.stat().st_mtime
                ):
                    self._replay_cache_log(skip_known=True)
                return
        self._replay_cache_log(skip_known=False)

    def _replay_cache_log(self, *, skip_known: bool) -> None:
        assert self.cache_path is not None
        if not self.cache_path.exists():
            return
        for key, vec in _iter_cache_log(self.cache_path, self.cache if skip_known else None):
            if skip_known and key in self.cache:
                continue
            self.cache[key] = vec

    def _queue_cache(self, key: str, emb) -> None:
        if not self.cache_path:
            return
        self._cache_dirty.append((key, emb))
        if len(self._cache_dirty) >= self.cache_flush_every:
            self.flush_cache()

    def flush_cache(self) -> None:
        if not self.cache_path or not self._cache_dirty:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        rows, self._cache_dirty = self._cache_dirty, []
        text = "".join(
            json.dumps({"key": key, "embedding": np.asarray(emb, dtype=np.float32).tolist()})
            + "\n"
            for key, emb in rows
        )
        # Same lock as the snapshot's log truncation; on timeout append anyway
        # (worst case a later restart misses the row and re-embeds it).
        with _CacheFileLock(self.cache_path, 5.0):
            with self.cache_path.open("a", encoding="utf-8") as f:
                f.write(text)

    def save_cache_npz(
        self,
        *,
        live_keys: set[str] | None = None,
        keep_extra: int = CACHE_KEEP_EXTRA,
    ) -> Path | None:
        """Snapshot the cache to ``.npz`` and empty the append log.

        With *live_keys*, rows outside it are dropped except the newest
        *keep_extra* (recent queries and just-replaced chunk text).
        """
        if not self.cache_path or not self.cache:
            return None
        self.flush_cache()
        sig = write_cache_snapshot(
            self.cache_path,
            self.cache,
            npz_sig=getattr(self, "_npz_sig", None),
            live_keys=live_keys,
            keep_extra=keep_extra,
        )
        if sig is None:
            return None
        self._npz_sig = sig
        return self.cache_path.with_suffix(".npz")

    def _ensure_fastembed(self):
        if self._fe_model is not None:
            return self._fe_model
        from pipeline.accel import register_coderank, resolve_runtime

        register_coderank()
        from fastembed import TextEmbedding

        prof = self._accel or resolve_runtime()
        providers = prof.providers()
        model_name = self.model if self.model else CODERANK_MODEL

        # CPU-only: use INT8 quantized model if available (1.5x faster, 4x smaller)
        if prof.profile == "cpu" and not self.model:
            from pipeline.accel import coderank_int8_onnx_path
            int8_path = coderank_int8_onnx_path()
            if int8_path:
                # Re-register with INT8 model file so FastEmbed loads it
                from pipeline.accel import CODERANK_HF_ONNX, CODERANK_INT8_ONNX_FILE
                from fastembed.common.model_description import ModelSource, PoolingType
                try:
                    TextEmbedding.add_custom_model(
                        model=CODERANK_MODEL,
                        pooling=PoolingType.MEAN,
                        normalization=True,
                        sources=ModelSource(hf=CODERANK_HF_ONNX),
                        dim=768,
                        model_file=CODERANK_INT8_ONNX_FILE,
                        description="CodeRankEmbed INT8 ONNX (CPU optimized)",
                        license="mit",
                        size_in_gb=0.13,
                    )
                except (ValueError, TypeError):
                    pass  # Already registered or API mismatch — FP16 still works

        if prof.profile == "coreml":
            from pipeline.coreml_mac import coreml_model_name

            model_name = coreml_model_name(model_name)
        _diag(
            f"[embed] loading FastEmbed {model_name} profile={prof.profile} "
            f"batch={self.batch_size} providers={providers[0] if providers else '?'}"
        )
        t0 = time.perf_counter()
        # CPU-only profiles use the thread budget from memory_budget (20% for
        # bootstrap, 15% for background sync). GPU/DML profiles keep threads=1
        # since the GPU handles matmul; CPU still does tokenize + ORT fallback ops.
        if prof.profile == "cpu":
            ort_threads = int(os.environ.get("CTX_CPU_EMBED_THREADS", "0")) or max(
                1, int((os.cpu_count() or 4) * 0.20)
            )
        else:
            ort_threads = 1
        from pipeline.accel import fastembed_cache_root

        extra = fastembed_session_kwargs()
        self._fe_model = TextEmbedding(
            model_name=model_name,
            threads=ort_threads,
            providers=providers,
            lazy_load=True,
            cache_dir=str(fastembed_cache_root()),
            **extra,
        )
        from pipeline.coreml_mac import bind_coreml_tokenizer, pad_embed_batch, static_embed_batch_size

        warm_bs = 1
        warm = ["warmup"]
        if prof.profile == "coreml":
            bind_coreml_tokenizer(self._fe_model)
            warm_bs = static_embed_batch_size(prof, self.batch_size)
            warm = pad_embed_batch(warm, warm_bs)
        list(self._fe_model.embed(warm, batch_size=warm_bs, parallel=None))
        _diag(f"[embed] FastEmbed ready in {(time.perf_counter()-t0)*1000:.0f}ms")
        if (os.environ.get("CTX_SCUBIEE_ROLE") or "").strip().lower() == "engine":
            try:
                from pipeline.engine import publish_dense_phase

                publish_dense_phase()
            except Exception:  # noqa: BLE001
                pass
        return self._fe_model

    def _ensure_coderank(self):
        if self._st_model is not None:
            return self._st_model
        from sentence_transformers import SentenceTransformer

        _diag(
            f"[embed] loading ST {self.model} on {self.device} "
            f"(batch={self.batch_size}, seq={self.max_seq_length})"
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
        _diag(f"[embed] model ready in {(time.perf_counter()-t0)*1000:.0f}ms device={self.device}")
        return self._st_model

    def _ensure_mlx(self):
        model = getattr(_MLX_THREAD, "model", None)
        if model is not None:
            self._mlx_model = model
            self._mlx_tokenizer = getattr(_MLX_THREAD, "tokenizer", None) or self._mlx_tokenizer
            return model
        from pipeline.mlx_mac import (
            CodeRankMLX,
            load_coderank_tokenizer,
            mlx_thread_stream,
            require_mlx_gpu,
        )

        report = require_mlx_gpu()
        self._mlx_device_report = report
        from pipeline.mlx_mac import resolve_embed_dtype

        dtype = resolve_embed_dtype()
        _diag(f"[embed] loading MLX CodeRankEmbed dtype={dtype} device={report.get('default_device')}")
        t0 = time.perf_counter()
        with mlx_thread_stream():
            model = CodeRankMLX(dtype=dtype, require_gpu=True)
        tok = load_coderank_tokenizer()
        _MLX_THREAD.model = model
        _MLX_THREAD.tokenizer = tok
        self._mlx_model = model
        self._mlx_tokenizer = tok
        _diag(
            f"[embed] MLX ready in {(time.perf_counter() - t0) * 1000:.0f}ms "
            f"metal={bool(report.get('metal_available'))}"
        )
        return self._mlx_model

    def _embed_cpu_backup(self, batch: list[str], *, batch_size: int) -> np.ndarray:
        """Embed one operation on CPU without changing the installed profile."""

        if self._cpu_backup_model is None:
            from fastembed import TextEmbedding

            from pipeline.accel import fastembed_cache_root

            extra = fastembed_session_kwargs()
            self._cpu_backup_model = TextEmbedding(
                model_name=self.model if self.model else CODERANK_MODEL,
                threads=1,
                providers=["CPUExecutionProvider"],
                lazy_load=True,
                cache_dir=str(fastembed_cache_root()),
                **extra,
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
        if self.backend in {"coderank", "fastembed", "mlx"} and not query.startswith(QUERY_PREFIX):
            return QUERY_PREFIX + query
        return query

    def _encode_batch(self, batch: list[str]) -> np.ndarray:
        # GC is disabled globally in the daemon process (server.py run_server).
        # For non-daemon callers (CLI scubiee index), disable GC during native
        # embedding to prevent SIGSEGV from GC traversing partially-modified
        # objects while tokenizers/numpy/MLX release the GIL.
        import gc

        def _run() -> np.ndarray:
            gc_was_enabled = gc.isenabled()
            if gc_was_enabled:
                gc.disable()
            try:
                return self._encode_batch_inner(batch)
            finally:
                if gc_was_enabled:
                    gc.enable()

        # Engine process: all ORT/DML (map keepalive + incremental sync) must
        # share the single embed worker. Concurrent DirectML from the keeper
        # sync thread + keepalive wedged /health and hung map forever.
        try:
            from pipeline.lifecycle_runtime import is_engine_process

            if is_engine_process():
                from pipeline.engine import run_embed_infer

                return run_embed_infer(_run, timeout_s=None)
        except Exception:  # noqa: BLE001
            pass
        return _run()

    def _encode_batch_inner(self, batch: list[str]) -> np.ndarray:
        if self.backend == "mlx":
            from pipeline.mlx_mac import content_token_count, tokenize_batch

            model = self._ensure_mlx()
            t0 = time.perf_counter()
            ids, mask = tokenize_batch(
                batch,
                tokenizer=self._mlx_tokenizer,
                max_seq=min(int(self.max_seq_length or 512), 512),
            )
            self._mlx_timings["tokenization"] = self._mlx_timings.get("tokenization", 0.0) + (
                time.perf_counter() - t0
            )
            self._last_batch_tokens = content_token_count(mask)
            self._last_batch_seq = int(ids.shape[1])
            if ids.shape[1] > 512:
                raise RuntimeError(f"MLX batch seq {ids.shape[1]} exceeds model max 512")
            return model.embed_ids(ids, mask, timings=self._mlx_timings)
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
            # Callers may normalize in place; never hand out the cached row.
            vec = np.array(self.cache[key], dtype=np.float32, copy=True)
            if self.dim is None:
                self.dim = int(vec.shape[0])
            return vec
        if self.backend in {"coderank", "fastembed", "mlx"}:
            arr = self._encode_batch([payload])
            vec = np.array(arr[0], dtype=np.float32, copy=True)
        else:
            vec = np.asarray(self._ollama_embed(payload), dtype=np.float32)
        self.cache[key] = vec
        self._queue_cache(key, vec)
        self.flush_cache()
        if self.dim is None:
            self.dim = int(vec.shape[0])
        return vec.copy()

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
            if progress:
                progress(len(texts), len(texts))
            self.flush_cache()
            return np.stack(rows, axis=0)

        pending_idx: list[int] = []
        pending_text: list[str] = []
        encoded: dict[int, np.ndarray] = {}
        skip_cache = bool(getattr(self, "_skip_cache", False))

        for i, t in enumerate(texts):
            payload = self.format_query(t) if is_query else t
            key = text_key(("q:" if is_query else "d:") + payload)
            if not skip_cache and key in self.cache:
                encoded[i] = np.asarray(self.cache[key], dtype=np.float32)
            else:
                pending_idx.append(i)
                pending_text.append(payload)

        bs = max(1, int(self.batch_size))
        t_all = time.perf_counter()
        done_new = 0
        n_cached = len(texts) - len(pending_text)
        if progress:
            progress(n_cached, len(texts))
        # Adaptive batching via Resource Manager
        try:
            from pipeline.resources import get_resource_manager, resources_disabled

            if resources_disabled():
                rm = None
            else:
                rm = get_resource_manager()
                if rm.is_disabled():
                    rm = None
                else:
                    rm.refresh_base_from_accel()
        except Exception:  # noqa: BLE001
            rm = None

        start = 0
        # Floor: never thrash below the hardware-tuned batch on healthy systems.
        # Adaptive RM may raise (idle boost) or cut on busy/critical only.
        configured_bs = max(1, int(self.batch_size))
        self._embed_token_total = 0
        gpu_tok_total = 0
        n_forwards = 0
        self._mlx_timings = {}
        # A hot save embeds 1-64 chunks (a few MB): it must not sit on the
        # near-OOM guard for minutes, one-chunk batches, or spam the log.
        # Bulk indexing keeps the original wait/shrink behaviour (issue 3).
        try:
            from pipeline.resources import hot_lane_max_chunks, hot_lane_wait_s

            small = len(pending_text) <= hot_lane_max_chunks()
            small_wait = hot_lane_wait_s()
        except Exception:  # noqa: BLE001
            small, small_wait = False, 0.0
        while start < len(pending_text):
            if rm is not None:
                budget = rm.wait_for_capacity(
                    "embed",
                    timeout_s=small_wait if small else 180.0,
                    on_wait=None if small else (lambda b: print(
                        f"[resources] embed waiting pressure={b.pressure} {b.reason}",
                        file=sys.stderr,
                        flush=True,
                    )),
                )
                if budget.pressure in {"idle", "normal"}:
                    bs = max(configured_bs, int(budget.batch_size))
                elif budget.pressure == "busy":
                    bs = max(max(1, configured_bs // 2), 1)
                else:
                    bs = 1 if not budget.allow else max(1, min(int(budget.batch_size), configured_bs))
                bs = max(1, min(bs, len(pending_text) - start))
                if not budget.allow and budget.pressure == "critical":
                    if small:
                        bs = max(1, min(configured_bs, len(pending_text) - start))
                        avail = (budget.sample or {}).get("ram_available_mb")
                        print(
                            f"[resources] hot save embed {len(pending_text)} chunk(s) under low RAM "
                            f"(available={avail}MB) — proceeding after {small_wait:.1f}s",
                            file=sys.stderr,
                            flush=True,
                        )
                        rm = None  # one short wait per save, not one per batch
                    else:
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
                vec = np.array(arr[j], dtype=np.float32, copy=True)
                encoded[idx] = vec
                if not skip_cache:
                    key = text_key(("q:" if is_query else "d:") + batch[j])
                    self.cache[key] = vec
                    self._queue_cache(key, vec)
            done_new += len(batch)
            batch_ms = (time.perf_counter() - t_batch) * 1000
            rate = len(batch) / max(batch_ms / 1000.0, 1e-6)
            real_tok = 0
            if self.backend == "mlx":
                real_tok = int(getattr(self, "_last_batch_tokens", 0) or 0)
            else:
                try:
                    fe = self._fe_model
                    inner = getattr(fe, "model", fe) if fe is not None else None
                    tok = getattr(inner, "tokenizer", None) if inner is not None else None
                    if tok is not None:
                        real_tok = sum(int(sum(enc.attention_mask)) for enc in tok.encode_batch(batch))
                except Exception:  # noqa: BLE001
                    real_tok = max(1, sum(len(t) for t in batch) // 4)
            wall_s = max(batch_ms / 1000.0, 1e-6)
            tok_ps = real_tok / wall_s
            self._embed_token_total = int(getattr(self, "_embed_token_total", 0)) + real_tok
            n_forwards += 1
            if (self._accel and getattr(self._accel, "profile", None) == "coreml") or self.device == "coreml":
                from pipeline.coreml_mac import COREML_STATIC_BATCH, COREML_STATIC_SEQ

                gpu_tok_total += COREML_STATIC_BATCH * COREML_STATIC_SEQ
            else:
                gpu_tok_total += real_tok
            if progress:
                progress(n_cached + min(start + bs, len(pending_text)), len(texts))
            if not progress and _diag_on() and (
                start == 0
                or (start // max(bs, 1)) % 5 == 0
                or start + bs >= len(pending_text)
            ):
                print(
                    f"[embed] {done_new}/{len(pending_text)} new "
                    f"(+{len(encoded)-done_new} cached) "
                    f"{rate:.2f} chunk/s {tok_ps:.0f} tok/s "
                    f"batch_ms={batch_ms:.0f} bs={bs} device={self.device}"
                    + (
                        f" seq={getattr(self, '_last_batch_seq', '?')}"
                        if self.backend == "mlx"
                        else ""
                    ),
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
        # The .jsonl append above already persists every new row. The .npz is
        # only a load-time snapshot, and rewriting it re-compresses the *whole*
        # cache (~1.5s at 10k entries) — paid on every agent save. Refresh it only
        # for batches big enough to matter; _load_cache replays the log tail.
        snapshot_min = int(os.environ.get("CTX_EMBED_NPZ_MIN_NEW", "64") or "64")
        if len(pending_text) >= max(1, snapshot_min):
            try:
                self.save_cache_npz()
            except Exception:  # noqa: BLE001
                pass

        rows = [encoded[i] for i in range(len(texts))]
        matrix = np.stack(rows, axis=0)
        self.dim = int(matrix.shape[1])
        elapsed = time.perf_counter() - t_all
        tok_total = int(getattr(self, "_embed_token_total", 0) or 0)
        self._embed_token_total = 0
        self._last_stats = {
            "total": len(texts),
            "cached": len(texts) - len(pending_text),
            "embedded": len(pending_text),
            "seconds": round(elapsed, 2),
            "chunk_per_s": round(len(pending_text) / max(elapsed, 1e-6), 2),
            "tokens": tok_total,
            "tok_per_s": round(tok_total / max(elapsed, 1e-6), 1),
            "gpu_tok_per_s": round(gpu_tok_total / max(elapsed, 1e-6), 1),
            "forwards": n_forwards,
            "device": self.device,
            "batch_size": bs,
            "backend": self.backend,
            "timings_s": {k: round(v, 4) for k, v in (self._mlx_timings or {}).items()},
        }
        if not progress and _diag_on():
            print(
                f"[embed] done: {self._last_stats['embedded']} new / {self._last_stats['cached']} cached "
                f"in {elapsed:.1f}s ({self._last_stats['chunk_per_s']:.2f} chunk/s, "
                f"{self._last_stats['tok_per_s']:.0f} content tok/s, "
                f"{self._last_stats['gpu_tok_per_s']:.0f} GPU tok/s) on {self.device}",
                file=sys.stderr,
                flush=True,
            )
            if self.backend == "mlx" and self._mlx_timings:
                parts = " ".join(
                    f"{k}={v:.3f}s" for k, v in sorted(self._mlx_timings.items())
                )
                print(f"[embed] mlx breakdown: {parts}", file=sys.stderr, flush=True)
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
