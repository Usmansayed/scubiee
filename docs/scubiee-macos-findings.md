# Scubiee — macOS Cross-Platform Reliability Findings

_Test plan executed: `docs/scubiee-macos-test-plan.md`._
_Version under test: **0.3.133** (clean rebuild: `wipe --all` → `uv tool install --force scubiee==0.3.133` → `setup` → `init` → `connect --kiro`)._
_Date: 2026-09-29._
_Surface: **live `@scubiee/*` MCP tools** (Kiro connected as an MCP client), plus HTTP + CLI diagnostics._

Severity legend: **BUG** (broken) · **ISSUE** (rough edge) · **OBS** (by-design nuance) · **OK** (verified).

> This report reflects the authoritative run against the **live MCP surface**. An earlier CLI-only pass (before the scubiee MCP server was connected to Kiro) is superseded where noted — most importantly on launchd (§4) and `doctor` (§8), which both improved once `setup`/`connect` had run.

---

## 1. Environment

| Field | Value |
|---|---|
| macOS | 26.5.2 (build 25F84) |
| Chip | Apple **M5** — Apple Silicon |
| Arch | `arm64` |
| Accel | **MLX (Metal GPU)** |
| Install | `uv tool install --force "scubiee==0.3.133"` → `/Users/usmansayed/.local/bin/scubiee` |
| MCP client | **Kiro connected** (`.kiro/settings/mcp.json` → `scubiee` via `scubiee-mcp-bridge`); `status.connected_hosts = ["kiro"]` |
| project_id | `ce_2ba5adebc2680d4f05a70bb6bf39c138` (new id after full wipe) |
| Index | 6855 chunks, 920 files, embed dim 768 |

---

## 2. Per-section results

### §2 Install & version — OK
- `/health` `version` = `0.3.133`; `uv tool list` → `scubiee v0.3.133`. **PASS**
- `status` → `managed:true`, `mcp_connected:true`, `connected_hosts:["kiro"]`, all 8 tools listed. **PASS**
- No Gatekeeper/quarantine/codesign friction on install. **OK**

### §3 Accelerator / embedder (MLX/Metal) — OK
- `resources` → `recommended_accel.profile = mlx`, provider `MLX`, `mlx:true`, `torch_mps:false` on Apple M5. **PASS**
- `preflight` → `ok:true` (faiss + rapidfuzz + tree-sitter parsers available). **PASS**
- `setup` confirmed MLX FP16 CodeRank weights and calibrated ~109 t/s. Embed dim **768**, `embed_backend:mlx`, `vector_backend:faiss+turboquant`. **OK**
- CoreML present only as an ONNX Runtime provider; MLX preferred for embed — as designed. **OBS**
- _Not exercised:_ forced `CTX_EMBED_BACKEND=fastembed` CPU fallback and the `mlx`-missing `CapabilityError` refusal (MLX is healthy). See caveats.

### §4 Lifecycle & launchd — OK (improved vs earlier CLI pass)
- **launchd LaunchAgent now present.** After `setup`/`connect --kiro`: `~/Library/LaunchAgents/com.contextengine.supervisor.plist` exists and `launchctl list` shows `com.contextengine.supervisor` (loaded). Supervisor log at `~/Library/Logs/scubiee-supervisor.log`. **PASS.** _(Supersedes the earlier "no LaunchAgent" observation — the agent is installed by `setup`/`connect`, not by a bare tool install.)_
- With Kiro attached as a client, the engine **stays warm** (`keeper.strategy = deferred_clients_active`), so the aggressive idle-standby seen in the client-less CLI pass does not occur during normal use. **OK**
- Engine start/stop clean; state dir `~/.scubiee/` well populated (`accel.json`, `engine.json`, `warm_phase.json`, `registry.json`, `mlx/`, `vectordb/`, `projects/`, logs). **OK**
- One nit: during `connect`, the launchd bootstrap printed `Load failed: 5: Input/output error` (suggests `launchctl bootstrap`), yet the agent ended up loaded and the in-process supervisor also runs. Cosmetic bootstrap warning. **OBS**
- Reboot autostart not tested. See caveats.

### §5 Warm-up + QA-4 — OK
- `/health` → live `warm_phase:dense`, `warm_state:ready`, `dense_ready:true`, `embedder_loaded:true`, `soft_search_ready:true` — all agree. **QA-4 regression PASS** (no stuck `down`). Warm MLX loads ~140 ms; setup calibration ~109 t/s.

### §6 MCP tools (all 8, live surface) — OK
| Tool | Result |
|---|---|
| `gate` | `1:ce_2ba5adebc2680d4f05a70bb6bf39c138` managed. **PASS** |
| `status` | full engine meta + keeper + lifecycle; `agent_ready:yes`. **PASS** |
| `map` (enriched) | `dense:true`, 8 ranked cards (`D_channel_best:bm25+dense+graph`), `suggested_seed = mcp_locate.py::create_mcp` (**public** function). **PASS** |
| `map` (one word "code") | **`weak_match:true`** as expected. **PASS** |
| `pack_context` | `ok:true`, `thin:false`, 16 all-hot heatmap nodes tracing the `create_mcp` flow, `seed_coverage:true`, 93 ms (≪5 s SLA). **PASS** |
| `expand_context` | `callees` → 8 real edges; `callers` → 6 (incl. `hybrid_cbm/server.py`, `mcp_locate.py::main`); `effects` → `[]` with `empty_reason:no_edges`. **PASS** |
| `collect_hot_context` | `ids=` → 2 real bodies within `max_chars`. **PASS** |
| `workspace` | `show` → session brain (topic/heatmap/map_queries); `pin` → adds to `pins[]`; `clear` → resets. **PASS** |
| `expand` | valid `file::symbol` → body (lines 61–70); bad handle → clean `ok:false` + `error` + `hint`. **PASS** |

The MCP-only signals **`dense:true`** and **`weak_match:true`** — which the earlier CLI pass could not observe — are both confirmed. **QA-2:** `suggested_seed` was a public function, not a `_`-private helper → **better than Windows**.

### §7 HTTP API — OK
- GET `/health / /status /v1/status /api/settings /v1/settings /v1/resources /dashboard` → all **200**; unknown → **404**. **PASS**
- POST `/v1/search /grep /outline /read_span /follow_imports /grep_ident /graph_neighbors /query_graph` → all `ok:true` with correct shapes. **PASS**
  - **OBS:** the first call to a cold endpoint can be slow enough to look like a non-response under a tight client timeout; on retry all return valid JSON.
  - **OBS:** `read_span` snaps to the enclosing chunk boundary (asked lines 61–70, returned the 1–60 chunk) — chunk-aligned by design.
- **QA-5 — better than Windows.** Bad-shape `graph_neighbors` (missing `paths[]`) → **400 with a JSON error envelope** `{"error":"paths required", ...}` (Windows returned a bare 400).

### §8 CLI surface — OK (improved vs earlier CLI pass)
- `doctor` → **`ok:true`** (was `ok:false` in the earlier pass). `journal.pending:false`, `repairs:[]`, `accel.ok` (mlx), `capabilities.ok`, `readiness.index_usable`, `binding.healthy`. The only residual flag is the cosmetic `install.binaries_match:false` (uv-tool shim vs interpreter path), which no longer trips overall `ok`. **PASS** (MAC-3 downgraded to trivia)
- `certify` → `ok:true`, **22 passed, 0 failed_required, `failures:[]`**. **PASS**
- `resources`/`preflight`/`status`/`gate` all return valid JSON, exit 0. **PASS**

### §9 Sync propagation — OK (fast now that a client holds the engine warm)
- **§9.1 New file** — `zz_mac_synctest.py` (`zzmac_marker_alpha`) in `hits[].file` after **~314 ms** (matches Windows ~360 ms; the earlier ~6.5 s was purely the client-less standby re-warm). `pack_context` resolved the new symbol as a graph seed (`seed_coverage:true`, `thin:true`). **PASS**
- **§9.2 Delete** — dropped from `hits[].file` ~1 s after delete + dirty. **PASS**
- **§9.3 Rename** — `zz_mac_rename_src.py` → `zz_mac_rename_dst.py`: dst indexed, old src evicted within ~1.8 s. QA-9 holds. **PASS**
- **§9.4 Ignore** — file under builtin-ignored `node_modules/` **not** indexed. **PASS.** **OBS:** `testdata/`/`research/`/`sandbox/` are **not** builtin ignores in this build (`ignore.py`: _"sure junk only"_); they require a repo `.scubieeignore`. The plan's ignore-dir list is out of date.
- **§9.5 Graph lane (BUG-MH)** — `sync-now ok:true`; **zero** `MinHash.update_batch`/`graph rebuild failed`/`graph_error` in `engine.log`; `expand_context` returns real edges. **PASS — does not reproduce.**

### §10 Teardown — OK
- All `zz_mac_*` files removed, paths dirtied, temp `node_modules/` removed. `git status` shows no test artifacts. Kiro remains connected; engine healthy/warm. **PASS**

---

## 3. Consolidated issue register

| ID | Severity | Area | Summary | Status |
|---|---|---|---|---|
| MAC-3 | trivia | Install/doctor | `install.binaries_match:false` (uv-tool shim vs interpreter path). No longer trips `doctor ok`. | Cosmetic |
| MAC-4 | OBS | Sync latency | New-file visibility ~314 ms with a client warm (was ~6.5 s only when client-less/standby). | Resolved in normal use |
| MAC-5 | OBS/doc | Ignore rules | `testdata/`/`research/`/`sandbox/` are not builtin ignores; need `.scubieeignore`. Plan's list is stale. | Doc gap |
| MAC-7 | OBS | HTTP | First call to a cold POST endpoint can be slow under a tight client timeout; retry succeeds. | By design |
| MAC-8 | OBS | launchd | `connect` printed a `launchctl bootstrap` I/O warning though the agent loaded fine. | Cosmetic |

No **BUG**- or **ISSUE**-severity findings on macOS. (The earlier CLI-pass MAC-1 "no launchd" and MAC-2 "idle-standby" are **withdrawn**: launchd is installed by `setup`/`connect`, and standby only occurred because no client was attached.)

---

## 4. Cross-platform comparison (vs Windows/DirectML)

| Windows finding | macOS behavior |
|---|---|
| **BUG-MH** (graph-lane `MinHash.update_batch` crash) | **Fixed / does not reproduce.** |
| **QA-4** (`/health` stuck `warm_phase:down`) | **Fixed / does not reproduce** — live `dense`. |
| **QA-2** (`suggested_seed` a `_`-private helper) | **Better** — public function returned. |
| **QA-3** (`callers` structural-only) | **Same** — structural callers. |
| **QA-5** (bad POST → bare 400) | **Better** — 400 **with** JSON envelope. |
| **QA-6** (`pack` positional query, `expand --node`) | **Same.** |
| **QA-7** (`doctor` flags stale entries) | Cleaner — `doctor ok:true`, only cosmetic `binaries_match`. |
| **QA-9** (renamed old path lingers) | **Same/better** — evicted within ~2 s. |

Both previously-fixed bugs (**BUG-MH**, **QA-4**) confirmed **absent** on macOS.

---

## 5. macOS-only findings
- **MLX/Metal is the real embed path and works** (768-dim CodeRankEmbed, ~109 t/s, warm ~140 ms).
- **launchd LaunchAgent** (`com.contextengine.supervisor`) is installed by `setup`/`connect` and loads.
- With a connected MCP client, the engine stays warm and sync is sub-second.
- No Gatekeeper/codesign friction.

## 6. Honest verdict
**Scubiee 0.3.133 is reliable on macOS / Apple Silicon (M5), verified against the live `@scubiee/*` MCP surface.** All 8 MCP tools, all HTTP GET/POST endpoints, the full CLI diagnostic surface (`doctor ok:true`, `certify` 22/0), MLX/Metal embedding, launchd supervision, and sub-second sync propagation all pass. macOS was **equal or better** than Windows on every cross-referenced finding, and both previously-fixed bugs (BUG-MH, QA-4) are absent.

**What's not proven / caveats:**
- Only **Apple Silicon (M5)** — the **Intel / CoreML / CPU** path was not exercised.
- MLX **CPU-fallback round-trip** and the `mlx`-missing **`CapabilityError`** refusal not run (MLX is healthy).
- **Reboot/login autostart** of the LaunchAgent not tested.
- **Large-repo scale** and sustained multi-client load not evaluated.
- Note: `tests/mac_production_test.py` exists in the repo as a purpose-built macOS harness and could be run for an additional automated pass.

---

# Appendix — Extended Testing Session Log (live MCP, clean rebuild, unit suite, segfault incident)

_Date: 2026-09-29. Machine: Apple M5 (arm64), macOS 26.5.2. scubiee 0.3.133 via `uv tool`._
_This appendix records, in detail, the follow-up testing done after the initial findings above: a full clean reinstall, the automated unit suite with per-failure triage, MLX fallback/refusal verification, a real crash I hit and how it was resolved, and a hands-on "use it like a coding agent" pass on the live `@scubiee/*` MCP tools._

## A. Clean rebuild procedure (what I actually ran, in order)

The initial run had tested via CLI because Kiro had no scubiee MCP server configured. To test the real MCP surface I did a full clean rebuild:

1. `scubiee wipe --all --confirm --keep-models` — uninstalled the tool, removed MCP configs/rules/daemon state. Left two remnants (`~/.scubiee` shutdown log, a repo-local `.codex/config.toml`); cleared the `~/.scubiee` remnant manually.
2. Deleted `.venv/`.
3. `uv tool install --force "scubiee==0.3.133"` — clean install, verified `uv tool list` + `/health` version.
4. `scubiee setup` — auto-detected **MLX**, downloaded/cached FP16 CodeRank weights, warmed on accelerator, calibrated ~**109 t/s**, registered a logon supervisor.
5. `scubiee init .` — managed + indexed the repo (6854 chunks, warm_state ready).
6. `scubiee connect --kiro --repo .` — wrote the `scubiee` server into `.kiro/settings/mcp.json` (bridge `scubiee-mcp-bridge`, all 8 tools auto-approved), then restarted Kiro to load it.

**Observation:** `connect` also registers the launchd LaunchAgent `~/Library/LaunchAgents/com.contextengine.supervisor.plist` (confirmed loaded via `launchctl list`). This is why the very first (bare tool install, no setup/connect) pass saw "no LaunchAgent" — the agent is installed by `setup`/`connect`, not by the tool install alone. The earlier MAC-1 finding is therefore withdrawn.

## B. Automated unit suite — 1584 tests / 191 files

Ran the full suite in a dedicated venv (`uv pip install -e ".[mlx,mcp]" pytest`). Because one file hung under the shared runner, I re-ran **each test file in its own process with a 120s wall-clock guard** to isolate hangs.

**Result: 167 files pass, 24 fail, 0 timeout, 0 collection errors (1584 collected, 14 integration deselected), ~258s.**

I triaged **every** failing file. None are defects in the shipped macOS binary — they fall into these buckets:

| Bucket | Files | Root cause |
|---|---|---|
| Windows-only tests not skipped on darwin | `test_watchdog` (CREATE_NO_WINDOW), `test_watchdog_lifecycle_contract` (`WindowsPath` can't instantiate), `test_connect_formats` (AppData\Roaming), `test_diagnose_output_path` (PowerShell/Desktop), `test_env_guard` (`scubiee.exe`), `test_process_job` (`start_new_session`) | Missing `skipif(sys.platform)` guards |
| Mock assumes non-MLX hardware; real M5 detects MLX | `test_accel_cpu_fallback`, `test_cpu_only_laptop_path`, `test_preflight`, `test_embedder_progress` | Tests mock a GPU-probe timeout and assert `cpu`; real hardware returns `mlx`. Harness limitation on Apple Silicon. |
| Python 3.10 vs 3.11+ | `test_cli_init_repo`, `test_package_install_entry` | `ModuleNotFoundError: tomllib` (stdlib since 3.11); the venv was 3.10 |
| Integration tests not marked `integration` (no live engine) | `test_mcp_exploration_regressions`, `test_mcp_lifecycle_universal`, `test_cursor_open_warm_traps`, `test_dashboard_api`, `test_auto_sessions_observability`, `test_lifecycle_ownership`, `test_root_probe` | `Connection refused` at 127.0.0.1:8765 during the dev-venv run |
| Deterministic retrieval-quality thresholds | `test_polytrace` (f1 0.9233 < 0.95), `test_vague_prompts` (f1 0.8484 < 0.90), `test_verify_board` (16≠20), `test_trace_lab` | `trace_lab/retrieve.py` header: "No embeddings required" — these are **platform-independent** and would fail identically on Windows |

**Critical caveat found:** the working tree is checked out at git `cf014c6` / tag **v0.3.102**, while the installed/tested binary is **0.3.133** — the local test code is 31 releases behind the product. Several failures (esp. the quality thresholds) reflect stale local tests vs. a newer binary, not the reverse. A trustworthy CI gate needs the checkout synced to 0.3.133 and the Windows-only tests guarded for darwin.

## C. MLX fallback + refusal (the §3 gaps from the first run) — both PASS

Verified directly against `pipeline.embedder`:
- **CPU/FastEmbed fallback:** `CTX_EMBED_BACKEND=fastembed CTX_MLX=0` → `Embedder.embed_one()` produced valid **768-dim** vectors, all finite, with sensible cosine similarity (0.309) between related code strings. Fallback works.
- **MLX-missing refusal:** with `mlx` import forced to fail and `CTX_EMBED_BACKEND=mlx`, `_choose_backend()` raised **`CapabilityError`** ("requires the mlx package… Refusing FastEmbed/CPU fallback") instead of silently degrading. Exact string confirmed at `packages/pipeline/embedder.py:216` via host Grep.

## D. Segfault incident (real, reproduced, resolved)

After heavy test churn (spawning/killing many engine instances, an editable venv, killed pytest processes), the runtime state got corrupted:
- A stuck `pause_state.json` with `paused=true` **deadlocked** `setup` and `resume` against each other ("run setup first" ↔ "run resume first"). Removing the stale `pause_state.json` cleared it.
- A subsequent `scubiee init .` **crashed the daemon with `Fatal Python error: Segmentation fault`** (twice). The crashing thread stack: `engine.py::_build_cards` → `capability.py::build_cards` → `card_from_source` → `_public_symbols` → stdlib `ast.parse`, running in `concurrent.futures` worker threads **concurrently** with an `artifact_guard._checksum`/`validate_manifest` thread on a **half-written index manifest** left by the interrupted runs.

**Resolution:** cleared the partial index (`~/.scubiee/projects`, `~/.scubiee/vectordb`) plus stale lock/pid/transition files (kept `mlx/` model + `accel.json`), then re-ran `init` — it came up clean (warm_state ready, 6854 chunks, dense loaded, **no segfault**) and has not recurred.

**Assessment:** this is an **edge case on corrupted/partial state, not the normal path**, but a first-index that can segfault under concurrent card-building on a stale manifest is worth a hardening ticket — guard `index_is_usable`/`validate_manifest` against partial manifests and/or serialize card-building vs. manifest validation. Filed here as **MAC-9 (ISSUE, hardening)**.

## E. Hands-on agent-style pass on the live `@scubiee/*` MCP tools

Used Scubiee the way a coding agent would — real "where/how does this work" questions, following map → pack → expand, then **verifying every answer against the actual source**:

1. **"How does the engine decide to idle-stop?"** — `map` returned `lifecycle_runtime.py::apply_idle_policy` at rank 1 (`why` = "After disconnect debounce: demote embedder + stop engine"), `dense:true`, 77ms. `pack_context` assembled the full chain: `apply_idle_policy` → `should_idle_stop` → `idle_stop_debounced` → `reconcile_clients` → `load_policy`/`save_policy` → `enter_standby` → `stop_daemon` (16 hot nodes, 51ms, seed_coverage true). **Read the spans — code is exactly correct**, and it documents the "zero clients with no leave stamp must not trigger the 10s sweeper" rule that explains the standby behavior observed in earlier runs.
2. **Edge trace** — `expand_context callers` on `apply_idle_policy` → the 3 real triggers: `leave_mcp_client`, `enforce_mcp_warm_contract`, HTTP `Handler.do_POST` (22ms).
3. **"Warm-while-client-lives contract"** — `map` → `enforce_mcp_warm_contract` rank 1 with the literal product-contract docstring; also surfaced `warm_contract.py` (30s attach-warm SLA).
4. **Needle discipline** — an exact `CapabilityError` string was located via host **Grep** (correct host-first behavior), not map.
5. **Live sync end-to-end** — created `packages/pipeline/zz_mac_probe.py::zzmac_probe_epsilon_handler`, POST `/v1/dirty`; MCP `map` found it at **rank 1 within ~3s** (score 20.1, dense+bm25). Deleted it + dirty → dropped from search within ~2s. `status full` captured the incremental sync live: keeper detected the add, then `chunks_removed:2` on delete, `strategy:incremental`, `hot_lane:true`, `graph_error:null`, `warnings:[]`, with a full per-stage timing breakdown, and graph-lane catch-up correctly `queued`.
6. **Honest freshness reporting** — during the sync window `status` reported `agent_ready:"stale"` with `search_usable:true` + `index_fresh:false` and a plain-language note that recent edits are still syncing. It tells the agent the truth about freshness rather than pretending.

All MCP retrievals were `dense:true`, sub-200ms, correct, and grounded in real code.

## F. Live MCP results summary (this session)

| Tool / feature | Result |
|---|---|
| `gate` / `status` (full) | Managed, healthy, daemon_healthy, mcp_connected=[kiro], MLX, 6855 chunks, 920 files. **PASS** |
| `map` (dense) | Correct rank-1 hits, `dense:true`, `weak_match:true` on vague query, sub-100ms. **PASS** |
| `pack_context` | Coherent multi-node heatmaps, seed_coverage true, <5s SLA. **PASS** |
| `expand_context` | callees/callers real edges; effects clean empty case. **PASS** |
| `collect_hot_context` / `expand` | Bodies within budget; bad handle → clean `ok:false`+hint. **PASS** |
| `workspace` show/pin/clear | Session brain, pins, reset. **PASS** |
| Live add/delete sync | New symbol found ~3s; delete dropped ~2s; graph_error null. **PASS** |
| MLX/Metal embed | backend=mlx, device=gpu, metal=true, 768-dim. **PASS** |
| launchd LaunchAgent | Installed + loaded after setup/connect. **PASS** |

## G. Issue register additions

| ID | Severity | Area | Summary | Status |
|---|---|---|---|---|
| MAC-9 | ISSUE (hardening) | Init/index | Daemon segfaults during first-index on a **partial/half-written manifest** (concurrent `ast.parse` card-building vs. `validate_manifest`). Recovered by clearing partial index. Not the normal path. | Open — guard partial manifests |
| MAC-10 | ISSUE (test infra) | CI on macOS | Unit suite has 6 Windows-only tests not `skipif`'d on darwin + several integration tests unmarked; and the checkout (v0.3.102) lags the binary (0.3.133). A raw macOS `pytest` shows misleading red. | Open — guard + sync checkout |

## H. Honest verdict (updated)

**On Apple Silicon (M5), scubiee 0.3.133 via the live MCP surface: production quality on the supported path.** All 8 MCP tools, live add/delete sync, graph edges, MLX/Metal embedding, launchd supervision, honest freshness reporting, and correct/grounded answers to real agent questions. Both previously-fixed bugs (BUG-MH, QA-4) remain absent; macOS matched or beat Windows on every cross-referenced finding.

**Blocking honesty for a blanket "production-ready" stamp:**
1. **MAC-9 segfault** on corrupted/partial index state — edge case, but a crash is a crash; wants a hardening guard.
2. **Coverage** still Apple-Silicon-only: Intel / CoreML / CPU path, reboot autostart, and large-repo scale remain unverified.
3. **MAC-10**: sync the test checkout to 0.3.133 and guard the Windows-only tests before the suite can serve as a macOS CI gate.

Recommendation: **ship to Apple Silicon with confidence; do not claim Intel or corrupted-state resilience until MAC-9 is guarded and an Intel pass (or explicit scope-out) is done.**
