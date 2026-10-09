# Scubiee Windows reliability results

Counterpart to `docs/scubiee-macos-warm-segfault-fix.md`. After the macOS agent
found a ~5-17% warm-start SIGSEGV on Apple Silicon (MLX/Metal + native-lib
concurrent init), this run stress-tests the **same failure classes on Windows**
to confirm the engine does not drop or crash here.

**Platform:** Windows (win32), DirectML. **Version:** scubiee 0.3.143.
**Verdict:** **RELIABLE — the engine never crashes and never drops.** Windows was
not affected by the macOS SIGSEGV class.

---

## 1. Why Windows should (and does) differ from macOS

The macOS crash was concurrent initialization of **MLX/Metal** (not thread-safe)
plus numpy-LAPACK/faiss, bm25, graphify across threads during warm. The macOS fix
serializes the warm build **only on Darwin** (`CTX_SERIAL_WARM`, `sys.platform ==
"darwin"`); **Windows keeps the parallel warm path** (`ThreadPoolExecutor`
building faiss/bm25/graph while ORT/DirectML warms on another thread).

This run confirms that parallel path is safe on Windows: DirectML/ORT handles
concurrent initialization without the wild-pointer crash MLX exhibited.

---

## 2. Cold-restart reliability (mirror of the macOS SIGSEGV hunt)

Harness: `scripts/perf/_win_restart_reliability.py` — loop `engine stop` →
`engine start` → poll `/health` until `soft_search_ready`, per iteration detect
crash (health never returns), never-warmed, and **new fatal lines** in
`~/.scubiee/engine.log` (`Fatal Python error`, `Segmentation`, `0xC0000005`,
`EXCEPTION_ACCESS_VIOLATION`, `Windows fatal exception`).

**30 cold restarts:**

| Metric | Result |
|---|---|
| crashes | **0** |
| never-warmed | **0** |
| fatal log lines | **0** |
| soft-ready p50 / p95 | **4.4s / 4.7s** (max 5.1s) |

Every single run: `crashed=false`, `never_warm=false`, `fatal=[]`. Warm-up timing
is tight and consistent (no multi-second outliers). Result:
`scripts/perf/_win_restart_result.json`.

**Comparison:** macOS baseline before its fix was ~5-17% crash rate; Windows is
**0/30**. The parallel warm path is reliable here.

---

## 3. Mid-session stress

Harness: `scripts/perf/_win_midsession_stress.py`.

### A. Concurrent load during + after warm (8 clients, cold start, 40s)
| Signal | Count |
|---|---|
| ok | 25 |
| retryable 409/403 | 0 |
| **conn_closed** | **0** |
| **http_5xx** | **0** |
| **other_err** | **0** |
| timeout | 16 |
| engine_alive_after | **true** |

**No crashes, no dropped connections, no 5xx.** The 16 timeouts all occur in the
**DirectML/ORT embedder prewarm window** (~first 5-15s) — the known GIL-contention
behavior already documented in `docs/archive/qa-bug-reports/scubiee-production-readiness-report.md`
(the native ORT session build holds the GIL; concurrent `/v1/*` calls stall until
it finishes, then recover). This is a *transient warm-window latency* condition,
recoverable with client retry — **not** an engine drop or crash. The engine was
alive and `index_usable` after the burst.

### B. `index --force` x2 while polling `/health` every 0.5s
| Metric | Result |
|---|---|
| health polls UP (200) | **2309** |
| health polls DOWN | **0** |
| reindexes succeeded | **2 / 2** |
| engine_alive_after | **true** |

**2309 consecutive successful health checks, zero DOWN**, across two full forced
reindexes. The blue/green staged promote keeps the engine serving throughout the
rebuild on Windows — identical to the macOS result. This is the strongest
reliability signal: the engine never drops even during a destructive full reindex.

Post-stress engine health: `warm=true, index_usable=true, dense_ready=true,
chunks=8453`. `~/.scubiee/engine.log` has **no** `Fatal` / `Segmentation` /
`0xC0000005` / access-violation lines from this run.

---

## 4. Verdict

| Failure class | macOS (pre-fix) | Windows |
|---|---|---|
| Warm-start crash / SIGSEGV | ~5-17% | **0 / 30** |
| Never-warmed | occasional | **0 / 30** |
| Engine drop during reindex | n/a (fixed via blue/green) | **0 drops / 2309 polls** |
| Fatal log lines | present | **none** |
| Concurrent-during-warm | timeouts (transient) | timeouts (transient, 0 crashes) |

**Windows is reliable: the engine does not crash and does not drop.** The one
non-ideal behavior — some concurrent requests timing out during the first ~5-15s
of embedder prewarm — is a transient latency condition (recoverable with retry),
the same documented GIL characteristic, not an instability. No Windows-side fix is
needed; the macOS serial-warm change correctly left the Windows parallel path
untouched.

### Open (unchanged, by design)
- Concurrent calls during the cold-start embedder-prewarm window can time out
  until the native ORT session finishes building. A client that retries (or waits
  for `dense_ready`) is unaffected. A full fix would move the embedder to a
  subprocess (large change, deferred) — tracked in the production-readiness report.
