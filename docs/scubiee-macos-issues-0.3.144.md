# Scubiee macOS v0.3.144 — Issues Found & Fixed

_Platform: macOS 26.5.2, Apple Silicon (M5, arm64), MLX/Metal. Build: scubiee 0.3.144 (built from checkout)._
_Branch: `fix/macos-warm-segfault`. All fixes committed; see commit for the exact diff._
_Full verification report: `docs/scubiee-macos-findings-0.3.144.md`._

This document is the focused issue log: what was broken, how it was proven, the root cause, the fix, and how the fix was verified. Four issues were found during the 0.3.144 macOS verification pass; all four are fixed and re-verified end-to-end.

Severity: **BUG** (broken behavior) · **ISSUE** (rough edge / parity gap). All env knobs default to the fixed behavior and carry a rollback switch.

---

## Summary table

| ID | Severity | Area | One-line | Fix location | Env rollback |
|---|---|---|---|---|---|
| MAC-144-4 | **BUG** | Sync / delete lane | Explicit delete + rename-old-eviction not pruned promptly (waited ~10 min for the periodic sweep) | `incremental.py`, `sync_loop.py` | `CTX_HOT_DELETE_PRUNE=0` |
| MAC-144-2 | **BUG** | Release gate (`certify`) | `install_mcp_launches_map_v3` false-failed on the macOS bridge path → `certify ok:false` | `certify.py` | — (detection widened) |
| MAC-144-3 | ISSUE | CLI / MCP parity | CLI `map --config related\|graph` hard-errored instead of folding into find/focus like the MCP tool | `__main__.py` | — |
| MAC-144-1 | ISSUE | Embedder | MLX construction banner printed to stderr even with `quiet=True` | `embedder.py` | — |

Plus one **test-infrastructure** note (MAC-10) — not a product defect, documented at the end.

---

## MAC-144-4 — Deletes not pruned promptly (BUG)

**Symptom.** A file deleted and signalled via `/v1/dirty` kept showing up in search. Measured on this M5: not dropped within 30s, and even an explicit `scubiee sync-now` did not drop it. It was finally pruned only by the periodic corpus-ghost reconcile — observed ~10 minutes later. The same gap evicted the *old* path on a rename. (Windows prunes a delete in ~1.5s; the handoff's §9.2/§9.3/QA-9 expect prompt removal.)

**How it was proven.** A diagnostic indexed a file (confirmed it owned 3 chunks, present in both the chunk-merkle and file-merkle), then deleted it and re-dirtied it. Five seconds later the file **still owned all 3 chunks** in both merkles — the delete signal pruned nothing. The engine log showed the delete sync running as `[sync] no chunk delta … removed=0`.

**Root cause (two layers).**
1. **Path form mismatch (the core bug).** `/v1/dirty` carries **absolute** paths. Those flowed into `incremental_sync(force_files=…)`, but `chunks.jsonl` and the file-merkle store keys **relative** to the repo root. The removal path (`_slice_chunk_file`, `_patch_file_merkle`) matched the absolute path against relative keys, found nothing, and set `removed_ids=[]` → zero chunks pruned. (Additions still worked because the parse/extract path resolves `root / path` regardless.)
2. **Routing.** `BackgroundSyncLoop._split_explicit_writes` gated the prompt "write" lane on `(repo/path).is_file()`. A deleted path fails that check and fell to the slow disk-poll backlog, so even once path forms matched it was not on the prompt lane.

**Fix.**
- `packages/pipeline/incremental.py` — relativize `force_files` to the repo root at the single source that feeds `changed/removed/touch/touch_set`, using `resolve().relative_to(root)` so symlinked/`..` paths still land on the stored key. Now the slice matches and `removed_ids` is populated for a gone file.
- `packages/pipeline/sync_loop.py::_split_explicit_writes` — route a gone-but-still-indexed path marked with an **explicit** delete reason (`write`/`changed_file`/`editor_save`/`probe_write`/`after_kiro_write`) to the prompt write lane. Passive disk-poll discovery (`watch`/`disk_save`) stays on the deferred backlog so a real on-disk addition in the same drain is still synced ahead of a deletion (preserves the documented add-before-passive-delete ordering). Gated by `CTX_HOT_DELETE_PRUNE` (default on).

**Verification.**
- Isolated delete probe (no concurrent churn): **DELETE dropped at ~0.6–0.9s** (was: still present after 30s + sync-now).
- Full sync-lane probe post-fix: hot-save ~0.05s, incremental ~0.65s, **delete ~0.9s**, rename new ~1.0s / **old evicted ~0s**, bulk 80 files ~3.8s with batched graph catch-up.
- Regression tests added to `tests/test_lane_delete_consistency.py`: gone+indexed routes to the write lane; gone+unindexed stays on the backlog (no-op); `CTX_HOT_DELETE_PRUNE=0` restores old routing.
- Caught + fixed a self-inflicted regression: the first cut promoted `watch`-reason gone paths too, which broke `test_live_reindexing`'s add-before-delete ordering. Narrowing to explicit-delete reasons resolved it — `test_live_reindexing` + `test_lane_delete_consistency` = **64 passed**.

---

## MAC-144-2 — `certify` false-fail on the macOS bridge path (BUG)

**Symptom.** `scubiee certify` returned `ok:false` with one required failure: `install_mcp_launches_map_v3` → `detail: map_v3=False legacy_ref=False`. A clean macOS install could not pass the release gate.

**How it was proven.** Inspected `server_entry(repo)` on this Mac: it returns `command=scubiee-mcp-bridge, args=[], env` with **no** `CTX_MCP_BRIDGE_SPAWN_JSON`. The certify check only looked for the literal substring `map_v3_server` in the command/args/spawn-JSON blob — which is present **only** on the Windows path (where the spawn-JSON names the module). Confirmed `mcp_bridge.resolve_child_command()` **defaults** its child to `pipeline.map_v3_server` when no spawn-JSON is set, so the bridge genuinely launches Map V3 on macOS; the check was simply Windows-biased.

**Root cause.** `packages/pipeline/certify.py` recognized Map V3 only via the direct `map_v3_server` substring, which appears on the Windows spawn-JSON launch but not on the macOS/Linux bridge-shim launch.

**Fix.** `certify.py` now also accepts the bridge launch (`mcp_bridge` / `scubiee-mcp-bridge` in the entry) and the `scubiee-mcp` console shim (which re-exports `map_v3_server.main`), in addition to the direct substring — while still rejecting the retired `mcp_locate`. The detail string reports which path matched (`direct`/`bridge`/`shim`).

**Verification.** `scubiee certify` → **`ok:true`, 22 passed, 0 failed_required, failures:[]** on the final installed build.

---

## MAC-144-3 — CLI `map --config related|graph` hard-errored (ISSUE)

**Symptom.** `scubiee map … --config related` (and `graph`) exited with an argparse error: `invalid choice: 'related' (choose from 'find', 'focus')`. The MCP `map` tool, by contrast, accepts `related`/`graph` and **gracefully folds** them into find/focus with a note. The CLI's own docstring claimed "the CLI and the MCP surface never diverge" — so this was a self-contradiction and a parity gap.

**Root cause.** `packages/pipeline/__main__.py` declared the `--config` argparse choices as `("find", "focus")`, rejecting the hidden fallback configs **before** they could reach `tool_map`, which already handles them gracefully.

**Fix.** Widened the `--config` choices to include the hidden fallbacks (`related`, `graph`, `view`, `refs`, `open`, `around`, `outline`) with `metavar="{find,focus}"` so `--help`/usage still advertise only the two primary configs. `cmd_map` already forwards the config straight to `tool_map`, which emits the fold note and serves via find.

**Verification.** `--config related` and `--config graph` now print "folded into find … Serving via find" and return results; a genuinely invalid config (`zzgarbage`) is still rejected.

---

## MAC-144-1 — Embedder MLX banner ignored `quiet` (ISSUE, minor)

**Symptom.** Constructing `Embedder(…, quiet=True)` still printed the MLX diagnostic banner to stderr: `[embed] backend=mlx`, `device=gpu`, `metal=true`, `mlx_device=…`. Noise for any caller that drives its own progress bar in quiet mode.

**Root cause.** In `packages/pipeline/embedder.py::__init__`, the MLX banner block was not guarded by `self.quiet`, even though the sibling "plan" banner a few lines below already was.

**Fix.** Wrapped the four MLX banner prints in `if not self.quiet:`, matching the existing plan-banner guard.

**Verification.** `test_embedder_progress::test_embed_many_suppresses_stderr_when_progress_set` passes; the non-quiet path still prints as before.

---

## Also fixed: 4 stale/platform-unaware unit tests (not product bugs)

The macOS unit run surfaced 4 failing tests whose **product behavior was correct** — the tests encoded the pre-Apple-Silicon contract. The product correctly keeps MLX/Metal on Apple Silicon and never silently demotes to CPU on a GPU-probe/calibration timeout (`accel.py::_fallback_to_cpu_profile`, by design and confirmed via public MLX/Metal references). Fixes made the tests Apple-Silicon-aware:

- `tests/test_accel_cpu_fallback.py` (2) and `tests/test_cpu_only_laptop_path.py` (1): the generic CPU-fallback cases now pin a non-Apple host (`platform.system`/`machine` + `_is_apple_silicon`) so they exercise the CPU-demotion path they intend, on any machine.
- `tests/test_preflight.py` (2): the tests stubbed `load_accel`, but `inspect_accel` resolves the live profile via `resolve_runtime` (real MLX on this M5). Now also stub `resolve_runtime`.

---

## MAC-10 — Test infrastructure (ISSUE, not a product defect)

- At least one Windows-only test lacks a `skipif(sys.platform)` guard: `test_connect_formats::test_legacy_global_paths_include_devin_cascade` asserts a Windows `AppData/Roaming/devin/mcp_config.json` MCP path, while macOS correctly uses `~/.config/devin/mcp_config.json` (XDG). The product is right; the test needs a darwin guard.
- The full unit suite run in a **single process** segfaults intermittently (~15%) — a concurrent native-lib init race across many modules in one interpreter. This is a **test-execution artifact, not a shipped-engine path**: concurrent faiss+mlx+tree-sitter+onnxruntime init was clean across 20 iterations, the native-heavy module subset ran 80/80 single-process, and the shipped engine serializes its warm build (serial-warm fix) with zero segfaults across all restarts. A forked/isolated test runner (or a module-level native-init lock in the harness) would make a single-process macOS CI run reliable.

These two are prerequisites for using the raw `pytest` suite as a macOS CI gate; they do not affect the shipped engine.

---

## Files changed (branch `fix/macos-warm-segfault`)

Product:
- `packages/pipeline/incremental.py` — relativize `force_files` (MAC-144-4)
- `packages/pipeline/sync_loop.py` — prompt-prune routing for explicit deletes, `CTX_HOT_DELETE_PRUNE` (MAC-144-4)
- `packages/pipeline/certify.py` — accept bridge/shim map_v3 launch (MAC-144-2)
- `packages/pipeline/__main__.py` — widen CLI `--config` to fold hidden configs (MAC-144-3)
- `packages/pipeline/embedder.py` — MLX banner honors `quiet` (MAC-144-1)

Tests:
- `tests/test_lane_delete_consistency.py` — +3 MAC-144-4 regression tests
- `tests/test_accel_cpu_fallback.py`, `tests/test_cpu_only_laptop_path.py`, `tests/test_preflight.py` — Apple-Silicon-aware

Docs:
- `docs/scubiee-macos-findings-0.3.144.md` — full verification report
- `docs/scubiee-macos-issues-0.3.144.md` — this issue log

New env knob (safe default): `CTX_HOT_DELETE_PRUNE` (default on; `=0` to roll back MAC-144-4 routing).
