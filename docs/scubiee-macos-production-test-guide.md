# Scubiee macOS production test guide

**Audience:** an agent (or engineer) on a **macOS** machine, pulling this repo fresh.
**Goal:** reproduce the full production-readiness verification that was done on Windows,
on macOS/Apple-Silicon, and report the numbers back so we can confirm cross-platform
production readiness.

This document is **self-contained** — you do not need any prior session context. Follow it
top to bottom. Everything you need (the simulator, the thresholds, the commands) is in the repo.

---

## 0. Why this matters / what we already know

All functional + performance verification so far was done on **Windows / DirectML** and passed
(see `docs/scubiee-production-readiness-report.md`). Two fixes in this release are **platform-
specific** and were only *run* on Windows, so macOS is the unverified surface:

- **grep spawn fix** (`packages/pipeline/capability.py::_grep_via_rg`): on Windows it adds
  `CREATE_NO_WINDOW` + hidden `STARTUPINFO`. On macOS/Linux `windows_stdio_hidden_kwargs()`
  returns `{}`, so the code path is a plain `subprocess.run` with UTF-8 decode. **Expected to be
  a no-op difference, but must be confirmed it is actually fast on macOS** (ripgrep spawn cost is
  a non-issue on macOS, so grep should be fast without the flag).
- **path canonicalization** (BUG-1): the Windows bug was `os.path.normcase` folding case +
  backslashes. macOS is **case-insensitive but case-preserving** by default (HFS+/APFS), and uses
  forward slashes — a *different* path regime. The newcomer-canonicalization fix must be confirmed
  to behave correctly here too.

Everything else (sync correctness, blue/green reindex, loud grep) is platform-neutral but should
still be exercised.

The embedder backend differs: macOS Apple Silicon uses **MLX (Metal)**, not DirectML. Warm-up
timing and dense-ready latency will differ from the Windows numbers — that is expected; capture
the macOS numbers, don't compare 1:1.

---

## 1. Environment assumptions

- macOS 13+ (Ventura or newer). Apple Silicon (M1–M4) strongly preferred; Intel Mac is CPU/CoreML.
- Python 3.11+ available. `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- `git` available. Repo cloned.
- **ripgrep**: macOS editors (VS Code / Cursor / Kiro) bundle `@vscode/ripgrep`; the engine's
  `_resolve_ripgrep()` finds it under `~/.vscode*`, `/Applications`, `/opt`, `/usr/share`. If none
  is found it falls back to a pure-Python scan (slower but correct). Optionally `brew install
  ripgrep` to guarantee a PATH copy — note which case you're in.

Record exact versions:
```bash
sw_vers                      # macOS version
uname -m                     # arm64 (Apple Silicon) or x86_64 (Intel)
python3 --version
uv --version
which rg && rg --version || echo "rg not on PATH (engine will use bundled or python fallback)"
```

---

## 2. Build + install the release

From the repo root:

```bash
# 1. Build the wheel (needs the 'build' module; use any python that has it)
python3 -m pip install --user build 2>/dev/null || true
python3 -m build --wheel --outdir dist_prod

# 2. Install as a uv tool (isolated)
uv tool install --force --reinstall dist_prod/scubiee-0.3.143-py3-none-any.whl

# 3. One-time setup: detects Apple Silicon -> MLX profile, installs mlx + FastEmbed
scubiee setup

# 4. Index this repo (first index is a full build; expect minutes on first run)
scubiee index . --force

# 5. Start the engine and wait for warm
scubiee engine start --wait 120
scubiee engine status
```

Confirm the engine is up and on the MLX profile:
```bash
curl -s http://127.0.0.1:8765/health | python3 -m json.tool
```
Expect `"version": "0.3.143"`, `"warm": true`, `"index_usable": true`, and eventually
`"dense_ready": true`. The accel profile should be `mlx` on Apple Silicon — verify:
```bash
scubiee resources 2>/dev/null | grep -i -E "profile|accel|mlx|metal" || true
```

---

## 3. Run the automated readiness simulator (primary gate)

The repo ships a self-contained simulator that measures every production dimension against
explicit thresholds and prints a PASS/FAIL per dimension plus a JSON report.

```bash
# Full run: cold-start timing (restarts the engine twice) + 180s soak. ~10-12 min.
python3 scripts/perf/prod_sim.py
```

It writes `scripts/perf/_prodsim_report.json` and prints a scorecard. The dimensions and their
thresholds (defined at the top of `scripts/perf/prod_sim.py`):

| Dimension | What it measures | Threshold |
|---|---|---|
| A. cold_start | engine stop→start→soft_search_ready / dense_ready | soft ≤30s |
| B. tool_latency | grep + locate warm p50/p95, cold first-call | grep p95 ≤3s, locate p95 ≤4s |
| C. concurrency | 8 parallel clients, error rate (steady state) | error rate ≤2% |
| D. large_repo | full-glob grep finds a deep symbol, complete, locate | deep symbol found + complete |
| E. soak | 180s dirty→sync→search→delete churn | 0 errors, drift ≤2.5x, sync p95 ≤5s |

**Pass condition:** `"all_pass": true` in the report. If a dimension fails, do NOT stop — capture
the numbers and continue; the point is to learn where macOS differs.

Quick smoke variant (skips cold restart + short soak) if you want a fast first look:
```bash
python3 scripts/perf/prod_sim.py --quick
```

---

## 4. Measure the SHIPPED MCP tools end-to-end (map find / focus)

The simulator measures internal endpoints. Also measure the two tools agents actually call —
`map config=find` and `map config=focus` — through the engine. Paste this into a file
`scripts/perf/_mac_map_bench.py` (delete it after) and run it:

```python
import json, time, urllib.request
from pathlib import Path
BASE="http://127.0.0.1:8765"; ROOT=Path.cwd()
def p(path, body):
    s=time.perf_counter()
    req=urllib.request.Request(BASE+path, data=json.dumps(body).encode(),
                               headers={"Content-Type":"application/json"})
    r=json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    return (time.perf_counter()-s)*1000, r
def pctl(xs,q):
    xs=sorted(xs); import math; k=max(0,min(len(xs)-1,round(q/100*(len(xs)-1)))); return round(xs[k],1)
# wait fully warm
for _ in range(120):
    try:
        h=json.loads(urllib.request.urlopen(BASE+"/health",timeout=5).read().decode())
        if h.get("embedder_loaded") and not h.get("embed_prewarm_running"): break
    except Exception: pass
    time.sleep(1)
find_q=["where is ripgrep spawned","how does staged index promote work",
        "canonical path merkle key","sync publish engine generation",
        "embedder prewarm readiness","faiss collection swap"]
syms=["promote_staged_store","_grep_via_rg","canonical_relpath","incremental_sync","publish_engine","swap_collection"]
lat=[]
for q in find_q*3:
    try: ms,_=p("/v1/locate",{"query":q,"top_k":5,"path":str(ROOT)}); lat.append(ms)
    except Exception as e: print("find err",e)
print(f"map find  p50={pctl(lat,50)}ms p95={pctl(lat,95)}ms n={len(lat)}")
lat=[]
for sym in syms*3:
    try:
        ms,gi=p("/v1/grep_ident",{"ident":sym,"path":str(ROOT),"max_hits":5}); t=ms
        hits=gi.get("hits") or []
        if hits:
            h=hits[0]; ms2,_=p("/v1/read_span",{"file":h.get("path") or h.get("file"),
                "start_line":max(1,int(h.get("line",1))),"end_line":int(h.get("line",1))+40,"path":str(ROOT)}); t+=ms2
        lat.append(t)
    except Exception as e: print("focus err",e)
print(f"map focus p50={pctl(lat,50)}ms p95={pctl(lat,95)}ms n={len(lat)}")
```
```bash
python3 scripts/perf/_mac_map_bench.py
rm scripts/perf/_mac_map_bench.py
```
**Expected:** both well under 1s (Windows got find ~54ms, focus ~258ms). macOS may differ; record it.

---

## 5. Sync correctness battery (the thing that was originally broken)

Run the committed sync battery — it exercises add / modify / partial-edit / delete / rapid-churn
and asserts each becomes searchable:

```bash
python3 scripts/perf/probe_sync_battery.py
```
**Expected:** every case `"pass": true`, new-file visible in ~1s or less, 0 errors. This is the
BUG-1/BUG-5 regression guard — it MUST pass on macOS.

Also confirm the newcomer-canonicalization is correct on the macOS path regime:
```bash
PYTHONPATH=packages python3 scripts/perf/probe_bug1_newcomers.py
```
**Expected:** "FIXED subtraction = 0 newcomers" on a clean, freshly-indexed corpus (i.e. an
already-indexed file is NOT re-flagged as new). If macOS case-insensitivity causes a mismatch,
this will show a non-zero FIXED count — flag it.

---

## 6. Zero-downtime forced reindex

Confirm `index --force` keeps the engine serving on macOS (blue/green promote is platform-neutral,
but verify):

```bash
# Terminal 1: start a health poller
while true; do
  curl -s -o /dev/null -w "%{http_code} " http://127.0.0.1:8765/health 2>/dev/null || echo -n "DOWN "
  sleep 2
done
```
```bash
# Terminal 2: force a reindex while the poller runs
scubiee index . --force
```
**Expected:** the poller shows `200` continuously (no `DOWN`) throughout the rebuild, then the
`index` command prints `"engine": {... "ok": true ...}`. Stop the poller (Ctrl-C) when done.

---

## 7. Offline unit tests

```bash
# logfire/opentelemetry may be noisy or broken in some envs; disable the plugin.
PYTHONPATH=packages python3 -m pytest \
  tests/test_newcomer_canonical_keys.py \
  tests/test_grep_glob_scope.py \
  tests/test_capability_promotion.py \
  tests/test_sync_status_canaries.py \
  tests/test_sync_corpus_alignment.py \
  tests/test_graph_catchup_async.py \
  tests/test_incremental_confirm.py \
  -p no:logfire -q
```
**Expected:** all pass (Windows: 53 passed). If `fastembed` or `mlx` import issues appear, note
them — the macOS wheel set differs.

---

## 8. What to report back

Create `docs/scubiee-macos-test-results.md` in the repo with:

1. **Environment:** `sw_vers`, `uname -m`, python version, chip (M1/M2/M3/M4 or Intel),
   whether `rg` was on PATH / bundled / python-fallback, accel profile (`mlx`/`coreml`/`cpu`).
2. **prod_sim verdict:** paste the scorecard + `all_pass` value + the per-dimension numbers from
   `scripts/perf/_prodsim_report.json`.
3. **map find/focus** p50/p95 from section 4.
4. **sync battery:** pass/fail per case + new-file visible latency.
5. **newcomer probe:** the FIXED-subtraction count (must be 0).
6. **zero-downtime reindex:** did the poller stay 200 throughout? (yes/no)
7. **unit tests:** passed/failed count.
8. **Anything slow or broken**, with the raw numbers. Specifically call out:
   - grep latency (p50/p95) — on macOS it should be fast *without* the Windows console fix; confirm.
   - cold-start soft-ready and dense-ready seconds (MLX warm-up will differ from DirectML).
   - any `UnicodeDecodeError`, crash, or engine-down event in `~/.scubiee/engine.log`.

Commit that results file and push. Once it shows `all_pass: true` (or only expected-and-explained
differences), we confirm **cross-platform production ready**.

---

## 9. Known differences to EXPECT on macOS (not failures)

- **Dense-ready latency** differs — MLX Metal warm-up vs DirectML. Capture the number; don't fail on it.
- **grep** should be fast with no special spawn flags (the Windows console tax does not exist on macOS).
- **Path case-insensitivity**: APFS is case-insensitive by default. `canonical_relpath` lowercases
  only on Windows (`os.name == "nt"`); on macOS it keeps original case. Confirm the sync battery
  and newcomer probe still pass — if a rename that only changes case behaves oddly, flag it (it's a
  macOS-specific edge the Windows run could not cover).
- **First cold grep** may still be a second or two (ripgrep cold process + first tree walk) — a
  one-time startup cost, acceptable.

## 10. Cleanup

```bash
# remove any temp bench file you created; the committed probes/sim stay
rm -f scripts/perf/_mac_map_bench.py
# the generated report is fine to leave for the results commit, or delete:
# rm -f scripts/perf/_prodsim_report.json
```
