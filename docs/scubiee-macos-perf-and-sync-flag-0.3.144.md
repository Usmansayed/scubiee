# Scubiee macOS v0.3.144 — Performance, Idle/Wake & Large-Sync Flag

_Platform: macOS 26.5.2, Apple Silicon (M5, arm64), MLX/Metal. Build: scubiee 0.3.144 (clean install from the `main` wheel, all MAC-144 fixes applied)._
_Surface: live `@scubiee/*` MCP tools (Kiro connected) + HTTP engine + CLI. Index: 8497 chunks._

This is the live performance + behavior report for the final 0.3.144 build after a clean `setup → init → connect`. It covers response-time metrics, idle/wake behavior, sync-lane latency, and a detailed analysis of the "substantial indexing in progress" flag (is it code-size or file-count based?).

---

## 1. Performance battery (live HTTP engine)

| Metric | Result | Windows DML ref |
|---|---|---|
| **Engine warm — soft-ready** (cold start) | **1.57s** | 4–9s |
| **Engine warm — dense-ready** (cold start) | **3.62s** | ~14s |
| soft→dense gap | ~2.0s | ~10s |
| **First response** (first search after warm) | **419ms**, 5 hits | — |
| **Warm steady-state** (24 searches) | p50 **39.5ms**, p95 125.8ms, max 147.6ms | — |
| **/health under embed load** (40 files embedding, 120 calls) | p50 **0.6ms**, max 53.3ms, **0 timeouts** | p50 ~2ms, 0 timeouts |
| New segfaults this run (incl. a full cold restart) | **0** | — |

MLX/Metal is the real embed path (`backend=mlx device=gpu metal=true`, ~101 t/s — ≈3× Windows DML ~35 t/s).

---

## 2. Idle → wake response time

The engine keeps a client-driven keepalive (`CTX_EMBED_KEEPALIVE`, 8s tick) while a client is attached, so it stays warm across idle gaps. Measured first-call latency after increasing idle windows:

| Idle window | State before first call | First call after idle | Next 9 (warm) p50 |
|---|---|---|---|
| 30s | `warm_phase=dense`, embedder loaded | **27.9ms** | 35.3ms |
| 90s | `warm_phase=dense`, embedder loaded | **29.3ms** | 19.5ms |
| 150s (past the 120s demote timer) | `warm_phase=dense`, embedder loaded | **29.4ms** | 13.6ms |

**Finding:** with a client attached, there is **no cold-wake penalty** — first-call latency after idle (~28–29ms) is indistinguishable from steady-state warm, even past the 120s embed-demote timer, because the keepalive holds the embedder resident. The post-disconnect demote (engine stop ~2 min after the *last* client leaves) is a separate, intended path and is not hit during active use.

Interactive MCP calls during the idle windows all returned instantly with correct results: `map config=find`, `map config=focus` (returned the fixed `_split_explicit_writes` body with its 3 regression tests as callers — confirming the production build carries the MAC-144 fixes), and `focus` on a nonexistent symbol → clean "could not resolve …" (no hallucination).

---

## 3. Sync-lane latency (all lanes)

| Lane | Latency | Windows ref |
|---|---|---|
| Hot-save (edit tracked file) | **0.04s** | ~2.5s |
| Incremental (new file) | **0.68s** | ~3s |
| Delete | **0.66s** | ~1.5s |
| Rename — new path searchable | **0.67s** | ~2.2s |
| Rename — old path evicted | **0.0s** | ~4.2s |
| Multi-client (8 clients, 20s, + churn) | 783 OK, 0 err, 0 5xx, 0 dropped, engine alive | — |

Delete and rename-old-eviction are the MAC-144-4 fix landing (both were "never pruned until the ~10-min periodic sweep" before the fix).

---

## 4. Large-sync "indexing in progress" flag — code-size based ✓

**Component:** `packages/pipeline/workload.py::classify_workload`, wired through `reconciler.py::reconcile` into the agent-visible index state (`PendingSummary`). Verified by 27 passing unit tests (`test_workload.py`, `test_pending_contract.py`, incl. `test_reconciling_substantial_is_surfaced`).

**Design — it is a wall-clock-TIME estimate derived from CODE SIZE, not a file count:**

```
units  = Σ(code_chunks × type_weight)        # modified: exact indexed chunk count;
                                              # new: ~1 chunk / 25 lines
       + PER_FILE_OVERHEAD_UNITS × n_files    # default 10 units/file (parse/graph/publish
                                              # genuinely scale per file)
       + 0.5 × n_deletes                      # tombstone prune, ~free
seconds = units / measured_embed_throughput  # EMA of real embed cps, conservative default 20
substantial = seconds >= CTX_SUBSTANTIAL_SECONDS (default 25)
              OR full/forced reindex
              OR drift >= CTX_SUBSTANTIAL_FRACTION of corpus (default 0.4)
```

Type weights: code 1.0, docs 0.5, config 0.3, binary/vendored 0.0 (never counted). Because the ETA uses measured throughput, the threshold **self-adjusts to machine speed** — a fast GPU silently absorbs more work.

**Proof it is code-size driven (file COUNT held fixed at 5, varying code SIZE):**

| 5 files × lines each | units | est seconds | flagged? |
|---|---|---|---|
| 5 × 10 | 55 | 2.8s | silent |
| 5 × 100 | 70 | 3.5s | silent |
| 5 × 500 | 150 | 7.5s | silent |
| 5 × 2000 | 450 | 22.5s | silent |
| 5 × 10000 | 2050 | 102.5s | **FLAGGED** |

Same 5 files; the estimate rises purely with the amount of code and trips the flag at ~10k lines. A pure file-count gate could not produce this.

**The 5-file question specifically:**
- 5 small files (40 lines each) → 60 units, **3.0s → SILENT** (a normal 5-file edit does not nag the agent).
- 5 huge files (4000 lines each) → 850 units, **42.5s → FLAGGED** (5 files, but genuinely minutes of embedding).

**Why file count still contributes a little** (varying COUNT at 10 lines/file): 5 files → silent (2.8s), 50 → flagged (27.5s), 300 → 165s, 600 → `bulk_paste`. This is intentional: a 300-file paste is minutes of parse/graph/publish work even if each file is tiny, so the `PER_FILE_OVERHEAD_UNITS` term keeps it from wrongly staying silent. Code size dominates; file count is a secondary, correct contributor.

**Tunable:** the default threshold is **25 seconds** (`CTX_SUBSTANTIAL_SECONDS`). If a deployment prefers to flag only minute-plus work, set `CTX_SUBSTANTIAL_SECONDS=60`. No code change required.

---

## 5. Production-readiness assessment

**On Apple Silicon (M5): production-ready.** Every tested dimension is green — clean install/setup/init/connect, MLX/Metal embed, cold-start (~3.6s dense), warm response (p50 ~40ms), no idle/wake penalty, all sync lanes sub-second, `/health` never blocking under load, multi-client concurrency clean, the large-sync flag correct on both the size and count axes, and 0 new segfaults. macOS matched or beat the Windows baseline on every cross-referenced metric. All four MAC-144 fixes are on scubiee `main`.

**Still not proven (do before a blanket "ship to everyone"):**
1. **Intel / CoreML / CPU-only Mac** — zero testing; unverified tier.
2. **Windows/Linux re-check** of the shared-code changes (`incremental.py`, `sync_loop.py` — the delete-prune path) — the Windows pass predates these fixes.
3. **Reboot/login autostart** of the launchd agent; **very large repos (10k+ files)**; sustained long-run load.

Recommendation: **ship to Apple Silicon with confidence; gate Intel and a Windows re-verification (or an explicit scope-out) before calling it cross-platform production-ready.**
