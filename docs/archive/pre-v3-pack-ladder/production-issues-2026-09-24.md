# Production issues — 24 Sep 2026

Live battery on 0.3.120: 105 checks, 100 passed. The failures below are the ones that remain. Ranking stays composite. The 10k auto-full-index cap stays.

## 1. `POST /v1/sync` blocks the caller

**Cause.** The HTTP handler runs `incremental_sync` on the request thread. That waits up to 90s for capacity, then walks the repo for newcomers. Clients time out at 35–45s. The engine log shows `large_reindex` and a late HTTP 200.

**Fix.** The request path waits at most 2s for capacity. If capacity is not free, return `strategy=deferred` immediately. Do not discover newcomers on this call, and do not extract or embed on the request thread. A dirty merkle returns `strategy=deferred` with the file list. The keeper poll syncs those indexed files.

## 2. Disk poll does nothing while an MCP client is connected

**Cause.** `poll_repo_changes` returns before probing when `CTX_KEEPER_DEFER_WHILE_CLIENTS=1` and any client is registered. Copilot and Cursor stay registered, so a save is invisible unless something calls `/v1/dirty`. The full newcomer walk was the original reason for the skip (multi-second GIL stall).

**Fix.** Keep polling while clients are connected, but probe indexed files only (`discover_newcomers=False`). That check is about 200ms here, not the 7–12s newcomer walk. Interval ticks that embed a large dirty set still defer while clients are up.

## 3. A locate streak defers a one-file edit

**Cause.** Map and pack call `note_locate`. For 60s, `drain_due` defers every dirty path, including a single write. Copilot that keeps locating never lets that edit publish.

**Fix.** Defer only bulk dirty sets (above `bulk_reindex_threshold`) during a locate streak or while clients are connected. A small edit syncs immediately.

## 4. Publish stays held for the same streak

**Cause.** `_publish_or_hold` keeps the new generation in overlay while a locate streak is active, so search keeps the old index.

**Fix.** After a small sync finishes, publish it. Bulk work still waits.

## 5. `k` is checked after the AST warm gate

**Cause.** `pack_context` and `expand_context` return `ast_warming` before `_bound_k`. `k=0` on a cold AST looks like a warm-up failure.

**Fix.** Reject `k < 1` before the warm check. Cold AST with a valid `k` still returns `ast_warming`.

## 6. A second collect looks empty

**Cause.** The first collect stores those ids in `packed_ids`. The next call skips them and returns `empty_bodies` with no reason.

**Fix.** When every candidate was skipped because it was already collected, return `already_packed=true`, the skipped ids, and a hint to pass `ids=` to read them again.

## 7. Map rank and score can disagree

**Cause.** Soft map sorts by role penalty, then score, and still prints the raw score.

**Fix.** Do not change who wins. When a lower score sits above a higher score, set `rank_note=role_adjusted` on the card.

## 8. Legacy heatmap helper floors `k` at 4

**Cause.** `max(4, min(int(k or 16), 48))` in the lean map-reuse helper. Not on the phase tool list, but the same silent floor.

**Fix.** Honor `k >= 1`. `k=0` or missing still means the helper default (16), capped at 48.

## Verified

- Request-style sync on this repo: `strategy=deferred`, 6 files, **436.8ms**, no embed. The earlier inline run embedded 316 chunks in 33.9s; that path is no longer what `/v1/sync` calls.
- Unit: `k=0` on pack and expand returns `k must be >= 1` without touching the AST gate. A second collect with those ids already packed returns `already_packed=true`.
- Unit: a 1-chunk edit is not deferred during a locate streak; a 400-chunk set is. Poll while a client is connected calls `root_probe(discover_newcomers=False)`.
- 12 contract tests passed. The installed bridge is still 0.3.120 until the next local install and a Cursor restart.

## Not changed

- Composite / multi-seed ranking weights.
- The 10k chunk cap.
- Evicting a live IDE client for silence. Those PIDs are real; the poll fix is what unblocks sync.
