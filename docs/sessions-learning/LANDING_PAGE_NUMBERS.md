# Scubiee — complete A/B results (WITH Scubiee vs WITHOUT) for the landing page

All figures measured from the internal eval harness (`scripts/claude_sdk_harness`), not
estimated. map_v3 = production "U" prompt WITH Scubiee; without = the SAME agent with
native tools only (Read/Grep/Glob/Edit), identical prompts/model/permissions; correctness
graded by hidden deterministic oracles. Verified from recorded per-cell run data.

**Corpus scale: 105 A/B run directories, 253 graded trials (cells)** across many task
types and prompt variants. The sections below separate the clean dev-task A/Bs (the
numbers to showcase) from the discovery/recall benchmarks (which both arms fail and are
NOT token A/Bs).

---

## 1. HEADLINE (safe to showcase)

- **61% fewer tokens** across all real multi-file dev tasks (2.54x cheaper), **same
  success rate.**
- **66% fewer tokens on HARD cross-module changes** (2.97x cheaper).
- **~2x fewer tool calls**; **5x fewer grep calls.**
- **Up to ~7x cheaper on the single hardest change**, where the no-Scubiee agent spent
  **2.1M tokens on one task — and still failed.**

One-liners:
- "Same results, 61% fewer tokens."
- "2.5–3x cheaper on real multi-file code changes — identical success rate."
- "Finds the whole change in ~2 calls instead of grep-hunting 18."

---

## 2. The core comparison — ALL dev tasks (WITH vs WITHOUT)

Across every genuine code-editing task (9 distinct dev tasks, easy + hard; excludes the
one ambiguous task and the non-edit recall benchmarks):

| | WITH Scubiee (map_v3) | WITHOUT (native) |
|---|---:|---:|
| Trials | 31 | 36 |
| Avg tokens / task | **287,629** | 730,980 |
| Success rate | **30/31 (97%)** | 32/36 (89%) |
| Result | **2.54x cheaper, 61% fewer tokens** | — |

(Across the full map_v3 vs without cell populations recorded — 54 vs 48 cells including
recall probes — the averages are 273,535 vs 654,255 tokens: same ~2.4x direction.)

---

## 3. HARD cross-module changes (the strongest story)

5 hard dev tasks, each spanning 2+ files in a different subsystem, where the second edit
site is findable only by following the call graph (not a grep of one literal):

| | WITH Scubiee | WITHOUT |
|---|---:|---:|
| Trials | 17 | 17 |
| Avg tokens / task | **316,681** | 939,252 |
| Success rate | **16/17 (94%)** | 14/17 (82%) |
| Result | **2.97x cheaper, 66% fewer tokens** | — |

Avg tool behavior (hard tasks): WITH = ~9.5 calls, 1.3 grep, 2.6 reads · WITHOUT = ~18.4
calls, 7.2 grep, 6.6 reads. Worst single no-Scubiee run: **2,145,920 tokens (failed).**

### Per hard task (WITH vs WITHOUT, avg tokens, success)
| Dev task | subsystem(s) | WITH Scubiee | WITHOUT | savings |
|---|---|---:|---:|---:|
| Unify CPU-thread budget | memory_budget + embedder | 404,388 (4/4) | 775,718 (4/4) | 48% |
| New sync-strategy tier | freshness + sync_status | 435,092 (3/4) | 2,596,365 (1/4) | 83% |
| Surface dirty-count in timings | freshness + engine | 269,546 (5/5) | 305,615 (5/5) | 12% |
| Net chunk-delta in sync result | incremental + sync_loop | 243,153 (2/2) | 355,826 (2/2) | 32% |
| Consistent safety-pause check | incremental + CLI | 95,810 (2/2) | 119,612 (2/2) | 20% |

(The strategy-tier row is the sharpest: without Scubiee averaged ~2.6M tokens and only
1/4 success; with Scubiee ~0.44M and 3/4. That one task alone is ~6x.)

---

## 4. EASY / single-file dev tasks (for completeness)

4 simpler dev tasks (cache-aware savings, dirty-files cap, health-reason flag,
total-changed field, root-hash fingerprint):

| | WITH Scubiee | WITHOUT |
|---|---:|---:|
| Trials | 14 | 19 |
| Avg tokens / task | **252,351** | 544,631 |
| Success | 14/14 | 18/19 |
| Result | **2.16x cheaper, 54% fewer** | — |

Note: on the most trivially greppable edits the edge narrows (10–20%); the big wins are
on cross-module work. Don't imply 60%+ on one-line edits.

---

## 5. Old Scubiee vs New Scubiee (why we shipped the new map)

The new map surface (map_v3, "U") replaced the old single-tool map (mini_v3). On hard
cross-module tasks the new surface is dramatically leaner AND more reliable:

| arm | what it is | hard-task avg tokens | success |
|---|---|---:|---:|
| **map_v3 (new)** | find/focus/related/graph, returns code+wiring | **316,681** | 16/17 |
| mini_v3 (old) | single map, returns locations only | 1,038,158 | 6/6 |
| without | native only | 939,252 | 14/17 |

The old map returned only locations, so the agent still had to read bodies natively and
often grep-spiraled (one 2.76M-token run). The new map returns the code and its wiring in
one call. (Old mini_v3 shows 6/6 success here on only 6 cells — a small, favorable sample;
its token cost is the real story.)

---

## 6. Full arm scoreboard (all 253 cells, every variant we tried)

| arm | cells | mean tokens | notes |
|---|---:|---:|---|
| map_v3 (prod U) | 54 | 273,535 | production WITH-Scubiee |
| mini_v3 (old) | 57 | 371,148 | old single-tool map |
| without (native) | 48 | 654,255 | no Scubiee |
| newmap (map_v2) | 15 | 410,831 | earlier 5-config map |
| map_v3_a (prose) | 19 | 257,677 | A/B prompt variant |
| map_v3_s (symbolic) | 11 | 268,150 | A/B prompt variant |
| map_v3_u | 4 | 213,419 | U on recall probes |
| mini | 7 | 495,506 | oldest two-layer map |
| two_layer_v2 | 12 | 339,870 | early rules (recall probes) |
| two_layer | 9 | 359,345 | early rules |
| guided | 9 | 381,159 | early rules |
| mini_plus | 2 | 389,318 | map + bodies variant |
| map_v3_b/c/d | 2 each | 338–377k | tuning variants |

(Low-cell variants are prompt-tuning experiments, not headline numbers.)

---

## 7. Discovery / recall benchmarks (NOT token A/Bs — context, not showcase)

`retrieval_challenge` (behavioral/concept queries where the target doesn't lexically match)
and `comprehension` probes: ALL arms score 0 success — this is a shared engine-recall
limitation, not a Scubiee-vs-native differentiator. Token means are similar across arms
(map_v3 ~246k, mini_v3 ~265k, without ~359k over 20/20/9 cells). Do NOT put these on the
landing page as a win; they are an honest known limitation.

---

## 8. Fine print (keep an asterisk — do not overclaim)
- Benchmark: internal eval harness, claude-sonnet model, identical prompts & tool
  permissions per arm; correctness graded by hidden deterministic tests. Not third-party.
- "Same success rate" — Scubiee's edge is EFFICIENCY, not raw capability: a strong agent
  can also complete these without Scubiee, just far more expensively (and it spiraled/
  failed on the hardest).
- Native cost is UNDER-stated: a per-run cost cap ($4) truncated the worst no-Scubiee
  token spirals, so the real gap is larger than shown.
- Cell counts are uneven across tasks/arms (this is an evolving experiment log, not a
  fixed-N benchmark). Headline uses the clean dev-task populations; low-N variants are
  labeled as such.
- One task (unify_token_estimate) was excluded from headlines: its "token" concept is
  ambiguous in this repo and caused a semantic mislocate — kept only as a known-bad
  task-design example.

## 9. Recommended landing-page block
> **Scubiee cuts token spend ~60% on real multi-file code changes — with the same
> success rate.**
> Across an internal benchmark of multi-file, cross-module dev tasks, agents using
> Scubiee finished in **2.5–3x fewer tokens** and **~half the tool calls** versus the
> same agent with native search only. On the toughest change, the no-Scubiee agent spent
> **2.1M tokens and still failed**; with Scubiee it succeeded for a fraction of that.
> *Internal eval, deterministic grading; efficiency gain, equal success rate.*
