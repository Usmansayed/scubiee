# Why the new map performed worse and the old map better: session-level analysis

A trace-by-trace look at the one task where the new map lost (`cache_aware_savings`, multi-module). Pulled from the real cell JSON of the latest arm re-test.

## The two traces, side by side

| | mini_v3 (old map) | newmap (new 3-config) |
|---|---|---|
| total tokens | 318,481 | 546,890 |
| API calls | 9 | 14 |
| locate calls | 1 map | 4 (find, view, view, refs) |
| edits | 4 | 6 |
| oracle | 1.0 | 1.0 |

**mini_v3 sequence:** `map` (4,373c) -> `Read token_meter.py` (whole file, 7,753c) -> 4 Edits.
**newmap sequence:** `find` (3,138c) -> `view` outline (483c) -> `view` [token_meter.py:1-65 + more] (6,940c) -> `refs` [compare_queries, ArmResult, QueryCompare, baseline_grep_read] (1,983c) -> 6 Edits.

## Root cause: the old map WON because it was WORSE at scoping

The arms diverged on the very first locate call, and the reason is counter-intuitive.

**Old map returned a whole-file pointer.** Its top card was:
```
"loc": "packages/pipeline/token_meter.py", "symbol": null, "score": 39.17
```
A module-level hit with **no line range**. The old map has no span for a whole-file match. So the agent did one plain `Read token_meter.py` with no offset/limit - the **entire file** (7,753 chars) - and then had every symbol in context. One map + one whole-file read, and it could edit all four sites. **1 locate call.**

**New map returned a precise span.** Its `find` top result was:
```
confidence: medium
1. packages/pipeline/token_meter.py:193-236  compare_queries  [keyword+semantic]
```
A tight 36-line span for `compare_queries`, plus matched lines for the other symbols. This is find doing its job well - it located the exact relevant code. But this task's correct fix edits **four symbols spread across the file** (`ArmResult`, `QueryCompare`, `compare_queries`, `baseline_grep_read`). A 36-line span shows one of them. So the agent made follow-up calls (`view` outline, `view` the dataclass region, `refs` the symbols) to see the other three before editing. **4 locate calls.**

So the paradox: **the old map's imprecision (dump the whole file) was accidentally optimal for a dense, multi-symbol file**, while the new map's precision (a tight span) forced extra calls to assemble the same whole-file picture. Precision costs calls when the edit is spread across a file.

## Two concrete, fixable reasons - both in `find`

### 1. find withheld the body because it scored MEDIUM, not high
In the real run the agent's first `find` passed only a free-text query, no `keywords`. That scores **medium** -> find does NOT attach the inline body -> the agent must go read it with `view`. Verified:
- `find query="..." keywords=["compare_queries"]`  -> **confidence high**, body attached.
- `find query="..."` (no keywords)                  -> **confidence medium**, no body.

The whole follow-up chain started because the first find was medium. If find had given the body (as it does with a keyword), the agent would have had `compare_queries` inline immediately.

### 2. find scopes to ONE symbol; this edit needs FOUR
Even high-confidence find returns the single top symbol's body. When keywords span several functions (`compare_queries` in one, `ArmResult` in another), no single span covers them, so coverage drops to medium and the agent fans out. find's design assumes a single-symbol edit; the old map's "here's the whole file" happens to serve a multi-symbol edit better.

## Why this is NOT simply "new map is worse"

- On the **single-symbol** task (dirty_files_cap) the new map WON this same re-test: 122k / 1 map call vs old map 147k. There, precision is exactly right - one symbol, one span, one call.
- The old map's 1-call win here is the same behavior that made it **FAIL this task (oracle 0.33)** in an earlier run: editing a dense module from one undirected whole-file read is cheap but error-prone. This run it happened to get all four edits right; it has not always.
- The new map's extra calls bought a correct, complete 4-symbol edit (oracle 1.0) with tiny payload (13.9k result chars total). The cost is calls, and the calls map 1:1 to symbols the edit touches.

## Fixes that would close the gap (not yet applied)

1. **Let find return multiple bodies when the top hits cluster in one file.** If ranks 1-4 are all in `token_meter.py` and together they're a coherent region, return that region (or the several symbols) in the one find response. That turns this 4-call task into 1 - directly, by giving find the "whole relevant file region" behavior that made the old map cheap, but scoped to the hot symbols instead of the literal whole file.
2. **Raise find to high when the top N hits are all in the same file and keyword-covered**, so the body is attached even when a single symbol doesn't cover every keyword.
3. **Rules nudge:** when find's results are several symbols in one file, prefer ONE `view` with all of them batched over separate view+refs calls. (The agent did eventually batch the second view; the outline call before it was the wasted one.)

Fix #1 is the real lever: it attacks the structural reason (span precision vs multi-symbol edit), not just the agent's behavior.

## Honest standing

- The new map is better on single-symbol tasks and correct on multi-symbol ones; it costs more only when an edit spans several symbols in one file, because it scopes tightly where the old map dumped the whole file.
- n=1: old map swings 318k-998k on this task across runs, so the 318-vs-547 gap is not stable. But the mechanism above is structural and reproducible, independent of the token noise.
- Next: implement fix #1 (find returns the clustered multi-symbol region in one call), re-verify gates, re-run - expect the hard-task locate calls to drop from 4 toward 1.

---

# Resolution (follow-up): multi-body `find` fixed it — newmap now wins this task

The fix followed directly from the root cause above: the old map accidentally won by dumping the whole file in one read, so the agent saw every symbol at once. The new `find` was too precise — it returned the top span only, forcing follow-up calls to see the other three edit sites.

So `find` was changed to do deliberately what the old map did accidentally, but scoped: when the top in-scope hits cluster in one file, return **all** of their bodies in a single call (not just the top one). This gives the agent the whole relevant region in one response without dumping unrelated file content.

Fresh re-run of the same task against the updated bridge:

| | mini_v3 (old map) | newmap (multi-body find) |
|---|---|---|
| total tokens | 404,813 | **271,702** |
| API calls | 11 | **7** |
| locate calls | 1 map | 2 (find, view) |
| oracle | 1.0 | 1.0 |

**newmap sequence now:** `find` (returns 3 clustered `token_meter.py` bodies: `compare_queries`, `QueryCompare.tokens_saved`, `QueryCompare.pct_saved`) -> one `view` (imports + `context_engine_arm`) -> 3 Edits.

The two follow-up locate calls (`view` outline + `refs`) that the old trace needed are gone, because the first `find` already carried the symbols the edit touches. Locate calls dropped 4 -> 2, total calls 14 -> 7, tokens 547k -> 272k. The old map's "accidental whole-file win" is now reproduced on purpose, scoped to the clustered region, and newmap is the cheaper arm on both the easy and the hard task. See `scubiee-newmap-fewest-calls-arms.md` for the full table.
