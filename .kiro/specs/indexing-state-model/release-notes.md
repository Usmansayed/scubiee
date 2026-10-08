# Release notes — Unified Indexing & State-Management Model

**Version:** 0.3.144
**Spec:** `.kiro/specs/indexing-state-model/`

## Summary

Scubiee's indexing, change-detection, recovery, and lifecycle logic grew
case-by-case, so each edge case (delete latency, offline-change loss risk,
crash-mid-index recovery) needed its own patch and the patches perturbed each
other. This release introduces one durable state model that separates the three
entangled concerns:

- **Change detection** — "what changed" (the existing merkle/journal/probe
  primitives, unchanged).
- **Workload classification** — "how big / how urgent" (new, wall-clock based).
- **Execution & lifecycle** — "process up, work owed" (now gated on one record).

The unifying mechanism is a durable per-project **`index_state.json`** (single
source of truth) plus one idempotent **Reconciler** (detect → enqueue → classify)
invoked at engine start, on client connect, and from the periodic poll. It builds
entirely on existing primitives (merkle baseline, dirty journal,
publication-manifest fence, blue/green staging) — no primitive was rewritten, and
the retrieval/dense path is untouched.

## What's new / fixed

- **Offline changes are recovered automatically.** On engine start — before it
  reports write-current, with no MCP client required — the Reconciler diffs the
  working tree against `merkle.json` (thorough newcomer walk) and enqueues all
  drift into the durable journal. A folder of files added while the engine was
  off is now fully detected, not just mtime-moved folders.

- **Interrupted indexing resumes safely.** A durable build-intent record is
  written before staging is mutated and cleared only after the new generation's
  manifest publishes. On start, a build record owned by a dead pid is classified
  `interrupted`, stale staging is swept, and the live generation is never torn.

- **MCP connection state no longer drives indexing correctness.** Pending work is
  processed whether or not a client is connected; idle-stop is blocked while the
  index state is `indexing`, `reconciling`, or `interrupted`, so substantial work
  finishes before the engine stops.

- **Small changes stay silent; only substantial work is surfaced.** Pending work
  is classified by estimated embed cost converted to wall-clock seconds via a
  measured throughput. The agent is told about pending indexing only when it is
  genuinely minutes-scale (`reconciling`) or recovering (`interrupted`). The
  threshold is a time budget that self-adjusts to machine speed, not a file count.

- **Delete latency is now consistent.** The `CTX_HOT_DELETE_MASK` hack — which
  deferred a deletion-only batch whenever an unrelated hot save was pending — is
  retired by default. A deleted file now prunes within one consistent drain,
  independent of concurrent save activity.

## Agent-facing contract changes

- **`/health`** now carries:
  - `pending` — the derived pending object, or `null`. Present only when state is
    `reconciling` (substantial) or `interrupted`. Shape:
    ```json
    { "substantial": true, "state": "reconciling", "reason": "offline_batch",
      "estimated_seconds": 42.0, "done_units": 0, "total_units": 318,
      "search_usable": true, "action": null }
    ```
  - `index_fresh` — `true` when the served generation matches the tree with no
    substantial work owed. `search_usable` stays `true` through a reconcile (the
    current generation keeps serving).

- **`status` MCP tool** renders a one-line pending hint only when substantial,
  e.g. `pending=reconciling(offline_batch) ~42s search_usable=true`, with an
  `action='scubiee index . --force'` when a full reindex is required.

- **Retired:** the raw per-change `dirty_count` is no longer the agent-facing
  pending signal. It remains in the internal/debug `status()` payload under
  `pending_internal` for diagnostics.

## New durable file

- **`projects/<project_id>/index_state.json`** (schema version 1): index state,
  durable generation (epoch + monotonic counter), indexed git HEAD, matched
  merkle root, any in-flight build record, and the pending summary. A missing,
  corrupt, or old-version file degrades gracefully to a "reconcile from scratch"
  sentinel — never a crash. No migration needed; it is created on first write.

## Configuration (env knobs)

| Knob | Default | Purpose |
|---|---|---|
| `CTX_UNIFIED_STATE` | `1` (on) | Master switch. `0` makes the Reconciler a no-op and disables the index-state idle-stop gate — the pre-existing poll/lane behavior is restored. **Primary rollback.** |
| `CTX_SUBSTANTIAL_SECONDS` | `25` | Wall-clock budget above which pending work is "substantial" and surfaced to the agent. |
| `CTX_SUBSTANTIAL_FRACTION` | `0.4` | Drift covering this fraction of the corpus trips substantial even under the time budget. |
| `CTX_DEFAULT_EMBED_CPS` | `20` | Conservative embed throughput (chunks/sec) used until a real measurement exists. Measured throughput persists to `meta.embed_cps`. |
| `CTX_HOT_DELETE_MASK` | `0` (retired) | Set to `1` to restore the old conditional deletion-defer behavior. Rollback only. |

## Rollback

The feature is reversible without a redeploy:

1. **Full rollback** — set `CTX_UNIFIED_STATE=0`. The Reconciler becomes a no-op,
   the idle-stop index-state gate is disabled, and change handling reverts to the
   pre-existing poll/lane path. `index_state.json` is still written as a harmless
   shadow but is not consulted for decisions.
2. **Delete-behavior-only rollback** — set `CTX_HOT_DELETE_MASK=1` to restore the
   previous deletion-defer heuristic without touching the rest of the model.
3. **Tuning instead of rollback** — raise `CTX_SUBSTANTIAL_SECONDS` to make the
   agent-facing pending signal quieter, or lower it to surface sooner.

A corrupt or stale `index_state.json` is self-healing (sentinel → reconcile), so
deleting the file is also safe.

## Compatibility

- No change to the embedding model, vector store format, or the map/find/focus
  tool surface.
- Backward compatible: all new durable records degrade to "reconcile from scratch"
  when missing or version-mismatched.

## Verification

64 deterministic offline unit tests cover the model (index_state, reconciler,
workload classifier, pending contract, lifecycle idle-gate, delete consistency).
The scenario matrix (A1–A7, B1–B2, C1–C6, D1–D4, E1–E3) is mapped to covering
tests in `docs/scubiee-scenario-test-results.md`. The broader sync + lifecycle
regression is green except one pre-existing environment-only failure
(`_FakeCE.search(lean=)` in `test_open_preservation`), unrelated to this change.
