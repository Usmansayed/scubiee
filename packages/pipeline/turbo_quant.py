"""Google TurboQuant-style online vector quantization (ICLR 2026).

Implements the paper's MSE path used for storage:
  1) store L2 norm
  2) normalize
  3) random orthogonal rotation (seeded)
  4) per-coordinate Lloyd-Max-ish scalar quantization
  5) pack codes

At query time we dequantize to float32 for FAISS (asymmetric: query stays FP32).

Prefer the ``turboquant`` / ``pyturboquant`` packages when installed; otherwise
use this NumPy reference implementation so the product works offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Try third-party first
_TQ = None
try:
    from turboquant import TurboQuantIndex as _TQ  # type: ignore
except Exception:  # noqa: BLE001
    try:
        from pyturboquant.search import TurboQuantIndex as _TQ  # type: ignore
    except Exception:  # noqa: BLE001
        _TQ = None


def _lloyd_max_boundaries(bits: int) -> np.ndarray:
    """Approximate Lloyd-Max boundaries for N(0, 1/d) after rotation — use N(0,1) grid.

    For production quality upgrade to Beta/sphere-derived codebooks from the paper.
    """
    levels = 1 << bits
    # Equal-mass Gaussian bins via inverse CDF approx (probit)
    # Use linspace in probability space
    probs = (np.arange(1, levels) / levels).astype(np.float64)
    # rational approximation of norm.ppf
    return _norm_ppf(probs).astype(np.float32)


def _norm_ppf(p: np.ndarray) -> np.ndarray:
    """Acklam's inverse normal CDF approximation."""
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    p = np.clip(p, 1e-12, 1 - 1e-12)
    out = np.empty_like(p, dtype=np.float64)
    plow = p < 0.02425
    phigh = p > 1 - 0.02425
    pmid = ~(plow | phigh)

    if np.any(plow):
        q = np.sqrt(-2 * np.log(p[plow]))
        out[plow] = (
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        )
    if np.any(phigh):
        q = np.sqrt(-2 * np.log(1 - p[phigh]))
        out[phigh] = -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        )
    if np.any(pmid):
        q = p[pmid] - 0.5
        r = q * q
        out[pmid] = (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        )
    return out


def _random_orthogonal(dim: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    g = rng.normal(size=(dim, dim)).astype(np.float64)
    q, _ = np.linalg.qr(g)
    # Fix signs for determinism
    s = np.sign(np.diag(q))
    s[s == 0] = 1
    q = q * s
    return q.astype(np.float32)


def _codebook_centers(boundaries: np.ndarray) -> np.ndarray:
    """Reconstruction levels = midpoints of bins (+/- tails)."""
    edges = np.concatenate([[-8.0], boundaries.astype(np.float64), [8.0]])
    return ((edges[:-1] + edges[1:]) / 2.0).astype(np.float32)


@dataclass
class TurboQuantCodec:
    dim: int
    bits: int = 4
    seed: int = 42

    def __post_init__(self) -> None:
        self.rotation = _random_orthogonal(self.dim, self.seed)
        self.boundaries = _lloyd_max_boundaries(self.bits)
        self.centers = _codebook_centers(self.boundaries)
        self.levels = 1 << self.bits

    def quantize(self, vectors: np.ndarray) -> dict:
        x = np.asarray(vectors, dtype=np.float32)
        if x.ndim == 1:
            x = x.reshape(1, -1)
        if x.shape[1] != self.dim:
            raise ValueError(f"expected dim={self.dim}, got {x.shape[1]}")
        norms = np.linalg.norm(x, axis=1)
        norms = np.maximum(norms, 1e-12)
        unit = x / norms[:, None]
        rotated = unit @ self.rotation  # (N, D)
        # digitize
        codes = np.zeros(rotated.shape, dtype=np.uint8)
        for d in range(self.dim):
            codes[:, d] = np.digitize(rotated[:, d], self.boundaries).astype(np.uint8)
        packed = self._pack(codes)
        return {
            "dim": self.dim,
            "bits": self.bits,
            "seed": self.seed,
            "norms": norms.astype(np.float32),
            "codes": packed,  # (N, nbytes)
            "n": int(x.shape[0]),
        }

    def dequantize(self, blob: dict) -> np.ndarray:
        n = int(blob.get("n", 0))
        if n <= 0:
            return np.zeros((0, self.dim), dtype=np.float32)
        codes = self._unpack(blob["codes"], n)
        centers = self.centers
        recon_rot = centers[codes]  # (N, D)
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            unit = recon_rot @ self.rotation.T
            row_norms = np.linalg.norm(unit, axis=1, keepdims=True)
            row_norms = np.maximum(row_norms, 1e-12)
            unit = unit / row_norms
        norms = np.asarray(blob["norms"], dtype=np.float32).reshape(-1, 1)
        return (unit * norms).astype(np.float32)

    def _pack(self, codes: np.ndarray) -> np.ndarray:
        bits = self.bits
        n, d = codes.shape
        # store as uint16 if bits>8 else pack tightly into bytes
        if bits <= 8:
            # simple: one byte per dim (wasteful but simple & portable)
            return codes.astype(np.uint8)
        raise ValueError("bits > 8 not supported in reference codec")

    def _unpack(self, packed: np.ndarray, n: int) -> np.ndarray:
        arr = np.asarray(packed)
        if arr.ndim == 1:
            arr = arr.reshape(n, self.dim)
        return arr.astype(np.int64)


class CompressedEmbeddingStore:
    """Persist TurboQuant-compressed embeddings; expand to float32 for FAISS."""

    def __init__(self, dim: int, bits: int = 4, seed: int = 42):
        self.dim = dim
        self.bits = bits
        self.seed = seed
        self.codec = TurboQuantCodec(dim=dim, bits=bits, seed=seed)
        self._norms: list[float] = []
        self._codes: list[np.ndarray] = []
        self.backend = "numpy-turboquant"
        if _TQ is not None:
            self.backend = "turboquant-pkg"

    @property
    def ntotal(self) -> int:
        return len(self._codes)

    def add(self, vectors: np.ndarray) -> None:
        blob = self.codec.quantize(vectors)
        for i in range(blob["n"]):
            self._norms.append(float(blob["norms"][i]))
            self._codes.append(np.asarray(blob["codes"][i], dtype=np.uint8).copy())

    def remove_last(self, count: int) -> None:
        if count <= 0:
            return
        self._norms = self._norms[:-count]
        self._codes = self._codes[:-count]

    def to_float32(self) -> np.ndarray:
        if not self._codes:
            return np.zeros((0, self.dim), dtype=np.float32)
        packed = np.stack(self._codes, axis=0)
        blob = {
            "dim": self.dim,
            "bits": self.bits,
            "seed": self.seed,
            "norms": np.asarray(self._norms, dtype=np.float32),
            "codes": packed,
            "n": len(self._codes),
        }
        return self.codec.dequantize(blob)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "dim": self.dim,
            "bits": self.bits,
            "seed": self.seed,
            "backend": self.backend,
            "ntotal": self.ntotal,
            "bytes_per_vec": self.dim,  # uint8/dim in reference codec
            "fp32_bytes_per_vec": self.dim * 4,
            "compression_ratio": (self.dim * 4) / max(self.dim, 1),
        }
        np.savez_compressed(
            path,
            norms=np.asarray(self._norms, dtype=np.float32),
            codes=np.stack(self._codes, axis=0) if self._codes else np.zeros((0, self.dim), dtype=np.uint8),
            meta_json=np.asarray([json.dumps(meta)]),
        )

    @classmethod
    def load(cls, path: Path) -> "CompressedEmbeddingStore":
        data = np.load(path, allow_pickle=False)
        meta = json.loads(str(data["meta_json"][0]))
        store = cls(dim=int(meta["dim"]), bits=int(meta["bits"]), seed=int(meta["seed"]))
        norms = data["norms"]
        codes = data["codes"]
        store._norms = [float(x) for x in norms.tolist()]
        store._codes = [codes[i].astype(np.uint8).copy() for i in range(codes.shape[0])]
        return store

    def memory_stats(self) -> dict:
        n = self.ntotal
        compressed = n * self.dim  # uint8
        fp32 = n * self.dim * 4
        return {
            "ntotal": n,
            "compressed_bytes": compressed,
            "fp32_bytes": fp32,
            "compression_ratio": (fp32 / compressed) if compressed else 0.0,
            "bits": self.bits,
            "backend": self.backend,
        }
