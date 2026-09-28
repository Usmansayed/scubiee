"""Graph catch-up off the keeper (issue 6).

A graph catch-up is a whole-graph ``build_merge(dedup=True)`` plus a 20MB JSON
export: 10-15s of pure-Python CPU on this repo. Run on the keeper thread, every
save that lands meanwhile waits for it; run on a second thread, it holds the GIL
against the save. So the merge runs in a short-lived, below-normal-priority
child process that writes the merged graph to a temp file next to graph.json.
The keeper only commits it: a rename plus the usual merkle/publication refresh.

The commit is optimistic: the job records graph.json's (size, mtime_ns) at
start, and the keeper discards the result if anything else rewrote graph.json
in between (a non-hot sync patches it synchronously), re-queueing the paths.

    python -m pipeline.graph_merge_worker --root R --graph G --out O --result J --paths-file P
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_TMP_PREFIX = ".graph_catchup."
_STALE_TMP_AGE_S = 600.0

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
CREATE_NO_WINDOW = 0x08000000


def async_enabled() -> bool:
    raw = (os.environ.get("CTX_GRAPH_CATCHUP_ASYNC") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def file_stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (int(st.st_size), int(st.st_mtime_ns))


def sweep_stale_temps(store_base: Path, *, now: float | None = None) -> list[str]:
    """Delete merge outputs and ``write_json_atomic`` temps left by a dead process."""
    current = time.time() if now is None else now
    removed: list[str] = []
    patterns = (f"{_TMP_PREFIX}*", ".graph.json.*.tmp")
    for pattern in patterns:
        for p in store_base.glob(pattern):
            try:
                if current - p.stat().st_mtime < _STALE_TMP_AGE_S:
                    continue
                p.unlink()
                removed.append(p.name)
            except OSError:
                continue
    return removed


@dataclass
class GraphMergeJob:
    """One in-flight child merge. ``poll()`` is non-blocking."""

    paths: list[str]
    out: Path
    result_path: Path
    graph_json: Path
    graph_stamp: tuple[int, int] | None
    started_at: float
    proc: subprocess.Popen | None = None
    log_path: Path | None = None
    _log_fh: object | None = field(default=None, repr=False)

    def poll(self) -> dict | None:
        if self.proc is None:
            return {"ok": False, "error": "not started"}
        if self.proc.poll() is None:
            return None
        self._close_log()
        info: dict = {}
        try:
            info = json.loads(self.result_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            info = {"ok": False, "error": f"no result ({exc!r}) rc={self.proc.returncode}"}
        if self.proc.returncode != 0:
            info["ok"] = False
            info.setdefault("error", f"rc={self.proc.returncode}")
        if info.get("ok") and not self.out.is_file():
            info = {"ok": False, "error": "merged graph missing"}
        info["wall_ms"] = round((time.monotonic() - self.started_at) * 1000)
        return info

    def graph_unchanged(self) -> bool:
        return self.graph_stamp is not None and file_stamp(self.graph_json) == self.graph_stamp

    def kill(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
        self._close_log()
        self.discard()

    def discard(self) -> None:
        for p in (self.out, self.result_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    def _close_log(self) -> None:
        fh = self._log_fh
        self._log_fh = None
        if fh is not None:
            try:
                fh.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass


def _package_roots() -> list[str]:
    """Directories that hold the ``pipeline`` and ``graphify`` packages."""
    roots: list[str] = []
    for mod in ("pipeline", "graphify"):
        try:
            m = __import__(mod)
            parent = str(Path(m.__file__).resolve().parent.parent)
        except Exception:  # noqa: BLE001
            continue
        if parent not in roots:
            roots.append(parent)
    return roots


def start_graph_merge(
    root: Path,
    store_base: Path,
    paths: list[str],
    *,
    prune: list[str] | None = None,
) -> GraphMergeJob:
    """Spawn the child merge for ``paths`` (repo-relative) against graph.json."""
    sweep_stale_temps(store_base)
    graph_json = store_base / "graph.json"
    token = f"{os.getpid()}.{time.time_ns()}"
    out = store_base / f"{_TMP_PREFIX}{token}.json"
    result_path = store_base / f"{_TMP_PREFIX}{token}.result"
    paths_file = store_base / f"{_TMP_PREFIX}{token}.paths"
    paths_file.write_text(json.dumps({"paths": paths, "prune": prune or []}), encoding="utf-8")
    job = GraphMergeJob(
        paths=list(paths),
        out=out,
        result_path=result_path,
        graph_json=graph_json,
        graph_stamp=file_stamp(graph_json),
        started_at=time.monotonic(),
        log_path=store_base / "graph_catchup_worker.log",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(_package_roots())
    env["GRAPHIFY_QUIET"] = "1"
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env["CTX_SCUBIEE_ROLE"] = "graph_worker"
    cmd = [
        sys.executable,
        "-m",
        "pipeline.graph_merge_worker",
        "--root",
        str(root),
        "--graph",
        str(graph_json),
        "--out",
        str(out),
        "--result",
        str(result_path),
        "--paths-file",
        str(paths_file),
    ]
    kwargs: dict = {"env": env, "stdin": subprocess.DEVNULL, "cwd": str(store_base)}
    try:
        job._log_fh = open(job.log_path, "w", encoding="utf-8")  # noqa: SIM115
        kwargs["stdout"] = job._log_fh
        kwargs["stderr"] = subprocess.STDOUT
    except OSError:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    if os.name == "nt":
        # Below-normal so the save the user is waiting on wins every core fight.
        kwargs["creationflags"] = BELOW_NORMAL_PRIORITY_CLASS | CREATE_NO_WINDOW
    else:
        kwargs["preexec_fn"] = lambda: os.nice(10)  # noqa: PLW0108
    job.proc = subprocess.Popen(cmd, **kwargs)
    return job


def _run(args: argparse.Namespace) -> dict:
    t0 = time.perf_counter()
    root = Path(args.root).resolve()
    graph_json = Path(args.graph)
    spec = json.loads(Path(args.paths_file).read_text(encoding="utf-8"))
    rels = [str(p) for p in spec.get("paths") or []]
    files = [root / r for r in rels if (root / r).is_file()]
    # A catch-up for a file deleted since its save must drop the file's nodes;
    # nothing else ever prunes them once the hot delete has left the Merkle.
    gone = [r for r in rels if not (root / r).is_file()]
    prune = sorted({str(p) for p in spec.get("prune") or []} | set(gone)) or None

    from graphify.build import build_merge
    from graphify.export import to_json
    from graphify.extract import extract

    t = time.perf_counter()
    raw = extract(files, root=root, cache_root=graph_json.parent) if files else {}
    extract_ms = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    G = build_merge(
        [raw] if raw else [{}],
        graph_path=graph_json,
        prune_sources=prune,
        directed=False,
        dedup=True,
        root=root,
    )
    merge_ms = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    if not to_json(G, {}, str(args.out), force=True):
        raise RuntimeError("graph export refused")
    export_ms = (time.perf_counter() - t) * 1000
    return {
        "ok": True,
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "files": len(files),
        "extract_ms": round(extract_ms),
        "merge_ms": round(merge_ms),
        "export_ms": round(export_ms),
        "ms": round((time.perf_counter() - t0) * 1000),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--graph", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--result", required=True)
    ap.add_argument("--paths-file", required=True)
    args = ap.parse_args(argv)
    try:
        info = _run(args)
        rc = 0
    except BaseException as exc:  # noqa: BLE001
        info = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        rc = 1
        try:
            Path(args.out).unlink(missing_ok=True)
        except OSError:
            pass
    finally:
        try:
            Path(args.paths_file).unlink(missing_ok=True)
        except OSError:
            pass
    tmp = Path(args.result + ".part")
    tmp.write_text(json.dumps(info), encoding="utf-8")
    os.replace(tmp, args.result)
    print(json.dumps(info), flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
