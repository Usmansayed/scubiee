# Scubiee bugfix log — context-engine audit follow-up

Source of bugs: `docs/scubiee-context-engine-audit.md` (build 0.3.132).
Process per bug: investigate → research → fix one thing → test → document.
Windows, engine `:8765`, uv-tool install. Nothing committed.

---

## BUG-A (MAJOR) — `map` recommends seeds `pack_context` cannot resolve

**Symptom.** `map` returns `suggested_seeds` for an edited/new file; passing that
seed into `pack_context` fails with `seed not found`. Breaks the core
locate→pack workflow for exactly the files an agent is editing.

### Investigation

Two read paths for two corpora:
- **map / search** read the live dense+BM25 index (`chunks.jsonl`, FAISS, `graph.json`),
  refreshed by the keeper on every save. Fresh.
- **pack_context** resolves its seed against an AST *trace bundle* pickle at
  `.scubiee/cache/trace_repo_v{N}.pkl` via `context_trace._load_repo` →
  `resolve_seed_node(rt.nodes, …)`. `rt.nodes` comes from `extract_nodes(root)`
  baked into that pickle.

Bundle lifecycle (`packages/pipeline/context_trace.py`):
- `_repo_bundle_path` = `root/.scubiee/cache/trace_repo_v3.pkl`.
- `corpus_fingerprint(root)` (`trace_lab/corpus.py`) = sha1 over every project
  `*.py` file's `(mtime_ns, size)`. An edit **does** change it.
- `_load_repo` calls `_try_load_repo_bundle(..., allow_stale=True)`. When the
  on-disk fingerprint ≠ the current corpus it returns the bundle anyway with
  `stale=True`, and `_load_repo` uses it as-is. A fresh bake only happens when the
  bundle is *missing* (and only if not on the MCP bridge/locate child, which set
  `CTX_TRACE_NO_BAKE`/`CTX_MCP_BRIDGE_CHILD` and raise `ast_bundle_missing`).
- `hydrate_ast_bundle` also loads `allow_stale=True` and never rebakes unless the
  bundle is missing and `bake_on_miss=True`.
- `_save_repo_bundle` is the only writer, called only from a cold bake in
  `_load_repo`.

**Root cause:** nothing rebakes the bundle after an edit. Grepping
`sync_loop / incremental / ce_service / runtime_publish` for
`hydrate_ast_bundle|rebake|bake_on_miss|persist_trace` → **no matches**. Saves
update chunks/graph/vectors but never the trace bundle, and the stale bundle is
served forever. Live proof: `trace_repo_v3.pkl` was from Sep 26 1:57pm — 0 nodes
for files created this session, and `server.py` had 20 nodes but none named
`EngineHTTPServer` (a class edited after that bake). map saw them; pack did not.

**Why stale-accept exists:** rejecting the stale bundle made the locate worker
cold-bake AST synchronously on the request (~15-23s `ast_warming`) — the BETA-02
regression. So "serve stale" is deliberate; "revalidate" is missing.

### Research

Standard fix is **stale-while-revalidate (SWR)**: serve the stale entry now,
kick an async refresh so the *next* request is fresh. Confirmed as the industry
pattern for exactly this "don't block the request, don't serve stale forever"
tension:
- Cloudflare Cache — "Revalidation is fully asynchronous … the first request
  after expiry triggers revalidation in the background [and] immediately receives
  stale content" ([docs](https://developers.cloudflare.com/cache/concepts/revalidation/)).
- Google Cloud CDN — serves the just-expired content "while triggering a separate
  revalidation" ([docs](https://cloud.google.com/cdn/docs/serving-stale-content)).
- Fastly, Dynatrace SWR, Next.js ISR, Laravel `Cache::flexible()` — same shape.
Content rephrased for compliance with licensing restrictions.

Scubiee already does the "serve stale" half (BETA-02). The missing half is a
background revalidate, triggered on the keeper's quiet-window cadence.

### Fix

Stale-while-revalidate, in two halves (both needed — the first without the second
does nothing, because the long-lived MCP locate worker caches the trace in
memory for 600s).

`packages/pipeline/context_trace.py`:
- `_bundle_mtime_ns(root)` — cheap disk mtime of the bundle.
- `_RepoTrace.bundle_mtime_ns` — the disk mtime the in-memory trace was built
  from. `_load_repo`'s cache hit now also requires
  `cached.bundle_mtime_ns == _bundle_mtime_ns(root)`, so a background rebake takes
  effect in the worker on its next `_load_repo` instead of waiting out the TTL.
  **(This was the missing second half — the first live run still failed until
  this was added.)**
- `_load_repo(..., force_bake=True)` and `hydrate_ast_bundle(..., force=True)` —
  re-extract and rewrite the disk bundle even when a stale one exists.
- `_spawn_ast_bake(root, force=True)` — force-bake in a fresh interpreter (no
  engine GIL) so the child writes a fresh disk bundle.
- `ast_bundle_is_stale(root)` — fingerprint/engine/graphify/version check.
- `refresh_ast_bundle_if_stale(root, block=)` — single-flight (`_REFRESH_INFLIGHT`)
  + fingerprint coalescing (`_REFRESH_LAST_FP`); spawns the force-bake only when
  stale; returns `{skipped: fresh|in_flight}` otherwise.

`packages/pipeline/sync_loop.py`:
- `_start_ast_revalidate()` runs `refresh_ast_bundle_if_stale` on its own daemon
  thread (single-flight). The `_run` loop calls it on the `CTX_AST_REVALIDATE_S`
  cadence (20s), skipping only a *very recent* locate (`CTX_AST_REVALIDATE_QUIET_S`,
  5s) — not the full 60s streak and not `_hot_work_pending`, so a tight
  map/edit loop cannot starve it. The rebake is a below-priority child, so it is
  safe to run during an active session (like the graph catch-up).

Tuning: gated first on `_locate_streak_active` + `_hot_work_pending` (matching the
newcomer scan), but a live map/pack loop kept the streak alive forever and the
rebake never ran. Relaxed to the 5s locate-quiet check.

### Verification

- Unit: `tests/test_ast_bundle_revalidate.py` (6): stale-on-missing→fresh-after-bake;
  edit→stale→force rebake makes the new symbol resolvable; single-flight +
  fingerprint coalescing; skip-when-fresh; keeper starts a revalidate thread;
  **worker in-memory cache reloads when the disk bundle mtime moved** (the
  second-half regression). All pass.
- Live: `scripts/ast_revalidate_live_probe.py` — create a new file, map finds the
  seed in 1.7s, and **pack resolves it in 27.3s with no manual rebake** (was ∞
  before — pack failed indefinitely). Keeper log shows `[keeper] ast bundle
  revalidated`. Fix confirmed end-to-end through the real MCP bridge.

**Status: FIXED.**

---

## BUG-B (minor) — `gate` with a wrong `project_id` returns bare `0`

**Symptom.** `gate(project_id="ce_deadbeef")` returns the string `0` — no error,
no hint; indistinguishable from a genuinely unmanaged repo.

### Investigation

Path: `gate_impl` → `_bind_request_repo(project_id=…)` → `_resolve_request_repo`.
A non-empty `project_id` that the registry cannot resolve (or a wrong id on a real
`root`) returns the sentinel `Path("__scubiee_unresolved_project__")` — deliberately
kept out of the real repo space so a mistyped id can never bind and *look* managed.
`_gate_line` then sees `managed=false` and emits the contract's "unmanaged" token
`0`. Gate contract: `0`=unmanaged, `0:r`=retry after TTL, `1:ce_…`=managed,
`p`=paused. So `0` is *correct* (not managed), but a wrong id and a genuinely
unmanaged folder are reported identically — the agent can't tell "you typoed the
id" from "this repo isn't enrolled". Empty id correctly falls through to the
workspace (`1:ce_…`).

### Research

Not a code-behavior bug, a legibility one — same class as
[FastMCP issue #536](https://github.com/jlowin/fastmcp/issues/536): a model that
gets an opaque error "unable to do error correction on its own". Standard fix is a
distinct, self-describing error sub-code + a one-line remediation hint (rephrased
for compliance). Keep the `0` prefix so the "not managed → native tools" contract
still holds for non-Scubiee-aware parsers.

### Fix (`packages/pipeline/mcp_locate.py`)

- Named the sentinel `_UNRESOLVED_PROJECT` (was a bare magic string in two spots).
- `_request_repo_unresolved()` — True when the current call bound the sentinel.
- `gate_impl`: when the bind is unresolved, return `0:badpid` + a one-line hint
  ("could not resolve project_id/root …; recheck the ce_… id or omit it") instead
  of a bare `0`.
- `status(detail="gate")`: returns `0:badpid` too.
- `_managed_signal_fields`: adds `bad_project_id: true` + hint to the not-managed
  branch, so `status` full/summary JSON explains it.

### Verification

- Unit: `tests/test_gate_bad_project_id.py` (5): wrong id binds the sentinel;
  empty id does not; `_request_repo_unresolved` detects only the sentinel;
  `_managed_signal_fields` flags `bad_project_id`. All pass.
- Live (`scripts/bugbc_live_probe.py`): wrong id → `0:badpid`; empty id →
  `1:ce_…`; good id → `1:ce_…`; `status(detail=gate)` wrong id → `0:badpid`.

**Status: FIXED.**

---

## BUG-C (minor) — inconsistent error envelope for missing required args

**Symptom.** A missing required arg (e.g. `map` with no `query`) returns the raw
framework text `{"_text":"Error executing tool …"}`, while other validation errors
return `{"ok":false,"error":…}`. Inconsistent for an agent parsing `ok`.

### Investigation

Tools register via `mcp.tool(name=…, fn=_wrapped)`. `map_impl(query, …)` declared
`query` with **no default**, so FastMCP marks it required and validates it *before*
calling the function. A missing `query` is rejected by the framework and the
tool's own `try/except ValidationError → _err(...)` never runs → raw
`Error executing tool map: 1 validation error …` text. An *empty* `query` passes
FastMCP's type check (it's a str) but fails the tool's internal
`MapArgs(min_length=1)` → clean `{ok:false}`. Hence the two shapes.

### Research

Confirmed the mechanism against FastMCP docs — "FastMCP validates required
arguments up-front so the underlying function never runs"
([standardbeagle FastMCP](https://errors.standardbeagle.com/PrefectHQ/fastmcp/missing-required-arguments-missing/)),
and [FastMCP issue #536](https://github.com/jlowin/fastmcp/issues/536): argument
validation errors lose detail and block model self-correction. Rephrased for
compliance. Because the framework validates *before* the wrapper, `_wrapped` can't
catch it — the fix has to be at the signature so the call reaches the tool, which
already returns the uniform `_err`.

### Fix (`packages/pipeline/mcp_locate.py`)

- `map_impl` / `pack_impl`: `query` now defaults to `""` (description prefixed
  `REQUIRED.`) so a missing arg reaches the tool instead of tripping the
  framework. `map` then fails `MapArgs(min_length=1)` → `_err`; `pack` gets an
  explicit `if not query.strip(): return _err(tool, "query required", …)` guard
  ahead of the seed check.
- Tradeoff: the advertised JSON-Schema `required` array no longer lists `query`
  (IDEs won't hard-block an omitted query). Accepted: a parseable `{ok:false}` an
  agent can self-correct on beats a raw framework string, and the tool still
  enforces the field. The `REQUIRED.` description keeps the intent visible.

### Verification

- Live (`scripts/bugbc_live_probe.py` + direct map probe): `map` no-query,
  `map` empty-query, `pack` no-query, `pack` empty-query all return
  `{"ok":false,"error":…}` (was raw `_text` for the missing-arg cases).
- Regression: `tests/test_locate_contract_bounds.py`, `test_attach_warm_pipeline.py`,
  `test_mcp_exploration_regressions.py` pass (the `map`/`pack` contract tests still
  hold with the defaulted signature).

**Status: FIXED.**

---

## Regression

Standard loop + all affected suites + the three new test files:
`test_root_probe test_live_reindexing test_dirty_ledger test_chunk_merkle
test_runtime_publish test_open_preservation test_sync_corpus_alignment test_wipe
test_watcher_recovery test_sync_status_canaries test_corpus_ghosts
test_graph_catchup_async test_project_id test_locate_contract_bounds test_fast_stat
test_prewarm_stamp_locked test_warm_autoload test_ast_bundle_revalidate
test_gate_bad_project_id test_embedder_wedge` → **352 passed, 0 failed**.

Four failures in `test_multi_seed_v1` (×3) and
`test_mcp_exploration_regressions::test_client_retries_transient_url_error` are
**pre-existing** — verified failing identically on a clean `HEAD` worktree, and
untouched by these changes (`test_multi_seed_v1` exercises
`trace_lab/multi_seed.py`, not edited here; the retry test reaches the live engine
on :8765).

All three fixes deployed to the uv-tool install (`sync-uv-install.ps1`:
`differ: 0  missing: 0`) and proven live through the real MCP bridge. Nothing
committed.

## Files changed

- `packages/pipeline/context_trace.py` — BUG-A: `force_bake`/`force`,
  `_spawn_ast_bake(force=)`, `ast_bundle_is_stale`, `refresh_ast_bundle_if_stale`,
  `_bundle_mtime_ns`, `_RepoTrace.bundle_mtime_ns` + cache-mtime check.
- `packages/pipeline/sync_loop.py` — BUG-A: `_start_ast_revalidate`, keeper
  quiet-window trigger (`CTX_AST_REVALIDATE_S` / `CTX_AST_REVALIDATE_QUIET_S`).
- `packages/pipeline/mcp_locate.py` — BUG-B: `_UNRESOLVED_PROJECT`,
  `_request_repo_unresolved`, `0:badpid` in gate/status, `bad_project_id` field.
  BUG-C: defaulted `query`, pack query-required guard.
- Tests: `tests/test_ast_bundle_revalidate.py` (6), `tests/test_gate_bad_project_id.py` (5).
- Probes: `scripts/ast_revalidate_live_probe.py`, `scripts/bugbc_live_probe.py`.
