# Keeper sync lifecycle (Cursor-aligned)

**Status:** approved (user 2026-08-03)  
**Scope:** MCP + `ctx serve` session lifecycle; root-hash-first idle path; final check on cwd switch and process exit.

## Problem

Background sync must stay alive while a workspace session is open, stay cheap when nothing changed, and shut down cleanly when the user closes the app or switches working directory — with **one last lightweight check** so the index is not left knowingly stale.

A naive full freshness/reindex path previously walked `.venv-proof` / untracked junk and froze the host. The keeper must never do that.

## Goals

1. Keep indexing current for the active repo while MCP / `ctx serve` is running.
2. Idle tick starts with **one question**: did the Merkle **root** of the indexed universe change?
3. On `set_repo` / cwd switch **and** process shutdown: run that same cheap check once more, sync if needed, then stop.
4. Match Cursor + Claude Context product shape (~5 min poll, Merkle gate, async dense, search stays available).

## Non-goals

- Remote turbopuffer / simhash team index reuse (Cursor cloud-only).
- OS-wide daemon outside MCP/`serve` (CLI one-shots stay opt-in).
- Auto full-corpus reindex on timer (`CTX_ALLOW_BG_FULL` remains off by default).
- Replacing query-time `ensure_fresh` / BM25 hot-patch (those stay as the Cursor “vectors are pointers” path).

## Prior art (research summary)

| Source | Pattern we copy |
|--------|-----------------|
| [Cursor secure indexing](https://cursor.com/blog/secure-codebase-indexing) | Merkle tree; sync walks only divergent branches; root match ⇒ skip; embeddings async |
| [Cursor indexing docs](https://cursor.com/help/customization/indexing) | Index on open project; periodic sync ~5 minutes |
| Claude Context MCP | Background sync default on; `SYNC_INTERVAL_MS` = 5m; `.sync-trigger`; stderr-only |
| Our `docs/research-freshness.md` | Disk text at query time; hybrid boost while dense lags |

## Design

### Components

1. **`KeeperLoop`** (evolve `BackgroundSyncLoop` or thin wrapper)
   - Owns one `repo: Path`
   - Interval from `CTX_SYNC_INTERVAL_MS` (default **300000**)
   - Initial delay from `CTX_SYNC_INITIAL_DELAY_MS` (default **5000**)
   - Optional trigger watcher (`~/.context-engine/.sync-trigger`) unchanged

2. **`root_probe(repo) -> RootProbeResult`**
   - Load stored Merkle snapshot + mtimes from `PipelineStore`
   - Re-hash **indexed universe only** (mtime short-circuit; never whole-tree / venv)
   - Optionally include **newcomers under `meta.fast_roots`** (same as incremental discovery)
   - Compute `root_hash(current)` and compare to stored `root_hash`
   - Return `{ clean: bool, root, stored_root, diff? }` — **no embed, no graphify** on clean

3. **`keeper_tick(repo)`**
   ```
   probe = root_probe(repo)
   if probe.clean:
       log "root clean" (stderr); return
   incremental_sync(repo)  # existing caps / refuse-full guards
   ```

4. **`final_check(repo)`**
   - Exactly one `keeper_tick(repo)`
   - Best-effort; errors logged, never block exit hard

### Lifecycle (C = both)

```text
MCP main / ctx serve start
  ├─ warm engine (existing)
  └─ KeeperLoop(repo).start()     # default ON for these entrypoints

every interval:
  └─ keeper_tick(repo)

set_repo(new) / cwd switch:
  ├─ final_check(old)
  ├─ KeeperLoop.stop()
  └─ start warm + KeeperLoop(new)

process exit (atexit / KeyboardInterrupt / MCP shutdown):
  ├─ final_check(current)
  └─ KeeperLoop.stop()
```

### Defaults / env

| Var | Default (MCP / serve) | CLI one-shot |
|-----|----------------------|--------------|
| `CTX_BACKGROUND_SYNC` | `1` (on) | unset / off unless user sets |
| `CTX_SYNC_INTERVAL_MS` | `300000` (5m) | n/a |
| `CTX_SYNC_INITIAL_DELAY_MS` | `5000` | n/a |
| `CTX_ALLOW_BG_FULL` | `0` | `0` |
| `CTX_TRIGGER_WATCHER` | `1` | n/a |

Implementation note: flip default **inside** MCP/`serve` start paths (set env if unset), rather than flipping the global sync_loop default for every import — keeps smoke scripts and CLI safe.

### Safety invariants (hard)

1. Root probe never descends into junk (`.venv*`, `site-packages`, `node_modules`, …) — reuse `is_junk_rel` / walk pruning.
2. Indexed-universe-only by default; newcomers only under configured `fast_roots`.
3. `incremental_sync` still refuses `strategy=full` and oversized touch sets.
4. Idle clean path does **not** load FastEmbed / DML.
5. All keeper logs → **stderr** only (MCP protocol hygiene).

### Search interaction

- Keeper updates dense in the background (Cursor-style async).
- `search_code` / `ensure_fresh_for_search` remain: small incremental sync-before-search; else BM25/disk hot-patch + dirty boost while dense catches up.
- Hit previews continue to read live disk spans.

### Observability

- `status` tool includes: `keeper: { running, interval_ms, last_probe, last_sync }`
- Last probe: `{ clean, root, ms }` so agents can see “root clean” vs sync.

## Implementation sketch (files)

| File | Change |
|------|--------|
| `packages/pipeline/root_probe.py` (new) or `freshness.py` | `root_probe()` cheap API |
| `packages/pipeline/sync_loop.py` | `keeper_tick` / `final_check`; call probe first |
| `packages/pipeline/mcp_server.py` | default sync on; `atexit` + `set_repo` final_check |
| `packages/pipeline/server.py` | same shutdown + default on |
| `scripts/timed_sync_probe.py` | optional: assert root-clean no-op path |
| `docs/research-freshness.md` | pointer to this keeper spec |

## Test plan

1. **Root clean no-op:** with warm index, `root_probe` / tick < ~200ms on packages-sized corpus; no embed load logs.
2. **Edit detected:** change one indexed file → next tick (or shortened interval) refreshes that file only.
3. **New file under packages/:** discovered via fast_roots; searchable after tick.
4. **Delete:** removed from Merkle + vectors after tick.
5. **set_repo:** final_check runs on old; new loop starts; no orphan threads.
6. **Process exit:** `atexit`/`KeyboardInterrupt` runs final_check once (log line).
7. **Junk immunity:** untracked `.venv-proof` must not flip root or inflate diff.
8. **MCP smoke:** warm + search + status shows keeper running; `CTX_BACKGROUND_SYNC=0` still disables for tests.

## Risks

| Risk | Mitigation |
|------|------------|
| Mtime clock skew false clean | Hash on mtime mismatch (existing leaf verify) |
| Probe scans too much | Universe = merkle keys ∪ fast_roots collect only |
| Exit final_check slows shutdown | Cap: root probe always; sync only if dirty and touch ≤ `CTX_INCREMENTAL_MAX_TOUCH` |
| Multiple MCP instances | Optional lock file later (CC pattern); v1: document single keeper per repo |

## Success criteria

- Idle 5m ticks are root-hash gated and do not load the embedder when clean.
- Session close and cwd switch each perform exactly one final check.
- No regression of venv storm (freshness dirty flood / auto-full).
