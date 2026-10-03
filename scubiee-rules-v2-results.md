# Rules v2 test + Scubiee map audit

Run: `.ab_workspaces/claude_sdk_harness/20260930T184945Z_retrieval/` (18 cells).
Setup: retrieval challenge (vague query → locate → write `RETRIEVAL_ANSWER.md` → stop),
max 14 turns, map-only Scubiee surface, bare server instructions, `claude-sonnet-5`.
Arms: `guided`, `two_layer`, `two_layer_v2`. Queries: `idle_engine_self_retire`
(discovery, gold `server.py`), `dirty_path_first_char` (focused, gold `freshness.py`).
3 repeats each → n=6 per arm.

## 1. Changes to Scubiee map so far: none

No Scubiee code was changed in this study. `git status` / `git diff HEAD -- packages/`
are clean. The last commit touching map code (`mcp_locate.py`, `context_trace.py`,
`map_result_cache.py`) is `eacdd67` (0.3.132, 2026-09-28), which predates these
experiments. Everything tuned so far is on the agent side (CLAUDE.md rules) and in the
harness (instrumentation, `CTX_MCP_BARE_INSTRUCTIONS` env flag). The map improvements
from the earlier analysis are still proposals.

## 2. Results

| Arm | rule tokens | tokens median | tokens mean | min–max | model calls (mean) | tool calls (median) | recall (mean) | precision (mean) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| guided | 326 | 426,389 | 405,291 | 319,927–461,011 | 12.0 | 13.5 | 0.83 | 0.39 |
| two_layer | 622 | 344,092 | 345,040 | 270,912–433,979 | 10.2 | 12 | 1.00 | 0.61 |
| **two_layer_v2** | **517** | **314,186** | **323,970** | 258,202–426,744 | **9.7** | **10** | **1.00** | **0.65** |

Per query:

| Arm | discovery tokens (mean) | focused tokens (mean) | focused precision |
|---|---:|---:|---:|
| guided | 412,431 | 398,151 | 0.50 |
| two_layer | 338,192 | 351,889 | 0.83 |
| two_layer_v2 | 308,459 | 339,482 | 1.00 |

What this supports:
- **v2 vs guided: −26% median, −20% mean tokens, better accuracy.** All six guided runs
  cost ≥320k; half of v2's runs came in below that. guided also had the only failure: in
  one run it went off with 4 Bash calls, hit the 14-turn cap, and never wrote an answer
  (recall 0). Fairly consistent, though n=6 per arm.
- **v2 vs two_layer: −9% median, −6% mean.** The ranges overlap a lot (v2 max 427k,
  two_layer min 271k), so this is within noise. v2 is at least no worse, with ~100 fewer
  rule tokens and the best precision. Weak evidence.

What the rules did not do:
- **Batching did not measurably increase.** Tool calls per model call were guided 1.22,
  two_layer 1.28, v2 1.26. v2's savings came from doing **less work** (median 10 tool
  calls vs 12–13.5, fewer greps: 1.5 vs 2.5), not from sending more calls in parallel.
  The batch rule can stay, but it isn't the lever it was meant to be.

## 3. New finding: the first map call fails in every Scubiee run

In **18 of 18 cells** the first `map` call returned an error (~990 chars):

```
{"ok":false,"tool":"map","error":"Server disconnected without sending a response.",
 "should_retry":false,"ambiguous_repos":true,
 "candidates":[{"path":"...ws_<arm>_<query>_r1","project_id":"ce_3536...","source":"ide"},
               {"path":"C:\\Users\\usman\\Downloads\\context-engine","project_id":"ce_3536...","source":"ctx_repo"}]}
```

The agent then retries the same query with `project_id` added, and that call succeeds
(~3.8–4.4k chars of cards). So the "always 2 maps" pattern is **a failed call plus a
retry**. It is not the `next` field telling the agent to re-query; that earlier guess was
wrong. The same ~990-char first map appears in every earlier Scubiee run, so the whole
study paid this cost.

Cost: one extra model call per run, re-reading ~21–26k tokens of context. That's roughly
**6–9% of every Scubiee run's tokens**, plus a turn of latency.

Contributing causes seen in the code:
- `"server disconnected"` is not in `_TRANSIENT_ENGINE_MARKERS`
  (`packages/pipeline/client.py`), so the error comes back with `should_retry: false`
  rather than being retried inside Scubiee.
- Repo resolution flags `ambiguous_repos` even though **both candidates have the same
  `project_id`**. That shouldn't count as ambiguous.
- Part of the ambiguity comes from the harness: locate is pointed at the warm parent
  index (`CTX_REPO`) while the agent runs in a snapshot folder. But the disconnect on the
  first call without `project_id` looks like a real bridge/first-request issue, and
  real users would hit it too. I haven't yet separated the disconnect from the ambiguity.

## 4. Map changes, re-ranked with this data (still proposals)

1. **Make the first map call succeed.** Retry internally on a disconnected transport
   (add the marker to `_TRANSIENT_ENGINE_MARKERS` and retry once in the bridge), and
   don't mark repos ambiguous when the candidates share a `project_id`. This is the only
   measured, guaranteed saving, ~6–9% per Scubiee run.
2. **Make `next` match the available tools.** Don't suggest `pack_context` when it isn't
   exposed (it still does). Then the "ignore pack" clause can come out of the rules.
3. **Return a compact confidence signal** so the stop rule has something to check.
4. **List code cards first, then tests/docs as one line each.**

## 5. Rules

Keep `two_layer_v2` (87 + 430 tokens) as the lead candidate: cheapest and most accurate
here. Text is in `scripts/claude_sdk_harness/two_layer.py` (`RULES_V2`,
`INSTRUCTIONS_V2`). Candidate edits for a v3, all small:
- Replace the "ignore pack suggestions" line once map change #2 lands.
- Keep the batch clause short. It didn't change behavior, so it shouldn't grow.
- Add "if a Scubiee call errors, retry once with `project_id`". The agents already do
  this on their own, so it's optional, and it's moot once map change #1 lands.

## 6. Limits

- n=6 per arm, 2 queries, both single-file gold. Recall is saturated except for guided's
  turn-cap failure. Harder multi-file queries are still untested.
- Tool-per-call parallelism is derived from deduplicated usage snapshots (validated: the
  collapsed `cache_read` sums match the run totals exactly).
- The harness now saves tool inputs and map response bodies per cell, which is how the
  first-call failure was found.


---

## 7. v2 vs without (run `20260930T191159Z_retrieval`, 12 cells, n=3 per arm per query)

| Arm | Query | tokens (mean) | range | model calls | tools/call | recall | precision |
|---|---|---:|---:|---:|---:|---:|---:|
| without | discovery (idle_retire) | 348,567 | 346,643–352,240 | 9.7 | 1.71 | 1.0 | 0.23 |
| **two_layer_v2** | discovery | **276,212** | 260,578–297,611 | 8.3 | 1.37 | 1.0 | 0.29 |
| **without** | focused (dirty_path) | **223,719** | 177,504–281,435 | 6.0 | 1.62 | 1.0 | 0.58 |
| two_layer_v2 | focused | 435,328 | 388,484–462,382 | 13.0 | 1.31 | 1.0 | 0.67 |
| without | both | 286,143 | | 7.8 | 1.66 | 1.0 | 0.41 |
| two_layer_v2 | both | 355,770 | | 10.7 | 1.34 | 1.0 | 0.48 |

- **Discovery: v2 wins by 21%, consistently.** Every v2 run (max 298k) cost less than
  every without run (min 347k). Native search needed 9–11 greps to find `_retire_self`.
- **Focused: v2 costs about 2× as much, also consistently.** For this literal-sounding
  question ("dirty files", "freshness"), grep found `freshness.py` on the first or second
  call.
- Recall was 1.0 everywhere. Precision was slightly better with v2.
- The native agent batches more (1.66 tools per model call vs 1.34).

### Why v2 lost the focused query: a harness confound, not only map

The v2 focused runs read files that **do not exist in the agent's workspace**:

```
Read[test_freshness.py@120+45] = 203   "File does not exist."
Glob[**/test_freshness.py]     = 14    "No files found"
Bash[find . -iname "test_freshness.py"] ...
Bash[ls -la .; find packages -maxdepth ...] = 15,634 chars
Read[docs/freshness.md@1+41]   = 203   "File does not exist."
```

Cause: the workspace snapshot copies only `packages/`, but map searches the index of the
**whole parent repo** (`CTX_REPO`). For this query the most specific card is
`tests/test_freshness.py::test_git_dirty_keeps_the_first_filename_intact`. That file
exists in the real repo, but not in the snapshot. The agent follows the card, gets "File
does not exist", then burns turns on Glob/Bash/ls trying to find it. The native arm
can't see tests/ or docs/ at all, so it never goes down that path.

What this means:
- The focused loss is **mostly caused by the harness**. In real use the index and the
  working tree are the same repo, and the test card would just open.
- **The same mismatch was present in every earlier run** (retrieval runs copied
  `packages/`; the coding-task runs copied only `packages/pipeline`). All earlier
  Scubiee arms were disadvantaged to some degree. It's also part of the
  `ambiguous_repos` first-map failure (two candidate roots).
- Even so, on this kind of literal-vocabulary question grep is simply cheap. The rules
  should keep sending "known literal / strongly keyword-like" questions to grep.

### To fix before trusting Scubiee-vs-native totals

1. Make the snapshot match the index: copy the full repo (minus heavy dirs) so every
   path map can return exists. Or run locate against an index of the snapshot itself.
2. Re-run v2 vs without on both queries (12 cells) plus the harder multi-file queries.
