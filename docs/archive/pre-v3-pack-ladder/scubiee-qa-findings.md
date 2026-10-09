# Scubiee QA — Feature Testing & Findings

_Version 0.3.132 · Windows (DirectML) · repo `context-engine` (7858 chunks, 1154 files) · engine warm on `127.0.0.1:8765`_

This document records a thorough, hands-on test of every Scubiee surface: the 8 MCP tools, the HTTP API, the CLI, and lifecycle/sync behavior. Each section states what was exercised, the observed behavior, and any bugs/issues. A consolidated issue table is at the end.

Severity legend: **BUG** (incorrect/broken), **ISSUE** (works but rough edge / inconsistency), **OBS** (observation / by-design nuance worth noting), **OK** (verified working).

---

## 1. MCP tools (primary surface)

Tested through the real `@scubiee/*` Kiro MCP tools against the live warm engine.

### 1.1 `gate` — OK
- `gate(project_id=ce_…)` → returns compact `1:<project_id> sid:<session> shared` line + a shared-process advisory. Fast, correct managed confirmation.

### 1.2 `status` — OK (one ISSUE)
- `detail=gate` → single compact line `1:<project_id>`. 
- `detail=summary` → concise health JSON (`warm_phase`, `embedder_loaded`, `semantic_ready`, `agent_ready`).
- `detail=full` → complete dump: engine meta (chunks/files/model), keeper state, per-file dirty ledger with sync lane reasons (`hot_lane`, `graph_catchup`), lifecycle, connected hosts.
- **ISSUE (QA-1):** `status full` is verbose enough that its per-file `dirty.paths` ledger surfaces stale test artifacts still tracked in the repo (`packages/pipeline/zz_newfile_test.py`, `packages/pipeline/zz_synctests.py`) — leftovers from earlier sync tests. Not a status bug, but the ledger made it obvious these need cleanup. (Cleaned up in §5.)

### 1.3 `map` — OK (one ISSUE)
- Enriched query (~40 tokens) → dense retrieval (`dense:true`, `retrieve_mode:D_channel_best`), ranked cards with `loc`, `role`, `why` snippet, `source` channel attribution, and `suggested_seeds`. ~1.2s cold-cache, 14ms on repeat.
- Vague single word (`"fix"`) → still returns cards but sets **`weak_match: true`** and the `next` hint pushes query enrichment. Graceful degradation — good.
- **ISSUE (QA-2):** For the enriched query, the top `suggested_seed` was `_managed_locate_err` — a `_`-prefixed private helper — while the tool's own `next` guidance says "Forbid `_helper` seeds." The suggester and the guidance disagree. Minor, but an agent following the seed blindly would pick a discouraged seed. Prefer surfacing the nearest public entrypoint (`create_mcp`) as `suggested_seed[0]`.

### 1.4 `pack_context` — OK
- Valid seed (`mcp_locate.py::create_mcp`) → coherent heatmap (220ms) clustering the true registration + error path (`create_mcp`, `_is_repo_managed`, `_managed_locate_err`, `_err`). `seed_coverage:true`, `thin:false`, `full_loc` gives the whole enclosing block span. SLA profile reported (`lean_single_seed_warm`).
- `include_bodies=1, budget_chars=2000, max_bodies=2` → returned real `create_mcp` body, truncated at the char budget with `…`. Budget honored. `chain` edges labeled `calls`; `cold` list of lower-scored nodes included.
- Error: nonexistent `seed_file`+`seed_symbol` → clean `ok:false` `"seed not found: …"` with `hint`. 
- Error: no `seed_file` → clean `ok:false` `"seed_file required"` with `hint`.

### 1.5 `expand_context` — OK (one OBS)
- `direction=callees` from `create_mcp` → 6 real direct callees (34ms, `hydrate_source:cache`).
- `direction=callers` from `_err` → 2 callers, one flagged `already_in_pack:true` (good dedup signal).
- `direction=effects` from `create_mcp` → empty with explicit `empty_reason:no_edges` (create_mcp has no log/file-write effects — correct).
- **OBS (QA-3):** `callers` of `_err` returned only 2 nodes, though `_err` is referenced in dozens of textual call sites across `mcp_locate.py`. This is consistent with the composite graph capturing *structural* call edges, not every textual reference — expected behavior, but agents should not assume `callers` is an exhaustive reference list.

### 1.6 `collect_hot_context` — OK
- Explicit `ids=` (two node ids) + `max_chars=2500` → returned both full function bodies within budget, with `next` guidance. Correct.

### 1.7 `workspace` — OK
- `show` → session brain: `topic`, per-file `heatmap` (hits/heat/roles/last_queries), `pins`, `spans`, `focus_seen`, `map_queries`. Accurate reflection of the session's activity.
- `pin (path=…, root=…)` → added file to `pins`.
- `clear` → fully reset topic/pins/heatmap/map_queries to empty (verified with a follow-up `show`).

### 1.8 `expand` — OK
- Valid handle (`file::symbol`) → returns body with `start_line`/`end_line`. `file:start-end` handles also accepted per the hint.
- Bad handle → clean `ok:false` `"unknown handle …"` with a helpful `hint`.

**MCP verdict:** All 8 tools work, are fast when warm, and have clean, hint-bearing error envelopes. Two minor issues (QA-1 artifact leftovers surfaced by status, QA-2 private-helper suggested_seed) and one by-design observation (QA-3 structural-only callers).

---

_HTTP, CLI, and lifecycle/sync sections follow as those phases are tested._

## 2. HTTP API (`127.0.0.1:8765`)

Tested with PowerShell `Invoke-WebRequest` and JSON request-body files against the live engine.

### 2.1 GET endpoints — OK (one BUG)
| Endpoint | Result |
|---|---|
| `/health`, `/` | 200, identical body (463 bytes). Reports version, pid, warm flags, chunks. |
| `/status`, `/v1/status` | 200, ~15.8 KB full status (same shape as MCP `status full`). |
| `/api/settings`, `/v1/settings` | 200, 281 bytes: registration mode, incremental/watching flags, auto-admission, resource limits. |
| `/v1/resources` | 200, 1.7 KB: CPU/RAM sample, pressure tier, per-lane budgets (embed/index/sync/graph), scheduler. |
| `/dashboard` | 200, HTML (5.9 KB). |
| unknown (`/v1/nonexistent_zzz`) | 404. Correct. |

- **BUG (QA-4) — FIXED:** `/health` reported **`"warm_phase": "down"`** even when the engine was fully warm — every sibling field disagreed (`warm:true`, `warm_state:"ready"`, `warm_ready:true`, `dense_ready:true`, `embedder_loaded:true`), and the MCP `status` reported the live phase for the same engine. Reproduced on two separate engine PIDs (19180 and a freshly-restarted 24588).
  - **Root cause:** the health builder in `packages/pipeline/ce_service.py` read the phase from `warm_autoload.read_phase()`, which defaults a missing/unset on-disk phase to `"down"` (`str(raw.get("phase") or PHASE_DOWN)`). Because `"down"` is not `None`, the existing `warm_phase is None` fallbacks (prewarm/dense/soft) never ran, so a stale/absent phase file pinned the payload to `"down"`.
  - **Fix:** treat `None`/`""`/`"down"`/`"error"` as "no reliable phase" and derive `warm_phase` from the live warm flags (`prewarm_busy` → `prewarm`, `embedder_loaded` → `dense`, `soft_ok` → `soft`), only falling back to `"down"` when the engine genuinely isn't warm.
  - **Verified:** deployed via `sync-uv-install` (`differ:0 missing:0`), restarted the engine (pid 11892); `/health` now reports `"warm_phase":"dense"` consistent with the sibling flags.

### 2.2 POST retrieval endpoints — OK
| Endpoint | Body | Result |
|---|---|---|
| `/v1/search` | `{query,repo,k}` | 200, dense hits + rich keeper/timings block. ~13ms retrieve. |
| `/v1/grep` | `{pattern,repo,k}` | 200. |
| `/v1/outline` | `{path,repo}` | 200, ~10.7 KB outline. |
| `/v1/read_span` | `{path,start,end,repo}` | 200. |
| `/v1/follow_imports` | `{path,repo}` | 200. |
| `/v1/grep_ident` | `{ident,repo,k}` | 200. |
| `/v1/graph_neighbors` | `{paths:[…],query,repo}` | 200 (see ISSUE below). |
| `/v1/query_graph` | `{question,repo,keep}` | 200, ~7.9 KB. |
| `/v1/note_locate`, `/v1/session_anchors`, `/v1/reopen_anchors` | `{repo}` | 200. |

- **ISSUE (QA-5):** `/v1/graph_neighbors` and `/v1/query_graph` reject malformed/mis-keyed bodies with a **bare HTTP 400 and no JSON error envelope** — unlike the MCP tools, which always return `{ok:false, error, hint}`. `graph_neighbors` needs `paths`/`files` (not `node`); `query_graph` needs a non-empty `question`/`query` (not `symbol`). `/v1/lifecycle` with a minimal body also 400s. The endpoints work correctly with the right shape; the gap is that the HTTP layer doesn't return a helpful, machine-readable error body the way the MCP layer does. Consider mirroring the `_err()` envelope on 400s.

### 2.3 Control endpoints — not exercised destructively
`/v1/shutdown` (+`/shutdown`), `/reload`, `/v1/session/end` were intentionally not called to avoid disrupting the warm engine mid-test. Their routes are registered; behavior not verified here.

---

## 3. Critical bug found and FIXED during HTTP testing

### BUG-MH (HIGH) — graph catch-up lane silently broken by missing `MinHash.update_batch`
- **Symptom:** `/v1/search` keeper block reported `"warnings": ["graph rebuild failed: 'MinHash' object has no attribute 'update_batch'"]`, with `strategy:"none"`, `refreshed:false`. The graph (AST/edge) sync lane was failing on every rebuild while the hot BM25 lane masked it — so `search`/`map` stayed fresh but the code graph (used by `pack_context`/`expand_context`) went stale.
- **Root cause:** `packages/graphify/dedup.py:51` calls `m.update_batch([...])` (with a comment referencing `MinHash.update_batch`), but `packages/graphify/_minhash.py`'s `class MinHash` defined only `update()` — the `update_batch` method was **never present in the source**. Every `_make_minhash` call raised `AttributeError`, aborting dedup and therefore the graph rebuild.
- **Fix:** Added a vectorized `MinHash.update_batch(values)` to `_minhash.py`: hashes all inputs in one `np.fromiter` pass, builds the `(num_perm, n)` permuted-hash matrix, and folds with a single `min(axis=1)` + `np.minimum`. No-op on empty batch.
- **Verification:**
  - Bit-identical to the per-value `update()` loop over 200 values (`np.array_equal` → True); empty batch is a safe no-op.
  - `_make_minhash('graph extractor pipeline')` returns a 128-wide sketch with no error.
  - Deployed via `scripts/sync-uv-install.ps1` (`differ:0 missing:0`), restarted the engine (pid 19180 → 24588).
  - After restart + a graph-inclusive sync/rebuild, `/v1/search` keeper `warnings` and `graph_error` are **empty**; `strategy` no longer errors.
  - MCP `expand_context(packages/graphify/dedup.py::_make_minhash, callees)` returns the real callee `_shingles` — graph edges intact.
- **Status:** Fixed in `packages/graphify/_minhash.py`, deployed, engine restarted, verified end-to-end. Not yet committed (no commit requested).

---

## 4. CLI surface

Tested via the installed uv-tool exe: `& "$env:APPDATA\uv\tools\scubiee\Scripts\scubiee.exe" <cmd>`. Destructive commands (`wipe`, `remove`, `halt`, `stop`, `disconnect`, `never-index`) were **not** run to preserve the working install.

### 4.1 Verified working — OK
| Command | Result |
|---|---|
| `status` | Full JSON status (engine health, warm, chunks). |
| `gate` | `1:ce_…` compact managed line. |
| `list` | Managed repos JSON — repo enrolled, `index_state:ready`. |
| `settings` | Prefs JSON (auto-admission, resource limits, prefs_path). |
| `search "<q>"` | Dense hits (~655ms). |
| `map "<q>"` | Ranked cards + `suggested_seeds`. |
| `pack "<query>" --seed-file … --seed-symbol …` | Full heatmap (query is a required positional). |
| `expand --node "file::symbol" --direction callees` | 10 callee delta nodes. |
| `engine status` | Engine url/running/health. |
| `preflight` | Dependency + capability report (faiss etc.), `ok:true`. |
| `doctor` | Readiness + repair plan (see OBS below). |
| `resources` | Hardware snapshot (CPU/RAM/accel profile `dml`) + live budgets. |
| `certify` | Release certification gate, `failures:[]`. |
| `--help` | Enumerates all 40 subcommands with descriptions. |

### 4.2 Observations / issues
- **ISSUE (QA-6):** CLI argument names diverge from the MCP tool parameter names, which is easy to trip over. `pack` takes `query` as a **required positional** (plus `--seed-file`/`--seed-symbol`), and `expand` requires `--node` (positional `path` is not the node). The MCP equivalents use `seed_file`/`node` keyword args. Both CLI commands print a clear argparse usage error, so this is a discoverability/consistency nit, not a failure.
- **OBS (QA-7):** `doctor` correctly flags a **stale registry entry** pointing at a deleted pytest temp dir (`…\pytest-1548\test_gate_with_root_marks_enro0\enrolled`, project `ce_d609…`) and offers a manual repair. This is leftover state from test runs, not a real repo — good that doctor detects it, but the registry accumulates dead test enrollments over time. Worth a periodic prune.
- **OBS (QA-8):** CLI `status` reports a live `warm_phase` (`"dense"`/`"ready"`), which is correct — confirming that the stuck `"down"` value (QA-4) is specific to the `/health` HTTP endpoint's payload builder, not the shared warm-state logic.
- **Environment note:** All CLI output is heavily interleaved with a Miniconda/pydantic `logfire`/`opentelemetry` `ImportError` warning on this machine. It's cosmetic (the plugin just isn't installed) and does not affect exit codes, but it makes CLI output noisy and can swallow stdout in piped PowerShell contexts.

---

## 5. Lifecycle & sync propagation

Tested against the warm engine by creating/deleting/renaming files with unique markers and polling `/v1/search` (hot lane) and `pack_context` (graph lane). All timings on this machine (Ryzen 7 5800H, DirectML, ~7860 chunks).

### 5.1 Warm-up — OK
- After the mid-test engine restart (BUG-MH deploy), soft-locate was ready in ~4–5s and dense (`embedder_loaded:true`, `semantic_ready:true`) followed shortly after — consistent with the documented ~4s soft / ~11s dense profile. `map`/`pack` were usable during the soft window (with a note that dense densifies once the embedder finishes).

### 5.2 New file — OK
- Created `packages/pipeline/zz_qa_synctest.py` with a unique symbol → hot lane (`/v1/search`) surfaced it in **362ms** (first poll after `/v1/dirty`).
- Graph lane: `pack_context` resolved the new symbol as a valid seed (`seed_coverage:true`, correct `loc`) in ~0.76s (mostly trace-bundle re-hydration). `thin:true` because a standalone function has no edges yet — correct.

### 5.3 Delete — OK (test-harness caveat)
- Deleted the file → after a short settle, the path was gone from search hits (`in_hits=0`, `on_disk=False`).
- **Caveat (not a product bug):** a naive `-match "filename"` against the raw search response gives a false positive because the response echoes the query string; checking the `hits[].file` field precisely is required. Documented so future harnesses don't misread delete propagation.

### 5.4 Rename — OK with lag (OBS)
- Renamed `zz_qa_rename_src.py` → `zz_qa_rename_dst.py`.
- **OBS (QA-9):** Immediately after rename the **new path was indexed but the old path lingered** (`src_after=1, dst_after=1`). After a fuller reconcile/settle the stale old path was evicted (`src_in_hits=0, dst_in_hits=1`). So rename = add-new (hot lane, immediate) + evict-old (deferred, on the next merkle reconcile). Brief window where a renamed symbol appears under both paths. This matches the known K4 rename-eviction lag; low impact but worth noting for freshness-sensitive callers.

### 5.5 Ignore rules — OK
- Created `sandbox/zz_qa_ignored.py` (a `.scubieeignore`d dir) with a unique symbol → after sync it was **not indexed** (`ignored_in_hits=0`) though present on disk (`on_disk=True`). `.scubieeignore` (sandbox/, testdata/, research/, experiments/, references/, design_benchmarks/, fixtures/) is honored correctly.

### 5.6 Workspace session brain — OK
- Covered in §1.7: `pin`/`show`/`clear` all behave; `clear` fully resets topic/pins/heatmap/map_queries. The session heatmap accurately accumulates per-file hits/roles/last_queries across `map`/`pack` calls.

**Lifecycle/sync verdict:** Two-lane sync works as designed — hot BM25 lane reflects new files and content in well under a second; the graph lane and merkle reconcile catch up shortly after. Rename eviction lags by one reconcile pass (QA-9). Ignore rules are correctly enforced.

---

## 6. Consolidated issue register

| ID | Severity | Area | Summary | Status |
|---|---|---|---|---|
| **BUG-MH** | **HIGH** | graphify / sync | `dedup.py` calls `MinHash.update_batch()` but the method didn't exist in `_minhash.py` → `AttributeError` aborted every graph rebuild; graph catch-up lane silently degraded (`strategy:"none"`), masked by the hot BM25 lane. | **FIXED & verified** (added vectorized `update_batch`, deployed, engine restarted, keeper warnings clear, graph edges resolve). |
| **QA-4** | BUG (low impact) | HTTP `/health` | `warm_phase` reported `"down"` even on a fully warm engine (stale on-disk phase not overridden by live flags); contradicted sibling fields and the MCP/CLI status. | **FIXED & verified** (derive phase from live warm flags in `ce_service.py`; `/health` now reports `"dense"` when warm). |
| **QA-5** | ISSUE | HTTP API | `/v1/graph_neighbors`, `/v1/query_graph`, `/v1/lifecycle` return a bare HTTP 400 with no JSON error body, unlike the MCP `_err()` envelope. Harder to debug bad requests. | Open. |
| **QA-1** | ISSUE | status / hygiene | `status full` dirty-ledger surfaced stale test artifacts (`zz_*` files) tracked in the tree. | Resolved (files cleaned up this session). |
| **QA-2** | ISSUE | MCP `map` | `suggested_seed[0]` returned a `_`-prefixed private helper (`_managed_locate_err`) while the tool's own `next` hint says "Forbid `_helper` seeds." Suggester vs. guidance disagree. | Open. |
| **QA-6** | ISSUE | CLI | CLI arg names diverge from MCP params: `pack` needs a positional `query`; `expand` needs `--node`. Clear argparse errors, but inconsistent with the MCP surface. | Open (nit). |
| **QA-7** | OBS | registry | `doctor` flags a stale registry entry pointing at a deleted pytest temp dir. Dead test enrollments accumulate over time. | Open (housekeeping). |
| **QA-3** | OBS | MCP `expand_context` | `callers` returns structural graph edges only, not every textual reference — don't treat it as an exhaustive reference list. | By design. |
| **QA-8** | OBS | status | CLI/MCP `status` report a live `warm_phase`; confirms QA-4 is `/health`-endpoint-specific. | Info. |
| **QA-9** | OBS | sync / rename | After a rename the new path indexes immediately but the old path lingers for one reconcile pass before eviction (K4 lag). Brief window where a symbol appears under both paths. | Low impact. |

### Notes / non-issues
- **Env noise (this machine):** a Miniconda `pydantic`/`logfire`/`opentelemetry` `ImportError` warning interleaves all CLI/subprocess output. Cosmetic (plugin not installed), but it can swallow stdout in piped PowerShell — a testing hazard, not a Scubiee defect.
- **Stray build artifact:** `build/lib/pipeline/zz_editrepro_*.py` exists in the `build/` output tree (pre-existing, not indexed). Left untouched — it's a build artifact, not source.
- **Version drift (prior observation):** git branch is `release/0.3.131` while code reports `0.3.132`. Cosmetic; noted for release hygiene.

---

## 7. Coverage checklist

What was exercised in this QA pass:

- **MCP tools (8/8):** `gate`, `status` (summary/full/gate), `map` (enriched + vague), `pack_context` (seed / include_bodies / bad-seed / no-seed), `expand_context` (callees/callers/effects), `collect_hot_context` (explicit ids), `workspace` (show/pin/clear), `expand` (valid handle / bad handle). ✓
- **HTTP GET (8/8 routes):** `/health`, `/`, `/status`, `/v1/status`, `/api/settings`, `/v1/settings`, `/v1/resources`, `/dashboard` + 404 path. ✓
- **HTTP POST retrieval (11):** `search`, `grep`, `outline`, `read_span`, `follow_imports`, `grep_ident`, `graph_neighbors`, `query_graph`, `note_locate`, `session_anchors`, `reopen_anchors`, `dirty`. ✓
- **HTTP control:** `shutdown`/`reload`/`session/end` intentionally not fired (would disrupt the warm engine). Routes confirmed registered only. ⚠ (deliberate)
- **CLI (14 exercised):** `status`, `gate`, `list`, `settings`, `search`, `map`, `pack`, `expand`, `engine status`, `preflight`, `doctor`, `resources`, `certify`, `--help`. Destructive (`wipe`/`remove`/`halt`/`stop`/`disconnect`/`never-index`) intentionally skipped. ⚠ (deliberate)
- **Lifecycle/sync:** warm-up phases, new-file/delete/rename propagation (both lanes), ignore rules, workspace session brain. ✓

### Not covered (scope/environment limits)
- Cold-start-from-zero timing (engine was kept warm; a prior session measured ~4s soft / ~11s dense).
- CPU-only embedder path (this machine uses DirectML).
- Large-repo / multi-repo scale (single repo, ~7860 chunks).
- Destructive CLI/HTTP control paths (deliberately avoided to keep the engine serving).
- Full pytest suite green end-to-end (known pre-existing failures in `test_open_preservation.py` golden-envelope drift and one `test_multi_seed_v1` import — unrelated to this pass).

---

## 8. Overall assessment

Scubiee's three surfaces are functional and, when warm, fast: MCP locate ladder in the tens-to-hundreds of ms, HTTP retrieval ~10–20 ms, sync propagation sub-second on the hot lane. Error handling on the MCP surface is clean and hint-bearing.

The one material defect found was **BUG-MH** — a missing `MinHash.update_batch` that silently broke the graph catch-up lane on every rebuild. It was masked by the hot BM25 lane (search stayed fresh) so it would not surface in casual use, but it degraded `pack_context`/`expand_context` freshness over time. It is now **fixed and verified end-to-end**.

Both bugs are now fixed: **QA-4** (`/health` `warm_phase` stuck at `"down"`) was traced to a stale on-disk phase not being overridden by live warm flags, fixed in `ce_service.py`, and verified (`/health` now reports `"dense"` when warm). The remaining items are an HTTP error-envelope consistency gap (QA-5) and minor nits/observations (QA-2/QA-6/QA-7 and the by-design QA-3/QA-8/QA-9).
