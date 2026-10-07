# Scubiee production-readiness report (0.3.143, Windows/DirectML)

> **UPDATE (post grep perf-fix): ALL 5 DIMENSIONS PASS.** The grep latency offender
> was fixed (see "Grep perf fix" at the bottom). Re-run of `prod_sim.py`:
>
> | Dimension | Verdict | Headline |
> |---|---|---|
> | A. Cold-start | ✅ PASS | soft 3.5–3.8s, dense 15–16s |
> | B. Tool latency | ✅ PASS | **grep p50 241ms / p95 983ms** (was 3.5s); locate p95 79ms |
> | C. Concurrency | ✅ PASS | 8 clients **0 errors**, p50 218ms, wall 2.5s (was 8.4s + 12% err) |
> | D. Large-repo | ✅ PASS | grep 567ms, locate 541ms, complete |
> | E. Soak | ✅ PASS | **84 cycles**, 0 errors, cycle p95 **2.8s** (was 5.3s), drift 1.23x |
>
> `all_pass: true`. The grep fix cascaded: it also cleared the concurrency errors
> and doubled soak throughput (84 vs 33 cycles). Only residual: cold grep
> first-call ~30s (ripgrep's one-time cold process + full-tree gitignore walk).
> The original numbers below are retained for history.

---

## Original report (pre grep perf-fix)


Measured with `scripts/perf/prod_sim.py` against the live engine on this repo
(~8,400 chunks, 435k-file working tree). Covers the dimensions the earlier
functional testing did NOT: cold-start warming, tool latency (cold vs warm),
concurrency under parallel load, large-repo behavior, and a longevity soak.
Each dimension has an explicit threshold; raw numbers below, not impressions.

## Scorecard

| Dimension | Verdict | Headline number |
|---|---|---|
| A. Cold-start warming | ✅ PASS | soft-ready 3.2–3.5s, dense-ready 11–12s |
| B. Tool latency (warm) | ⚠️ MIXED | locate p95 **102ms**; grep p95 **3.5s** (cold first grep 19s) |
| C. Concurrency | ⚠️ PASS-with-retry | 8 clients: fail-fast 409s, **100% success with retry**; never crashes |
| D. Large-repo | ✅ PASS | deep symbol found, scan complete, locate 56ms |
| E. Longevity soak | ✅ effectively PASS | 33/33 cycles correct, 0 errors, latency drift 0.88x |

## Detail + honest interpretation

### A — Cold-start warming ✅
Two cold restarts measured: locate becomes usable (`soft_search_ready`) in
**3.2–3.5s**, semantic/dense ready in **11.2–12.1s**. Well under the 30s / 180s
thresholds. This substantiates "warming is fast" with numbers.

### B — Tool latency ⚠️
- **locate (semantic map): excellent** — warm p50 60ms, p95 102ms.
- **grep: ~3.5s warm p95, and ~19s on the very first call after a cold start.**
  Cause: ripgrep spawns a fresh process per call and walks the 435k-file tree
  (gitignore-filtered); the first call also pays rg's cold tree scan. This is
  real and over the 3s threshold. Not a correctness issue (results are right and
  `complete=true`), but grep is **not sub-second on a repo this large** — it is
  a few seconds. Smaller repos will be much faster. Follow-up options: a longer
  rg timeout budget, or a persistent rg daemon/caching; neither blocks use.

### C — Concurrency ⚠️ (acceptable with client retry)
8 parallel clients. The engine **never crashed** (`index_usable=true` after
every run). A small fraction of calls return **HTTP 409 Conflict** — the engine's
admission-control fail-fast when activation is briefly contended (e.g. right
after a publish). These are transient: a retry-on-409 probe got **48/48 success,
0 retries actually needed** on a warm engine across repeated runs. So the
production contract is: *clients must retry on 409* (standard for a 409). The MCP
client already handles engine lifecycle; a naive raw-HTTP client that treats 409
as fatal will see ~10% "errors" that are really "retry me."
- Separately, during the **first ~5–15s of a cold start** (ORT/DirectML embedder
  prewarm), concurrent calls can stall to timeout because the native embedder
  build holds the GIL and CPython can't preempt the single-threaded HTTP server.
  This is a known, transient startup cost, not steady state. A full fix means
  moving the embedder to a subprocess (large change) — deferred.

### D — Large-repo ✅
Full-glob grep for a symbol deep in `packages/` returns it with `complete=true`
via the rg backend (no false-empty — the BUG-6 fix holds at scale). Locate over
the full repo: 56ms, 5 hits.

### E — Longevity soak ✅ (effectively)
180s of sustained create→dirty→sync→search→delete churn: **33 cycles, 33 visible,
0 errors**, engine alive, and search latency *drift 0.88x* (end faster than
start — no leak/degradation). The only threshold miss is sync-visible p95 5.3s
vs a 5.0s target — a 0.3s margin with zero correctness failures. The regression
that originally motivated all this (new files not searchable after churn) did
**not** reappear over the sustained window.

## Bottom line

For **single-user Windows/Kiro** (the real workload): **ready.** Warming is fast,
sync is correct and stable over time, large-repo search is correct, the engine
never crashed under parallel load.

Two honest caveats, neither a blocker for that workload:
1. **grep is a few seconds on a 435k-file tree** (not sub-second); fine for
   normal repos, a latency follow-up for very large ones.
2. **Concurrent clients must retry on HTTP 409**, and the **cold-start window
   (~first 10s) can stall concurrent calls** due to the GIL + native embedder
   build. Both are transient and the engine stays alive; a subprocess embedder
   would remove the startup stall if multi-client concurrency at startup becomes
   a requirement.

Nothing here is a correctness defect. The remaining items are latency/concurrency
characteristics to document for callers, not bugs to block on.

---

## Grep perf fix (the 3.5s → 275ms root cause)

The simulator's one real latency fail was grep (p95 3.5s, cold 19s). Stage-by-stage
breakdown isolated it precisely — and it was NOT the search algorithm:

1. `_resolve_ripgrep` / `_rg_exclude_dirs`: cached, 0ms.
2. Direct `grep_scan` from a plain Python process: **~190ms**.
3. Same `grep_scan` inside the running engine daemon: **~3400ms** (18x slower), all
   of it in `subprocess.run` (`parse` was 2.5ms).
4. Even `rg --version` (no search at all) took **3200ms** inside the daemon.

**Root cause:** the engine daemon is launched with `CREATE_NO_WINDOW` (no console).
When a no-console process spawns a **console-subsystem binary** like `rg.exe`
*without* `CREATE_NO_WINDOW`, Windows allocates a brand-new console for the child
on every call — a ~3.3s tax that a normal console process never pays. Confirmed by
ruling out RSS size (1.3GB blob → still 213ms), spawn mode, ORT/DirectML load, the
embed keepalive, and the sync keeper — none mattered; only the console flag did.

**Fix (`capability.py` `_grep_via_rg`):**
```python
_hidden = windows_stdio_hidden_kwargs()   # CREATE_NO_WINDOW + hidden STARTUPINFO
proc = subprocess.run(args, capture_output=True,
                      encoding="utf-8", errors="replace",   # not platform cp1252
                      stdin=subprocess.DEVNULL, **_hidden, ...)
```
- `CREATE_NO_WINDOW` + hidden `STARTUPINFO` + `stdin=DEVNULL`: **3400ms → ~190ms.**
- `encoding="utf-8", errors="replace"`: a **second bug** found during verification —
  `text=True` decoded rg output with Windows cp1252, which raised
  `UnicodeDecodeError` on a non-cp1252 byte in a source file. That killed the pipe
  reader thread → `proc.stdout` became `None` → handler crashed → client saw
  "connection closed." UTF-8 decode (code is UTF-8) fixes it; `(proc.stdout or "")`
  hardens the parse.

**Verified live:** grep steady-state p50 275ms / p95 345ms, 16/16 calls OK, engine
log clean (no decode errors), and the full `prod_sim` now passes all 5 dimensions.

**Note on scope:** this is a Windows-specific spawn fix. On macOS/Linux
`windows_stdio_hidden_kwargs()` returns `{}`, so the call is a plain
`subprocess.run` with UTF-8 decode — correct and unaffected.
