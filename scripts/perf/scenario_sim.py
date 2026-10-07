"""Scubiee scenario simulator — HIGH-priority pre-production scenarios.

Covers (from docs/scubiee-scenario-test-matrix.md):
  D2  big pull within caps        -> all searchable, engine never down, no oversize
  D3  huge pull beyond caps       -> needs_full/oversize surfaced, NOT a silent false
                                     publish; old index still served (stale, not down)
  E3  interrupted reindex         -> kill index --force mid-run; old index still usable
                                     (no torn generation); engine recovers
  B4  idle -> requery             -> after an idle gap the next query is correct
  F3  query during promote        -> queries during a staged promote stay coherent

Global invariants checked throughout: G1 no crash (engine.log fatal scan),
G2 /health coherent, G3 no confident-empty, G4 no torn generation (index_usable).

SAFE BY DESIGN: all file churn happens in scripts/perf/_scenario/ (throwaway),
dirtied via /v1/dirty — never touches real git history or the working tree.
Only E3 stops/kills the engine process (watchdog + ensure brings it back).

Run: python scripts/perf/scenario_sim.py            (all)
     python scripts/perf/scenario_sim.py D2 D3       (subset)
"""
from __future__ import annotations
import json, subprocess, sys, threading, time, urllib.request, urllib.error, shutil
from pathlib import Path

BASE = "http://127.0.0.1:8765"
SCUBIEE = shutil.which("scubiee") or r"C:/Users/usman/AppData/Roaming/uv/tools/scubiee/Scripts/scubiee.exe"
REPO = Path(__file__).resolve().parents[2]
WORK = REPO / "scripts" / "perf" / "_scenario"
ENGINE_LOG = Path.home() / ".scubiee" / "engine.log"
OUT = REPO / "scripts" / "perf" / "_scenario_result.json"
FATAL = ("Fatal Python error", "Segmentation", "0xC0000005", "0xc0000005",
         "EXCEPTION_ACCESS_VIOLATION", "Windows fatal exception")


def post(path, body, timeout=60):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read().decode())


def health(timeout=4):
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=timeout) as r:  # noqa: S310
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return None


def log_size():
    try:
        return ENGINE_LOG.stat().st_size
    except OSError:
        return 0


def fatal_since(offset):
    try:
        with ENGINE_LOG.open("rb") as f:
            f.seek(offset)
            txt = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return [ln.strip()[:140] for ln in txt.splitlines() if any(m in ln for m in FATAL)]


def rel(p: Path) -> str:
    return p.relative_to(REPO).as_posix()


def grep(token, glob="scripts/perf/_scenario/**/*.py", timeout=20):
    return post("/v1/grep", {"pattern": token, "path": str(REPO), "glob": glob, "max_hits": 5}, timeout)


def wait_warm(budget=120):
    t = time.perf_counter() + budget
    while time.perf_counter() < t:
        h = health()
        if h and h.get("index_usable"):
            return True
        time.sleep(1)
    return False


def visible(token, budget=40.0, want=True):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < budget:
        try:
            g = grep(token)
            if bool(g.get("hits")) == want:
                return time.perf_counter() - t0
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0)
    return None


# ---------------- D2: big pull within caps ----------------
def scn_D2(stamp):
    log0 = log_size()
    WORK.mkdir(parents=True, exist_ok=True)
    n = 300  # a "big pull" sized batch, well under the 25k touch / 10k chunk caps
    toks, rels = [], []
    for i in range(n):
        t = f"D2_{stamp}_{i}"
        f = WORK / f"d2_{stamp}_{i}.py"
        f.write_text(f"def {t.lower()}():\n    return {t!r}\n", encoding="utf-8")
        toks.append(t); rels.append(rel(f))
    # dirty all at once (simulates a pull landing many files), then sync
    post("/v1/dirty", {"paths": rels, "reason": "scn_d2_bigpull", "path": str(REPO)})
    time.sleep(1.5)
    s = post("/v1/sync", {"path": str(REPO)})
    down = 0
    # poll health while it settles; sample visibility of a few tokens
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 90:
        if health() is None:
            down += 1
        if visible(toks[0], budget=1.0) and visible(toks[n//2], budget=1.0) and visible(toks[-1], budget=1.0):
            break
        time.sleep(1.0)
    seen = sum(1 for tk in (toks[0], toks[n//2], toks[-1], toks[n//4], toks[3*n//4])
               if visible(tk, budget=15.0))
    oversize = "exceeding the automatic limit" in str(s.get("error") or "")
    h = health()
    return {
        "files": n, "sync_strategy": s.get("strategy"), "sync_error": s.get("error"),
        "oversize_refusal": oversize, "sampled_visible": f"{seen}/5",
        "health_down_polls": down, "engine_alive_after": h is not None and h.get("index_usable"),
        "fatal": fatal_since(log0),
        "pass": seen == 5 and not oversize and down == 0 and h is not None and not fatal_since(log0),
    }


# ---------------- D3: huge pull beyond caps ----------------
_D3_SNIPPET = r'''
import os, sys, json
os.environ["CTX_AUTO_FULL_INDEX_CHUNKS"] = "5"   # any real change-set exceeds this
os.environ["CTX_INCREMENTAL_MAX_TOUCH"] = "5"
sys.path.insert(0, r"{pkgs}")
from pathlib import Path
from pipeline.incremental import incremental_sync
# a real multi-file change-set (the scenario files already exist on disk)
res = incremental_sync(Path(r"{repo}"), discover_newcomers=True, inline=True)
d = res.to_dict() if hasattr(res, "to_dict") else dict(res)
print(json.dumps({{"strategy": d.get("strategy"), "refreshed": d.get("refreshed"),
                   "error": d.get("error"), "chunks_upserted": d.get("chunks_upserted")}}))
'''

def scn_D3(stamp):
    """Beyond-caps pull must SURFACE needs_full/oversize, never silently publish a
    half index, and keep serving the old generation.

    The running daemon was started with default caps, so we exercise the exact
    guard path INLINE in a subprocess with the caps lowered (env honored at
    import time, like probe_bug1_inline_sync). The live engine is untouched and
    must keep serving the old index throughout."""
    import os as _os
    log0 = log_size()
    WORK.mkdir(parents=True, exist_ok=True)
    for i in range(12):
        t = f"D3_{stamp}_{i}"
        (WORK / f"d3_{stamp}_{i}.py").write_text(
            f"def {t.lower()}():\n    return {t!r}\n", encoding="utf-8")
    # old index must still serve BEFORE and AFTER the oversize attempt
    before = grep("def grep_scan", glob="packages/pipeline/**/*.py", timeout=20)
    snippet = _D3_SNIPPET.format(pkgs=str(REPO / "packages"), repo=str(REPO))
    proc = subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True, timeout=300)
    out = (proc.stdout or "").strip()
    try:
        parsed = json.loads(out.splitlines()[-1]) if out else {}
    except Exception:  # noqa: BLE001
        parsed = {}
    strat = str(parsed.get("strategy") or "")
    err = str(parsed.get("error") or "")
    # The guard surfaced the over-cap change-set via ANY of its refusal paths:
    #  - the chunk-count cap  -> strategy explicit_full_index_required / "exceeding the automatic limit"
    #  - the touch-count cap  -> IndexConfirmRequired "Safety pause: N files ... cap M ... --confirm"
    # In every case it must NOT have silently published (refreshed with no error).
    surfaced = ("explicit_full_index_required" in strat
                or "exceeding the automatic" in err
                or "Safety pause" in err
                or "--confirm" in err
                or "--force" in err)
    not_false_published = not (bool(parsed.get("refreshed")) and not err)
    h = health()
    after = grep("def grep_scan", glob="packages/pipeline/**/*.py", timeout=20)
    old_served = bool(before.get("hits")) and bool(after.get("hits"))
    return {
        "inline_strategy": strat, "inline_error": err[:120],
        "surfaced_needs_full": surfaced, "not_false_published": not_false_published,
        "engine_alive_after": h is not None and h.get("index_usable"),
        "old_index_served_before_and_after": old_served,
        "fatal": fatal_since(log0),
        "pass": surfaced and not_false_published and h is not None and old_served and not fatal_since(log0),
    }


# ---------------- E3: interrupted reindex ----------------
def scn_E3(stamp):
    log0 = log_size()
    if not wait_warm():
        return {"pass": False, "reason": "engine not warm pre-test"}
    # start index --force, let it run a few seconds (into embed), then kill it
    p = subprocess.Popen([SCUBIEE, "index", ".", "--force"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(20)  # let it get into the staged build
    p.kill()
    try:
        p.wait(timeout=15)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(3)
    # The OLD generation must still be usable — staged build never touched live.
    # index_is_usable on the live store should hold; a known symbol still served.
    h = health()
    # engine may need a moment / watchdog; give it a chance
    if h is None:
        wait_warm(budget=90)
        h = health()
    known = grep("def promote_staged_store", glob="packages/pipeline/**/*.py", timeout=20)
    old_served = bool(known.get("hits"))
    # no leftover staging dir corrupting the store
    import os as _os
    proj_root = Path.home() / ".scubiee" / "projects"
    staging_leftovers = []
    try:
        for d in proj_root.glob("*.staging-*"):
            staging_leftovers.append(d.name)
    except OSError:
        pass
    return {
        "engine_alive_after": h is not None and h.get("index_usable"),
        "old_index_still_served": old_served,
        "staging_leftovers": staging_leftovers,
        "fatal": fatal_since(log0),
        "pass": h is not None and old_served and not fatal_since(log0),
    }


# ---------------- B4: idle -> requery ----------------
def scn_B4(stamp):
    log0 = log_size()
    if not wait_warm():
        return {"pass": False, "reason": "engine not warm pre-test"}
    idle_s = 60.0  # a quiet gap (not full idle-stop window, but enough to demote)
    time.sleep(idle_s)
    # first query after idle must be correct (may be a touch slower)
    t0 = time.perf_counter()
    g = grep("def canonical_relpath", glob="packages/pipeline/**/*.py", timeout=30)
    ms = (time.perf_counter() - t0) * 1000
    h = health()
    return {
        "idle_s": idle_s, "requery_ms": round(ms), "hits": g.get("count"),
        "engine_alive_after": h is not None,
        "fatal": fatal_since(log0),
        "pass": bool(g.get("hits")) and h is not None and not fatal_since(log0),
    }


# ---------------- F3: query during promote ----------------
def scn_F3(stamp):
    log0 = log_size()
    if not wait_warm():
        return {"pass": False, "reason": "engine not warm pre-test"}
    results = {"ok": 0, "empty": 0, "err": 0}
    stop = threading.Event()

    def querier():
        while not stop.is_set():
            try:
                g = grep("def grep_scan", glob="packages/pipeline/**/*.py", timeout=15)
                if g.get("hits"):
                    results["ok"] += 1
                else:
                    # empty while a known symbol exists = a coherency failure IF complete
                    if g.get("complete", True):
                        results["empty"] += 1
                    else:
                        results["ok"] += 1  # incomplete is honestly flagged, acceptable
            except Exception:  # noqa: BLE001
                results["err"] += 1
            time.sleep(0.3)

    qt = threading.Thread(target=querier)
    qt.start()
    # trigger a staged promote via index --force while querying
    proc = subprocess.run([SCUBIEE, "index", ".", "--force"], capture_output=True, text=True, timeout=1200)
    stop.set()
    qt.join()
    h = health()
    return {
        "reindex_rc": proc.returncode, "query_ok": results["ok"],
        "query_false_empty": results["empty"], "query_err": results["err"],
        "engine_alive_after": h is not None and h.get("index_usable"),
        "fatal": fatal_since(log0),
        # PASS = never a confident-empty (G3) and never an error/down during promote
        "pass": results["empty"] == 0 and results["err"] == 0 and h is not None and not fatal_since(log0),
    }


SCENARIOS = {"D2": scn_D2, "D3": scn_D3, "E3": scn_E3, "B4": scn_B4, "F3": scn_F3}


def cleanup():
    try:
        if WORK.exists():
            shutil.rmtree(WORK, ignore_errors=True)
    except OSError:
        pass


def main():
    which = [a for a in sys.argv[1:] if a in SCENARIOS] or list(SCENARIOS)
    stamp = int(time.time())
    report = {}
    if health() is None:
        print("ENGINE DOWN — start it first"); return 2
    try:
        for name in which:
            print(f"[scenario] {name} ...", flush=True)
            try:
                report[name] = SCENARIOS[name](stamp)
            except Exception as e:  # noqa: BLE001
                report[name] = {"pass": False, "error": repr(e)}
            r = report[name]
            print(f"  -> pass={r.get('pass')} {json.dumps({k:v for k,v in r.items() if k!='pass'})[:200]}")
            # dirty-cleanup scenario files between runs
            for p in list(WORK.glob("*.py")) if WORK.exists() else []:
                try:
                    rp = rel(p); p.unlink()
                    post("/v1/dirty", {"paths": [rp], "reason": "scn_cleanup", "path": str(REPO)})
                except Exception:  # noqa: BLE001
                    pass
    finally:
        cleanup()
        report["all_pass"] = all(v.get("pass") for v in report.values() if isinstance(v, dict))
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n==================== SCENARIO RESULTS ====================")
    for k, v in report.items():
        if k == "all_pass":
            continue
        print(f"  [{'PASS' if v.get('pass') else 'FAIL'}] {k}")
    print(f"ALL PASS: {report.get('all_pass')}")
    print("=========================================================")
    return 0 if report.get("all_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
