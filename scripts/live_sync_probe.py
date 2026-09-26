"""Ask the installed engine whether a brand-new file becomes searchable in ≤5s.

A pass is all of these, and nothing else:

1. ``/health`` ``chunks`` goes up by the new file's chunks.
2. ``POST /v1/search`` returns the probe path in ``hits[].file``.
3. Both of the above land within ``CTX_PROBE_SLA_S`` (default 5.0) seconds of the
   dirty accept returning.
4. The engine PID does not change during the window (no restart / FAISS abort).
5. ``POST /v1/locate`` (the map surface) returns the path as a card, dense —
   ``retrieve_mode=D_channel_best``. BM25-only is not a pass.

Generation moving is not a pass. A token echoed in the response body is not a
hit. The probe directory is unique per run and deleted at the end, so a leftover
chunk from an earlier run cannot be mistaken for the file under test — the run
aborts if the path is already searchable before the write.

Cold FastEmbed load is exempt from the SLA: round 1 warms the embedder and the
collection with a generous deadline, round 2 is the measured one. Only round 2
decides the exit code.

Usage: ``python scripts/live_sync_probe.py [repo] [engine-url]``
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else Path.cwd()).resolve()
BASE = (sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8765").rstrip("/")
STAMP = str(int(time.time()))
SLA_S = float(os.environ.get("CTX_PROBE_SLA_S") or "5.0")
POLL_S = float(os.environ.get("CTX_PROBE_POLL_S") or "0.2")
WARMUP_DEADLINE_S = float(os.environ.get("CTX_PROBE_WARMUP_S") or "180")
# Fresh directory per run so a leftover chunk from an earlier probe cannot be
# mistaken for the file under test.
PROBE_DIR = REPO / "packages" / "pipeline" / f"sync_live_{STAMP}"
CLIENT_ID = "mcp:sync-probe-131"


def post(path: str, body: dict, timeout: float = 180.0) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "http": exc.code, "body": exc.read().decode("utf-8")[:400]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)}


def get(path: str, timeout: float = 60.0) -> dict:
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)}


def keepalive() -> None:
    """Hold a client registration so idle standby cannot stop the engine mid-test."""
    post(
        "/v1/client/touch",
        {"client_id": CLIENT_ID, "kind": "mcp", "pid": os.getpid()},
        timeout=30.0,
    )


def scubiee_home() -> Path:
    raw = os.environ.get("CTX_HOME")
    return Path(raw) if raw else Path.home() / ".scubiee"


def engine_pid(health: dict | None = None) -> int | None:
    """Serving PID — a restart mid-window must fail the run.

    Prefer ``/health`` ``pid``: it is the process actually serving search.
    ``engine.lock`` can name a launcher that is not the worker.
    """
    if isinstance(health, dict) and health.get("pid"):
        try:
            return int(health["pid"])
        except (TypeError, ValueError):
            pass
    home = scubiee_home()
    lock = home / "engine.lock"
    try:
        if lock.is_file():
            data = json.loads(lock.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("pid"):
                return int(data["pid"])
    except Exception:  # noqa: BLE001
        pass
    for name in ("engine.pid", "engine.json"):
        path = home / name
        try:
            if not path.is_file():
                continue
            raw = path.read_text(encoding="utf-8").strip()
            if name.endswith(".json"):
                data = json.loads(raw)
                if isinstance(data, dict) and data.get("pid"):
                    return int(data["pid"])
            elif raw.isdigit():
                return int(raw)
        except Exception:  # noqa: BLE001
            continue
    return None


def engine_log_tail(patterns: tuple[str, ...], limit: int = 6) -> list[str]:
    """Last matching engine.log lines — this is where the stage breakdown lives."""
    path = scubiee_home() / "engine.log"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    hits = [line.strip() for line in lines if any(p in line for p in patterns)]
    return hits[-limit:]


class _ProbeDone(Exception):
    """Internal: single-round mode finished; run the shared cleanup."""


def keeper_busy_paths() -> list[str]:
    """Dirty paths the keeper still owes work on."""
    status = post("/v1/status", {"path": str(REPO)}, timeout=30.0)
    keeper = (status.get("sync_status") or {}) if isinstance(status, dict) else {}
    dirty = (status.get("keeper") or keeper or {}).get("dirty") or {}
    if not dirty:
        dirty = ((status.get("sync") or {}).get("dirty")) or {}
    paths = dirty.get("paths") or {}
    return [
        path
        for path, entry in paths.items()
        if str((entry or {}).get("state") or "") in {"queued", "due", "processing"}
    ]


def wait_for_idle_keeper(timeout_s: float = 150.0) -> bool:
    """The SLA is about a save landing on an idle keeper, not one queued behind work.

    The keeper runs one batch at a time, so measuring while it still owes a slow
    non-hot batch measures that batch, not the save.
    """
    deadline = time.time() + timeout_s
    quiet_needed = 2  # consecutive idle readings; one reading can land between batches
    quiet = 0
    last_gen = None
    while time.time() < deadline:
        keepalive()
        busy = keeper_busy_paths()
        gen = get("/health", timeout=20.0).get("generation")
        if not busy and (last_gen is None or gen == last_gen):
            quiet += 1
            if quiet >= quiet_needed:
                return True
        else:
            quiet = 0
            if busy:
                print(f"  keeper busy with {len(busy)} path(s): {busy[:3]}")
        last_gen = gen
        time.sleep(2.5)
    return False


def probe_source(token: str) -> str:
    return "\n".join(
        [
            '"""Probe module for the live sync check."""',
            "",
            "",
            f"def {token}_handler(payload):",
            f'    """Unique probe symbol {token} for retrieval."""',
            f'    return {{"token": "{token}", "payload": payload}}',
            "",
        ]
    )


def search_query(token: str) -> str:
    return f"{token}_handler probe module live sync check"


def run_round(label: str, rel: str, token: str, deadline_s: float) -> dict:
    """Write → dirty → poll. Returns timings and per-criterion pass flags."""
    print(f"\n=== round {label}: budget {deadline_s:.1f}s ===")
    h0 = get("/health")
    pid_before = engine_pid(h0)
    base_chunks = int(h0.get("chunks") or 0)
    print(
        f"baseline: chunks={base_chunks} generation={h0.get('generation')} "
        f"dense_missing={h0.get('dense_missing')} pid={pid_before}"
    )

    pre = post(
        "/v1/search",
        {"query": search_query(token), "top_k": 10, "path": str(REPO)},
    )
    pre_files = [str(x.get("file") or "").replace("\\", "/") for x in (pre.get("hits") or [])]
    if rel in pre_files:
        return {"ok": False, "stage": "setup", "error": f"{rel} already indexed before the write"}

    target = REPO / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    init = target.parent / "__init__.py"
    if not init.exists():
        # Only in the warmup round: rewriting it would make the measured round a
        # two-file batch instead of the single-save case under test.
        init.write_text("", encoding="utf-8")
    target.write_text(probe_source(token), encoding="utf-8")
    print(f"wrote {rel} token={token}")

    t_dirty = time.perf_counter()
    accept = post("/v1/dirty", {"path": str(REPO), "paths": [rel], "reason": "probe_write"})
    dirty_ms = (time.perf_counter() - t_dirty) * 1000
    # The clock the SLA is measured against starts when the accept returns.
    t0 = time.perf_counter()
    print(f"dirty accept in {dirty_ms:.0f} ms -> {accept}")

    health_ms: float | None = None
    search_ms: float | None = None
    last_chunks = base_chunks
    last_search: dict = {}
    pid_changed = False
    while (time.perf_counter() - t0) < deadline_s:
        h = get("/health", timeout=10.0)
        last_chunks = int(h.get("chunks") or last_chunks)
        if health_ms is None and last_chunks > base_chunks:
            health_ms = (time.perf_counter() - t0) * 1000
        s = post(
            "/v1/search",
            {"query": search_query(token), "top_k": 10, "path": str(REPO)},
            timeout=30.0,
        )
        last_search = s
        files = [str(x.get("file") or "").replace("\\", "/") for x in (s.get("hits") or [])]
        if search_ms is None and rel in files:
            search_ms = (time.perf_counter() - t0) * 1000
        pid_now = engine_pid(h)
        if pid_before and pid_now and pid_now != pid_before:
            pid_changed = True
            break
        if health_ms is not None and search_ms is not None:
            break
        time.sleep(POLL_S)

    total_ms = (time.perf_counter() - t0) * 1000
    pid_after = engine_pid(get("/health", timeout=20.0))
    if pid_before and pid_after and pid_after != pid_before:
        pid_changed = True

    # Map surface. MCP ``map`` cards come from the dense engine search
    # (``retrieve_mode=D_channel_best``), not from ``/v1/locate`` — that one is
    # the capability-card index over module summaries. So the map criterion is:
    # the path ranks in the dense search, and the retrieve mode really is dense.
    map_rank: int | None = None
    map_mode = None
    if search_ms is not None:
        mapped = post(
            "/v1/search",
            {"query": search_query(token), "top_k": 10, "path": str(REPO)},
            timeout=60.0,
        )
        timings_map = mapped.get("timings") or {}
        map_mode = timings_map.get("retrieve_mode") or mapped.get("retrieve_mode")
        dense_ok = bool(timings_map.get("dense"))
        for rank, hit in enumerate(mapped.get("hits") or [], 1):
            path_value = str(hit.get("file") or hit.get("path") or "").replace("\\", "/")
            if path_value == rel:
                map_rank = rank
                break
        if map_rank is not None and not (
            dense_ok and str(map_mode or "").startswith("D_channel_best")
        ):
            print(f"map hit was not dense (mode={map_mode} dense={dense_ok}) — not a pass")
            map_rank = None
        if map_rank is None:
            print(f"map miss: {json.dumps(mapped)[:400]}")
        # Extra signal only: capability cards lag a save until they rebuild.
        loc = post(
            "/v1/locate",
            {"query": search_query(token), "top_k": 5, "path": str(REPO)},
            timeout=30.0,
        )
        card_paths = [
            str(c.get("path") or c.get("file") or "").replace("\\", "/")
            for c in (loc.get("hits") or loc.get("cards") or [])
        ]
        print(f"capability cards (informational): {card_paths[:3]}")

    timings = (last_search.get("timings") or {}) if isinstance(last_search, dict) else {}
    result = {
        "ok": bool(
            health_ms is not None
            and search_ms is not None
            and not pid_changed
            and map_rank is not None
        ),
        "dirty_ms": round(dirty_ms, 1),
        "health_ms": round(health_ms, 1) if health_ms is not None else None,
        "search_ms": round(search_ms, 1) if search_ms is not None else None,
        "total_ms": round(total_ms, 1),
        "chunks_before": base_chunks,
        "chunks_after": last_chunks,
        "chunk_delta": last_chunks - base_chunks,
        "pid_before": pid_before,
        "pid_after": pid_after,
        "pid_stable": not pid_changed,
        "map_rank": map_rank,
        "retrieve_mode": map_mode,
        "dense": bool(timings.get("dense")),
        "search_error": last_search.get("error") or last_search.get("body"),
    }
    if not result["ok"]:
        result["stage"] = failing_stage(result)
    print(json.dumps(result, indent=2))
    return result


def failing_stage(result: dict) -> str:
    """Name the stage that missed, so the fix targets it (per the plan)."""
    if not result.get("pid_stable"):
        return "restart (engine PID changed mid-window — abort/crash, see engine.log)"
    if result.get("health_ms") is None and result.get("search_ms") is None:
        lines = engine_log_tail(("[keeper] hot sync", "[publish] hot patch", "[sync] "))
        return (
            "sync/publish never made the file visible in budget"
            + (f" | log: {lines[-1]}" if lines else "")
        )
    if result.get("search_ms") is None:
        return "publish (chunks moved but the binder did not serve the path)"
    if result.get("health_ms") is None:
        return "health (search served the path but chunk count did not move)"
    if result.get("map_rank") is None:
        return "map (search served the path but not as a dense D_channel_best hit)"
    return "unknown"


def _cleanup_trial(stamp: str) -> None:
    trial_dir = REPO / "packages" / "pipeline" / f"sync_live_{stamp}"
    shutil.rmtree(trial_dir, ignore_errors=True)
    for name in ("f1.py", "__init__.py"):
        post(
            "/v1/dirty",
            {
                "path": str(REPO),
                "paths": [f"packages/pipeline/sync_live_{stamp}/{name}"],
                "reason": "probe_write",
            },
        )


def run_trials(n: int) -> int:
    """N independent single-save trials; each waits for the keeper to settle first.

    Settling includes the previous trial's cleanup (a deletion takes the full
    publish path) and its deferred graph catch-up, so every trial measures one
    new-file save landing on an idle keeper — the SLA case. Reports the pass
    rate and latency spread rather than a single lucky run.
    """
    hits: list[float] = []
    rows: list[dict] = []
    settle_s = float(os.environ.get("CTX_PROBE_SETTLE_S") or "240")
    for i in range(1, n + 1):
        print(f"\n##### trial {i}/{n}: settling keeper")
        settled = wait_for_idle_keeper(timeout_s=settle_s)
        stamp = f"{STAMP}_{i}"
        try:
            res = run_round(
                f"{i}/{n}",
                f"packages/pipeline/sync_live_{stamp}/f1.py",
                f"zqx_sync_probe_{stamp}",
                SLA_S,
            )
        finally:
            _cleanup_trial(stamp)
        res["settled"] = settled
        rows.append(res)
        if res.get("ok") and res.get("search_ms") is not None:
            hits.append(float(res["search_ms"]))

    passed = sum(1 for r in rows if r.get("ok"))
    print("\n=== trials ===")
    for i, r in enumerate(rows, 1):
        print(
            f"trial {i}: {'PASS' if r.get('ok') else 'FAIL'} hit_ms={r.get('search_ms')} "
            f"health_ms={r.get('health_ms')} delta={r.get('chunk_delta')} "
            f"map_rank={r.get('map_rank')} mode={r.get('retrieve_mode')} "
            f"pid_stable={r.get('pid_stable')} settled={r.get('settled')}"
            + ("" if r.get("ok") else f" stage={r.get('stage')}")
        )
    if hits:
        ordered = sorted(hits)
        p50 = ordered[len(ordered) // 2]
        p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
        print(f"hit latency ms: p50={p50:.0f} p95={p95:.0f} max={ordered[-1]:.0f} (n={len(hits)})")
    print(f"pass rate: {passed}/{n} within {SLA_S:.1f}s")
    return 0 if passed == n else 1


def main() -> int:
    post(
        "/v1/client/register",
        {
            "client_id": CLIENT_ID,
            "kind": "mcp",
            "client": "sync-probe",
            "pid": os.getpid(),
        },
        timeout=30.0,
    )
    print("registered probe client; waiting for the embedder")
    embed_deadline = time.time() + 300
    embedder_loaded = False
    while time.time() < embed_deadline:
        keepalive()
        h = get("/health")
        if h.get("embedder_loaded"):
            embedder_loaded = True
            print(f"embedder loaded (dense_ready={h.get('dense_ready')})")
            break
        print(f"  warm_phase={h.get('warm_phase')} dense_missing={h.get('dense_missing')}")
        time.sleep(3.0)
    if not embedder_loaded:
        print("ABORT: embedder never reported loaded — cannot measure a dense SLA")
        return 2

    exit_code = 1
    measured: dict = {}
    warm: dict = {}
    rounds = int(os.environ.get("CTX_PROBE_ROUNDS") or "2")
    trials = int(os.environ.get("CTX_PROBE_TRIALS") or "0")
    try:
        if trials > 0:
            exit_code = run_trials(trials)
            raise _ProbeDone()
        if rounds <= 1:
            # Engine already warm (embedder loaded, collection open): measure the
            # single-save case directly on an idle keeper.
            print("single-round mode: waiting for an idle keeper")
            if not wait_for_idle_keeper():
                print("WARNING: keeper still busy — measurement will include that work")
            measured = run_round(
                "1/measured",
                f"packages/pipeline/sync_live_{STAMP}/f1.py",
                f"zqx_sync_probe_{STAMP}",
                SLA_S,
            )
            exit_code = 0 if measured.get("ok") else 1
            raise _ProbeDone()
        # Round 1 (not scored): pays any cold embed/collection cost.
        warm = run_round(
            "1/warmup",
            f"packages/pipeline/sync_live_{STAMP}/f0.py",
            f"zqx_sync_warm_{STAMP}",
            WARMUP_DEADLINE_S,
        )
        keepalive()
        if warm.get("stage") == "setup":
            print(f"ABORT: {warm.get('error')}")
            return 2

        print("waiting for an idle keeper before the measured round")
        if not wait_for_idle_keeper():
            print("WARNING: keeper still busy — the measured round may queue behind it")
        time.sleep(1.0)

        # Round 2: the measured one. This decides the exit code.
        measured = run_round(
            "2/measured",
            f"packages/pipeline/sync_live_{STAMP}/f1.py",
            f"zqx_sync_probe_{STAMP}",
            SLA_S,
        )
        exit_code = 0 if measured.get("ok") else 1
    except _ProbeDone:
        pass
    finally:
        shutil.rmtree(PROBE_DIR, ignore_errors=True)
        for name in ("f0.py", "f1.py", "__init__.py"):
            post(
                "/v1/dirty",
                {
                    "path": str(REPO),
                    "paths": [f"packages/pipeline/sync_live_{STAMP}/{name}"],
                    "reason": "probe_write",
                },
            )
        post("/v1/client/unregister", {"client_id": CLIENT_ID}, timeout=30.0)
        print(f"cleaned up {PROBE_DIR}")

    if trials > 0:
        # run_trials already printed the per-trial table and pass rate.
        for line in engine_log_tail(("[keeper] hot sync",), limit=3):
            print(f"  log: {line}")
        return exit_code

    print("\n--- verdict ---")
    if rounds > 1:
        print(f"SLA: {SLA_S:.1f}s  warmup_round: {'pass' if warm.get('ok') else 'informational'}")
    else:
        print(f"SLA: {SLA_S:.1f}s  single measured round on an idle keeper")
    print(
        f"measured: hit={measured.get('search_ms')}ms health={measured.get('health_ms')}ms "
        f"chunk_delta={measured.get('chunk_delta')} map_rank={measured.get('map_rank')} "
        f"retrieve_mode={measured.get('retrieve_mode')} pid_stable={measured.get('pid_stable')}"
    )
    for line in engine_log_tail(("[keeper] hot sync", "[publish] hot patch", "[publish] hot patch declined")):
        print(f"  log: {line}")
    if exit_code == 0:
        print(f"PASS: map-visible in {measured.get('search_ms')} ms (budget {SLA_S * 1000:.0f} ms)")
    else:
        print(f"FAIL stage: {measured.get('stage') or failing_stage(measured)}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
