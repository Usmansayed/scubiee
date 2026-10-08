#!/usr/bin/env python
"""Offline-reopen simulator — mimics a real user with Kiro over the REAL MCP.

Faithfully reproduces the lifecycle the unified indexing/state model is built for:

    1. OPEN   — spawn the real `scubiee-mcp-bridge` (the same binary + env Kiro
                launches), handshake initialize + notifications/initialized. This
                registers a client and warms the engine.
    2. CLOSE  — close the bridge (stdin EOF -> /v1/client/unregister), then
                `scubiee engine stop` so the engine PROCESS actually exits (as it
                would ~2 min after the editor closes). The engine is now gone.
    3. EDIT    — mutate files ON DISK while the engine is stopped (add a folder of
                files / modify / delete). No /v1/dirty: the editor is closed, so
                this is the OFFLINE path the reconciler must catch on next start.
    4. REOPEN  — spawn the bridge again. Cold warm runs _reconcile_offline(start)
                -> root_probe detects the drift -> keeper drains it, with NO manual
                trigger and NO client needed to START the work.
    5. VERIFY  — poll /health for `pending`/`index_fresh`, confirm the engine stays
                busy (no idle-stop) until drift drains, then confirm the new
                symbols are searchable via the real `map` tool.

This drives the REAL engine + REAL bridge over stdio. To stay safe it churns a
throwaway subtree (`scripts/perf/_offline_sim/`) inside the managed repo — real
on-disk changes the engine genuinely reconciles, but trivially cleaned up and not
real source. The subtree is removed at the end (a final delete-reconcile cycle).

Usage:
    python scripts/perf/offline_reopen_sim.py                 # 3 cycles, defaults
    python scripts/perf/offline_reopen_sim.py --cycles 5 --files 40
    python scripts/perf/offline_reopen_sim.py --keep          # leave the subtree

Report: scripts/perf/_offline_reopen_report.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SIM_DIR = REPO / "scripts" / "perf" / "_offline_sim"
REPORT = REPO / "scripts" / "perf" / "_offline_reopen_report.json"
ENGINE_URL = "http://127.0.0.1:8765"
SCUBIEE = str(Path.home() / ".local" / "bin" / "scubiee.EXE")


# ---------------------------------------------------------------- engine control

def _scubiee(*args: str, timeout: float = 150.0) -> subprocess.CompletedProcess:
    exe = SCUBIEE if Path(SCUBIEE).is_file() else "scubiee"
    return subprocess.run(
        [exe, *args],
        capture_output=True, text=True, timeout=timeout, cwd=str(REPO),
    )


def engine_stop() -> None:
    _scubiee("engine", "stop", timeout=60)


def engine_running() -> bool:
    try:
        return bool(health().get("ok"))
    except Exception:  # noqa: BLE001
        return False


def health(timeout: float = 4.0) -> dict:
    req = urllib.request.Request(f"{ENGINE_URL}/health", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def wait_engine_down(max_s: float = 60.0) -> float:
    """Block until /health stops answering. Returns seconds waited."""
    t0 = time.time()
    while time.time() - t0 < max_s:
        if not engine_running():
            return time.time() - t0
        time.sleep(1.0)
    return time.time() - t0


# ---------------------------------------------------------------- file churn

def _write_module(path: Path, token: str, n_funcs: int = 6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'"""Offline-sim module {token}."""', ""]
    for i in range(n_funcs):
        lines += [
            f"def {token}_fn_{i}(x):",
            f'    """Marker {token} function {i} for retrieval checks."""',
            f"    return x + {i}",
            "",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def seed_baseline(files: int) -> list[str]:
    """A small baseline set present at the first open (so the index knows it)."""
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    rels = []
    for i in range(max(1, files // 4)):
        rel = f"scripts/perf/_offline_sim/base_{i}.py"
        _write_module(REPO / rel, f"base{i}")
        rels.append(rel)
    return rels


def apply_offline_edits(cycle: int, files: int) -> dict:
    """Mutate on disk while the engine is OFF: add a folder, modify, delete."""
    added, modified, removed = [], [], []
    # add a folder of new files (the headline offline-paste case)
    for i in range(files):
        rel = f"scripts/perf/_offline_sim/c{cycle}/new_{i}.py"
        _write_module(REPO / rel, f"c{cycle}new{i}")
        added.append(rel)
    # modify an existing baseline file if present
    base0 = REPO / "scripts/perf/_offline_sim/base_0.py"
    if base0.is_file():
        base0.write_text(
            base0.read_text(encoding="utf-8")
            + f"\ndef base0_edited_c{cycle}(x):\n    return x * {cycle}\n",
            encoding="utf-8",
        )
        modified.append("scripts/perf/_offline_sim/base_0.py")
    # delete a prior cycle's folder if present
    prev = REPO / f"scripts/perf/_offline_sim/c{cycle - 1}"
    if prev.is_dir():
        for p in prev.rglob("*.py"):
            removed.append(str(p.relative_to(REPO)).replace("\\", "/"))
        shutil.rmtree(prev, ignore_errors=True)
    return {"added": added, "modified": modified, "removed": removed}


# ---------------------------------------------------------------- bridge host

def make_host(project_id: str):
    from pipeline.mcp_host_sim.hosts.bridge_stdio import BridgeHost

    return BridgeHost(
        repo=REPO,
        project_id=project_id,
        engine_url=ENGINE_URL,
        mcp_client="kiro",  # behave as the Kiro host
        # Keep the install-default 2-min debounce OUT of the way; we stop the
        # engine deterministically ourselves so the test is not timing-flaky.
        env_extra={"CTX_DISCONNECT_DEBOUNCE_S": "8"},
    )


# ---------------------------------------------------------------- verification

def poll_until_fresh(host, expect_tokens: list[str], max_s: float = 180.0) -> dict:
    """After reopen: watch /health pending/index_fresh and confirm the new
    symbols become searchable. Returns timing + the observed pending states."""
    t0 = time.time()
    pending_seen: list[dict | None] = []
    index_fresh_at: float | None = None
    searchable_at: float | None = None
    busy_observed = False
    last_pending = "unset"

    while time.time() - t0 < max_s:
        try:
            h = health()
        except Exception:  # noqa: BLE001
            time.sleep(1.0)
            continue
        p = h.get("pending")
        if p != last_pending:
            pending_seen.append(p)
            last_pending = p
        if isinstance(p, dict) and p.get("substantial"):
            busy_observed = True
        if h.get("index_fresh") and index_fresh_at is None:
            index_fresh_at = time.time() - t0
        # probe searchability of a token from this cycle's additions
        if expect_tokens and searchable_at is None:
            try:
                r = host.map(f"{expect_tokens[0]} marker function", k=5)
                txt = str(r.get("_raw") or r.get("text") or "")
                if any(tok in txt for tok in expect_tokens):
                    searchable_at = time.time() - t0
            except Exception:  # noqa: BLE001
                pass
        if index_fresh_at is not None and (searchable_at is not None or not expect_tokens):
            break
        time.sleep(2.0)

    return {
        "index_fresh_after_s": round(index_fresh_at, 1) if index_fresh_at is not None else None,
        "searchable_after_s": round(searchable_at, 1) if searchable_at is not None else None,
        "busy_pending_observed": busy_observed,
        "pending_transitions": pending_seen,
        "total_wait_s": round(time.time() - t0, 1),
    }


# ---------------------------------------------------------------- one cycle

def run_cycle(cycle: int, files: int, project_id: str) -> dict:
    rec: dict = {"cycle": cycle, "files": files, "steps": {}}
    print(f"\n===== CYCLE {cycle} ({files} offline files) =====", flush=True)

    # 1. OPEN the bridge (Kiro host) — registers client, warms engine
    host = make_host(project_id)
    t = time.time()
    start = host.start()
    rec["steps"]["open"] = {"ok": bool(start.get("ok")), "warm_ms": round((time.time() - t) * 1000)}
    print(f"[open] bridge pid={start.get('pid')} ok={start.get('ok')}", flush=True)
    # confirm warm/ready via the real gate+status tools
    try:
        g = host.gate()
        rec["steps"]["open"]["gate"] = g.get("text")
    except Exception as e:  # noqa: BLE001
        rec["steps"]["open"]["gate_err"] = str(e)

    # 2. CLOSE — stop the bridge (EOF -> unregister), then stop the engine process
    host.stop()
    print("[close] bridge stopped (stdin EOF -> unregister)", flush=True)
    engine_stop()
    down_s = wait_engine_down(max_s=45)
    rec["steps"]["close"] = {"engine_down": not engine_running(), "down_after_s": round(down_s, 1)}
    print(f"[close] engine down after {down_s:.1f}s -> {not engine_running()}", flush=True)

    # 3. EDIT on disk while the engine is OFF
    edits = apply_offline_edits(cycle, files)
    rec["steps"]["offline_edits"] = {
        "added": len(edits["added"]),
        "modified": len(edits["modified"]),
        "removed": len(edits["removed"]),
    }
    print(f"[edit] offline: +{len(edits['added'])} ~{len(edits['modified'])} "
          f"-{len(edits['removed'])} (engine was down)", flush=True)

    # 4. REOPEN — cold warm runs _reconcile_offline(start) with no manual trigger
    host2 = make_host(project_id)
    t = time.time()
    start2 = host2.start()
    rec["steps"]["reopen"] = {"ok": bool(start2.get("ok")), "warm_ms": round((time.time() - t) * 1000)}
    print(f"[reopen] bridge pid={start2.get('pid')} ok={start2.get('ok')}", flush=True)

    # 5. VERIFY offline drift is detected + drained + searchable
    tokens = [f"c{cycle}new0", f"c{cycle}new{files - 1}"] if files > 0 else []
    verify = poll_until_fresh(host2, tokens, max_s=180)
    rec["steps"]["verify"] = verify
    print(f"[verify] index_fresh@{verify['index_fresh_after_s']}s "
          f"searchable@{verify['searchable_after_s']}s "
          f"busy_pending={verify['busy_pending_observed']} "
          f"pending_states={verify['pending_transitions']}", flush=True)

    # grade the cycle
    ok = (
        rec["steps"]["open"]["ok"]
        and rec["steps"]["reopen"]["ok"]
        and verify["index_fresh_after_s"] is not None
        and (not tokens or verify["searchable_after_s"] is not None)
    )
    rec["pass"] = bool(ok)
    print(f"[cycle {cycle}] {'PASS' if ok else 'FAIL'}", flush=True)

    host2.stop()
    return rec


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--files", type=int, default=30, help="new files added per offline cycle")
    ap.add_argument("--project-id", default="")
    ap.add_argument("--keep", action="store_true", help="leave the sim subtree on disk")
    args = ap.parse_args()

    # resolve project_id
    project_id = args.project_id
    if not project_id:
        from pipeline.project_id import peek_project

        ref = peek_project(REPO)
        if ref is None:
            print("ERROR: repo not enrolled. Run `scubiee init .` first.", file=sys.stderr)
            return 2
        project_id = ref.project_id
    print(f"[sim] repo={REPO} project_id={project_id} cycles={args.cycles} files={args.files}", flush=True)

    # ensure a clean start: engine up + baseline present + indexed
    if not engine_running():
        print("[sim] starting engine…", flush=True)
        _scubiee("engine", "start", str(REPO), "--wait", "90", timeout=150)
    seed_baseline(args.files)
    # one dirty nudge + settle so the baseline is in the generation before we begin
    try:
        urllib.request.urlopen(  # noqa: S310
            urllib.request.Request(
                f"{ENGINE_URL}/v1/dirty",
                data=json.dumps({"path": str(REPO),
                                 "paths": [f"scripts/perf/_offline_sim/base_{i}.py"
                                           for i in range(max(1, args.files // 4))],
                                 "reason": "sim_baseline"}).encode(),
                headers={"Content-Type": "application/json"}, method="POST"),
            timeout=10)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(8)

    results = []
    for c in range(1, args.cycles + 1):
        try:
            results.append(run_cycle(c, args.files, project_id))
        except Exception as e:  # noqa: BLE001
            import traceback
            results.append({"cycle": c, "pass": False, "error": str(e),
                            "trace": traceback.format_exc()[-1500:]})
            print(f"[cycle {c}] EXCEPTION: {e}", flush=True)
            # make sure the engine is back for the next cycle
            if not engine_running():
                _scubiee("engine", "start", str(REPO), "--wait", "90", timeout=150)

    # cleanup: delete the sim subtree, then one more reopen so the engine
    # reconciles the deletion back out (leaves the index clean).
    if not args.keep:
        shutil.rmtree(SIM_DIR, ignore_errors=True)
        print("[cleanup] removed sim subtree; reconciling the deletion…", flush=True)
        try:
            engine_stop(); wait_engine_down(30)
            _scubiee("engine", "start", str(REPO), "--wait", "90", timeout=150)
            time.sleep(8)
        except Exception:  # noqa: BLE001
            pass

    passed = sum(1 for r in results if r.get("pass"))
    summary = {
        "repo": str(REPO),
        "project_id": project_id,
        "cycles": args.cycles,
        "files_per_cycle": args.files,
        "passed": passed,
        "failed": args.cycles - passed,
        "verdict": "PASS" if passed == args.cycles else "FAIL",
        "results": results,
    }
    REPORT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n===== VERDICT: {summary['verdict']} ({passed}/{args.cycles}) ====="
          f"\nreport: {REPORT}", flush=True)
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
