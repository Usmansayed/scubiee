# Where a `map find` spends its time — first call, new session, after idle

Scubiee 0.3.166, warm engine (127.0.0.1:8765), this repo (8,319 files walked, 4,944 code/test files
grep-scoped), Windows 11. Env exactly as in `.cursor/mcp.json`.

## TL;DR

The ~3 s "first find" is **not** the engine and **not** idle decay. It is a race inside the
freshly spawned map worker: a `find` that arrives within ~2 s of the worker starting runs at the
same time as the worker's background `_warm` thread, and its "connections" caller-grep re-reads
the whole repo from disk itself.

| Scenario (real stdio path through the bridge) | `map find` |
|---|---|
| find sent right after `initialize` (run 1 / run 2) | **2,874 / 2,980 ms** |
| same find, sent 4 s after `initialize` (run 1 / run 2) | **495 / 490 ms** |
| next new query, same session | ~250–480 ms |
| new query after 200 s idle (worker alive) | 456 ms |

Removing the race saves ~2.4 s. After idle the cost is ~+200 ms over steady state (a stat-TTL gap), not seconds.

## The path a find takes

1. Cursor → `pipeline.mcp_bridge` (stdio). At `initialize` the bridge spawns the worker
   `pipeline.map_v3_server` (`ChildWorker.ensure_ready` → `spawn`) and forwards the handshake.
   `initialize` = 720–760 ms (process spawn + imports + bridge anchor register + runtime attach).
   On `tools/call` the bridge only forwards; no extra work. Measured stdio overhead ≈ 0–10 ms
   (stdio 490 ms vs in-process 485 ms for the same call).
2. Worker `main()` starts two daemon threads:
   - `_warm`: `/health` (pre-pay urllib init), `_repo_files()` walk, then `_lines()` read of all
     4,944 code/test files, then stamps `_TEXT_VALIDATED_AT`. **Takes 1.8–2.4 s.**
   - `_keepalive_loop(120 s)`: `/health` + re-stamp grep stat-TTL while idle.
3. `tool_map` → `cfg_find` (cluster_files=2) → `map_v3_helpers.cfg_find`:
   - `_search` → engine `POST /v1/search` (query embed + vector search)
   - per hit: `_enclosing` / `_outline` (Python AST, mtime-cached) + `_code_text`
   - `_append_connections` → `_grep(r"\bNAME\s*\(", scope="code")` over **every code file**
     (callers block), then `_callees_in`
   - body packing (`_numbered`)

## Stage breakdown (in-process probe, wraps every helper, main thread only)

| Stage | find racing `_warm` | find after `_warm` done | next new query | after 200 s idle |
|---|---:|---:|---:|---:|
| `_grep` (connections callers) | **2,113** | 146 | 21 | 343 |
| └ of which `_lines` disk reads | 1,533 (3,604 files) | 7 (81) | 6 | 5 |
| engine `/v1/search` round trip | **775** | 112 | 67–83 | 85 |
| `_repo_files` walk | 261 | 0 | 0 | 0 |
| `_enclosing`+`_outline` (AST) | 132 | 141 | 81 | 11 |
| `_code_text` | 88 | 86 | 68 | 11 |
| **TOTAL** | **3,117** | **492** | **244–478** | **456** |

### Why each number is what it is

- **Grep 2,113 ms (root cause #1).** `_text_cached_fast` only skips disk when `_warm` has
  already stamped that file. Mid-warm, the find thread reads ~3,600 files itself while the warm
  thread reads the rest. Both are GIL-bound Python (`read_text` + `splitlines`), so they slow
  each other down. Once warm is done the same grep costs 18–21 ms.
- **Engine search 775 ms vs ~70–110 ms (root cause #2, same race).** The engine itself is fast;
  the worker's HTTP call and JSON parse are starved of the GIL by the warm thread's read loop.
- **`_repo_files` 261 ms.** Both threads see `_FILES is None` and walk the repo concurrently
  (duplicate walk).
- **AST 130–140 ms on first find.** First parse of ~25 hit files; cached afterwards (11 ms).
  Real but small; this is the bulk of the remaining ~490 ms "warm first find".
- **After idle +~320 ms on grep.** `_keepalive_loop` skips its pulse if a call happened within
  the last 120 s. A call at t≈3 s makes the t=120 s pulse skip; the next pulse is t=240 s. The
  effective stat-TTL is 180 s (120 × 1.5), so a call at t=203 s finds every stamp expired and
  pays a ~5k-file `stat()` storm (343 ms). Engine search after idle stayed ~85 ms — the
  engine/embedder did not go cold in this run (Cursor's bridge is a registered client).

## When users actually hit the 3 s

The worker is not killed on idle (no idle eviction in shared mode; only death, hot-reload build
change, or >8 sessions respawn it). So the race fires only when the first find lands within ~2 s
of a worker (re)spawn:

- Cursor start / MCP reconnect where the agent's first call is immediate
- right after an upgrade (hot-reload build-id change → respawn on the next `tools/call`, so
  the find that triggers the respawn is guaranteed to race)
- scripted/new-session probes (our `scubiee_one_find.py`, host-sim lanes) — which is why the
  benchmarks show ~3 s

Plain idle gaps with a live worker cost ~0.45 s, not 3 s.

## Fix candidates (not implemented — for a follow-up decision)

1. **Don't duplicate warm's work on the find path.** If `_warm` is still running, either
   (a) skip the connections callers-grep for that one call (saves ~2.1 s; the answer is
   unchanged, only the callers line is missing), or (b) have `_grep` wait on a warm-done event
   instead of reading files itself (no duplicate reads, less GIL thrash; still pays the warm
   remainder).
2. **Share the `_repo_files` walk** under a lock so warm and the first call don't both walk.
3. **Keepalive gap:** pulse on time-since-last-stamp instead of time-since-last-call (or TTL
   ≥ 2 × interval) so the post-idle grep never re-stats ~5k files (~300 ms).
4. **Respawn-triggered race:** on hot-reload respawn, start the new worker's warm before
   forwarding the pending call, or answer the triggering call from the old worker.

Per the release rule, any fix must be validated with the live host-sim battery
(`mcp_host_sim` Lane A live + settle, `warm_contract_acceptance`, `scubiee_mcp_ship_check`),
not unit tests alone.

## Reproduce

- `%TEMP%\find_probe.py immediate|afterwarm [idle_s]` — fresh worker in-process, per-stage timers
- `%TEMP%\scubiee_one_find.py <wait_s>` — real Cursor-identical stdio session, one find
- `%TEMP%\warm_check.py` — confirms `_warm` stamps all 4,944 grep files; grep after = 18 ms
