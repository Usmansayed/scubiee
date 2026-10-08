"""Workload classifier — is pending index work small (silent) or substantial?

Spec: ``.kiro/specs/indexing-state-model/design.md`` (component C3).

The agent is told about pending indexing ONLY when the work is genuinely
minutes-scale. The threshold is a wall-clock TIME, not a file count, so it
self-adjusts to machine speed: a fast GPU silently absorbs more work.

Cost model (``estimate_units`` ≈ chunks to embed, the dominant cost):
  * existing (modified) files  -> their EXACT indexed chunk count (chunk_merkle),
  * new (added) files          -> a line-based estimate (~1 chunk / 25 lines),
  * removed files              -> ~0 units (a tombstone, not an embed),
  * each weighted by file type (code ≈ 1.0, docs ≈ 0.5, config ≈ 0.3,
    vendored / binary ≈ 0 — never indexed).

``estimated_seconds = units / embed_throughput`` where throughput (chunks/sec)
is measured from recent embed stages and persisted; a conservative default is
used until a real measurement exists so an unmeasured engine never UNDER-flags.

``substantial`` iff:
  * estimated_seconds >= CTX_SUBSTANTIAL_SECONDS (default 25), OR
  * a full / forced reindex is required, OR
  * drift covers >= CTX_SUBSTANTIAL_FRACTION of the corpus (default 0.4).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

# ---- tunables (env-overridable) ---------------------------------------------

def substantial_seconds() -> float:
    raw = (os.environ.get("CTX_SUBSTANTIAL_SECONDS") or "25").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 25.0


def substantial_fraction() -> float:
    raw = (os.environ.get("CTX_SUBSTANTIAL_FRACTION") or "0.4").strip()
    try:
        return min(1.0, max(0.01, float(raw)))
    except ValueError:
        return 0.4


# Conservative default embed throughput (chunks/sec) until measured. Low on
# purpose: unmeasured must never make a big batch look small.
DEFAULT_THROUGHPUT_CHUNKS_PER_S = float(os.environ.get("CTX_DEFAULT_EMBED_CPS") or "20")

# ---- file-type weighting ----------------------------------------------------

_CODE_EXT = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".cs", ".cpp", ".cc", ".c", ".h", ".hpp", ".rb", ".php", ".swift", ".scala",
    ".m", ".mm", ".sh", ".bash", ".ps1", ".sql", ".lua", ".dart", ".ex", ".exs",
}
_DOC_EXT = {".md", ".mdx", ".rst", ".txt", ".adoc"}
_CONFIG_EXT = {".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".xml", ".env"}


def file_type_weight(rel: str) -> float:
    """Relative embed cost of a file by extension (0 = not indexed)."""
    suf = Path(rel).suffix.lower()
    if suf in _CODE_EXT:
        return 1.0
    if suf in _DOC_EXT:
        return 0.5
    if suf in _CONFIG_EXT:
        return 0.3
    # unknown / binary / vendored: effectively free (not embedded)
    return 0.0


# ---- throughput measurement -------------------------------------------------

def throughput_chunks_per_s(store: Any | None = None) -> float:
    """Measured embed throughput (chunks/sec), or a conservative default.

    Reads a persisted running average from meta.json (key ``embed_cps``) when a
    store is available; falls back to the conservative default so an engine that
    has never measured never under-flags a large batch.
    """
    if store is not None:
        try:
            meta = store.load_meta()
            cps = float(meta.get("embed_cps") or 0.0)
            if cps > 0.0:
                return cps
        except Exception:  # noqa: BLE001
            pass
    return DEFAULT_THROUGHPUT_CHUNKS_PER_S


def record_embed_throughput(store: Any, *, chunks: int, seconds: float) -> None:
    """Fold a measured embed stage into the persisted running average.

    Best-effort: a bad write never affects indexing. Uses an exponential moving
    average so a single slow/fast batch does not whipsaw the estimate.
    """
    if store is None or chunks <= 0 or seconds <= 0.0:
        return
    sample = float(chunks) / float(seconds)
    # Ignore implausible samples (tiny batches dominated by fixed overhead).
    if chunks < 8 or sample <= 0.0 or sample > 100000.0:
        return
    try:
        meta = store.load_meta()
        prev = float(meta.get("embed_cps") or 0.0)
        alpha = 0.3
        new = sample if prev <= 0.0 else (alpha * sample + (1 - alpha) * prev)
        meta["embed_cps"] = round(new, 2)
        store.save_meta(meta)
    except Exception:  # noqa: BLE001
        pass


# ---- unit estimation --------------------------------------------------------

def _line_estimate(repo: Path, rel: str) -> int:
    """Chunk estimate for a NEW file (no indexed count yet): ~1 chunk / 25 lines."""
    p = repo / rel
    try:
        if not p.is_file():
            return 0
        lines = sum(1 for _ in p.open("r", encoding="utf-8", errors="ignore"))
    except OSError:
        return 0
    return max(1, min(2000, (lines + 24) // 25))


def estimate_units(
    added: list[str],
    modified: list[str],
    removed: list[str],
    *,
    repo: Path,
    store: Any | None = None,
) -> int:
    """Estimated embed units for a drift set (weighted chunks). Removed ≈ 0."""
    repo = Path(repo)
    # Exact per-file chunk counts for already-indexed files.
    existing_counts: dict[str, int] = {}
    if store is not None:
        try:
            from pipeline.sync_loop import count_chunks_per_file

            existing_counts = count_chunks_per_file(store.chunks_path)
        except Exception:  # noqa: BLE001
            existing_counts = {}

    units = 0.0
    for rel in modified:
        w = file_type_weight(rel)
        if w <= 0.0:
            continue
        base = existing_counts.get(rel.replace("\\", "/"))
        base = base if base and base > 0 else _line_estimate(repo, rel)
        units += w * base
    for rel in added:
        w = file_type_weight(rel)
        if w <= 0.0:
            continue
        units += w * _line_estimate(repo, rel)
    # removed files: pruning a tombstone is ~free; count a flat tiny cost so a
    # massive delete still registers as *some* work but never looks substantial
    # on deletions alone.
    units += 0.0 * len(removed)
    return int(round(units))


# ---- classification ---------------------------------------------------------

def classify_workload(
    added: list[str],
    modified: list[str],
    removed: list[str],
    *,
    repo: Path,
    store: Any | None = None,
    corpus_size: int = 0,
    full_reindex: bool = False,
    reason_hint: str = "",
) -> "Any":
    """Return a PendingSummary. ``substantial`` iff minutes-scale / full / big-fraction."""
    from pipeline.index_state import PendingSummary

    units = estimate_units(added, modified, removed, repo=repo, store=store)
    cps = throughput_chunks_per_s(store)
    est_seconds = (units / cps) if cps > 0 else float(units)

    budget = substantial_seconds()
    frac = substantial_fraction()
    corpus_frac = (units / corpus_size) if corpus_size > 0 else 0.0

    substantial = bool(
        full_reindex
        or est_seconds >= budget
        or (corpus_size > 0 and corpus_frac >= frac)
    )

    if full_reindex:
        reason = "full_reindex"
        action = "scubiee index . --force"
    elif reason_hint:
        reason = reason_hint
    elif corpus_size > 0 and corpus_frac >= frac:
        reason = "bulk_paste"
        action = None
    else:
        reason = "offline_batch" if substantial else "incremental"
        action = None

    total = len(added) + len(modified) + len(removed)
    return PendingSummary(
        substantial=substantial,
        reason=reason,
        estimated_units=units,
        estimated_seconds=round(est_seconds, 1),
        done_units=0,
        total_units=total,
        search_usable=True,  # the current generation keeps serving during reconcile
        action=(action if full_reindex else None),
        detected_at=time.time(),
    )
