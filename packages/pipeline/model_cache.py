"""Where the CodeRank weights live.

fastembed's ``define_cache_dir`` defaults to ``$TMPDIR/fastembed_cache``. When the OS
sweeps temp the blobs go but the Hugging Face snapshot metadata stays, so nothing
re-downloads and the embedder silently falls back to hash vectors.

``TextEmbedding`` resolves the directory itself at load time and several call sites
(preflight warmup, accel calibration) don't pass ``cache_dir``, so the choice has to be
in the environment before anything imports fastembed. Kept dependency-free so
``pipeline/__init__`` can pin it at import.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Honored before the default, so an operator can still place the cache themselves.
CACHE_ENV_KEYS = ("FASTEMBED_CACHE", "FASTEMBED_CACHE_PATH")


def default_fastembed_cache_root() -> Path:
    """Durable model cache root.

    Anchored to the real home rather than ``CTX_HOME``: tests point ``CTX_HOME`` at
    temp dirs, and a cache that moved with it would re-download the model every run.
    """
    for key in CACHE_ENV_KEYS:
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return Path(raw)
    return Path.home() / ".cache" / "fastembed"


def pin_fastembed_cache_env() -> Path:
    """Publish the durable root so fastembed's own resolution agrees with ours."""
    root = default_fastembed_cache_root()
    os.environ.setdefault("FASTEMBED_CACHE_PATH", str(root))
    return root
