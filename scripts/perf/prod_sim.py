"""Scubiee production-readiness simulator.

Measures the dimensions that the earlier functional testing did NOT cover, each
against an explicit threshold, and emits a JSON report + a per-dimension verdict.

Dimensions:
  A. cold-start warming   - stop -> start -> time to soft_search_ready & dense_ready
  B. tool latency         - cold first-call vs warm p50/p95 for grep/locate/outline/sync
  C. concurrency          - N parallel clients, error rate + latency under load
  D. large-repo behavior  - full-repo grep/locate completeness + latency, no false-empty
  E. longevity soak       - sustained dirty/sync/search churn; latency drift + correctness

Pure stdlib so it runs on the installed scubiee python. Writes
scripts/perf/_prodsim_report.json and prints a summary table.

Usage:
  python scripts/perf/prod_sim.py                 # full run (includes cold restart + soak)
  python scripts/perf/prod_sim.py --quick         # skip cold-restart and shorten soak
  python scripts/perf/prod_sim.py --soak-s 120    # custom soak window
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"
REPO = Path(__file__).resolve().parents[2]
# Resolve the scubiee CLI from PATH (cross-platform) with the Windows uv-tool
# path as a fallback, so prod_sim runs unmodified on macOS/Linux too. Without
# this the first subprocess.run([SCUBIEE, ...]) raises FileNotFoundError off
# Windows (found during the macOS production run).
import shutil as _shutil

SCUBIEE = _shutil.which("scubiee") or r"C:/Users/usman/AppData/Roaming/uv/tools/scubiee/Scripts/scubiee.exe"
OUT = REPO / "scripts" / "perf" / "_prodsim_report.json"

# --- thresholds (what "production ready" means, per dimension) ---
TH = {
    "cold_soft_ready_s": 30.0,     # locate usable within 30s of a cold start
    "cold_dense_ready_s": 180.0,   # dense/semantic ready within 3 min
    "grep_warm_p95_ms": 3000.0,    # warm grep p95 under 3s
    "locate_warm_p95_ms": 4000.0,  # warm locate p95 under 4s
    "sync_visible_p95_s": 5.0,     # edit visible within 5s p95
    "concurrency_error_rate": 0.02,  # <2% errors under parallel load
    "soak_latency_drift": 2.5,     # end p95 <= 2.5x start p95 (no runaway drift)
}


def _post(path, body, timeout=60):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read().decode())


def _get(path, timeout=15):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read().decode())


def _health(timeout=5):
    try:
        return _get("/health", timeout=timeout)
    except Exception:  # noqa: BLE001
        return None


def _pctl(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(round((p / 100.0) * (len(xs) - 1)))))
    return round(xs[k], 1)


def _timed(fn):
    t0 = time.perf_counter()
    ok = True
    try:
        fn()
    except Exception:  # noqa: BLE001
        ok = False
    return (time.perf_counter() - t0) * 1000.0, ok


# ---------------- Dimension A: cold-start warming ----------------
def dim_cold_start(repeats=2):
    runs = []
    for _ in range(repeats):
        subprocess.run([SCUBIEE, "engine", "stop"], capture_output=True, timeout=60)
        time.sleep(2.0)
        # start detached; poll health ourselves for precise timing
        subprocess.Popen(
            [SCUBIEE, "engine", "start", "--wait", "1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        t0 = time.perf_counter()
        soft_s = dense_s = None
        deadline = t0 + 240.0
        while time.perf_counter() < deadline:
            h = _health(timeout=3)
            if h:
                if soft_s is None and h.get("soft_search_ready"):
                    soft_s = time.perf_counter() - t0
                if dense_s is None and (h.get("dense_ready") or h.get("embedder_loaded")):
                    dense_s = time.perf_counter() - t0
                if soft_s is not None and dense_s is not None:
                    break
            time.sleep(0.5)
        runs.append({"soft_ready_s": round(soft_s, 1) if soft_s else None,
                     "dense_ready_s": round(dense_s, 1) if dense_s else None})
        time.sleep(2.0)
    softs = [r["soft_ready_s"] for r in runs if r["soft_ready_s"] is not None]
    denses = [r["dense_ready_s"] for r in runs if r["dense_ready_s"] is not None]
    soft_ok = bool(softs) and max(softs) <= TH["cold_soft_ready_s"]
    dense_ok = bool(denses) and max(denses) <= TH["cold_dense_ready_s"]

    # Document the KNOWN startup-window behavior: fire concurrent load while the
    # embedder is still prewarming (if it still is), so the report shows the real
    # transient cost rather than hiding it. Informational, not a gate.
    warmup_load = None
    h = _health()
    if h and h.get("embed_prewarm_running"):
        warmup_load = _run_load(clients=8, per_client=4)
        warmup_load["note"] = (
            "concurrent calls during ORT/DirectML prewarm; GIL-held session build "
            "can stall some to timeout — transient, clears when embedder_loaded=true"
        )
    return {
        "runs": runs,
        "soft_ready_max_s": max(softs) if softs else None,
        "dense_ready_max_s": max(denses) if denses else None,
        "warmup_window_concurrency": warmup_load,
        "pass": soft_ok,  # dense is background; soft readiness gates usability
        "dense_pass": dense_ok,
    }


# ---------------- Dimension B: tool latency cold vs warm ----------------
def _grep(pat, glob=None):
    b = {"pattern": pat, "path": str(REPO), "max_hits": 10}
    if glob:
        b["glob"] = glob
    return _post("/v1/grep", b, timeout=30)


def _locate(q):
    return _post("/v1/locate", {"query": q, "top_k": 5, "path": str(REPO)}, timeout=30)


def dim_tool_latency(warm_calls=15):
    # Cold first-call = whatever state we are in right now (call once, measure).
    cold = {}
    cold["grep_ms"], _ = _timed(lambda: _grep("def canonical_relpath"))
    cold["locate_ms"], _ = _timed(lambda: _locate("ripgrep resolver grep backend"))

    # Warm steady-state p50/p95 over N calls with varied queries.
    grep_lat, loc_lat = [], []
    gq = ["def grep_scan", "canonical_relpath", "promote_staged_store", "incremental_sync",
          "swap_collection", "needs_full", "discover_newcomers", "publish_engine"]
    lq = ["how does sync publish", "grep ripgrep resolver", "merkle canonical path",
          "engine warm state readiness", "staged index promote", "faiss collection swap"]
    for i in range(warm_calls):
        ms, ok = _timed(lambda i=i: _grep(gq[i % len(gq)]))
        if ok:
            grep_lat.append(ms)
        ms, ok = _timed(lambda i=i: _locate(lq[i % len(lq)]))
        if ok:
            loc_lat.append(ms)
    out = {
        "cold": {k: round(v) for k, v in cold.items()},
        "grep_warm_p50_ms": _pctl(grep_lat, 50),
        "grep_warm_p95_ms": _pctl(grep_lat, 95),
        "locate_warm_p50_ms": _pctl(loc_lat, 50),
        "locate_warm_p95_ms": _pctl(loc_lat, 95),
        "samples": {"grep": len(grep_lat), "locate": len(loc_lat)},
    }
    out["pass"] = (
        (out["grep_warm_p95_ms"] or 1e9) <= TH["grep_warm_p95_ms"]
        and (out["locate_warm_p95_ms"] or 1e9) <= TH["locate_warm_p95_ms"]
    )
    return out


# ---------------- Dimension C: concurrency ----------------
def _wait_fully_warm(timeout_s=180.0) -> bool:
    """Block until embedder is loaded and prewarm is done (steady state)."""
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        h = _health()
        if h and h.get("embedder_loaded") and not h.get("embed_prewarm_running"):
            return True
        time.sleep(1.0)
    return False


def _run_load(clients=8, per_client=6):
    """Fire N parallel clients mixing grep/locate/health; return error/latency stats."""
    results = {"calls": 0, "errors": 0, "lat_ms": []}
    lock = threading.Lock()
    gq = ["def grep_scan", "canonical_relpath", "incremental_sync", "swap_collection"]
    lq = ["sync publish path", "grep backend resolver", "merkle canonical"]

    def worker(wid):
        local, errs = [], 0
        for i in range(per_client):
            op = (wid + i) % 3
            try:
                t0 = time.perf_counter()
                if op == 0:
                    _grep(gq[(wid + i) % len(gq)])
                elif op == 1:
                    _locate(lq[(wid + i) % len(lq)])
                else:
                    _get("/health", timeout=10)
                local.append((time.perf_counter() - t0) * 1000.0)
            except Exception:  # noqa: BLE001
                errs += 1
        with lock:
            results["calls"] += per_client
            results["errors"] += errs
            results["lat_ms"].extend(local)

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(clients)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0
    err_rate = results["errors"] / max(1, results["calls"])
    return {
        "clients": clients,
        "total_calls": results["calls"],
        "errors": results["errors"],
        "error_rate": round(err_rate, 4),
        "p50_ms": _pctl(results["lat_ms"], 50),
        "p95_ms": _pctl(results["lat_ms"], 95),
        "wall_s": round(wall, 1),
    }


def dim_concurrency(clients=8, per_client=6):
    """Steady-state concurrency is the production gate; warm-up window is
    reported separately because ORT/DirectML prewarm holds the GIL and can stall
    concurrent calls during the first ~5-15s (a known, transient startup cost,
    not a steady-state failure)."""
    warm = _wait_fully_warm()
    steady = _run_load(clients, per_client)
    h = _health()
    steady["engine_alive_after"] = h is not None and h.get("index_usable", False)
    return {
        "fully_warm_before_test": warm,
        "steady_state": steady,
        # Gate on steady state only (what a running engine actually serves).
        "pass": (
            warm
            and steady["error_rate"] <= TH["concurrency_error_rate"]
            and steady["engine_alive_after"]
        ),
    }


# ---------------- Dimension D: large-repo behavior ----------------
def dim_large_repo():
    # Full-glob grep for a symbol that lives deep in packages/ (late alphabet).
    t0 = time.perf_counter()
    g = _grep("def promote_staged_store")  # full **/* glob
    grep_ms = (time.perf_counter() - t0) * 1000.0
    found_pkg = any("packages/pipeline/artifact_guard.py" in h.get("path", "") for h in g.get("hits", []))
    complete = g.get("complete", True)
    # locate on the full repo
    t0 = time.perf_counter()
    loc = _locate("zero downtime staged index promote blue green")
    loc_ms = (time.perf_counter() - t0) * 1000.0
    loc_hits = len(loc.get("hits") or loc.get("results") or [])
    return {
        "grep_full_glob_ms": round(grep_ms),
        "grep_found_deep_packages_symbol": found_pkg,
        "grep_complete": complete,
        "grep_backend": g.get("backend"),
        "locate_full_ms": round(loc_ms),
        "locate_hits": loc_hits,
        # pass: deep symbol found (no false-empty from budget), scan complete, locate returns hits
        "pass": found_pkg and complete and loc_hits > 0,
    }


# ---------------- Dimension E: longevity soak ----------------
def dim_soak(window_s=180.0):
    work = REPO / "scripts" / "perf" / "_soak"
    work.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())
    created = []
    cycle_lat = []  # dirty->sync->visible seconds
    search_lat = []  # grep ms during soak
    errors = 0
    t_end = time.perf_counter() + window_s
    i = 0
    first_window = []
    last_window = []
    try:
        while time.perf_counter() < t_end:
            i += 1
            tok = f"SOAK_{stamp}_{i}"
            f = work / f"soak_{stamp}_{i}.py"
            try:
                f.write_text(f"def {tok.lower()}():\n    return {tok!r}\n", encoding="utf-8")
                created.append(f)
                rel = f.relative_to(REPO).as_posix()
                c0 = time.perf_counter()
                _post("/v1/dirty", {"paths": [rel], "reason": "soak", "path": str(REPO)})
                time.sleep(1.2)
                _post("/v1/sync", {"path": str(REPO)})
                # poll visible
                vis = None
                vd = time.perf_counter() + 20.0
                while time.perf_counter() < vd:
                    gms0 = time.perf_counter()
                    g = _grep(tok, glob="scripts/perf/**/*.py")
                    search_lat.append((time.perf_counter() - gms0) * 1000.0)
                    if g.get("hits"):
                        vis = time.perf_counter() - c0
                        break
                    time.sleep(0.8)
                if vis is not None:
                    cycle_lat.append(vis)
                    (first_window if i <= 5 else last_window).append(vis)
                else:
                    errors += 1
                # delete it to keep churn + exercise delete path
                f.unlink()
                _post("/v1/dirty", {"paths": [rel], "reason": "soak_del", "path": str(REPO)})
                time.sleep(0.5)
            except Exception:  # noqa: BLE001
                errors += 1
    finally:
        for p in created:
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        try:
            if work.exists() and not any(work.iterdir()):
                work.rmdir()
        except OSError:
            pass
    h = _health()
    start_p95 = _pctl(search_lat[: max(5, len(search_lat) // 4)], 95)
    end_p95 = _pctl(search_lat[-max(5, len(search_lat) // 4):], 95)
    drift = (end_p95 / start_p95) if (start_p95 and end_p95) else None
    return {
        "cycles": i,
        "visible_ok": len(cycle_lat),
        "errors": errors,
        "cycle_p50_s": _pctl(cycle_lat, 50),
        "cycle_p95_s": _pctl(cycle_lat, 95),
        "search_p95_start_ms": start_p95,
        "search_p95_end_ms": end_p95,
        "latency_drift_x": round(drift, 2) if drift else None,
        "engine_alive_after": h is not None and h.get("index_usable", False),
        "pass": (
            errors == 0
            and h is not None
            and (drift is None or drift <= TH["soak_latency_drift"])
            and (_pctl(cycle_lat, 95) or 1e9) <= TH["sync_visible_p95_s"]
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip cold restart, short soak")
    ap.add_argument("--soak-s", type=float, default=180.0)
    args = ap.parse_args()

    report = {"ts": time.time(), "version": None, "dimensions": {}, "thresholds": TH}
    h = _health()
    if h is None:
        print("ENGINE DOWN — start it first (scubiee engine start)")
        return 2
    report["version"] = h.get("version")
    print(f"[prodsim] engine v{h.get('version')} chunks={h.get('chunks')} — starting")

    if not args.quick:
        print("[prodsim] A: cold-start warming (stops/starts engine)...")
        report["dimensions"]["A_cold_start"] = dim_cold_start(repeats=2)
        # wait for dense to settle before latency tests
        for _ in range(120):
            hh = _health()
            if hh and hh.get("soft_search_ready"):
                break
            time.sleep(1.0)

    print("[prodsim] B: tool latency cold vs warm...")
    report["dimensions"]["B_tool_latency"] = dim_tool_latency()
    print("[prodsim] C: concurrency...")
    report["dimensions"]["C_concurrency"] = dim_concurrency()
    print("[prodsim] D: large-repo behavior...")
    report["dimensions"]["D_large_repo"] = dim_large_repo()
    print(f"[prodsim] E: longevity soak ({'30s quick' if args.quick else str(args.soak_s)+'s'})...")
    report["dimensions"]["E_soak"] = dim_soak(window_s=30.0 if args.quick else args.soak_s)

    # verdict
    passes = {k: v.get("pass") for k, v in report["dimensions"].items()}
    report["verdict"] = {"per_dimension": passes, "all_pass": all(passes.values())}

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n================= PRODUCTION-READINESS REPORT =================")
    for name, d in report["dimensions"].items():
        mark = "PASS" if d.get("pass") else "FAIL"
        print(f"[{mark}] {name}")
        for k, v in d.items():
            if k in ("pass", "runs"):
                continue
            print(f"        {k} = {v}")
    print("---------------------------------------------------------------")
    print(f"ALL PASS: {report['verdict']['all_pass']}")
    print(f"report: {OUT}")
    print("===============================================================")
    return 0 if report["verdict"]["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
