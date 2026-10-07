# Scubiee macOS production test results

_Executed per `docs/scubiee-macos-production-test-guide.md`._
_Date: 2026-10-07. Version under test: **0.3.143** (built from source at `282737f`, `uv tool install`)._
_Surface: engine HTTP API on `127.0.0.1:8765` + CLI + offline unit suite._

**Verdict: production-ready on Apple Silicon / MLX.** 4 of 5 prod_sim dimensions pass as-run; the 5th (soak) passes on re-run once the engine is kept warm — the as-run failure was the known client-less idle-standby behavior (engine self-stopped mid-soak because no MCP client was attached), not a sync/stability defect. All other sections (map bench, sync battery, BUG-1 newcomer probe, zero-downtime reindex, offline unit tests) pass.

---

## 1. Environment

| Field | Value |
|---|---|
| macOS | 26.5.2 (build 25F84) |
| Arch | `arm64` — Apple Silicon |
| Accel profile | **mlx** (provider `MLX`, Metal) |
| scubiee | **0.3.143** via `uv tool` (built wheel `dist_prod/scubiee-0.3.143-py3-none-any.whl`) |
| Tool interpreter | CPython 3.12.14 (Homebrew) |
| `uv` | 0.12.5 |
| `python3` for guide steps | `/opt/homebrew/bin/python3.12` (system `/usr/bin/python3` is 3.9.6, too old) |
| ripgrep | **not on PATH** — engine resolved a bundled/vscode `rg` (prod_sim dim D reports `grep_backend: "rg"`, so a real ripgrep was found, not the python fallback) |
| Index | 8269 chunks, 1332 files, embed dim 768, model `nomic-ai/CodeRankEmbed`, backend `mlx` |
| project_id | `ce_9e4dfab59f563d7ee8c1ab509ad098a9` |

Final engine health: `version 0.3.143, ok=true, warm_state=ready, dense_ready=true, chunks=8269`.

---

## 2. prod_sim verdict (section 3)

Report: `scripts/perf/_prodsim_report.json`. **As-run `all_pass: false`** (soak only — see §2.E).

| Dim | Result | Key numbers | Threshold | Verdict |
|---|---|---|---|---|
| A. cold_start | PASS | soft_ready max **1.2s**, dense_ready max **2.2s** (2 restarts) | soft ≤30s, dense ≤180s | PASS |
| B. tool_latency | PASS | grep warm p50 **30.4ms** / p95 **34.4ms**; locate warm p50/p95 **2.2ms**; cold grep **859ms**, cold locate **2ms** | grep p95 ≤3s, locate p95 ≤4s | PASS |
| C. concurrency | PASS | 8 clients, 48 calls, **0 errors** (rate 0.0), p50 66.3ms / p95 360ms, engine alive after | error rate ≤2% | PASS |
| D. large_repo | PASS | full-glob grep **100ms** found deep symbol + complete (`grep_backend: rg`); locate **75ms**, 5 hits | deep symbol found + complete | PASS |
| E. soak | **FAIL as-run → PASS on re-run** | see below | 0 errors, drift ≤2.5x, sync p95 ≤5s | see below |

### 2.E Soak — failure analysis + re-run

**As-run (FAIL):** `cycles=1,131,487`, `errors=1,131,482`, `visible_ok=5`, `engine_alive_after=false`.
That cycle count in a 180s window (~0.16ms/cycle) is a tight error-spin, not real churn. Root cause from `~/.scubiee/engine.log`:

```
18:59:21 [lifecycle] standby_stop running=True debounce_s=10.0
18:59:21 [lifecycle] standby_stop reason=idle_standby
18:59:21 [stop] ... reason=stop_daemon:idle_standby ...
         enter_standby < apply_idle_policy < enforce_mcp_warm_contract
```

prod_sim drives the engine over **raw HTTP**, not as a registered MCP client. The warm-contract/idle policy saw **0 connected clients**, and after the 10s debounce it stopped the daemon mid-soak. Once the engine was down, every subsequent `/v1/dirty` POST failed instantly → the million-cycle error spin. The 5 healthy cycles before the stop had good numbers (cycle_p50 1.4s, drift 1.0x, search p95 99.5ms). This is the previously-documented **MAC-2 idle-standby** behavior (by design; a real attached MCP client keeps the engine warm), **not** a sync or crash defect.

**Re-run (PASS)** — same `dim_soak(window_s=180)` with the engine kept warm (`CTX_ENGINE_IDLE_S=4800 CTX_EMBED_IDLE_DEMOTE_S=4800`):

```json
{"cycles": 89, "visible_ok": 89, "errors": 0,
 "cycle_p50_s": 1.4, "cycle_p95_s": 1.9,
 "search_p95_start_ms": 233.1, "search_p95_end_ms": 111.8,
 "latency_drift_x": 0.48, "engine_alive_after": true, "pass": true}
```

89 add→sync→search→delete cycles, every file visible, **0 errors**, sync p95 **1.9s** (≤5s), latency **improved** over the window (drift 0.48x). Dimension E is healthy on macOS.

---

## 3. map find / focus (section 4)

Measured through the shipped engine endpoints (`/v1/locate`, `/v1/grep_ident` + `/v1/read_span`), 18 samples each:

| Tool | p50 | p95 |
|---|---|---|
| map **find** | **11.1ms** | **12.7ms** |
| map **focus** | **51.5ms** | **216.1ms** |

Both well under 1s. Windows baseline was find ~54ms / focus ~258ms — macOS is faster on find and comparable on focus.

---

## 4. Sync battery (section 5)

`scripts/perf/probe_sync_battery.py` — **all 5 cases pass, 0 errors:**

| Case | Result |
|---|---|
| new_file | visible **0.2s** |
| modify | new visible 0.2s, old gone 0.0s |
| partial_edit | dropped symbol gone 0.0s, kept symbol still visible |
| delete | gone 0.0s |
| rapid_churn | 5 files created, **5 visible** |

Engine stayed warm throughout (gen 9 → 10, chunks 8278 → 8279). BUG-1/BUG-5 regression guard holds.

New-file visible latency: **~0.2s** (well under the guide's ~1s expectation).

---

## 5. Newcomer canonicalization probe (section 5, BUG-1 guard)

`scripts/perf/probe_bug1_newcomers.py` (via test venv so `pipeline.store` imports resolve):

```
os.name=posix
indexed files (collect_index_relpaths) : 1332
merkle keys   (load_merkle, canonical) : 1334
newcomers under CURRENT subtraction    : 0
newcomers under FIXED   subtraction    : 0   <-- required 0
raw key overlap (index ∩ merkle)       : 1332
false newcomers (already indexed, mis-flagged): 0
VERDICT: BUG-1 NOT reproduced
```

**FIXED-subtraction count = 0.** On the macOS/posix regime, `canonical_relpath` keeps original case (e.g. `AGENTS.md → AGENTS.md`, not lowercased as on Windows) and keys align with the merkle store. No case-insensitivity mismatch. PASS.

---

## 6. Zero-downtime forced reindex (section 6)

A 1s health poller ran continuously while `scubiee index . --force` executed (two forced reindexes, 19:37:43 → 19:39:51). **Every poll returned `200`; zero `DOWN`, zero non-200.** The index command reported `engine: {was_running: true, ok: true, republished: true}`. Blue/green staged promote keeps the engine serving on macOS. PASS.

---

## 7. Offline unit tests (section 7)

```
tests/test_newcomer_canonical_keys.py tests/test_grep_glob_scope.py
tests/test_capability_promotion.py tests/test_sync_status_canaries.py
tests/test_sync_corpus_alignment.py tests/test_graph_catchup_async.py
tests/test_incremental_confirm.py  -p no:logfire -q
```

**53 passed** in 5.89s (test venv: python 3.12 + `.[mlx,mcp]` + pytest). Matches the Windows baseline (53 passed). No fastembed/mlx import issues. PASS.

---

## 8. Call-outs (section 8)

- **grep latency:** fast on macOS **without** the Windows console-spawn fix, as predicted — warm p50 30.4ms / p95 34.4ms, cold first grep 859ms (one-time ripgrep cold-process + first tree walk, acceptable). The `windows_stdio_hidden_kwargs()` → `{}` no-op path is confirmed harmless and fast.
- **cold-start readiness (MLX):** soft-ready 1.2s, dense-ready 2.2s — much faster than the Windows/DirectML figures, as expected for warm MLX model cache. (Numbers captured, not compared 1:1.)
- **path case-insensitivity (APFS):** `canonical_relpath` keeps original case on posix; sync battery and newcomer probe both pass. No case-only-rename anomaly observed in the exercised cases.
- **No crashes / engine-down (today):** `~/.scubiee/engine.log` has **no `Segmentation fault` dated 2026-10-07**. The only segfaults in the log are the earlier MAC-9 incident from 2026-09-29 (prior 0.3.133 session). No `UnicodeDecodeError`.
- **Only engine-down event today** was the intentional-by-policy `idle_standby` stop during the client-less prod_sim soak (see §2.E).

---

## 9. Test-harness bug found + fixed (macOS portability)

`scripts/perf/prod_sim.py` hardcoded a Windows executable path:

```python
# before
SCUBIEE = r"C:/Users/usman/AppData/Roaming/uv/tools/scubiee/Scripts/scubiee.exe"
# after
import shutil as _shutil
SCUBIEE = _shutil.which("scubiee") or r"C:/Users/usman/AppData/Roaming/uv/tools/scubiee/Scripts/scubiee.exe"
```

As shipped, `prod_sim.py` cannot run on macOS (first `subprocess.run([SCUBIEE, ...])` raises `FileNotFoundError`). Resolving `scubiee` from PATH with the Windows path as fallback makes it cross-platform while preserving existing Windows behavior. The guide's section-3 command (`python3 scripts/perf/prod_sim.py`) only works after this fix.

**Recommended follow-ups (test infra, not product):**
1. Keep the `shutil.which` fix (committed here) so the macOS CI gate can run prod_sim unmodified.
2. Consider having prod_sim register as (or simulate) an MCP client, or run the engine with a raised idle window, so dimension E's soak reflects real agent-attached usage rather than tripping idle-standby. As-run on a client-less harness, E will always fail by design.

---

## 10. Summary scorecard

| Section | Result |
|---|---|
| §3 prod_sim A/B/C/D | **PASS** |
| §3 prod_sim E soak (as-run, client-less) | FAIL — idle-standby stop (by-design, MAC-2) |
| §3 prod_sim E soak (re-run, warm) | **PASS** (89/89, 0 errors, p95 1.9s) |
| §4 map find/focus | **PASS** (find p95 12.7ms, focus p95 216ms) |
| §5 sync battery | **PASS** (5/5) |
| §5 newcomer BUG-1 probe | **PASS** (0 false newcomers) |
| §6 zero-downtime reindex | **PASS** (continuous 200) |
| §7 offline unit tests | **PASS** (53/53) |

**Cross-platform production readiness confirmed on Apple Silicon / MLX**, with the one explained-and-expected difference (client-less soak trips idle-standby) and one test-harness portability fix. Not covered: Intel / CoreML / CPU path, reboot/login autostart, large-repo scale.

---

## 11. CLI combination matrix (`scripts/run_cli_combination_tests.py`)

Ran the state-machine combination suite three ways. The runner uses an isolated `tempfile` `CTX_HOME` per run, so the real `~/.scubiee` enrollment is never touched.

| Run | Mode | Scope | Result |
|---|---|---|---|
| Dev tree (quick) | `.venv_test` → `python -m pipeline` | 30 scenarios (no wipe/recovery/init_combo) | **30/30 PASS** |
| Dev tree (full) | `.venv_test` → `python -m pipeline` | 39 scenarios (incl. wipe + `unlock-tool`) | **39/39 PASS** |
| Real binary (quick) | `--cli ~/.local/bin/scubiee` (0.3.143) | 30 scenarios | **30/30 PASS** |

Behavior verified (identical dev-tree vs shipped binary):
- **Global stop guards:** after `stop -y`, `init` / `setup` (no `--repair`) / `engine start` / `search` / `index` are **blocked**; `setup --repair`, `engine status`, `halt`, `gate`, `list`, `resume`, `connect` (auto-resume) are allowed.
- **Engine-only stop** differs from global stop (engine down but not globally paused), `engine ensure`/`start` behave correctly.
- **Wipe confirm-gate:** `wipe .`, `wipe --all`, `halt`+`wipe --all` all return exit 2 (`confirm_required`) without `--confirm` — no accidental deletion.
- **Connect/disconnect** dry-runs for cursor + all tools; **lifecycle** pause/activate/sync-now/list/migrate; **recovery** upgrade --check, unlock-tool, stop→resume chains.
- `X2 unlock-tool` (destructive) ran last; in dev-tree mode it did not disturb the real uv-tool install (`uv tool list` still shows scubiee v0.3.143, no `*aside*` dir).

Result JSON: `/tmp/scubiee-cli-results-{quick,full,realbin}.json`.

### MAC-9 reproduced (ISSUE, hardening) — segfault on engine warm over churned index

After the combo runs (many stop/start/wipe/index cycles), restarting the real engine **segfaulted on warm**:

```
2026-10-07 20:44:01 [engine] opening /Users/usmansayed/Downloads/hidden-context-engine- …
Fatal Python error: Segmentation fault
  pipeline/turbo_quant.py:226 codec
  pipeline/turbo_quant.py:279 rows_float32
  pipeline/turbo_quant.py:256 to_float32
  pipeline/searcher.py:54 __init__
  pipeline/engine.py:1757 load_engine
  pipeline/ce_service.py:362 publish_engine  (_warm_registered <- _open_repo_sync)
```

The crash is in the **turboquant float32 reconstruction during searcher init** while publishing the engine over an index left in a partial/inconsistent state by the churn. This is the same class as the previously-filed **MAC-9** (segfault on first-index over a half-written manifest), now also reachable on the **warm/publish** path.

**Recovery (clean, worked first try):** `scubiee engine stop` → `scubiee index . --force` → engine warms with **no further segfault** (0.3.143, warm/ready, 8269 chunks, `/v1/locate` 2.7ms, `/v1/grep` serving). Not the normal path, but a crash is a crash.

**Recommendation:** keep MAC-9 open and widen its guard to cover the `publish_engine → load_engine → searcher → turbo_quant.to_float32` warm path (validate/guard the quantized store before float32 reconstruction, or atomically swap only fully-written stores). The CLI combination matrix itself is **fully green**; this is a state-robustness hardening item, not a command-surface defect.

### Note on idle-standby during CLI testing
Between combo runs the client-less engine was repeatedly stopped by the by-design idle-standby reaper (`stop_daemon:idle_standby` via `enforce_mcp_warm_contract`), same as the §2.E soak behavior. This is expected without an attached MCP client and is not a failure.

---

## 12. Clean-machine rebuild + CRITICAL finding: first-warm segfault on the clean path

Full teardown and clean rebuild (per the guide's clean-rebuild procedure):

1. `scubiee wipe --all --confirm` — removed `~/.scubiee` (857M incl. MLX model), uv tool, MCP configs, rules, launchd agent. Two tiny remnants (`~/.scubiee/{engine.log,engine_transition.json}` recreated post-wipe, and a stale `~/.codex/config.toml` MCP entry) were cleaned manually. Matches the known "remnants after wipe" nit.
2. Deleted `.venv_test` + `dist_prod`.
3. Rebuilt wheel → `uv tool install` → `setup` (fresh MLX CodeRank download + FP16 convert + calibrate ~101 t/s) → `init .` → `connect --kiro`.

**CRITICAL — MAC-9 escalation: the engine segfaulted on its FIRST warm of a completely clean install** (fresh model, fresh index, zero prior churn), during `init`'s daemon health check:

```
[engine] opening <repo> …
Fatal Python error: Segmentation fault
```

The faulthandler dump shows **why**: `_warm_registered` launches several `concurrent.futures` worker threads that build artifacts in different native C-extensions *simultaneously*:

| Thread | Stack | Native lib |
|---|---|---|
| load_engine (crashing path) | `publish_engine → load_engine → searcher.__init__ → turbo_quant.to_float32 → rows_float32 → codec → __post_init__ → _random_orthogonal → numpy.linalg.qr` | numpy/LAPACK |
| _build_bm25 | `bm25_cache.load_or_build_bm25 → conductor.bm25_index.__init__ → collections.update` | C ext |
| _build_graph | `graphify.serve._load_graph → networkx node_link_graph` | — |
| _build_cards | `capability.build_cards → read_text` | — |

So the crash is **concurrent native-extension initialization at warm time** (LAPACK `qr` in turboquant's random-orthogonal rotation racing bm25/graph/card builds). It is **nondeterministic**: a second `scubiee engine start` immediately after came up clean (`warm ready`, `dense true`, 8270 chunks, locate serving), and the engine has been stable since (5/5 health polls 200). Exactly **1 segfault** this clean session, on first warm only.

**Why this matters more than the earlier §11 note:** the earlier reproduction was after heavy stop/start/wipe churn and could be dismissed as corrupted-state. This one is on the **clean, documented happy path** (`wipe → install → setup → init`), which is exactly what a new user runs. It won/lost a thread race.

**Severity: BUG (intermittent crash on normal first-run), not cosmetic.** Recommended fix: serialize the native-heavy warm builders (turboquant float32 reconstruction / numpy LAPACK vs bm25/graph/card threads), or guard the LAPACK `qr` call with a lock, so first warm cannot race multiple C extensions. Until then, `init`'s "daemon health check timed out" on first run is a user-visible symptom; the engine recovers on the next start.

### Final state (ready for MCP testing)
- scubiee **0.3.143**, enrolled `state=active`, project_id `ce_c3bb9e1aeda5646a69be1d3708cc3625`, 8270 chunks / 1333 files, 768-dim MLX.
- Engine warm/ready/dense on :8765; `index_usable=true`.
- Kiro MCP wired in `.kiro/settings/mcp.json` (bridge `scubiee-mcp-bridge`) with `CTX_ENGINE_IDLE_S=4800` so the engine stays warm during an attached session.
- Restart Kiro to attach the MCP client, then exercise the `@scubiee/*` tools.

---

## 13. Live MCP feature + latency pass (Kiro attached, clean 0.3.143)

Full exercise of every `@scubiee/*` tool, sync, warm time, and latency with Kiro connected as the MCP client (`keeper.strategy = deferred_clients_active`, `clients_active = true` → engine held warm).

### 13.1 Warm-up time (3 cold restarts, MLX/Metal)
| Milestone | Run 1 | Run 2 | Run 3 | Typical |
|---|---|---|---|---|
| first `/health` 200 | 0.37s | 0.53s | 0.54s | ~0.5s |
| `soft_search_ready` (locate usable) | 0.93s | 0.78s | 0.77s | **~0.8s** |
| `embedder_loaded` + `dense_ready` | 2.66s | 2.56s | 2.40s | **~2.5s** |

Cold warm-up is fast and consistent: locate usable in <1s, full semantic (dense) in ~2.5s.

### 13.2 MCP tool correctness (live `@scubiee/*`)
- **`gate`** → `1:ce_c3bb9e1aeda5646a69be1d3708cc3625` (managed). PASS.
- **`status`** → `ok=True warm=True dense=True phase=dense chunks=8270 version=0.3.143`. PASS.
- **`map config=find`** → 10 ranked `[semantic]` results with confidence rating, inline bodies for top symbols, caller connections, related tests. Correct and grounded. PASS.
- **`map config=focus`** → exact symbol body + `wiring callers`/`calls`/`siblings` (e.g. `load_or_build_bm25` → caller `engine.py:1739 load_engine`). PASS.
- **structural/graph** (`outline`, `follow_imports`, `graph_neighbors`, `query_graph`) → all `ok:true`; `graph_neighbors` on `engine.py` returned 16 real neighbor spans. PASS. (A small file like `bm25_cache.py` returns few neighbors — sparse, not a bug.)

### 13.3 Warm tool response latency (20 reps each, p50/p95 ms)
| Tool | p50 | p95 | note |
|---|---|---|---|
| `/health` | 1.1 | 2.9 | |
| `/v1/status` | 62.4 | 62.9 | full engine snapshot (heaviest) |
| locate (`map find`) | **1.6** | **2.1** | |
| grep | 36.8 | 42.3 | one cold first-call 718ms (ripgrep spawn) |
| grep_ident | 24.9 | 27.6 | |
| read_span | 1.7 | 2.3 | |
| outline | 5.5 | 6.2 | |
| follow_imports | 9.7 | 9.8 | |
| graph_neighbors | 8.1 | 8.4 | |
| query_graph | 13.8 | 14.3 | |

All warm calls sub-100ms; semantic locate ~1.6ms p50. Only the very first cold grep pays the ripgrep process-spawn cost (~0.7s, one-time).

### 13.4 Sync feature (warm, client-attached)
| Operation | Latency |
|---|---|
| add → visible | 59ms |
| modify → new visible / old gone | 34ms / 33ms |
| rename → dst visible / old token gone | 33ms / 36ms |
| delete → gone | 35ms |

**End-to-end dense sync via MCP:** a freshly created symbol `zzmcp_syncprobe_lambda_<stamp>` was returned by `map config=find` at **rank 1, `confidence: high`, `[semantic]`** within ~3s of creation — proving the full `file → MLX embed → FAISS dense index → semantic retrieval` path works live. After delete+sync, grep returned 0 hits and the file was gone. PASS.

### 13.5 Post-idle latency
- **(a) Client attached, 45s quiet:** engine stayed `warm_state=ready, dense=True` (no idle demotion while Kiro holds it). First locate after idle **5.0ms** (even faster than the 7.2ms pre-quiet). In a real Kiro session there is **no post-idle penalty**.
- **(b) Cold after full stop:** first locate completed in **0.89s total** (soft_search_ready 0.88s + locate 3.2ms). Usable in under 1s even from a full idle-stop.

### 13.6 Reliability — intermittent warm-start segfault (confirms + strengthens §12 BUG)

During this session the engine was (re)started ~6 times (3 warm-up runs + idle test + recoveries). **2 of those starts segfaulted:**

| # | Time | Crashing top frame | Context |
|---|---|---|---|
| 1 | 21:11:53 | `turbo_quant.to_float32 → _random_orthogonal → numpy.linalg.qr` (+ concurrent bm25/graph/card threads) | clean-install first warm (§12) |
| 2 | 21:22:18 | `conductor/bm25_index.score_all → graphify._compute_idf → affinity_scores` | first query during warm, right after `[embed] MLX ready` |

Both are **concurrent native-extension execution** at warm time (numpy/LAPACK, bm25, graphify running across `concurrent.futures` worker threads). The supervisor/watchdog auto-restarts after each crash and the retry succeeded, so `dense_ready` was still reached and all functional tests passed — but a user hitting the race sees `init`/first-call stall then recover. The other ~4 restarts (including the idle-test cold-after-stop) were clean, confirming this is an **intermittent race (~1-in-3 here), not every start**.

**Severity: BUG (intermittent crash on warm/first-query).** Fix direction unchanged from §12: serialize or lock the native-heavy warm builders / first-query scoring so numpy-LAPACK, bm25, and graphify don't execute concurrently across threads during warm.

### 13.7 Verdict
On the clean 0.3.143 Apple-Silicon install with Kiro attached, **every MCP tool, the sync pipeline, warm-up, and latency are production-grade** — semantic locate ~1.6ms, sync sub-60ms, dense pickup ~3s, warm-up ~2.5s, no post-idle penalty in-session. The **one blocking reliability item** is the intermittent warm-start segfault (§12 + §13.6): functionally self-healing via watchdog, but it should be fixed before claiming crash-free, since it reproduces on the clean happy path.

---

## 14. ROOT CAUSE CONFIRMED — warm-start segfault is an MLX/Metal init thread-race (NOT sleep)

### Sleep hypothesis: ruled out
Ran **10 cold restarts under `caffeinate -dimsu`** (machine prevented from sleeping/display-off/disk-idle the whole time):

```
restarts=10  new_segfaults=2  crashed_runs=2
dense_times=[2.69,2.42,2.48,2.36,2.38,2.38,2.44, 49.84, 53.43, 2.56]
```

**2 of 10 restarts still segfaulted** with the machine fully awake → sleep/wake is **not** the cause. The macOS crash report corroborates: `Time Awake Since Boot: 990s`, process awake the whole time, `EXC_BAD_ACCESS (SIGSEGV) KERN_INVALID_ADDRESS at 0x3f9877b7cc15f423` (a non-canonical/garbage pointer — the classic signature of a native-extension data race, not logic error), `Triggered by Thread: 6` (a worker thread, not main).

### Exact crashing frame (both stress-test crashes, identical)
```
[embed] loading MLX CodeRankEmbed dtype=float16 device=Device(gpu, 0)
Fatal Python error: Segmentation fault — Current thread (worker):
  pipeline/mlx_mac.py:468   __init__          # MLX weight load + mx.array/mx.eval on Metal GPU
  pipeline/embedder.py:558  _ensure_mlx
  pipeline/engine.py:266    get_embedder
  pipeline/engine.py:208    _ensure
  pipeline/engine.py:236    _call
  pipeline/engine.py:77     _wrap
```

### Mechanism (confirmed in source)
`pipeline/engine.py::load_engine` warms by running native builders **concurrently**:
```python
with ThreadPoolExecutor(max_workers=3) as pool:
    f_graph = pool.submit(_build_graph)   # networkx / graphify (native)
    f_bm25  = pool.submit(_build_bm25)    # conductor bm25 (native)
    f_cards = pool.submit(_build_cards)
    dense = FaissDenseAdapter(...)        # faiss (native) on main thread
```
and the **MLX/Metal embedder** initializes on yet another worker thread (`get_embedder → _ensure_mlx → mlx_mac.__init__`, the `mx.array`/`mx.eval(device=gpu)` at `mlx_mac.py:468`). When MLX's Metal GPU context init overlaps faiss / numpy-LAPACK / bm25 initializing on sibling threads, the Metal/native allocators collide → wild-pointer SIGSEGV.

This explains every crash seen this session (the earlier `turbo_quant→numpy.qr` and `bm25_index.score_all→graphify` top-frames in §12/§13.6 are just whichever native thread happened to touch the corrupted allocator first; the common trigger is **MLX Metal init racing other native inits at warm**).

### Why it looks "mostly fine"
The watchdog restarts the engine on crash, and most retries win the race → `dense_ready` in ~2.4s. But a crashed start costs **~50s** (watchdog ~15s detect interval + a second attempt that may also crash, runs 8+9), and the user sees a `Python quit unexpectedly` dialog from the launchd-spawned interpreter. Rate observed this session: **~2 in 10 restarts (20%)**.

### Fix direction (concrete)
Serialize native-extension initialization at warm so MLX/Metal does **not** init concurrently with faiss/numpy/bm25/graphify. Options, cheapest first:
1. **Init MLX embedder first and alone** (block until `mlx_mac.__init__`/first `mx.eval` completes) *before* submitting the `ThreadPoolExecutor` graph/bm25/cards builders — i.e. move `get_embedder()` warm ahead of the pool, or
2. Guard all native-init entry points (MLX init, faiss adapter build, bm25 build, graph load) with a single process-wide `threading.Lock` so only one native library initializes at a time, or
3. Build graph/bm25/cards **serially** on macOS/MLX (lose a little warm parallelism — warm is already ~2.5s — in exchange for crash-free starts).

Option 1 is the smallest change and directly targets the observed collision.

### Status
**BUG confirmed — intermittent (~20%) warm-start SIGSEGV from MLX/Metal init racing other native extensions; independent of sleep.** Self-healing via watchdog (functional tests all pass) but user-visible (crash dialog + ~50s stall) and reproducible on the clean happy path. Should block a "crash-free on Apple Silicon" claim until the warm-init is serialized.

---

## 15. Fix attempt + verification: native-init serialization lock

### Change
Added `_NATIVE_INIT_LOCK` (a process-wide `threading.Lock`) in `packages/pipeline/engine.py` and held it around the two native-init phases that were racing:
- `get_embedder()` — around the `_ensure_mlx()` / `_ensure_coderank()` session creation (previously deliberately unlocked).
- `load_engine()` — around the `ThreadPoolExecutor` graph/bm25/cards block + `FaissDenseAdapter` build.

So MLX/Metal init can no longer overlap faiss/numpy/bm25/graph init. (The graph/bm25/cards builders still run in parallel with each other; only cross-library overlap is excluded.) Rebuilt the wheel and reinstalled.

### Result — big improvement, not fully eliminated
Re-ran the `caffeinate -dimsu` restart stress:

| Build | Restarts | Segfaults | Rate |
|---|---|---|---|
| before fix | 10 | 2 | ~20% |
| after fix | 15 | 0 | 0% |
| after fix (more) | 10 | 1 | 10% |
| **after fix (combined)** | **25** | **1** | **~4%** |

The lock cut the crash rate ~5x (20% → ~4%). dense_ready stayed ~2.4s typical (a few runs 8-25s when MLX init now waits on the builders — the expected serialization trade-off).

### Residual crash — a second MLX trigger
The one remaining crash (21:59:53) is **still `mlx_mac.py:468` MLX init**, but with **no faiss/bm25/graph builder thread in the dump** — the only other active threads were `sync_loop._watch`/`_run` and a second embedder path (`ce_service.py:948 _eager_prewarm → embed_one`). So the lock successfully removed the MLX-vs-faiss race; what's left is MLX init/first-eval racing **another MLX/embedder path** (eager-prewarm vs binder-load) and/or a background sync thread. The fix should be extended to route *all* MLX access (including `_eager_prewarm`'s `embed_one` first-eval) through the same `_NATIVE_INIT_LOCK`, or to a single-owner embedder-init thread, to close the last ~4%.

### Status
Partial fix landed and verified (uncommitted, in working tree). **Crash rate reduced from ~20% to ~4%**; root cause (concurrent native init, MLX-centric) confirmed and the primary overlap eliminated. Remaining work: serialize the eager-prewarm MLX path too. Still a BUG until 0% — but no longer the clean-path ~1-in-5 it was.

---

## 16. CORRECTION to §15 — the init-serialization lock did NOT fix it; reverted

§15's `_NATIVE_SESSION_LOCK` (serializing MLX/faiss **construction**) looked promising at n=15 (0 crashes) but a larger sample exposed it as noise:

| Build | Restarts | Crashed runs | Rate |
|---|---|---|---|
| shipped (no fix) | 10 | 2 | ~20% |
| lock fix, batch A | 15 | 0 | 0% |
| lock fix, batch B | 10 | 1 | 10% |
| **lock fix, batch C** | **20** | **3** (4 segfaults) | **~15-20%** |

With n=45 the lock build still crashes at essentially the original rate. **The construction-only lock does not fix the race.** The §15 "0/15" was luck. The fix has been **reverted**; the installed binary is clean shipped 0.3.143 again.

### Actual root cause (from the newest crash dumps)
The crashing thread is MLX model **construction** (`mlx_mac.py:459/468` — `np.load` mmap read + `CodeRankMLX.__init__`), while a sibling thread runs MLX **inference**:
```
Thread A (crashing): get_embedder → _ensure_mlx → mlx_mac.__init__   (building MLX, holds the lock)
Thread B:            ce_service.py:948 _eager_prewarm → embed_one → run_embed_infer  (MLX INFERENCE / mx.eval)
```
`_eager_prewarm` calls `embed_one` on the **already-built** live-binder embedder, so it goes straight to MLX inference and **never calls `_ensure_mlx`** — it never takes the construction lock. So the real collision is **MLX construction on one thread vs MLX inference (`mx.eval`/Metal) on another thread**, not construction-vs-construction. A lock around construction alone cannot stop it. (numpy `read_array` mmap in the construction thread racing Metal in the other is the concrete corruptor.)

### Correct fix direction
MLX/Metal work (both model build **and** every `mx.eval` inference) must be confined so it never runs on two threads at once during warm. The codebase already has the right primitive — `engine.py:_EMBED_EXECUTOR = ThreadPoolExecutor(max_workers=1)` ("executor is authority") — but the **binder-load eager `_ensure_mlx` runs on the caller's thread**, bypassing that single-worker executor, and `_eager_prewarm` drives inference concurrently. The fix is to route **all** MLX access (eager build in `load_engine`/`get_embedder` AND the `_eager_prewarm` warm-up inference) through the single `_EMBED_EXECUTOR` (or a shared MLX mutex that covers inference too), so Metal is single-threaded during warm. That is an architectural change to the embedder worker model — bigger than a one-line lock — and needs the maintainer to land + validate it against this same `caffeinate` restart-stress harness.

### Reproduction harness (for the fix author)
```
# 20+ cold restarts, machine kept awake, counts segfaults in ~/.scubiee/engine.log
caffeinate -dimsu python3 <restart-stress loop: stop; start --wait 0; poll /health dense_ready; diff segfault count>
```
Shipped baseline ≈ 2-3 crashes per 10-20 restarts. Target: 0 across ≥30 restarts.

### Net status
**BUG stands, unfixed.** Root cause now precisely identified (concurrent MLX construction-vs-inference on separate threads during warm; sleep ruled out). My attempted lock fix was insufficient and has been reverted — repo + installed binary are back to clean shipped 0.3.143. Everything else in §13 (all tools, sync, warm-up, latency) remains production-grade; the watchdog keeps the crash self-healing but user-visible (~15-20% of cold starts show a crash dialog + up to ~50-75s delayed warm).

---

## 17. Second fix attempt (confine MLX build to the embed worker) — also failed, reverted

Attempt: route the eager MLX construction through `run_embed_infer` (the single-worker `_EMBED_EXECUTOR`), so MLX **build and inference share one thread** and cannot run concurrently.

Result over 25 `caffeinate` restarts: **2 segfaults (~8%) AND 3 runs that never reached dense_ready within 90s** + many 25-85s warms. So it roughly halved the crash rate but introduced a worse regression — serializing build behind inference on one thread stalled/!deadlocked warm-up (dense_ready `None` on runs 15/17/20, 40-85s on several others). **Net worse.** Reverted; repo + installed binary are clean shipped 0.3.143 again.

### What the two failed attempts prove
1. A construction-only lock (§15/§16) does not stop it → the race involves inference, not just construction.
2. Forcing build+inference onto one thread (§17) reduces but doesn't eliminate crashes **and** breaks warm timing → the single-worker executor path has its own re-entrancy/ordering hazards during cold warm, and *something still runs MLX/Metal off that worker* (the residual 8% crash).

The real fix is more than a lock placement: it needs the maintainer to (a) make MLX/Metal access single-threaded **without** serializing it behind the inference queue during warm (likely a dedicated MLX-owner thread distinct from the search embed worker, or lazy-only MLX build so prewarm and binder-load never both touch Metal), and (b) keep warm-up latency intact. Two reasonable-looking fixes from the outside both regressed; this needs someone with the MLX/embedder-worker design context.

### Honest status
**Not fixed.** I attempted two fixes; both failed and were reverted. Root cause is correctly characterized (concurrent MLX/Metal across threads during warm, sleep-independent), the repro harness is documented (§16), but a correct fix requires an embedder-threading redesign beyond safe black-box patching. Code is back to pristine shipped 0.3.143.

---

## 18. Web research — the crash is a KNOWN MLX bug (mmap + auto-compile null MTLBuffer)

Researched the segfault against MLX upstream issues before attempting another fix. The crash matches a documented MLX bug, and our code hits the exact trigger. Sources are linked inline. _(Content rephrased for compliance with licensing restrictions.)_

### Installed versions (ours)
`mlx 0.32.3` + `mlx-metal 0.32.3` (per the uv-tool site-packages). This is **after** MLX's 0.31.2 thread-safety work, so the generic "MLX pre-0.31.2 isn't thread-safe" story is not the whole cause.

### Finding A — the primary match: lazy/mmap weights + auto-compiled kernel → null MTLBuffer SIGSEGV
[ml-explore/mlx #3329](https://github.com/ml-explore/mlx/issues/3329): MLX's automatic element-wise kernel fusion (`Compiled` kernels) crashes with **`SIGSEGV` / `KERN_INVALID_ADDRESS`** when an input array has a **null `MTLBuffer`** — which happens when weights are loaded via **mmap (lazy loading)** and MLX auto-fuses an op over those weights before they're promoted to a Metal buffer. The crash is in `CommandEncoder::set_input_array` dereferencing a null buffer pointer. Reporter notes background threads were actively reading mmap'd weights (`ParallelFileReader::read`) at crash time, and critically that **calling `mx.eval(weights)` beforehand does NOT reliably prevent it**.

**Why this is almost certainly our bug:** our `packages/pipeline/mlx_mac.py` `CodeRankMLX.__init__` does exactly this pattern:
```python
raw = np.load(load_path, mmap_mode="r")        # <-- mmap/lazy load
...  self.w[key] = mx.array(arr, dtype=mlx_dtype)
mx.eval(*self.w.values())                       # <-- the "eval beforehand" that #3329 says is NOT reliable
```
Our macOS crash report (`EXC_BAD_ACCESS (SIGSEGV) KERN_INVALID_ADDRESS`) and the engine-log stacks (`mlx_mac.py:459` `np.load` mmap read + Metal `eval_gpu`) line up with #3329 frame-for-frame.

**Documented workaround (from #3329):** `mx.disable_compile()` — disables the auto-fusion so `Compiled::eval_gpu`/`set_input_array` never receives a lazy array. This is a one-call, low-risk mitigation that does **not** touch threading or warm timing (unlike my two failed attempts §16/§17).

### Finding B — MLX thread-safety history (explains why §17 made it WORSE)
[huggingface/speech-to-speech #386](https://github.com/huggingface/speech-to-speech/issues/386): MLX gained multi-thread support only in **0.31.2** ("MLX can be used by multiple threads for independent computations"). But 0.31.2 also made **GPU streams thread-local**: [mlx-lm #1181](https://github.com/ml-explore/mlx-lm/issues/1181) / [#1256](https://github.com/ml-explore/mlx-lm/issues/1256) — *"streams created on one thread can no longer be used from another"* → `RuntimeError: There is no Stream(gpu, 0) in current thread`. That is exactly why §17 (building MLX on the single embed-worker thread, then using it elsewhere) stalled/failed warm-up: a model/stream built on the embed worker can't be driven from the HTTP/search threads.

### Finding C — MLX not thread-safe "at that level"
[ml-explore/mlx discussion #1448](https://github.com/ml-explore/mlx/discussions/1448): running `mx.eval` on separate threads is **not** generally thread-safe; the supported way to overlap is multiple CPU streams, not raw threads. Confirms concurrent Metal access across threads during warm is inherently unsafe — our build-thread vs eager-prewarm-inference-thread overlap.

### Finding D — mitigation libraries exist for this class of crash
[`metal-guard`](https://pypi.org/project/metal-guard/1.1.0/) and [`mlx-guard`](https://pypi.org/project/mlx-guard/0.1.0/) on PyPI exist specifically to supervise/mitigate Metal driver crashes in MLX servers and "agent frameworks with heavy tool calling" — external evidence that intermittent MLX/Metal crashes under concurrent/long-running use are a widespread, known problem, not specific to scubiee.

### Ranked fix options (for the maintainer)
1. **`mx.disable_compile()` at embedder init (recommended first try).** Directly targets the #3329 root cause (auto-fusion over lazy mmap arrays), one call, no threading/timing change. Verify embed throughput impact is acceptable (CodeRankEmbed is a small encoder; fusion gains are likely marginal vs. a crash).
2. **Force eager materialization of weights off mmap** before any GPU op: load without `mmap_mode="r"` (plain `np.load`), or copy each `mx.array` and `mx.eval` + a dummy forward pass *before* publishing — so no lazy/null-MTLBuffer array ever reaches a compiled kernel. Heavier RAM at load, but removes the lazy-array hazard.
3. **Confine ALL MLX to one dedicated owner thread** (build + every inference), respecting 0.31.2 thread-local streams — NOT the shared search embed-worker (that regressed, §17). This is the full threading redesign; largest change.
4. Pin/track MLX: 0.32.3 is current; watch for a #3329 fix in a later release and bump when available.

**Recommendation:** try option 1 (`mx.disable_compile()`) first — it's the smallest change that targets the proven root cause and avoids the thread-local-stream trap that broke §17. Validate with the §16 `caffeinate` restart-stress harness (target 0 crashes / ≥30 restarts).

---

## 19. Fix attempt 3 (research-driven): disable_compile + lock construction — ~20% → ~3%, timing preserved

Based on §18's research, applied TWO layered fixes in `packages/pipeline/mlx_mac.py`:

**Fix A — `mx.disable_compile()`** at `CodeRankMLX.__init__` (guarded by `CTX_MLX_DISABLE_COMPILE`, default on). Targets ml-explore/mlx#3329: stops auto-fused `Compiled` kernels from dereferencing a null `MTLBuffer` on lazy/mmap'd weights. Verified `mx.disable_compile()` exists in 0.32.3 and `mx.compile()` degrades to eager (still correct) under it.

**Fix B — hold `_MLX_EMBED_LOCK` across model CONSTRUCTION** (the mmap `mx.array` conversions + `mx.eval`), not just inference. The lock already serialized `embed_ids`/`embed_ids_compiled` inference; extending it over construction makes build vs inference mutually exclusive (addresses discussion #1448: MLX eval not thread-safe across threads).

### Measured result (caffeinate, 30 cold restarts)
```
new_segfaults=1  crashed_runs=1  never_warmed=0  dense_p50=2.41s  dense_max=52.13s
```
| Build | Crash rate | Warm timing |
|---|---|---|
| shipped (no fix) | ~15-20% | p50 ~2.4s |
| §17 (worker-confined) | ~8% + **broke warm** (3/25 never warmed, up to 85s) | regressed |
| **§19 (disable_compile + lock)** | **~3% (1/30)** | **preserved: p50 2.41s, 0 never-warmed** |

This is the first attempt that both **reduced crashes substantially (~5-7x)** AND **kept warm-up intact**. disable_compile removed the compiled-kernel variant; the lock removed most of the construction-vs-inference race.

### Residual (~3%) — the last race
The one crash (run 16) is still `mlx_mac.py` construction vs `ce_service._eager_prewarm` inference on another thread. Root cause of the remainder: `_MLX_THREAD` is **thread-local**, so the binder-load thread and the eager-prewarm/embed-worker thread each build their **own** `CodeRankMLX` instance; even with `_MLX_EMBED_LOCK` around each construction, MLX's global/Metal state is touched by two model instances close in time. Fully closing it needs the architectural change from §18 option 3: **one shared MLX owner** (single instance + single thread for build and inference), respecting 0.31.2 thread-local streams — not two thread-local instances. That is higher-risk and wants the embedder-worker owner to land it.

### Status
**Materially improved, not fully eliminated.** Two research-backed fixes cut the warm-start SIGSEGV from ~20% to ~3% with no warm-timing cost, and the watchdog still self-heals the rare remaining crash. Changes are in the working tree (`mlx_mac.py`), installed, and verified functional (engine warm/dense, locate serving). Recommend keeping A+B as a real improvement and filing the shared-MLX-owner redesign for the residual. `CTX_MLX_DISABLE_COMPILE=0` reverts Fix A if a compile-throughput regression is ever measured.

---

## 20. CORRECTION to §19 + redesign attempt — it's MULTIPLE native races; all point fixes reverted

§19's "~3%" was measurement luck. Re-validating the exact §19 build across more runs gave **0/30 then 4/30 back-to-back** → true rate ~5-13%, not 3%. Then I attempted the §18-option-3 redesign and two more targeted fixes. All failed to make it reliable. **Everything is reverted to pristine shipped 0.3.143.**

### What the extra attempts revealed
I tried, in order:
1. **Single MLX-owner thread** (route construction through the one embed worker). Result: 5/30 (~17%) — *worse*, and it unmasked that the crash is not only MLX.
2. **§19 MLX fixes alone** (disable_compile + construction lock), re-measured: 0/30 then 4/30.
3. **/health manifest-checksum skip during warm** (gate `index_is_usable(validate=False)` while `self.warming`), on top of the MLX fixes: still 3/30 (~10%).

Capturing the native frames of the last several crashes showed **three independent concurrent-native-code races during warm**, not one:
| Crash | Racing native subsystem |
|---|---|
| A | MLX/Metal — `mlx_mac.py` build vs inference |
| B | turboquant/faiss — `searcher → turbo_quant.to_float32 → numpy.linalg.qr` vs `artifact_guard._checksum` (from `/health → index_is_usable → validate_manifest`) |
| C | bm25 / graphify — `conductor.bm25_index` + `graphify/serve` builders |

They all run concurrently inside `_warm_registered` → `load_engine` (which uses a `ThreadPoolExecutor(max_workers=3)` for graph/bm25/cards + a faiss build on the main thread + the embedder build + `/health` handler threads). Each point fix closes ONE door; another native race stays open. That is why no single lock/flag got to 0.

### Root cause (final, precise)
The warm/publish path deliberately parallelizes native-heavy builders (faiss/turboquant, bm25, graphify, MLX) across threads for speed. On Apple Silicon these native libraries + Metal are **not safe to initialize/run concurrently across threads**, and `/health` adds a 4th thread doing a GIL-releasing manifest checksum. The result is an intermittent wild-pointer `SIGSEGV` whose top frame is *whichever* native lib lost the race that start — hence the shifting stacks (MLX one run, turboquant the next, bm25/graphify another).

### The only reliable fix (needs maintainer, out of scope for black-box patching)
**Serialize the entire warm build**: in `load_engine`/`_warm_registered`, build graph/bm25/cards/faiss/MLX **sequentially on one thread** (drop the `ThreadPoolExecutor` parallelism on macOS), AND suppress `/health`'s `validate_manifest` checksum for the whole warm window. This trades warm latency (likely ~2.5s → ~5-8s) for crash-free starts. It is a core change to the warm hot path with real perf implications and must be landed + benchmarked by whoever owns `load_engine` — not patched blind. The §18 research (MLX #1448/#3329, mlx-lm #1181) plus the three captured race signatures give them everything needed.

### Honest status — NOT fixed, reverted
I attempted 5 fixes across §15-§20 (two lock variants, worker-confinement, disable_compile+lock, /health checksum skip). Each either didn't help, regressed timing, or closed only one of three races. **None made cold start reliable**, so all are reverted; repo + installed binary are pristine shipped 0.3.143. The deliverable is a complete, correct diagnosis (multi-race warm concurrency, sleep-independent, 3 named subsystems) and the one architectural fix that will actually work (serialize warm + quiet /health). I did not push a fix because there isn't a reliable one that's safe to land without the warm-path owner.
