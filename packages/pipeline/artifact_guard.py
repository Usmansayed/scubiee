"""Atomic artifact writes and checksum manifests for CE index publication."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Iterable


MANIFEST_NAME = "publication_manifest.json"


def atomic_write_text(
    path: Path,
    text: str,
    *,
    lock_dir: Path | None = None,
) -> None:
    """Replace a text artifact atomically using a same-directory temporary file."""
    if lock_dir is not None:
        from pipeline.store_lock import store_write_lock

        with store_write_lock(lock_dir):
            _atomic_write_text_unlocked(path, text)
        return
    _atomic_write_text_unlocked(path, text)


def _atomic_write_text_unlocked(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _atomic_replace(Path(temp_name), path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _atomic_replace(src: Path, dst: Path) -> None:
    """os.replace with retries — Windows denies rename when readers hold dst open."""
    last_exc: OSError | None = None
    for attempt in range(30):
        try:
            src.replace(dst)
            return
        except OSError as exc:
            last_exc = exc
            winerr = getattr(exc, "winerror", None)
            if winerr not in (5, 32) and exc.errno not in (13, 16):
                raise
            if attempt < 29:
                time.sleep(min(0.25 * (attempt + 1), 2.0))
    if last_exc is not None:
        raise last_exc


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publish_manifest(store: Path, files: Iterable[Path]) -> dict[str, object]:
    """Publish checksums for an already-written coherent set of artifacts.

    Holds the store write lock for the whole checksum+rename so readers never
    observe a mid-window mismatch between mutated files and a stale manifest.
    """
    from pipeline.store_lock import store_write_lock

    store = store.resolve()
    with store_write_lock(store):
        artifacts = {}
        for path in files:
            resolved = path.resolve()
            artifacts[resolved.relative_to(store).as_posix()] = _checksum(resolved)
        payload = {"version": 1, "artifacts": artifacts}
        # Already under lock — skip nested lock in atomic_write_text.
        atomic_write_text(
            store / MANIFEST_NAME,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            lock_dir=None,
        )
        return payload


def invalidate_manifest(store: Path) -> None:
    """Drop publication so readiness fails closed during a rewrite."""
    from pipeline.store_lock import store_write_lock

    store = store.resolve()
    path = store / MANIFEST_NAME
    with store_write_lock(store):
        path.unlink(missing_ok=True)


def validate_manifest(store: Path) -> dict[str, object]:
    """Validate the current published artifact set; fail closed on corruption."""
    store = store.resolve()
    path = store / MANIFEST_NAME
    if not path.is_file():
        return {"ok": False, "reason": "manifest_missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        artifacts = payload["artifacts"]
        if not isinstance(artifacts, dict):
            raise ValueError("artifacts must be an object")
    except (OSError, ValueError, json.JSONDecodeError, KeyError):
        return {"ok": False, "reason": "manifest_invalid"}
    for relative, expected in artifacts.items():
        artifact = store / str(relative)
        if not artifact.is_file():
            return {"ok": False, "reason": "artifact_missing", "artifact": relative}
        if _checksum(artifact) != expected:
            return {"ok": False, "reason": "checksum_mismatch", "artifact": relative}
    return {"ok": True, "artifacts": sorted(artifacts)}


def republish_manifest_if_coherent(store: Path) -> dict[str, object]:
    """Rewrite publication checksums when on-disk artifacts look consistent.

    Used after a kill mid-write left a stale manifest but chunks/graph/meta and
    the vector collection still agree — avoids a multi-minute full reindex on
    every MCP attach.
    """
    store = Path(store).resolve()
    report = validate_manifest(store) if (store / MANIFEST_NAME).is_file() else {
        "ok": False,
        "reason": "manifest_missing",
    }
    if report.get("ok"):
        return {"ok": True, "republished": False, "reason": "already_valid"}
    reason = str(report.get("reason") or "")
    if reason not in {"checksum_mismatch", "manifest_invalid", "manifest_missing"}:
        return {"ok": False, "republished": False, "reason": reason}

    required = ["chunks.jsonl", "graph.json", "meta.json", "merkle.json"]
    missing = [name for name in required if not (store / name).is_file()]
    if missing:
        return {"ok": False, "republished": False, "reason": "artifact_missing", "missing": missing}

    try:
        meta = json.loads((store / "meta.json").read_text(encoding="utf-8"))
        n_meta = int(meta.get("chunks") or 0)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "republished": False, "reason": f"meta_unreadable:{exc}"}
    if n_meta <= 0:
        return {"ok": False, "republished": False, "reason": "meta_zero_chunks"}

    # Cheap line count vs meta — refuse republish on obvious mixed generations.
    # Off-by-one/few from a kill mid-append is common; sync meta and republish
    # instead of forcing a multi-minute full reindex that blows the warm SLA.
    try:
        with (store / "chunks.jsonl").open("r", encoding="utf-8", errors="replace") as handle:
            n_lines = sum(1 for line in handle if line.strip())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "republished": False, "reason": f"chunks_unreadable:{exc}"}
    drift = abs(n_lines - n_meta)
    sync_meta = False
    if n_lines != n_meta:
        # Tolerate tiny drift (append race / trailing newline) — not a mixed generation.
        max_drift = max(2, int(max(n_meta, n_lines) * 0.001))
        if n_lines <= 0 or drift > max_drift:
            return {
                "ok": False,
                "republished": False,
                "reason": "chunk_count_mismatch",
                "meta_chunks": n_meta,
                "chunk_lines": n_lines,
            }
        sync_meta = True
        meta["chunks"] = n_lines
        try:
            atomic_write_text(
                store / "meta.json",
                json.dumps(meta, indent=2, sort_keys=True) + "\n",
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "republished": False,
                "reason": f"meta_sync_failed:{exc}",
                "meta_chunks": n_meta,
                "chunk_lines": n_lines,
            }

    files = [store / name for name in required]
    graph_ir = store / "graph_ir.json"
    if graph_ir.is_file():
        files.append(graph_ir)
    try:
        payload = publish_manifest(store, files)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "republished": False, "reason": f"publish_failed:{exc}"}
    check = validate_manifest(store)
    if not check.get("ok"):
        return {"ok": False, "republished": False, "reason": "still_invalid", "check": check}
    return {
        "ok": True,
        "republished": True,
        "reason": reason,
        "synced_meta_chunks": sync_meta,
        "chunks": n_lines,
        "artifacts": list((payload.get("artifacts") or {}).keys()),
    }


def heal_checksum_mismatch(store: Path, *, root: Path | None = None) -> dict[str, object]:
    """One-shot auto-heal: rebuild index when publication checksums disagree.

    Does **not** drop the bad manifest up front — that would make
    ``index_is_usable`` pass (legacy no-manifest) and let load_engine read
    a mixed generation. Rebuild path invalidates+publishes under lock.
    """
    store = Path(store).resolve()
    report = validate_manifest(store) if (store / MANIFEST_NAME).is_file() else {
        "ok": False,
        "reason": "manifest_missing",
    }
    reason = str(report.get("reason") or "")
    if report.get("ok"):
        return {"ok": True, "healed": False, "reason": "already_valid"}
    if reason not in {"checksum_mismatch", "artifact_missing", "manifest_invalid"}:
        return {"ok": False, "healed": False, "reason": reason or "unusable"}

    repo = Path(root).resolve() if root is not None else None
    if repo is None:
        try:
            meta = json.loads((store / "meta.json").read_text(encoding="utf-8"))
            cand = meta.get("root") or meta.get("repo")
            if cand:
                repo = Path(str(cand)).expanduser().resolve()
        except Exception:  # noqa: BLE001
            repo = None
    if repo is None or not repo.is_dir():
        return {
            "ok": False,
            "healed": False,
            "reason": reason,
            "state": "error",
            "hint": "checksum corrupt; run scubiee index .",
            "repair": ["scubiee index .", "scubiee doctor"],
        }

    try:
        from pipeline.indexer import index_repo

        prev = os.environ.get("CTX_QUIET")
        os.environ["CTX_QUIET"] = "1"
        try:
            index_repo(repo, force=True)
        finally:
            if prev is None:
                os.environ.pop("CTX_QUIET", None)
            else:
                os.environ["CTX_QUIET"] = prev
        if (store / MANIFEST_NAME).is_file() and not validate_manifest(store).get("ok"):
            return {
                "ok": False,
                "healed": False,
                "reason": reason,
                "state": "error",
                "error": "rebuild_left_invalid_manifest",
                "repair": ["scubiee index .", "scubiee doctor"],
            }
        return {"ok": True, "healed": True, "reason": reason, "state": "ready", "repo": str(repo)}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "healed": False,
            "reason": reason,
            "state": "error",
            "error": str(exc),
            "repo": str(repo),
            "repair": ["scubiee index .", "scubiee doctor"],
        }
