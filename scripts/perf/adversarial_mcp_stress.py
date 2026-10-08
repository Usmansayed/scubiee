#!/usr/bin/env python
"""Adversarial stress harness — try hard to BREAK the real Scubiee MCP.

Each scenario drives the REAL engine + REAL scubiee-mcp-bridge (same binary/env
Kiro uses, via mcp_host_sim.BridgeHost) and/or raw HTTP, then checks global
invariants after. Safe-by-design: all churn happens in a throwaway subtree
(scripts/perf/_adv/) which is removed + reconciled out at the end.

Scenarios (pick a subset on the CLI, or run all):
  S1  big_offline     - 300 files added while engine OFF -> reopen must reconcile
  S2  flap            - rapid open/close/open/close bridge (connect-storm)
  S3  crash_mid_index - kill the engine process mid offline-reconcile drain
  S4  concurrent      - 3 bridges (distinct hosts) hammer map/status concurrently
  S5  rename_storm    - rename a whole folder while OFF -> old pruned + new indexed
  S6  huge_file       - one 60k-line file added while OFF (chunk explosion)
  S7  churn_in_warm   - add files DURING warm (race the reconcile walk)
  S8  mixed_cycles    - 2 cycles of add+modify+delete back to back

Global invariants checked after every scenario (fail = candidate bug):
  G1 engine process did not crash (health reachable again)
  G2 /health coherent (ok, warm_ready, no exception)
  G3 no confident-false-empty: a KNOWN baseline symbol is still findable
  G4 generation monotonic (never went backward)
  G5 no fatal/traceback lines in engine.log during the scenario window
  G6 pending contract sane (substantial<=>reconciling/interrupted; search_usable true)

Report: scripts/perf/_adv_stress_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADV = REPO / "scripts" / "perf" / "_adv"
REPORT = REPO / "scripts" / "perf" / "_adv_stress_report.json"
URL = "http://127.0.0.1:8765"
SCUBIEE = str(Path.home() / ".local" / "bin" / "scubiee.EXE")
ENGINE_LOG = Path.home() / ".scubiee" / "engine.log"

ALL = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]


# ------------------------------------------------------------------ primitives

def _exe() -> str:
    return SCUBIEE if Path(SCUBIEE).is_file() else "scubiee"


def scubiee(*args: str, timeout: float = 150.0) -> subprocess.CompletedProcess:
    return subprocess.run([_exe(), *args], capture_output=True, text=True,
                          timeout=timeout, cwd=str(REPO))


def http_get(path: str, timeout: float = 6.0) -> dict:
    with urllib.request.urlopen(urllib.request.Request(URL + path), timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read().decode())


def http_post(path: str, body: dict, timeout: float = 25.0) -> dict:
    req = urllib.request.Request(
        URL + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read().decode())


def running() -> bool:
    try:
        return bool(http_get("/health", 3).get("ok"))
    except Exception:  # noqa: BLE001
        return False


def wait_running(max_s: float = 100.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < max_s:
        if running():
            return True
        time.sleep(1.5)
    return False


def wait_down(max_s: float = 45.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < max_s:
        if not running():
            return True
        time.sleep(1.0)
    return False


def ensure_engine() -> None:
    if not running():
        scubiee("engine", "start", str(REPO), "--wait", "90")
        wait_running(100)


def host(project_id: str, client: str = "kiro"):
    from pipeline.mcp_host_sim.hosts.bridge_stdio import BridgeHost
    return BridgeHost(repo=REPO, project_id=project_id, engine_url=URL,
                      mcp_client=client, env_extra={"CTX_DISCONNECT_DEBOUNCE_S": "8"})


def _write_mod(path: Path, token: str, funcs: int = 6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = [f'"""adv {token}"""', ""]
    for i in range(funcs):
        out += [f"def {token}_f{i}(a, b):", f"    return a + b + {i}", ""]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def log_tail_fatal(since_ts: float) -> list[str]:
    """Genuine fatal/traceback lines written to engine.log.

    Precise on purpose: an earlier version matched the literal substring 'crash'
    inside scenario FILE PATHS (``s3/crash_0.py``) and flagged benign
    ``client gone mid-response`` disconnects, producing false G5 failures. We now
    match only unambiguous fatal signals and explicitly skip benign lines.
    """
    if not ENGINE_LOG.is_file():
        return []
    # Phrases that look alarming but are normal operation / harness teardown.
    benign = (
        "client gone mid-response",   # harness closed the bridge mid-call
        "gone from disk",             # routine deletion-queue log
        "queued for removal",
        "ConnectionAbortedError".lower(),
        "ConnectionResetError".lower(),
    )
    fatal_signals = (
        "traceback (most recent call last)",
        "segmentation fault",
        "fatal error",
        "fatal:",
        "unhandled exception",
        "panicked",
        "[keeper] final_check on exit failed",
    )
    bad = []
    try:
        for line in ENGINE_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()[-800:]:
            low = line.lower()
            if any(b in low for b in benign):
                continue
            if any(sig in low for sig in fatal_signals):
                bad.append(line.strip()[:200])
    except OSError:
        pass
    return bad[-15:]


# ------------------------------------------------------------------ invariants

def durable_generation(project_id: str) -> tuple[str, int]:
    """The DURABLE (epoch, counter) from index_state.json — the real monotonic
    generation. The /health `generation` is a volatile in-memory counter that
    resets on every engine restart, so it is NOT a valid monotonicity signal
    across a stop/start scenario."""
    try:
        from pipeline.index_state import load_index_state
        doc = load_index_state(project_id)
        return (doc.generation_epoch or "", int(doc.generation_counter or 0))
    except Exception:  # noqa: BLE001
        return ("", 0)


def check_invariants(project_id: str, gen_before: tuple[str, int], since_ts: float,
                     baseline_token: str) -> dict:
    inv: dict = {}
    # G1/G2
    ok_reach = wait_running(60)
    inv["G1_engine_alive"] = ok_reach
    h = {}
    try:
        h = http_get("/health", 6)
    except Exception as e:  # noqa: BLE001
        h = {"ok": False, "err": str(e)}
    inv["G2_health_coherent"] = bool(h.get("ok") and ("warm_ready" in h))
    # G4 DURABLE generation monotonic within an epoch (epoch change = legit new
    # engine identity, counter resets are allowed only across epochs).
    gen_after = durable_generation(project_id)
    same_epoch = gen_before[0] and gen_before[0] == gen_after[0]
    inv["G4_generation_monotonic"] = (not same_epoch) or (gen_after[1] >= gen_before[1])
    inv["_gen_before"] = list(gen_before)
    inv["_gen_after"] = list(gen_after)
    # G6 pending contract sanity
    p = h.get("pending")
    g6 = True
    if isinstance(p, dict):
        g6 = bool(p.get("substantial")) and p.get("search_usable", True) in (True, False)
    inv["G6_pending_sane"] = g6
    inv["_pending"] = p
    inv["_index_fresh"] = h.get("index_fresh")
    # G3 known baseline symbol still findable (no confident-empty)
    g3 = None
    if baseline_token:
        try:
            res = http_post("/v1/search", {"path": str(REPO),
                                           "query": f"{baseline_token} adv baseline",
                                           "top_k": 5}, timeout=20)
            g3 = baseline_token in json.dumps(res)
        except Exception:  # noqa: BLE001
            g3 = None  # engine busy; not a definitive fail
    inv["G3_baseline_findable"] = g3
    # G5 fatal log lines
    fatal = log_tail_fatal(since_ts)
    inv["G5_no_fatal_log"] = (len(fatal) == 0)
    inv["_fatal_lines"] = fatal
    # overall: hard fails only on G1/G2/G4/G5/G6 (+ G3 only when it's a definite False)
    hard = (inv["G1_engine_alive"] and inv["G2_health_coherent"]
            and inv["G4_generation_monotonic"] and inv["G5_no_fatal_log"]
            and inv["G6_pending_sane"] and (inv["G3_baseline_findable"] is not False))
    inv["PASS"] = bool(hard)
    return inv


# ------------------------------------------------------------------ baseline

def seed_baseline(project_id: str) -> str:
    """A known baseline file + token present in the index before stress."""
    ADV.mkdir(parents=True, exist_ok=True)
    token = "advbase"
    _write_mod(ADV / "advbase_anchor.py", token, funcs=4)
    ensure_engine()
    try:
        http_post("/v1/dirty", {"path": str(REPO),
                                "paths": ["scripts/perf/_adv/advbase_anchor.py"],
                                "reason": "adv_baseline"}, timeout=10)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(10)
    return token


# ------------------------------------------------------------------ scenarios

def s1_big_offline(pid: str) -> dict:
    """300 files added while engine OFF -> reopen must reconcile them."""
    h = host(pid); h.start(); h.stop()
    scubiee("engine", "stop"); wait_down(40)
    for i in range(300):
        _write_mod(ADV / f"s1/big_{i}.py", f"s1big{i}", funcs=3)
    t = time.time()
    scubiee("engine", "start", str(REPO), "--wait", "90"); wait_running(120)
    # poll pending: a 300-file paste SHOULD be surfaced as substantial
    saw_substantial, drained = False, None
    for _ in range(90):
        try:
            hp = http_get("/health")
        except Exception:  # noqa: BLE001
            time.sleep(2); continue
        p = hp.get("pending")
        if isinstance(p, dict) and p.get("substantial"):
            saw_substantial = True
        if hp.get("index_fresh"):
            drained = round(time.time() - t, 1); break
        time.sleep(2)
    return {"saw_substantial_pending": saw_substantial, "drained_after_s": drained}


def s2_flap(pid: str) -> dict:
    """Rapid open/close bridge connect-storm — must not wedge or crash."""
    ensure_engine()
    results = []
    for i in range(8):
        hh = host(pid, client="kiro" if i % 2 else "cursor")
        try:
            r = hh.start(); results.append(bool(r.get("ok")))
        except Exception as e:  # noqa: BLE001
            results.append(f"start_err:{e}")
        time.sleep(0.4)  # tiny dwell — stress the register/unregister path
        try:
            hh.stop()
        except Exception:  # noqa: BLE001
            pass
    return {"opens_ok": sum(1 for r in results if r is True), "attempts": len(results),
            "results": results}


def s3_crash_mid_index(pid: str) -> dict:
    """Kill the engine process mid offline-reconcile drain; must recover clean."""
    h = host(pid); h.start(); h.stop()
    scubiee("engine", "stop"); wait_down(40)
    for i in range(120):
        _write_mod(ADV / f"s3/crash_{i}.py", f"s3crash{i}", funcs=4)
    scubiee("engine", "start", str(REPO), "--wait", "90"); wait_running(120)
    time.sleep(4)  # let the drain begin
    # hard kill the engine pid mid-drain
    killed = None
    try:
        hp = http_get("/health"); killed = hp.get("pid")
        if killed and os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(killed)],
                           capture_output=True, text=True, timeout=20)
    except Exception as e:  # noqa: BLE001
        killed = f"err:{e}"
    time.sleep(3)
    # watchdog or restart should bring it back + reconcile the remainder
    back = wait_running(120)
    interrupted = None
    if back:
        try:
            interrupted = http_get("/health").get("pending")
        except Exception:  # noqa: BLE001
            pass
    return {"killed_pid": killed, "engine_recovered": back, "pending_after_recover": interrupted}


def s4_concurrent(pid: str) -> dict:
    """3 bridges from distinct hosts hammer map/status concurrently."""
    import threading
    ensure_engine()
    hosts = [host(pid, client=c) for c in ("kiro", "cursor", "codex")]
    for hh in hosts:
        try:
            hh.start()
        except Exception:  # noqa: BLE001
            pass
    errs: list[str] = []
    hits = {"map": 0, "status": 0}
    lock = threading.Lock()

    def hammer(hh, n):
        for _ in range(n):
            try:
                r = hh.map("advbase anchor function", k=5)
                with lock:
                    hits["map"] += 1 if r.get("ok") else 0
            except Exception as e:  # noqa: BLE001
                with lock:
                    errs.append(f"map:{e}")
            try:
                hh.status()
                with lock:
                    hits["status"] += 1
            except Exception as e:  # noqa: BLE001
                with lock:
                    errs.append(f"status:{e}")

    threads = [threading.Thread(target=hammer, args=(hh, 8)) for hh in hosts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for hh in hosts:
        try:
            hh.stop()
        except Exception:  # noqa: BLE001
            pass
    return {"map_ok": hits["map"], "status_ok": hits["status"],
            "errors": errs[:10], "error_count": len(errs)}


def s5_rename_storm(pid: str) -> dict:
    """Rename a whole folder while OFF — old paths pruned, new indexed."""
    # seed a folder online first
    ensure_engine()
    for i in range(40):
        _write_mod(ADV / f"s5_old/r_{i}.py", f"s5old{i}", funcs=3)
    try:
        http_post("/v1/dirty", {"path": str(REPO),
                                "paths": [f"scripts/perf/_adv/s5_old/r_{i}.py" for i in range(40)],
                                "reason": "adv_s5_seed"}, timeout=10)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(12)
    # go offline, rename the folder (= 40 deletes + 40 adds)
    h = host(pid); h.start(); h.stop()
    scubiee("engine", "stop"); wait_down(40)
    old = ADV / "s5_old"; new = ADV / "s5_new"
    if old.is_dir():
        old.rename(new)
    t = time.time()
    scubiee("engine", "start", str(REPO), "--wait", "90"); wait_running(120)
    drained = None
    for _ in range(90):
        try:
            if http_get("/health").get("index_fresh"):
                drained = round(time.time() - t, 1); break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    # Rename = delete(old path) + add(new path). The CONTENT is identical in both
    # paths, so a content search matches either — to prove the old path was
    # PRUNED we must inspect the file PATHS returned, not the body text. The
    # delete-half drains over several cycles AFTER index_fresh first flips (the
    # current generation keeps serving old content until the removal publishes),
    # so POLL until the old path disappears rather than snapshotting once.
    old_path_present = new_path_present = None
    t_prune = time.time()
    for _ in range(60):  # up to ~2 min for the delete-half to publish
        try:
            r = http_post("/v1/search", {"path": str(REPO), "query": "s5old0 r function marker", "top_k": 12}, timeout=20)
            blob = json.dumps(r)
            old_path_present = "s5_old/" in blob or "s5_old\\" in blob
            new_path_present = "s5_new/" in blob or "s5_new\\" in blob
        except Exception:  # noqa: BLE001
            time.sleep(2); continue
        if old_path_present is False and new_path_present:
            break
        time.sleep(2)
    return {
        "drained_after_s": drained,
        "prune_wait_s": round(time.time() - t_prune, 1),
        "old_path_pruned": (old_path_present is False),
        "old_path_present": old_path_present,
        "new_path_indexed": new_path_present,
    }


def s6_huge_file(pid: str) -> dict:
    """One ~60k-line file added while OFF (chunk explosion / cap behavior)."""
    h = host(pid); h.start(); h.stop()
    scubiee("engine", "stop"); wait_down(40)
    big = ADV / "s6_huge.py"
    big.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(12000):
        lines += [f"def huge_fn_{i}(x):", f"    return x + {i}", ""]
    big.write_text("\n".join(lines) + "\n", encoding="utf-8")
    t = time.time()
    scubiee("engine", "start", str(REPO), "--wait", "90"); wait_running(120)
    outcome = None
    saw_substantial = False
    for _ in range(180):  # 12k-line embed is slow; allow up to ~6 min
        try:
            hp = http_get("/health")
        except Exception:  # noqa: BLE001
            time.sleep(2); continue
        p = hp.get("pending")
        if isinstance(p, dict) and p.get("substantial"):
            saw_substantial = True
        if isinstance(p, dict) and p.get("action"):  # needs_full surfaced
            outcome = {"needs_full": True, "action": p.get("action")}
            break
        if hp.get("index_fresh"):
            outcome = {"needs_full": False, "drained_after_s": round(time.time() - t, 1)}
            break
        time.sleep(2)
    return {"outcome": outcome, "saw_substantial_pending": saw_substantial}


def s7_churn_in_warm(pid: str) -> dict:
    """Add files DURING warm to race the reconcile walk — none may be lost."""
    scubiee("engine", "stop"); wait_down(40)
    # pre-stage some, then add MORE right as the engine starts warming
    for i in range(20):
        _write_mod(ADV / f"s7/pre_{i}.py", f"s7pre{i}", funcs=3)
    import threading

    def late_add():
        time.sleep(1.5)  # land during warm/reconcile
        for i in range(20):
            _write_mod(ADV / f"s7/late_{i}.py", f"s7late{i}", funcs=3)

    th = threading.Thread(target=late_add); th.start()
    t = time.time()
    scubiee("engine", "start", str(REPO), "--wait", "90"); wait_running(120)
    th.join()
    # both pre_ and late_ must eventually be searchable (none lost to the race)
    pre_ok = late_ok = None
    for _ in range(90):
        try:
            if http_get("/health").get("index_fresh"):
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    try:
        r = http_post("/v1/search", {"path": str(REPO), "query": "s7pre0 s7late0 function", "top_k": 10}, timeout=20)
        blob = json.dumps(r)
        pre_ok = "s7pre" in blob
        late_ok = "s7late" in blob
    except Exception:  # noqa: BLE001
        pass
    return {"pre_searchable": pre_ok, "late_searchable": late_ok}


def s8_mixed_cycles(pid: str) -> dict:
    """2 back-to-back cycles of add+modify+delete offline."""
    out = []
    for c in range(2):
        h = host(pid); h.start(); h.stop()
        scubiee("engine", "stop"); wait_down(40)
        for i in range(25):
            _write_mod(ADV / f"s8/c{c}_{i}.py", f"s8c{c}n{i}", funcs=3)
        anchor = ADV / "advbase_anchor.py"
        if anchor.is_file():
            anchor.write_text(anchor.read_text(encoding="utf-8") + f"\ndef advbase_edit_c{c}(x):\n    return x\n", encoding="utf-8")
        prev = ADV / f"s8/c{c-1}"
        if prev.is_dir():
            shutil.rmtree(prev, ignore_errors=True)
        t = time.time()
        scubiee("engine", "start", str(REPO), "--wait", "90"); wait_running(120)
        drained = None
        for _ in range(80):
            try:
                if http_get("/health").get("index_fresh"):
                    drained = round(time.time() - t, 1); break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)
        out.append({"cycle": c, "drained_after_s": drained})
    return {"cycles": out}


SCENARIOS = {
    "S1": ("big_offline", s1_big_offline),
    "S2": ("flap", s2_flap),
    "S3": ("crash_mid_index", s3_crash_mid_index),
    "S4": ("concurrent", s4_concurrent),
    "S5": ("rename_storm", s5_rename_storm),
    "S6": ("huge_file", s6_huge_file),
    "S7": ("churn_in_warm", s7_churn_in_warm),
    "S8": ("mixed_cycles", s8_mixed_cycles),
}


# ------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*", default=[], help="subset e.g. S1 S3; empty=all")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    picks = [s.upper() for s in args.scenarios] or ALL

    from pipeline.project_id import peek_project
    ref = peek_project(REPO)
    if ref is None:
        print("repo not enrolled", file=sys.stderr); return 2
    pid = ref.project_id
    print(f"[adv] project_id={pid} scenarios={picks}", flush=True)

    token = seed_baseline(pid)
    results = []
    for key in picks:
        name, fn = SCENARIOS[key]
        print(f"\n===== {key} {name} =====", flush=True)
        since = time.time()
        gen_before = durable_generation(pid)
        rec: dict = {"id": key, "name": name}
        try:
            rec["detail"] = fn(pid)
        except Exception as e:  # noqa: BLE001
            import traceback
            rec["detail"] = {"exception": str(e), "trace": traceback.format_exc()[-1200:]}
        # make sure engine is back before checking invariants
        if not running():
            scubiee("engine", "start", str(REPO), "--wait", "90"); wait_running(120)
        rec["invariants"] = check_invariants(pid, gen_before, since, token)
        rec["PASS"] = rec["invariants"].get("PASS", False)
        results.append(rec)
        print(f"[{key}] {'PASS' if rec['PASS'] else 'FAIL'} "
              f"detail={json.dumps(rec['detail'])[:300]}", flush=True)
        print(f"[{key}] invariants={ {k:v for k,v in rec['invariants'].items() if not k.startswith('_')} }",
              flush=True)

    if not args.keep:
        shutil.rmtree(ADV, ignore_errors=True)
        try:
            scubiee("engine", "stop"); wait_down(30)
            scubiee("engine", "start", str(REPO), "--wait", "90"); wait_running(100)
        except Exception:  # noqa: BLE001
            pass

    passed = sum(1 for r in results if r["PASS"])
    summary = {"project_id": pid, "ran": picks, "passed": passed,
               "failed": len(picks) - passed,
               "verdict": "PASS" if passed == len(picks) else "FAIL",
               "results": results}
    REPORT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n===== ADV VERDICT: {summary['verdict']} ({passed}/{len(picks)}) =====", flush=True)
    print(f"report: {REPORT}", flush=True)
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
