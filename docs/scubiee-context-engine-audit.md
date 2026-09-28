# Scubiee context engine — full-feature audit

Build **0.3.132** (uv-tool install, engine `:8765`, Windows, Cursor + Kiro open).
Every surface driven end-to-end through the real process boundary: MCP tools via
the stdio bridge from `.cursor/mcp.json` (as Cursor/Kiro attach), the HTTP API on
`:8765`, and the `scubiee` CLI. Probes: `scripts/mcp_experiment.py`,
`scripts/ctx_engine_audit.py`, `scripts/mcp_seed_probe.py`,
`scripts/mcp_seed_probe2.py`, `scripts/ctx_concurrency_probe.py`.

## Verdict

The engine is healthy across every surface. All 8 MCP tools, the HTTP API, and
~40 CLI subcommands work; error paths are mostly clean; concurrency and lifecycle
are stable. **One real functional bug** (stale AST bundle breaks map→pack for
edited files) and a handful of UX/consistency papercuts.

| Surface | Result |
|---|---|
| MCP: gate, status, map, pack_context, expand_context, collect_hot_context, workspace, expand | all respond; see BUG-A |
| HTTP: /health, /v1/status, /v1/search, /v1/dirty, /v1/client/touch, /dashboard | pass |
| CLI: version, help, status, gate, search, map, ~40 subcommands | pass |
| Concurrency: 4 parallel MCP sessions, 16/16 map calls | pass, PID stable |
| Lifecycle: idle standby, wake, restart under load | pass |

---

## BUG-A (functional, MAJOR) — `map` recommends seeds `pack_context` cannot resolve

**map and pack_context read two different corpora.** `map` searches the live
dense/BM25 index (fresh after every save). `pack_context` resolves its seed
against a pre-baked AST pickle, `.scubiee/cache/trace_repo_v3.pkl`, loaded with
`allow_stale=True` (`context_trace._load_repo` / `_try_load_repo_bundle`) and
**never refreshed after an edit**. So `map` returns `suggested_seeds` for a file
whose symbols are not in the pickle, and passing that seed straight into
`pack_context` fails with `seed not found`.

Reproduced (`scripts/mcp_seed_probe2.py`, before a rebake):

```
old file: mcp_locate map_impl      seed=mcp_locate.py            -> pack ok=True  hot=7
old file: incremental_sync         seed=incremental.py::…        -> pack ok=True  hot=16
old file: server EngineHTTPServer  seed=server.py::EngineHTTPServer -> pack ok=FALSE seed not found
new file: graph_merge_worker       seed=…::start_graph_merge     -> pack ok=FALSE seed not found
new file: fast_stat                seed=…::cached_resolve        -> pack ok=FALSE seed not found
```

The bundle was 2 days stale (Sep 26 1:57pm): 0 nodes for the two files created
this session, and `server.py` had 20 nodes but none named `EngineHTTPServer`
(a class edited after the bake). map/search saw all of them; pack did not.

- It affects **exactly the files an agent is editing** — the ones most likely to
  be a pack seed.
- A restart does not fix it: the bake reloads the same stale pickle. Only a forced
  rebake (delete the pickle, or `CTX_TRACE_GRAPHIFY_REBUILD`-style path) refixes it.

**Confirmed fix direction:** deleting the pickle and rebaking (23.5s → 6582 nodes)
put `start_graph_merge`, `fast_stat` symbols, and `EngineHTTPServer` back; after an
engine restart all five seeds packed (`ok=True`, hot 1–16), and the full battery
re-ran green.

**Why it is stale on purpose:** rejecting the stale bundle made the locate worker
cold-bake AST on the request path (~15s+ `ast_warming`), the BETA-02 fix. The bake
was made stale-tolerant but nothing re-bakes after saves. The clean fix is to
rebake (or incrementally patch) the trace bundle when the graph catch-up commits
(the issue-6 child merge), so map and pack stay on one corpus. Until then, the
`map→pack` ladder silently degrades for edited code.

---

## BUG-B (minor) — `gate` with a wrong `project_id` returns bare `0`

`gate(project_id="ce_deadbeef")` returns the string `0` — no `ok`, no error, no
hint. A mistyped id resolves to the sentinel `__scubiee_unresolved_project__`
(`mcp_locate._resolve_request_repo`), so `managed=false` and `_gate_line` emits
`0`. That is the *documented* "not managed, use native tools" signal, and refusing
to bind the wrong repo is correct. But an agent that typos the id cannot tell a
wrong-id from a genuinely-unmanaged repo, and a bare `0` is not actionable.

- Empty `project_id` correctly falls back to the resolved project (`1:ce_…`).
- Suggestion: for a **non-empty but unresolvable** id, return `0:badpid` or a
  one-line hint so the caller knows the id was rejected, not that the repo is
  unmanaged.

---

## BUG-C (minor) — inconsistent error envelope for missing required args

Validation errors come back in two shapes:

```
map (no query)     -> {"_text":"Error executing tool map: 1 validation error …"}   (raw MCP framework)
pack (no query)    -> {"_text":"Error executing tool pack_context: …"}             (raw MCP framework)
map (query="")     -> {"ok":false,"tool":"map","error":"… String should have at least 1 character", "managed":true, …}
map (k=9999)       -> {"ok":false,"tool":"map","error":"… less than or equal to 25", …}
workspace (bad action) -> {"ok":false,"tool":"workspace","error":"… 'show','pin' or 'clear'", …}
expand (bad handle)    -> {"ok":false,"error":"unknown handle …"}
```

A **missing** required field escapes the tool's own `{"ok":false,…}` wrapper and
surfaces the framework's raw `Error executing tool …` text, while every other
validation error is wrapped. An agent parsing `ok` can't branch on the missing-arg
case. Minor, but worth normalizing so every error is a JSON object with `ok:false`.

---

## Observations (not bugs)

- **OBS-1 (map seed shape):** `map.suggested_seeds` carry `loc`
  (`file:142-202`) and `symbol` but **no `line`**. A caller copying a seed into
  `pack_context(seed_line=…)` must parse `loc`. pack resolves by symbol regardless,
  so this is cosmetic, but the two tools' seed shapes don't line up.
- **OBS-2 (pack policy=broad swaps the seed):** `policy=broad` on a function seed
  (`start_graph_merge`) returned a heatmap seeded at the enclosing class
  (`GraphMergeJob`). Reasonable widening, but the seed the caller passed is not the
  seed that was used — worth surfacing in the response (it is, as `seed.id`).
- **OBS-3 (expand_context empty deltas):** `direction=effects`/`broad`/`all` often
  return `count=0, delta=[]` with `ok=true` — same shape whether "no such hop
  exists" or "graph too thin". A caller can't distinguish. (Matches the earlier
  BETA-12 note.)
- **OBS-4 (CLI papercut):** every CLI invocation prints two `pydantic … logfire`
  plugin warnings on stderr, and on Windows `>` redirection writes UTF-16 with a
  BOM. Piping CLI JSON needs `-Encoding utf8` and stderr filtering. Cosmetic.
- **OBS-5 (no /metrics):** there is no Prometheus-style `/metrics` endpoint;
  `/v1/status` carries the diagnostics (~40 fields) instead. Fine, just noting.

---

## What passed (evidence)

**MCP tools** (warm session, `mcp_experiment.py`, post-rebake):

```
gate 1010ms · status 998ms · map cold 972ms / repeat 48ms (cache=last)
pack lean 84ms hot=6 · pack multi-seed · pack include_bodies chain[6] pack[4] · pack broad hot=5
expand callers/callees/effects/config/broad/all 60–90ms · with_bodies ok
collect (threshold) count=9 · collect (ids) count=1
workspace show/pin/show-after-pin/clear ok · expand file:lines ok · expand bad handle -> clean error
```

- **Cache invalidation after edit:** wrote a new function, polled `map`; it
  returned the fresh symbol within the catch-up window (no stale cache).
- **Session isolation:** a `workspace pin` in session A did not appear in session
  B (`ctx_engine_audit.py`).
- **Error paths:** empty seed → `seed_file required`; `_` seed → `seed not found`;
  unknown node → `node_unresolved`; unknown direction → `unknown direction`; bad
  handle → `unknown handle`; bad workspace action → literal-error.

**HTTP API:**

```
GET /health          200, rich JSON (version, pid, warm_state, embedder_loaded, generation, chunks…)
GET /v1/status       200, ~40 fields (lifecycle, keeper, dirty, sessions, resources, memory, meta…)
POST /v1/search      200 ranked hits; empty query -> 400; malformed JSON -> 400
POST /v1/dirty       ok
POST /v1/client/touch ok
GET /dashboard       200 text/html (5931 bytes)
GET /nonexistent     404 · GET /v1/search (wrong method) 404
```

**CLI:** `scubiee --version` → `scubiee 0.3.132`; `gate .` → `1:ce_…`;
`search "…" .` → ranked JSON (the newly-added `graph_merge_worker.py` ranks #1, so
the search index is fresh — only pack's AST bundle lagged); a bad subcommand →
clean argparse error listing all ~40 commands.

**Concurrency:** 4 parallel MCP sessions, 16/16 map calls ok, engine PID stable
(26448 throughout); first map ~2s under 4-way GIL contention, then 200–870ms.

**Lifecycle:** with no client attached the engine idle-stops after ~10s; `scubiee
engine ensure .` wakes it to `warm=ready`; a stop/ensure during a live search
recovers to `warm=ready` with a new PID.

---

## Priority

1. **BUG-A** — rebake/patch the trace AST bundle when the graph catch-up commits,
   so `map` and `pack_context` share one corpus. This is the one issue that
   silently breaks a core agent workflow (locate an edited symbol → pack it).
2. **BUG-B / BUG-C** — small response-contract fixes (wrong-id signal, uniform
   error envelope) that make failures legible to an agent.
3. **OBS-1..5** — cosmetic; fix opportunistically.
