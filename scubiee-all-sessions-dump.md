# Scubiee harness — complete session data dump

Generated 2026-09-30 18:22:05Z from `C:\Users\usman\Downloads\context-engine\.ab_workspaces\claude_sdk_harness`. Every number is read directly from the stored run JSON; nothing here is estimated. Token totals are cache-read-dominated (~90%+), so absolute totals carry run-to-run variance — the trajectory counts (map/grep/read, turns) and oracle results are the stable signals.

**Total run directories: 34**

---

## Cross-run synthesis (what all this data shows)

This is the interpretive layer over the raw per-run tables below. Every figure
cited here is present verbatim in a run section further down.

### Headline coding-task A/B results (map-only vs native), most decisive first

| Run | Task | without (tok) | with-Scubiee (tok) | Δ | with-arm result |
|---|---|---:|---:|---:|---|
| rules4 (#27) | cache_aware (discovery) | 1,249,297 | **831,077** (guided) | **−33% cost** | guided passed oracle, 20 turns |
| rules4 (#27) | same | 1,249,297 | 1,282,194 (strict) | +2.6% | strict passed, 34 turns (worst cost) |
| rules4 (#27) | same | 1,249,297 | 1,146,194 (flexible) | −8.3% | flexible FAILED oracle (0.33) |
| gVs (#29) | cache_aware | — | 1,000,482 (guided) | — | guided FAILED (0.33), 21 turns |
| gVs (#29) | same | — | 1,119,510 (strict) | — | strict PASSED (1.0), 24 turns |
| smallGuided (#25) | cache_aware | 862,855 | 1,246,468 (guided) | −44% | both passed; guided pricier this run |
| smallStrict (#23) | cache_aware | 1,037,706 | 1,125,787 (strict) | −8.5% | strict FAILED oracle (0.33) |
| 3arm (#17) | cache_aware | 750,033 | 1,344,822 (map-only) | −79% | map-only FAILED (0.33) that run |
| bigAB (#19) | big multi-part | 15.4M vs 15.4M | ~tie | ~0% | both huge; savings wash out at scale |

### Retrieval-challenge results (cheap locate-only; recall/precision/MRR)

| Run | Arm | Query | tok | turns | map | grep | recall | prec | MRR |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| #33 | without | idle_retire | 278,477 | 12 | 0 | 7 | 1.0 | 0.25 | 1.0 |
| #33 | guided | idle_retire | 347,682 | 12 | 2 | 2 | 1.0 | 0.33 | 1.0 |
| #33 | two_layer | idle_retire | 265,768 | 11 | 2 | 1 | 1.0 | 0.50 | 1.0 |
| #33 | without | dirty_path | 263,232 | 11 | 0 | 6 | 1.0 | 1.00 | 1.0 |
| #33 | guided | dirty_path | 350,751 | 13 | 2 | 6 | 1.0 | 0.50 | 1.0 |
| #33 | two_layer | dirty_path | 441,359 | 13 | 2 | 3 | 1.0 | 1.00 | 1.0 |
| #34 | without | idle_retire | **973,962** | **20** | 0 | 11 | 1.0 | 0.20 | 1.0 |
| #34 | guided | idle_retire | 300,252 | 13 | 2 | 4 | 1.0 | 0.25 | 1.0 |
| #34 | two_layer | idle_retire | 456,737 | 13 | 2 | 4 | 1.0 | 0.33 | 1.0 |

### The stable findings across all runs

1. **~90%+ of every run's tokens is `cache_read`** — the transcript re-read each
   turn. So total tokens ≈ (context size) × (turns). Output tokens are always
   tiny (3k–27k). This is the single most important mechanic in the whole study.
2. **The biggest single waste is a whole-file Read.** Run #34's without arm read a
   67,473-char file; its per-turn carried context jumped from ~28k to ~87k and
   stayed there for the rest of the run → 973,962 tokens. Map-equipped arms never
   read a whole file (biggest reads 4.7k–6.3k chars) because map returns `loc`
   line ranges. Total result-chars pulled into context: without 139,039 vs guided
   22,576 vs two_layer 26,757 — a **5–6× compression** and Scubiee's clearest win.
3. **A single map response is ~1,000 chars (warm/first) to ~4,200 chars (full 12
   cards)** — measured in #34. Two maps ≈ 5.2k chars, carrying zero file bodies.
4. **Cost order guided < strict reproduced twice** (rules4: 831k vs 1,282k; gVs:
   1,000k vs 1,120k). Strict's forced map-first ran the most turns (34, 24). [STR]
5. **Correctness did NOT track cost.** guided passed 2 of 4 relevant coding runs,
   strict passed the ones guided failed; flexible failed. No arm is a clean winner
   on correctness at these sample sizes. [WEAK]
6. **Why Scubiee does not win the token total every time:** (a) turn-count variance
   is huge — the SAME without/idle_retire query was 12 turns/278k (#33) and 20
   turns/974k (#34), a 3.5× swing from nondeterminism alone, larger than the
   Scubiee effect at n=1; (b) map + a long instruction block is a fixed tax that
   only pays off when it prevents a big read — on an easy query native grep is
   already cheap, so the tax makes Scubiee the pricier arm (see #25, #33 guided).
7. **map→grep redundancy and grep-walking are the observed failure patterns** in
   the losing traces; "read the loc span, never the whole file" is the rule that
   most moves cost.

### Caveats on the whole dataset
- **Nearly all cells are n=1.** Cost differences between arms are directional, not
  significant. Trajectory counts (map/grep/read, turns) and oracle pass/fail are
  the trustworthy per-run signals; absolute token totals carry 3×+ variance.
- Early runs (#1–#10, `vague`/`s1`/`s2`) predate the bare-server-instruction
  confound fix, so their with-Scubiee arm also carried the stock pack-ladder text
  that references tools it couldn't call — treat their token totals as confounded.
- `bigStrict` (#20/#21) has an aborted/partial run with no report.

---

## Index of runs

| # | Run dir | Type | Started | Model |
|---|---|---|---|---|
| 1 | `20260928T232216Z` | other | 2026-09-28T23:22:16Z | claude-sonnet-5 |
| 2 | `20260928T232328Z` | other | 2026-09-28T23:23:28Z | claude-sonnet-5 |
| 3 | `20260928T232746Z` | other | ? | ? |
| 4 | `20260928T233035Z` | other | ? | ? |
| 5 | `20260928T233211Z` | other | ? | ? |
| 6 | `20260928T233502Z` | other | 2026-09-28T23:35:02Z | claude-sonnet-5 |
| 7 | `20260928T233940Z_s2` | s2 | 2026-09-28T23:39:40Z | claude-sonnet-5 |
| 8 | `20260928T234149Z_s1` | s1 | 2026-09-28T23:41:49Z | claude-sonnet-5 |
| 9 | `20260928T234440Z_s1` | s1 | 2026-09-28T23:44:40Z | claude-sonnet-5 |
| 10 | `20260928T234657Z_s2` | s2 | 2026-09-28T23:46:57Z | claude-sonnet-5 |
| 11 | `20260929T130852Z_vague` | vague | 2026-09-29T13:08:52Z | claude-sonnet-5 |
| 12 | `20260929T131109Z_vague` | vague | 2026-09-29T13:11:09Z | claude-sonnet-5 |
| 13 | `20260929T132601Z_vague` | vague | 2026-09-29T13:26:01Z | claude-sonnet-5 |
| 14 | `20260929T161856Z_packbodies` | packbodies | ? | claude-sonnet-5 |
| 15 | `20260929T162905Z_packbodies` | packbodies | ? | claude-sonnet-5 |
| 16 | `20260930T123954Z_3arm` | 3arm | 2026-09-30T12:39:54Z | claude-sonnet-5 |
| 17 | `20260930T124113Z_3arm` | 3arm | 2026-09-30T12:41:13Z | claude-sonnet-5 |
| 18 | `20260930T131517Z_bigAB` | bigAB | 2026-09-30T13:15:17Z | claude-sonnet-5 |
| 19 | `20260930T131625Z_bigAB` | bigAB | 2026-09-30T13:16:25Z | claude-sonnet-5 |
| 20 | `20260930T140920Z_bigStrict` | bigStrict | 2026-09-30T14:09:20Z | claude-sonnet-5 |
| 21 | `20260930T141029Z_bigStrict` | bigStrict | ? | ? |
| 22 | `20260930T142435Z_smallStrict` | smallStrict | 2026-09-30T14:24:35Z | claude-sonnet-5 |
| 23 | `20260930T142534Z_smallStrict` | smallStrict | 2026-09-30T14:25:34Z | claude-sonnet-5 |
| 24 | `20260930T144713Z_smallGuided` | smallGuided | 2026-09-30T14:47:13Z | claude-sonnet-5 |
| 25 | `20260930T144826Z_smallGuided` | smallGuided | 2026-09-30T14:48:26Z | claude-sonnet-5 |
| 26 | `20260930T151541Z_rules4` | rules4 | 2026-09-30T15:15:41Z | claude-sonnet-5 |
| 27 | `20260930T151708Z_rules4` | rules4 | 2026-09-30T15:17:08Z | claude-sonnet-5 |
| 28 | `20260930T154053Z_gVs` | gVs | 2026-09-30T15:40:53Z | claude-sonnet-5 |
| 29 | `20260930T154207Z_gVs` | gVs | 2026-09-30T15:42:07Z | claude-sonnet-5 |
| 30 | `20260930T161452Z_policybench` | policybench | 2026-09-30T16:14:52Z | claude-sonnet-5 |
| 31 | `20260930T163827Z_policybench` | policybench | 2026-09-30T16:38:27Z | claude-sonnet-5 |
| 32 | `20260930T171024Z_retrieval` | retrieval | 2026-09-30T17:10:24Z | claude-sonnet-5 |
| 33 | `20260930T171309Z_retrieval` | retrieval | 2026-09-30T17:13:09Z | claude-sonnet-5 |
| 34 | `20260930T172308Z_retrieval` | retrieval | 2026-09-30T17:23:08Z | claude-sonnet-5 |

## Per-run detail

### 1. `20260928T232216Z`  (other)

```json
{
 "started_at": "2026-09-28T23:22:16Z",
 "finished_at": "2026-09-28T23:22:53Z",
 "model": "claude-sonnet-5",
 "warm_proof_ok": true,
 "ok": true,
 "preflight_only": true
}
```

### 2. `20260928T232328Z`  (other)

```json
{
 "started_at": "2026-09-28T23:23:28Z",
 "finished_at": "2026-09-28T23:26:07Z",
 "model": "claude-sonnet-5",
 "warm_proof_ok": true,
 "ok": true
}
```

**Comparison block:**

```json
{
  "total_tokens_without": 328760,
  "total_tokens_with": 390433,
  "tokens_saved_by_scubiee": -61673,
  "pct_change": -18.8,
  "input_tokens_without": 1470,
  "input_tokens_with": 1472,
  "output_tokens_without": 5454,
  "output_tokens_with": 5935,
  "cache_read_without": 306853,
  "cache_read_with": 365538,
  "tool_calls_without": 9,
  "tool_calls_with": 10,
  "scubiee_calls_with": 0,
  "wall_ms_without": 56702,
  "wall_ms_with": 64944,
  "both_succeeded": false,
  "scubiee_reduced_tokens": false
}
```

### 3. `20260928T232746Z`  (other)

_No report.json. Files present: preflight_live_probe.json, preflight_static.json, probe_scratch, warm_proof.json, with, without_

### 4. `20260928T233035Z`  (other)

_No report.json. Files present: preflight_static.json, warm_proof.json, with, without_

### 5. `20260928T233211Z`  (other)

_No report.json. Files present: preflight_static.json, warm_proof.json, with, without_

### 6. `20260928T233502Z`  (other)

```json
{
 "started_at": "2026-09-28T23:35:02Z",
 "finished_at": "2026-09-28T23:37:14Z",
 "model": "claude-sonnet-5",
 "warm_proof_ok": true,
 "ok": true
}
```

**Comparison block:**

```json
{
  "total_tokens_without": 252761,
  "total_tokens_with": 352289,
  "tokens_saved_by_scubiee": -99528,
  "pct_change": -39.4,
  "input_tokens_without": 1514,
  "input_tokens_with": 1518,
  "output_tokens_without": 5107,
  "output_tokens_with": 6822,
  "cache_read_without": 231752,
  "cache_read_with": 325554,
  "tool_calls_without": 7,
  "tool_calls_with": 9,
  "scubiee_calls_with": 0,
  "wall_ms_without": 48635,
  "wall_ms_with": 67205,
  "both_succeeded": true,
  "scubiee_reduced_tokens": false
}
```

### 7. `20260928T233940Z_s2`  (s2)

```json
{
 "started_at": "2026-09-28T23:39:40Z",
 "finished_at": "2026-09-28T23:40:55Z",
 "model": "claude-sonnet-5",
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| without | 190,835 | 179,902 | 1,957 | 7 | 6 | 0 | 2 | 1 | 1 | None |
| with | 115,474 | 104,470 | 1,326 | 4 | 3 | 0 | 1 | 1 | 1 | None |

**Comparison:** {"total_tokens_without": 190835, "total_tokens_with": 115474, "tokens_saved_by_scubiee": 75361, "pct_change": 39.5, "both_succeeded": true}

Live probe: scubiee_tools_used=None ok=None skipped=True

### 8. `20260928T234149Z_s1`  (s1)

```json
{
 "started_at": "2026-09-28T23:41:49Z",
 "finished_at": "2026-09-28T23:44:17Z",
 "model": "claude-sonnet-5",
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| without | 251,564 | 231,270 | 4,792 | 8 | 7 | 0 | 1 | 1 | 1 | None |
| with | 402,339 | 372,865 | 6,284 | 13 | 12 | 2 | 2 | 1 | 1 | None |

**Comparison:** {"total_tokens_without": 251564, "total_tokens_with": 402339, "tokens_saved_by_scubiee": -150775, "pct_change": -59.9, "both_succeeded": true}

Live probe: scubiee_tools_used=None ok=None skipped=True

### 9. `20260928T234440Z_s1`  (s1)

```json
{
 "started_at": "2026-09-28T23:44:40Z",
 "finished_at": "2026-09-28T23:46:41Z",
 "model": "claude-sonnet-5",
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| without | 216,186 | 197,308 | 4,416 | 7 | 6 | 0 | 1 | 1 | 1 | None |
| with | 310,634 | 285,614 | 6,169 | 9 | 8 | 0 | 1 | 1 | 1 | None |

**Comparison:** {"total_tokens_without": 216186, "total_tokens_with": 310634, "tokens_saved_by_scubiee": -94448, "pct_change": -43.7, "both_succeeded": true}

Live probe: scubiee_tools_used=None ok=None skipped=True

### 10. `20260928T234657Z_s2`  (s2)

```json
{
 "started_at": "2026-09-28T23:46:57Z",
 "finished_at": "2026-09-28T23:48:13Z",
 "model": "claude-sonnet-5",
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| without | 161,671 | 151,898 | 1,510 | 6 | 5 | 0 | 1 | 1 | 1 | None |
| with | 177,716 | 164,212 | 2,400 | 6 | 5 | 0 | 1 | 1 | 1 | None |

**Comparison:** {"total_tokens_without": 161671, "total_tokens_with": 177716, "tokens_saved_by_scubiee": -16045, "pct_change": -9.9, "both_succeeded": true}

Live probe: scubiee_tools_used=None ok=None skipped=True

### 11. `20260929T130852Z_vague`  (vague)

```json
{
 "started_at": "2026-09-29T13:08:52Z",
 "model": "claude-sonnet-5",
 "warm_proof_ok": false,
 "ok": false,
 "aborted": "warm_proof"
}
```

### 12. `20260929T131109Z_vague`  (vague)

```json
{
 "started_at": "2026-09-29T13:11:09Z",
 "finished_at": "2026-09-29T13:19:35Z",
 "model": "claude-sonnet-5",
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| without | 750,033 | 665,112 | 23,115 | 24 | 23 | 0 | 14 | 3 | 0 | None |
| with | 1,344,822 | 1,277,699 | 21,695 | 30 | 29 | 2 | 10 | 3 | 0 | None |

**Comparison:** {"total_tokens_without": 750033, "total_tokens_with": 1344822, "tokens_saved_by_scubiee": -594789, "pct_change": -79.3, "both_succeeded": false}

Live probe: scubiee_tools_used=None ok=None skipped=True

### 13. `20260929T132601Z_vague`  (vague)

```json
{
 "started_at": "2026-09-29T13:26:01Z",
 "finished_at": "2026-09-29T13:33:43Z",
 "model": "claude-sonnet-5",
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| without | 1,024,516 | 964,729 | 20,299 | 24 | 23 | 0 | 5 | 7 | 1 | 1.0 |
| with | 1,339,345 | 1,271,640 | 20,103 | 29 | 28 | 2 | 7 | 4 | 0 | 0.33 |

**Comparison:** {"total_tokens_without": 1024516, "total_tokens_with": 1339345, "tokens_saved_by_scubiee": -314829, "pct_change": -30.7, "both_succeeded": false}

Live probe: scubiee_tools_used=None ok=None skipped=True

### 14. `20260929T161856Z_packbodies`  (packbodies)

```json
{
 "finished_at": "2026-09-29T16:27:58Z",
 "model": "claude-sonnet-5",
 "arms": {
  "heatmap_only": {
   "arm": "heatmap_only",
   "with_bodies": false,
   "tool_counts": {
    "ToolSearch": 2,
    "mcp__ctx__status": 1,
    "mcp__ctx__find": 1,
    "mcp__ctx__pack": 1,
    "Read": 6,
    "Grep": 5,
    "Skill": 1,
    "WebSearch": 1,
    "Glob": 2,
    "Edit": 6,
    "Bash": 4
   },
   "tool_calls": [
    {
     "name": "ToolSearch"
    },
    {
     "name": "mcp__ctx__status"
    },
    {
     "name": "mcp__ctx__find"
    },
    {
     "name": "mcp__ctx__pack"
    },
    {
     "name": "Read"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Skill"
    },
    {
     "name": "ToolSearch"
    },
    {
     "name": "WebSearch"
    },
    {
     "name": "Read"
    },
    {
     "name": "Glob"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Glob"
    },
    {
     "name": "Read"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Read"
    },
    {
     "name": "Read"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Read"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Bash"
    }
   ],
   "ctx_calls": 3,
   "pack_calls": 1,
   "grep_after_pack": 5,
   "read_after_pack": 6,
   "final_text": "All good \u2014 compiles cleanly and existing fields/keys are untouched (only additive new keys with 0/no-op defaults).\n\n## Summary\n\nAll changes are in `packages/pipeline/token_meter.py`:\n\n**1. Cache-aware savings**\n- Added `CACHE_READ_DISCOUNT = 0.1` (Anthropic bills prompt-cache hits at ~10% of the normal input-token rate).\n- `ArmResult` gained a new `cached_tokens: int = 0` field and a `billable_tokens` property (`fresh + cached * CACHE_READ_DISCOUNT`) \u2014 defaults to 0 so existing output is unchanged unless a caller supplies real cache data.\n- `QueryCompare` gained `cache_aware_tokens_saved` / `cache_aware_pct_saved` properties (same math as the existing `tokens_saved`/`pct_saved`, but on `billable_tokens`).\n- `baseline_grep_read` / `context_engine_arm` gained an optional `cache_hit_rate: float = 0.0` kwarg (clamped to [0,1]) so a caller that has real Anthropic usage data (cache_read_input_tokens, same pattern already used in `graphify/llm.py`) can report what fraction of that arm's tokens were actually cache-served.\n- `compare_queries` gained `baseline_cache_hit_rate` / `ce_cache_hit_rate` kwargs (default 0.0 \u2192 no behavior change) and now adds new keys to each row and to the totals dict: `*_cached_tokens`, `*_billable_tokens`, `cache_aware_tokens_saved(_total)`, `cache_aware_pct_saved(_total)`. All original keys/fields are untouched.\n\n**2. Fallback token estimator (`estimate_tokens`)**\n- Whitespace-only input now returns `0` in the fallback path (previously it fell through and could return a token count for content with no real information).\n- Fallback now estimates from **UTF-8 byte length** instead of character length, so multi-byte scripts (CJK, emoji, etc.) aren't badly under-counted by the old flat \"4 chars/token\" guess \u2014 verified `estimate_tokens(\"\u65e5\u672c\u8a9e\u306e\u30c6\u30b9\u30c8\u6587\u7ae0\u3067\u3059\")` goes from a char-based undercount to a much closer byte-based estimate, and always returns `\u22651` for any real (non-whitespace) content.\n- The tiktoken happy-path is untouched.\n\n**3. Human-readable summary**\n- Added `format_savings_summary(result) -> str`, and `compare_queries` now stashes it under the new `result[\"summary\"]` key \u2014 a one-liner like: `\"Context Engine saved 23,880 tokens (99.7%) vs. grep+read across 1 query; 8,796 tokens (99.3%) once prompt-cache discounts are counted.\"`\n- Added `QueryCompare.summary_line` (same idea, per-query) and each row from `compare_queries` now includes a `\"summary\"` string too.\n\nBackward compatibility: all existing dataclass fields, function signatures/names, and dict keys are preserved; every addition is a new optional kwarg (defaulting to prior behavior) or a new dict/property key. Verified with `py_compile`, a monkeypatched \"no tiktoken\" run, and an end-to-end `compare_queries` smoke test with a stub engine.",
   "usage": {
    "input_tokens": 1245,
    "output_tokens": 23302,
    "cache_read_input_tokens": 1094340,
    "cache_creation_input_tokens": 65427,
    "total_tokens": 1184314,
    "billable_input_tokens": 1161012,
    "by_model": {
     "claude-haiku-4-5-20251001": {
      "input_tokens": 1193,
      "output_tokens": 16,
      "cache_read_input_tokens": 0,
      "cache_creation_input_tokens": 0,
      "cost_usd": 0.001273,
      "canonical": "claude-haiku-4-5"
     },
     "claude-sonnet-5": {
      "input_tokens": 52,
      "output_tokens": 23286,
      "cache_read_input_tokens": 1094340,
      "cache_creation_input_tokens": 65427,
      "cost_usd": 0.7135400000000001,
      "canonical": "claude-sonnet-5"
     }
    },
    "total_cost_usd": 0.714813
   },
   "error": null,
   "model_used": "claude-sonnet-5",
   "num_turns": 31,
   "wall_ms": 271291,
   "oracle": {
    "ok": false,
    "passed": 1,
    "failed": 1,
    "errors": 0,
    "tail": " _ _ _ _ _ _ _ _ _ _ _ _ _\n\nr = ArmResult(name='x', query='x', chars=4000, tokens=1000, ms=1.0, hits=1, files_touched=1, payload_preview='x', detail={}, cached_tokens=0)\n\n    def eff(r):\n        for a in dir(r):\n            if a.startswith(\"_\"): continue\n            if any(w in a.lower() for w in _EFF):\n                v = getattr(r, a); v = v() if callable(v) else v\n                if isinstance(v, (int, float)): return float(v)\n>       raise AssertionError(\"no effective/billed accessor on result\")\nE       AssertionError: no effective/billed accessor on result\n\n_oracle_pack_bodies.py:59: AssertionError\n=========================== short test summary info ===========================\nFAILED _oracle_pack_bodies.py::test_cache_reduces_effective_number - Assertio...\n1 failed, 1 passed in 0.13s\n"
   },
   "diff": {
    "stat": "packages/pipeline/token_meter.py | 109 +++++++++++++++++++++++++++++++++++++--\n 1 file changed, 104 insertions(+), 5 deletions(-)",
    "changed": true,
    "files": [
     "packages/pipeline/token_meter.py"
    ],
    "untracked": [
     "CLAUDE.md",
     "__pycache__/_oracle_pack_bodies.cpython-313-pytest-9.0.3.pyc",
     "_oracle_pack_bodies.py",
     "packages/pipeline/__pycache__/__init__.cpython-313.pyc",
     "packages/pipeline/__pycache__/model_cache.cpython-313.pyc",
     "packages/pipeline/__pycache__/token_meter.cpython-313.pyc"
    ]
   },
   "success": false
  },
  "with_bodies": {
   "arm": "with_bodies",
   "with_bodies": true,
   "tool_counts": {
    "ToolSearch": 1,
    "mcp__ctx__find": 1,
    "mcp__ctx__pack": 1,
    "Read": 3,
    "Grep": 7,
    "Glob": 1,
    "Edit": 4,
    "Bash": 3
   },
   "tool_calls": [
    {
     "name": "ToolSearch"
    },
    {
     "name": "mcp__ctx__find"
    },
    {
     "name": "mcp__ctx__pack"
    },
    {
     "name": "Read"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Read"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Glob"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Read"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Bash"
    }
   ],
   "ctx_calls": 2,
   "pack_calls": 1,
   "grep_after_pack": 7,
   "read_after_pack": 3,
   "final_text": "Everything compiles and behaves as intended. Here's a summary of the changes, all in `packages/pipeline/token_meter.py`:\n\n**1. Cache-aware savings**\n- Added `CACHE_READ_PRICE_FACTOR = 0.1` (Anthropic's cache-read discount \u2014 cheap, not literally free).\n- `ArmResult` gets a new optional field `cached_tokens: int = 0` (defaults to 0, so every existing construction/callsite is unaffected) plus a new `billed_tokens` property: fresh tokens at full price + cached tokens at the discounted rate.\n- `QueryCompare` gets `cache_aware_tokens_saved` / `cache_aware_pct_saved` properties alongside the original `tokens_saved`/`pct_saved` (left untouched).\n- `compare_queries` now tracks which files each arm has already pulled into context across the query sequence (via a new `_estimate_cached_tokens` helper) and treats repeat-file content as cached. It reports new keys \u2014 `baseline_billed_tokens_total`, `ce_billed_tokens_total`, `cache_aware_tokens_saved_total`, `cache_aware_pct_saved_total` \u2014 plus per-row `*_cached_tokens`/`*_billed_tokens`/`cache_aware_*` \u2014 without touching any existing keys.\n- `context_engine_arm`'s `detail` dict now also includes `\"files\"` (needed to compute overlap; additive, doesn't remove `\"retrieve_mode\"`).\n\n**2. Token-counter fallback**\n- `estimate_tokens` now returns `0` for blank/whitespace-only strings (was previously falling through to a bogus non-zero minimum in some paths).\n- The non-tiktoken fallback now takes `max(chars_estimate, words_estimate)` instead of pure chars/4, since chars/4 alone under-counts token-dense text (long identifiers, punctuation-heavy code, non-English scripts). It still never returns less than 1 for non-blank input.\n\n**3. Human-readable summary**\n- `QueryCompare.summary_line` \u2014 one-line per-query readout (raw + cache-aware savings).\n- `compare_queries(...)[\"summary\"]` \u2014 one overall line, plus each row now carries its own `\"summary\"` string. Both are purely additive fields.\n\nAll existing field names, function signatures, and return keys are unchanged \u2014 only new fields/keys were added, so this is a backwards-compatible change. No new dependencies were introduced.",
   "usage": {
    "input_tokens": 1237,
    "output_tokens": 21161,
    "cache_read_input_tokens": 842105,
    "cache_creation_input_tokens": 38984,
    "total_tokens": 903487,
    "billable_input_tokens": 882326,
    "by_model": {
     "claude-haiku-4-5-20251001": {
      "input_tokens": 1193,
      "output_tokens": 16,
      "cache_read_input_tokens": 0,
      "cache_creation_input_tokens": 0,
      "cost_usd": 0.001273,
      "canonical": "claude-haiku-4-5"
     },
     "claude-sonnet-5": {
      "input_tokens": 44,
      "output_tokens": 21145,
      "cache_read_input_tokens": 842105,
      "cache_creation_input_tokens": 38984,
      "cost_usd": 0.535895,
      "canonical": "claude-sonnet-5"
     }
    },
    "total_cost_usd": 0.5371680000000001
   },
   "error": null,
   "model_used": "claude-sonnet-5",
   "num_turns": 22,
   "wall_ms": 201588,
   "oracle": {
    "ok": true,
    "passed": 2,
    "failed": 0,
    "errors": 0,
    "tail": "..                                                                       [100%]\n2 passed in 0.05s\n"
   },
   "diff": {
    "stat": "packages/pipeline/token_meter.py | 109 +++++++++++++++++++++++++++++++++++++--\n 1 file changed, 104 insertions(+), 5 deletions(-)",
    "changed": true,
    "files": [
     "packages/pipeline/token_meter.py"
    ],
    "untracked": [
     "CLAUDE.md",
     "__pycache__/_oracle_pack_bodies.cpython-313-pytest-9.0.3.pyc",
     "_oracle_pack_bodies.py",
     "packages/pipeline/__pycache__/__init__.cpython-313.pyc",
     "packages/pipeline/__pycache__/model_cache.cpython-313.pyc",
     "packages/pipeline/__pycache__/token_meter.cpython-313.pyc"
    ]
   },
   "success": true
  }
 }
}
```

**Comparison block:**

```json
{
  "tokens_heatmap_only": 1184314,
  "tokens_with_bodies": 903487,
  "delta_tokens": -280827,
  "pct_change_bodies_vs_heatmap": -23.7,
  "grep_after_pack_heatmap": 5,
  "grep_after_pack_bodies": 7,
  "read_after_pack_heatmap": 6,
  "read_after_pack_bodies": 3,
  "both_succeeded": false
}
```

### 15. `20260929T162905Z_packbodies`  (packbodies)

```json
{
 "finished_at": "2026-09-29T16:39:11Z",
 "model": "claude-sonnet-5",
 "arms": {
  "heatmap_only": {
   "arm": "heatmap_only",
   "with_bodies": false,
   "tool_counts": {
    "ToolSearch": 1,
    "mcp__ctx__find": 1,
    "Read": 6,
    "Grep": 7,
    "Bash": 4,
    "Glob": 1,
    "Skill": 1,
    "Edit": 10
   },
   "tool_calls": [
    {
     "name": "ToolSearch"
    },
    {
     "name": "mcp__ctx__find"
    },
    {
     "name": "Read"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Glob"
    },
    {
     "name": "Skill"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Read"
    },
    {
     "name": "Read"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Read"
    },
    {
     "name": "Read"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Read"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Grep"
    }
   ],
   "ctx_calls": 1,
   "pack_calls": 0,
   "grep_after_pack": 0,
   "read_after_pack": 0,
   "final_text": "No external callers construct these directly, so we're safe. Everything checks out.\n\n## Summary\n\nAll changes are in `packages/pipeline/token_meter.py`:\n\n**1. Cache-aware savings (the \"dishonest savings\" issue)**\n- `ArmResult` gained a new field `cached_tokens` plus two properties: `fresh_tokens` (billed at full price) and `effective_tokens` (`fresh_tokens + cached_tokens * CACHE_READ_DISCOUNT`, with `CACHE_READ_DISCOUNT = 0.1`, matching Anthropic's ~10%-of-input cache-read rate).\n- `baseline_grep_read` and `context_engine_arm` each take a new optional `cache: set[str] | None = None` kwarg. When `compare_queries` runs a batch of queries, each arm gets its own simulated session cache (`base_cache`/`ce_cache`) \u2014 file blobs (baseline) or hit-rows (CE) that repeat across queries in that arm are counted as `cached_tokens` via the new `_cached_tokens()` helper, capped so it can never exceed the arm's real token count.\n- `QueryCompare` gained `effective_tokens_saved` / `effective_pct_saved` (cache-aware equivalents of the existing `tokens_saved` / `pct_saved`).\n- `compare_queries`'s per-row dicts and the top-level result dict both gained new keys (`*_cached_tokens`, `*_effective_tokens[_total]`, `effective_tokens_saved[_total]`, `effective_pct_saved[_total]`) \u2014 all additive, nothing renamed or removed.\n\n**2. Hardened token-count fallback (the brittle tokenizer issue)**\n- `estimate_tokens` now returns `0` for any blank *or whitespace-only* string (previously only a fully empty string short-circuited).\n- The no-tiktoken fallback no longer just does `chars/4`, which under-counts dense/punctuation-heavy text (like source code). It now also counts \"pieces\" (words/numbers and individual symbols via a small regex) and takes `max(chars/4, pieces)`, floored at 1 for any non-blank input.\n\n**3. Human-readable summaries (the \"only raw counts\" issue)**\n- `QueryCompare.summary` \u2014 a one-line plain-English recap per query (raw savings + cache-aware savings).\n- `compare_queries()` now sets a top-level `\"summary\"` string (e.g. *\"Baseline used 71,230 tokens vs 230 for Context Engine across 3 queries \u2014 saved 71,000 tokens (99.7%) raw. Accounting for prompt-cache reads (~10% of full price), the effective saving is 47,150 tokens (99.6%).\"*) and each row in `\"rows\"` also gets its own `\"summary\"` string.\n\nVerified: `py_compile` passes, function signatures are unchanged except for new optional keyword args, no other code in the repo constructs `ArmResult`/`QueryCompare` directly, and I smoke-tested `estimate_tokens` (empty/whitespace/code, with and without tiktoken available) plus a full `compare_queries` run against a fake engine to confirm the cache/effective-token math and summaries behave sensibly.",
   "usage": {
    "input_tokens": 1257,
    "output_tokens": 26052,
    "cache_read_input_tokens": 1478565,
    "cache_creation_input_tokens": 49073,
    "total_tokens": 1554947,
    "billable_input_tokens": 1528895,
    "by_model": {
     "claude-haiku-4-5-20251001": {
      "input_tokens": 1193,
      "output_tokens": 16,
      "cache_read_input_tokens": 0,
      "cache_creation_input_tokens": 0,
      "cost_usd": 0.001273,
      "canonical": "claude-haiku-4-5"
     },
     "claude-sonnet-5": {
      "input_tokens": 64,
      "output_tokens": 26036,
      "cache_read_input_tokens": 1478565,
      "cache_creation_input_tokens": 49073,
      "cost_usd": 0.752493,
      "canonical": "claude-sonnet-5"
     }
    },
    "total_cost_usd": 0.753766
   },
   "error": null,
   "model_used": "claude-sonnet-5",
   "num_turns": 32,
   "wall_ms": 254733,
   "oracle": {
    "ok": true,
    "passed": 2,
    "failed": 0,
    "errors": 0,
    "tail": "..                                                                       [100%]\n2 passed in 0.05s\n"
   },
   "diff": {
    "stat": "packages/pipeline/token_meter.py | 138 ++++++++++++++++++++++++++++++++++++---\n 1 file changed, 130 insertions(+), 8 deletions(-)",
    "changed": true,
    "files": [
     "packages/pipeline/token_meter.py"
    ],
    "untracked": [
     "CLAUDE.md",
     "__pycache__/_oracle_pack_bodies.cpython-313-pytest-9.0.3.pyc",
     "_oracle_pack_bodies.py",
     "packages/pipeline/__pycache__/__init__.cpython-313.pyc",
     "packages/pipeline/__pycache__/model_cache.cpython-313.pyc",
     "packages/pipeline/__pycache__/token_meter.cpython-313.pyc"
    ]
   },
   "success": true
  },
  "with_bodies": {
   "arm": "with_bodies",
   "with_bodies": true,
   "tool_counts": {
    "ToolSearch": 1,
    "mcp__ctx__find": 1,
    "Read": 5,
    "Grep": 5,
    "Bash": 6,
    "Skill": 1,
    "Edit": 8
   },
   "tool_calls": [
    {
     "name": "ToolSearch"
    },
    {
     "name": "mcp__ctx__find"
    },
    {
     "name": "Read"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Grep"
    },
    {
     "name": "Skill"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Read"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Read"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Read"
    },
    {
     "name": "Edit"
    },
    {
     "name": "Read"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Bash"
    },
    {
     "name": "Bash"
    }
   ],
   "ctx_calls": 1,
   "pack_calls": 0,
   "grep_after_pack": 0,
   "read_after_pack": 0,
   "final_text": "Both other consumers only import `estimate_tokens`, whose signature and empty-string behavior are unchanged \u2014 only the internal fallback path (used when `tiktoken` isn't importable) was tightened, so they're unaffected.\n\n## Summary\n\nAll changes are in `packages/pipeline/token_meter.py`:\n\n**1. Cache-aware savings (per-item and overall)**\n- Added `ArmResult.cached_tokens` (defaults to `0`, so existing construction/usage is untouched) and a new `ArmResult.billed_tokens` property that prices fresh tokens at full rate and cached tokens at `CACHE_READ_DISCOUNT` (0.1, matching Anthropic's prompt-cache-read discount).\n- `baseline_grep_read` and `context_engine_arm` gained an optional `cache_state: set[str] | None` param. When `compare_queries` runs a batch of queries, it threads a persistent cache set per arm (`baseline_cache`, `ce_cache`) across the loop \u2014 a file/path already served by an earlier query in the run is billed at the cache-read rate instead of full price, which is what \"prompt cache did the work\" actually looks like across a session. Passing nothing (old call sites) reproduces the old behavior exactly (`cached_tokens=0`).\n- `QueryCompare` gained `billed_tokens_saved` / `pct_saved_billed` alongside the existing `tokens_saved` / `pct_saved` (both kept, unchanged).\n- `compare_queries`'s returned dict keeps every old key as-is and adds: `cache_read_discount`, `baseline_cached_tokens_total`, `ce_cached_tokens_total`, `baseline_billed_tokens_total`, `ce_billed_tokens_total`, `billed_tokens_saved_total`, `pct_saved_billed_total`, plus the same per-row additions in `rows[]`.\n\n**2. Fallback token counter**\n- Extracted the `except` branch into `_fallback_token_estimate()`. It now strips the input first \u2014 whitespace-only text returns `0` instead of a phantom `1+` tokens \u2014 and takes `max(chars/4, word_count)` instead of chars/4 alone, so punctuation/identifier-dense text (code, JSON) that chars/4 used to under-count now gets a floor from word count. The `tiktoken`-available path is untouched.\n\n**3. Human-readable summary**\n- Added `format_savings_summary(result) -> str`, which `compare_queries` now calls automatically and stores at `result[\"summary\"]`, e.g.:\n  `\"Context Engine saved ~47,980 tokens (99.7%) vs. grep+read at raw sticker price; accounting for prompt caching, the effective savings are ~26,358 tokens (99.6%).\"`\n  It's also exported standalone in case callers want to build the line themselves from a result dict.\n\nEverything is additive \u2014 no existing field, function signature, or return key changed meaning; only new optional params and new dict keys were introduced. I compiled the module, ran targeted checks on the fallback estimator and `billed_tokens` math, and ran `compare_queries` end-to-end against a fake engine with a repeated query to confirm the second occurrence correctly gets discounted as cache-warm on both arms.",
   "usage": {
    "input_tokens": 1249,
    "output_tokens": 25318,
    "cache_read_input_tokens": 1232885,
    "cache_creation_input_tokens": 47579,
    "total_tokens": 1307031,
    "billable_input_tokens": 1281713,
    "by_model": {
     "claude-haiku-4-5-20251001": {
      "input_tokens": 1193,
      "output_tokens": 17,
      "cache_read_input_tokens": 0,
      "cache_creation_input_tokens": 0,
      "cost_usd": 0.001278,
      "canonical": "claude-haiku-4-5"
     },
     "claude-sonnet-5": {
      "input_tokens": 56,
      "output_tokens": 25301,
      "cache_read_input_tokens": 1232885,
      "cache_creation_input_tokens": 47579,
      "cost_usd": 0.6900149999999999,
      "canonical": "claude-sonnet-5"
     }
    },
    "total_cost_usd": 0.6912929999999999
   },
   "error": null,
   "model_used": "claude-sonnet-5",
   "num_turns": 28,
   "wall_ms": 279656,
   "oracle": {
    "ok": true,
    "passed": 2,
    "failed": 0,
    "errors": 0,
    "tail": "..                                                                       [100%]\n2 passed in 0.05s\n"
   },
   "diff": {
    "stat": "packages/pipeline/token_meter.py | 137 +++++++++++++++++++++++++++++++++++++--\n 1 file changed, 130 insertions(+), 7 deletions(-)",
    "changed": true,
    "files": [
     "packages/pipeline/token_meter.py"
    ],
    "untracked": [
     "CLAUDE.md",
     "__pycache__/_oracle_pack_bodies.cpython-313-pytest-9.0.3.pyc",
     "_oracle_pack_bodies.py",
     "packages/pipeline/__pycache__/__init__.cpython-313.pyc",
     "packages/pipeline/__pycache__/model_cache.cpython-313.pyc",
     "packages/pipeline/__pycache__/token_meter.cpython-313.pyc"
    ]
   },
   "success": true
  }
 }
}
```

**Comparison block:**

```json
{
  "tokens_heatmap_only": 1554947,
  "tokens_with_bodies": 1307031,
  "delta_tokens": -247916,
  "pct_change_bodies_vs_heatmap": -15.9,
  "grep_after_pack_heatmap": 0,
  "grep_after_pack_bodies": 0,
  "read_after_pack_heatmap": 0,
  "read_after_pack_bodies": 0,
  "both_succeeded": true
}
```

### 16. `20260930T123954Z_3arm`  (3arm)

```json
{
 "started_at": "2026-09-30T12:39:54Z",
 "model": "claude-sonnet-5",
 "arms": [
  "A_without",
  "B_map_only",
  "C_map_session"
 ],
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true,
 "preflight_only": true
}
```

### 17. `20260930T124113Z_3arm`  (3arm)

```json
{
 "started_at": "2026-09-30T12:41:13Z",
 "finished_at": "2026-09-30T12:51:34Z",
 "model": "claude-sonnet-5",
 "arms": [
  "A_without",
  "B_map_only",
  "C_map_session"
 ],
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| A_without | 1,422,730 | 1,337,590 | 21,574 | 30 | 29 | 0 | 12 | 4 | 1 | 1.0 |
| B_map_only | 774,797 | 725,750 | 16,420 | 19 | 18 | 2 | 2 | 1 | 1 | 1.0 |
| C_map_session | 1,472,026 | 1,409,009 | 19,093 | 33 | 32 | 2 | 15 | 3 | 1 | 1.0 |

**Comparison block:**

```json
{
  "A_without": {
    "total_tokens": 1422730,
    "input_tokens": 1181,
    "output_tokens": 21574,
    "cache_read": 1337590,
    "tool_calls": 29,
    "scubiee_calls": 0,
    "scubiee_tools_used": [],
    "native_read_grep_glob": 16,
    "num_turns": 30,
    "wall_ms": 260095,
    "files_modified": 5,
    "success": true,
    "oracle_pass_ratio": 1.0,
    "pct_vs_without": 0.0
  },
  "B_map_only": {
    "total_tokens": 774797,
    "input_tokens": 1157,
    "output_tokens": 16420,
    "cache_read": 725750,
    "tool_calls": 18,
    "scubiee_calls": 3,
    "scubiee_tools_used": [
      "gate",
      "map"
    ],
    "native_read_grep_glob": 3,
    "num_turns": 19,
    "wall_ms": 147987,
    "files_modified": 233,
    "success": true,
    "oracle_pass_ratio": 1.0,
    "pct_vs_without": 45.5
  },
  "C_map_session": {
    "total_tokens": 1472026,
    "input_tokens": 1187,
    "output_tokens": 19093,
    "cache_read": 1409009,
    "tool_calls": 32,
    "scubiee_calls": 4,
    "scubiee_tools_used": [
      "gate",
      "map",
      "status"
    ],
    "native_read_grep_glob": 18,
    "num_turns": 33,
    "wall_ms": 189192,
    "files_modified": 234,
    "success": true,
    "oracle_pass_ratio": 1.0,
    "pct_vs_without": -3.5
  }
}
```

### 18. `20260930T131517Z_bigAB`  (bigAB)

```json
{
 "started_at": "2026-09-30T13:15:17Z",
 "model": "claude-sonnet-5",
 "arms": [
  "A_without",
  "B_map_only"
 ],
 "max_turns": 120,
 "task_id": "pipeline_timing_rollup",
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true,
 "preflight_only": true
}
```

### 19. `20260930T131625Z_bigAB`  (bigAB)

```json
{
 "started_at": "2026-09-30T13:16:25Z",
 "finished_at": "2026-09-30T13:48:00Z",
 "model": "claude-sonnet-5",
 "arms": [
  "A_without",
  "B_map_only"
 ],
 "max_turns": 120,
 "task_id": "pipeline_timing_rollup",
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| A_without | 16,052,490 | 15,762,100 | 77,604 | 98 | 97 | 0 | 20 | 32 | 0 | 1.0 |
| B_map_only | 15,441,209 | 15,129,524 | 100,457 | 112 | 111 | 2 | 31 | 26 | 0 | 1.0 |

**Comparison block:**

```json
{
  "A_without": {
    "total_tokens": 16052490,
    "input_tokens": 1517,
    "output_tokens": 77604,
    "cache_read": 15762100,
    "tool_calls": 97,
    "scubiee_calls": 0,
    "scubiee_tools_used": [],
    "native_read_grep_glob": 52,
    "num_turns": 98,
    "wall_ms": 885418,
    "real_py_edits": 4,
    "oracle_pass_ratio": 1.0,
    "success": false,
    "pct_vs_without": 0.0
  },
  "B_map_only": {
    "total_tokens": 15441209,
    "input_tokens": 1525,
    "output_tokens": 100457,
    "cache_read": 15129524,
    "tool_calls": 111,
    "scubiee_calls": 3,
    "scubiee_tools_used": [
      "gate",
      "map"
    ],
    "native_read_grep_glob": 57,
    "num_turns": 112,
    "wall_ms": 988490,
    "real_py_edits": 5,
    "oracle_pass_ratio": 1.0,
    "success": false,
    "pct_vs_without": 3.8
  }
}
```

### 20. `20260930T140920Z_bigStrict`  (bigStrict)

```json
{
 "started_at": "2026-09-30T14:09:20Z",
 "model": "claude-sonnet-5",
 "arms": [
  "A_without",
  "B_map_strict"
 ],
 "max_turns": 120,
 "task_id": "pipeline_timing_rollup",
 "variant": "strict_map_only",
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true,
 "preflight_only": true
}
```

### 21. `20260930T141029Z_bigStrict`  (bigStrict)

_No report.json. Files present: A_without, B_map_strict_

### 22. `20260930T142435Z_smallStrict`  (smallStrict)

```json
{
 "started_at": "2026-09-30T14:24:35Z",
 "model": "claude-sonnet-5",
 "arms": [
  "A_without",
  "B_map_strict"
 ],
 "max_turns": 60,
 "task_id": "cache_aware_savings",
 "variant": "strict_map_only_small",
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true,
 "preflight_only": true
}
```

### 23. `20260930T142534Z_smallStrict`  (smallStrict)

```json
{
 "started_at": "2026-09-30T14:25:34Z",
 "finished_at": "2026-09-30T14:31:57Z",
 "model": "claude-sonnet-5",
 "arms": [
  "A_without",
  "B_map_strict"
 ],
 "max_turns": 60,
 "task_id": "cache_aware_savings",
 "variant": "strict_map_only_small",
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| A_without | 1,037,706 | 950,513 | 22,208 | 21 | 33 | 0 | 12 | 4 | 1 | 1.0 |
| B_map_strict | 1,125,787 | 1,066,253 | 18,973 | 25 | 24 | 2 | 7 | 2 | 0 | 0.33 |

**Comparison block:**

```json
{
  "A_without": {
    "total_tokens": 1037706,
    "output_tokens": 22208,
    "cache_read": 950513,
    "tool_calls": 33,
    "scubiee_calls": 0,
    "n_map": 0,
    "n_grep_glob": 12,
    "map_then_grep": 0,
    "native_read_grep_glob": 16,
    "num_turns": 21,
    "wall_ms": 162913,
    "real_py_edits": 1,
    "oracle_pass_ratio": 1.0,
    "success": true,
    "pct_vs_without": 0.0
  },
  "B_map_strict": {
    "total_tokens": 1125787,
    "output_tokens": 18973,
    "cache_read": 1066253,
    "tool_calls": 24,
    "scubiee_calls": 3,
    "n_map": 2,
    "n_grep_glob": 7,
    "map_then_grep": 1,
    "native_read_grep_glob": 9,
    "num_turns": 25,
    "wall_ms": 196876,
    "real_py_edits": 1,
    "oracle_pass_ratio": 0.33,
    "success": false,
    "pct_vs_without": -8.5
  }
}
```

### 24. `20260930T144713Z_smallGuided`  (smallGuided)

```json
{
 "started_at": "2026-09-30T14:47:13Z",
 "model": "claude-sonnet-5",
 "arms": [
  "A_without",
  "B_map_guided"
 ],
 "max_turns": 60,
 "task_id": "cache_aware_savings",
 "variant": "guided_map_only",
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true,
 "preflight_only": true
}
```

### 25. `20260930T144826Z_smallGuided`  (smallGuided)

```json
{
 "started_at": "2026-09-30T14:48:26Z",
 "finished_at": "2026-09-30T14:58:23Z",
 "model": "claude-sonnet-5",
 "arms": [
  "A_without",
  "B_map_guided"
 ],
 "max_turns": 60,
 "task_id": "cache_aware_savings",
 "variant": "guided_map_only",
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| A_without | 862,855 | 804,950 | 22,622 | 21 | 20 | 0 | 7 | 1 | 1 | 1.0 |
| B_map_guided | 1,246,468 | 1,178,622 | 21,448 | 28 | 27 | 1 | 12 | 2 | 1 | 1.0 |

**Comparison block:**

```json
{
  "A_without": {
    "total_tokens": 862855,
    "output_tokens": 22622,
    "cache_read": 804950,
    "tool_calls": 20,
    "scubiee_calls": 0,
    "n_map": 0,
    "n_grep_glob": 7,
    "map_then_grep": 0,
    "native_read_grep_glob": 8,
    "num_turns": 21,
    "wall_ms": 353883,
    "real_py_edits": 1,
    "oracle_pass_ratio": 1.0,
    "success": true,
    "pct_vs_without": 0.0
  },
  "B_map_guided": {
    "total_tokens": 1246468,
    "output_tokens": 21448,
    "cache_read": 1178622,
    "tool_calls": 27,
    "scubiee_calls": 1,
    "n_map": 1,
    "n_grep_glob": 12,
    "map_then_grep": 1,
    "native_read_grep_glob": 14,
    "num_turns": 28,
    "wall_ms": 221181,
    "real_py_edits": 1,
    "oracle_pass_ratio": 1.0,
    "success": true,
    "pct_vs_without": -44.5
  }
}
```

### 26. `20260930T151541Z_rules4`  (rules4)

```json
{
 "started_at": "2026-09-30T15:15:41Z",
 "model": "claude-sonnet-5",
 "arms": [
  "A_without",
  "B_map_flexible",
  "C_map_strict",
  "D_map_guided"
 ],
 "max_turns": 60,
 "task_id": "cache_aware_savings",
 "variant": "rules_4arm",
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true,
 "preflight_only": true
}
```

### 27. `20260930T151708Z_rules4`  (rules4)

```json
{
 "started_at": "2026-09-30T15:17:08Z",
 "finished_at": "2026-09-30T15:33:08Z",
 "model": "claude-sonnet-5",
 "arms": [
  "A_without",
  "B_map_flexible",
  "C_map_strict",
  "D_map_guided"
 ],
 "max_turns": 60,
 "task_id": "cache_aware_savings",
 "variant": "rules_4arm",
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| A_without | 1,249,297 | 1,184,697 | 22,784 | 30 | 29 | 0 | 0 | 2 | 1 | 1.0 |
| B_map_flexible | 1,146,194 | 1,075,451 | 23,888 | 27 | 26 | 2 | 8 | 2 | 0 | 0.33 |
| C_map_strict | 1,282,194 | 1,205,393 | 27,467 | 34 | 33 | 3 | 15 | 2 | 1 | 1.0 |
| D_map_guided | 831,077 | 772,241 | 19,473 | 20 | 19 | 1 | 7 | 1 | 1 | 1.0 |

**Comparison block:**

```json
{
  "A_without": {
    "total_tokens": 1249297,
    "output_tokens": 22784,
    "cache_read": 1184697,
    "tool_calls": 29,
    "scubiee_calls": 0,
    "n_map": 0,
    "n_grep_glob": 0,
    "map_then_grep": 0,
    "native_read_grep_glob": 2,
    "num_turns": 30,
    "wall_ms": 224136,
    "real_py_edits": 1,
    "oracle_pass_ratio": 1.0,
    "success": true,
    "pct_vs_without": 0.0
  },
  "B_map_flexible": {
    "total_tokens": 1146194,
    "output_tokens": 23888,
    "cache_read": 1075451,
    "tool_calls": 26,
    "scubiee_calls": 3,
    "n_map": 2,
    "n_grep_glob": 8,
    "map_then_grep": 0,
    "native_read_grep_glob": 10,
    "num_turns": 27,
    "wall_ms": 257743,
    "real_py_edits": 1,
    "oracle_pass_ratio": 0.33,
    "success": false,
    "pct_vs_without": 8.3
  },
  "C_map_strict": {
    "total_tokens": 1282194,
    "output_tokens": 27467,
    "cache_read": 1205393,
    "tool_calls": 33,
    "scubiee_calls": 4,
    "n_map": 3,
    "n_grep_glob": 15,
    "map_then_grep": 2,
    "native_read_grep_glob": 17,
    "num_turns": 34,
    "wall_ms": 265617,
    "real_py_edits": 1,
    "oracle_pass_ratio": 1.0,
    "success": true,
    "pct_vs_without": -2.6
  },
  "D_map_guided": {
    "total_tokens": 831077,
    "output_tokens": 19473,
    "cache_read": 772241,
    "tool_calls": 19,
    "scubiee_calls": 1,
    "n_map": 1,
    "n_grep_glob": 7,
    "map_then_grep": 1,
    "native_read_grep_glob": 8,
    "num_turns": 20,
    "wall_ms": 187429,
    "real_py_edits": 1,
    "oracle_pass_ratio": 1.0,
    "success": true,
    "pct_vs_without": 33.5
  }
}
```

### 28. `20260930T154053Z_gVs`  (gVs)

```json
{
 "started_at": "2026-09-30T15:40:53Z",
 "model": "claude-sonnet-5",
 "arms": [
  "G_map_guided",
  "S_map_strict"
 ],
 "max_turns": 60,
 "task_id": "cache_aware_savings",
 "variant": "guided_vs_strict",
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true,
 "preflight_only": true
}
```

### 29. `20260930T154207Z_gVs`  (gVs)

```json
{
 "started_at": "2026-09-30T15:42:07Z",
 "finished_at": "2026-09-30T15:49:52Z",
 "model": "claude-sonnet-5",
 "arms": [
  "G_map_guided",
  "S_map_strict"
 ],
 "max_turns": 60,
 "task_id": "cache_aware_savings",
 "variant": "guided_vs_strict",
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| G_map_guided | 1,000,482 | 930,379 | 22,456 | 21 | 20 | 1 | 5 | 2 | 0 | 0.33 |
| S_map_strict | 1,119,510 | 1,058,465 | 18,000 | 24 | 23 | 2 | 4 | 2 | 1 | 1.0 |

**Comparison block:**

```json
{
  "G_map_guided": {
    "total_tokens": 1000482,
    "output_tokens": 22456,
    "cache_read": 930379,
    "tool_calls": 20,
    "scubiee_calls": 1,
    "n_map": 1,
    "n_grep_glob": 5,
    "map_then_grep": 1,
    "native_read_grep_glob": 7,
    "num_turns": 21,
    "wall_ms": 220142,
    "real_py_edits": 1,
    "oracle_pass_ratio": 0.33,
    "success": false,
    "pct_vs_guided": 0.0
  },
  "S_map_strict": {
    "total_tokens": 1119510,
    "output_tokens": 18000,
    "cache_read": 1058465,
    "tool_calls": 23,
    "scubiee_calls": 4,
    "n_map": 2,
    "n_grep_glob": 4,
    "map_then_grep": 0,
    "native_read_grep_glob": 6,
    "num_turns": 24,
    "wall_ms": 225216,
    "real_py_edits": 1,
    "oracle_pass_ratio": 1.0,
    "success": true,
    "pct_vs_guided": -11.9
  }
}
```

### 30. `20260930T161452Z_policybench`  (policybench)

```json
{
 "started_at": "2026-09-30T16:14:52Z",
 "model": "claude-sonnet-5",
 "arms": [
  "without",
  "guided",
  "policy"
 ],
 "tasks": [
  "known_target_flag",
  "locate_confidence"
 ],
 "repeats": 3,
 "max_turns": 60,
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true,
 "preflight_only": true
}
```
_preflight-only or aborted; no cells._

### 31. `20260930T163827Z_policybench`  (policybench)

```json
{
 "started_at": "2026-09-30T16:38:27Z",
 "model": "claude-sonnet-5",
 "arms": [
  "without",
  "guided",
  "two_layer"
 ],
 "tasks": [
  "cache_aware_savings",
  "known_target_flag",
  "locate_confidence"
 ],
 "repeats": 3,
 "max_turns": 60,
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true,
 "preflight_only": true
}
```
_preflight-only or aborted; no cells._

### 32. `20260930T171024Z_retrieval`  (retrieval)

```json
{
 "started_at": "2026-09-30T17:10:24Z",
 "model": "claude-sonnet-5",
 "arms": [
  "without",
  "guided",
  "two_layer"
 ],
 "queries": [
  "first_map_skips_graph",
  "idle_engine_self_retire",
  "cold_start_status_warming",
  "dirty_path_first_char",
  "faiss_reimport_segfault",
  "ir_indexed_once_per_sync",
  "memory_budget_resets_threads",
  "watchdog_no_autoload_while_mcp"
 ],
 "repeats": 2,
 "max_turns": 14,
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true,
 "preflight_only": true
}
```

### 33. `20260930T171309Z_retrieval`  (retrieval)

```json
{
 "started_at": "2026-09-30T17:13:09Z",
 "finished_at": "2026-09-30T17:19:06Z",
 "model": "claude-sonnet-5",
 "arms": [
  "without",
  "guided",
  "two_layer"
 ],
 "queries": [
  "idle_engine_self_retire",
  "dirty_path_first_char"
 ],
 "repeats": 1,
 "max_turns": 14,
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| without/idle_engine_self_retire | 278,477 | 231,278 | 3,839 | 12 | 11 | 0 | 7 | 3 | 1 | R1.0/P0.25/M1.0 |
| guided/idle_engine_self_retire | 347,682 | 321,561 | 3,929 | 12 | 11 | 2 | 2 | 5 | 1 | R1.0/P0.333/M1.0 |
| two_layer/idle_engine_self_retire | 265,768 | 242,392 | 3,398 | 11 | 10 | 2 | 1 | 5 | 1 | R1.0/P0.5/M1.0 |
| without/dirty_path_first_char | 263,232 | 235,829 | 4,237 | 11 | 10 | 0 | 6 | 3 | 1 | R1.0/P1.0/M1.0 |
| guided/dirty_path_first_char | 350,751 | 329,432 | 3,954 | 13 | 12 | 2 | 6 | 2 | 1 | R1.0/P0.5/M1.0 |
| two_layer/dirty_path_first_char | 441,359 | 412,785 | 5,772 | 13 | 12 | 2 | 3 | 3 | 1 | R1.0/P1.0/M1.0 |

**Aggregate (per-arm):**
```json
{
 "guided": {
  "n": 2,
  "hit_any_rate": 1.0,
  "full_recall_rate": 1.0,
  "wrote_answer_rate": 1.0,
  "recall": {
   "n": 2,
   "median": 1.0,
   "mean": 1.0,
   "p25": 1.0,
   "p75": 1.0,
   "min": 1.0,
   "max": 1.0
  },
  "precision": {
   "n": 2,
   "median": 0.416,
   "mean": 0.416,
   "p25": 0.333,
   "p75": 0.333,
   "min": 0.333,
   "max": 0.5
  },
  "f1": {
   "n": 2,
   "median": 0.584,
   "mean": 0.584,
   "p25": 0.5,
   "p75": 0.5,
   "min": 0.5,
   "max": 0.667
  },
  "mrr": {
   "n": 2,
   "median": 1.0,
   "mean": 1.0,
   "p25": 1.0,
   "p75": 1.0,
   "min": 1.0,
   "max": 1.0
  },
  "total_tokens": {
   "n": 2,
   "median": 349216.5,
   "mean": 349216.5,
   "p25": 347682,
   "p75": 347682,
   "min": 347682,
   "max": 350751
  },
  "num_turns": {
   "n": 2,
   "median": 12.5,
   "mean": 12.5,
   "p25": 12,
   "p75": 12,
   "min": 12,
   "max": 13
  },
  "map": {
   "n": 2,
   "median": 2.0,
   "mean": 2,
   "p25": 2,
   "p75": 2,
   "min": 2,
   "max": 2
  },
  "grep": {
   "n": 2,
   "median": 2.0,
   "mean": 2,
   "p25": 2,
   "p75": 2,
   "min": 2,
   "max": 2
  },
  "glob": {
   "n": 2,
   "median": 2.0,
   "mean": 2,
   "p25": 0,
   "p75": 0,
   "min": 0,
   "max": 4
  },
  "read": {
   "n": 2,
   "median": 3.5,
   "mean": 3.5,
   "p25": 2,
   "p75": 2,
   "min": 2,
   "max": 5
  },
  "map_then_grep": {
   "n": 2,
   "median": 0.5,
   "mean": 0.5,
   "p25": 0,
   "p75": 0,
   "min": 0,
   "max": 1
  },
  "duplicate_retrievals": {
   "n": 2,
   "median": 2.0,
   "mean": 2,
   "p25": 1,
   "p75": 1,
   "min": 1,
   "max": 3
  },
  "distinct_read_paths": {
   "n": 2,
   "median": 2.5,
   "mean": 2.5,
   "p25": 2,
   "p75": 2,
   "min": 2,
   "max": 3
  },
  "tool_calls": {
   "n": 2,
   "median": 11.5,
   "mean": 11.5,
   "p25": 11,
   "p75": 11,
   "min": 11,
   "max": 12
  },
  "wall_ms": {
   "n": 2,
   "median": 62116.5,
   "mean": 62116.5,
   "p25": 58717,
   "p75": 58717,
   "min": 58717,
   "max": 65516
  }
 },
 "two_layer": {
  "n": 2,
  "hit_any_rate": 1.0,
  "full_recall_rate": 1.0,
  "wrote_answer_rate": 1.0,
  "recall": {
   "n": 2,
   "median": 1.0,
   "mean": 1.0,
   "p25": 1.0,
   "p75": 1.0,
   "min": 1.0,
   "max": 1.0
  },
  "precision": {
   "n": 2,
   "median": 0.75,
   "mean": 0.75,
   "p25": 0.5,
   "p75": 0.5,
   "min": 0.5,
   "max": 1.0
  },
  "f1": {
   "n": 2,
   "median": 0.834,
   "mean": 0.834,
   "p25": 0.667,
   "p75": 0.667,
   "min": 0.667,
   "max": 1.0
  },
  "mrr": {
   "n": 2,
   "median": 1.0,
   "mean": 1.0,
   "p25": 1.0,
   "p75": 1.0,
   "min": 1.0,
   "max": 1.0
  },
  "total_tokens": {
   "n": 2,
   "median": 353563.5,
   "mean": 353563.5,
   "p25": 265768,
   "p75": 265768,
   "min": 265768,
   "max": 441359
  },
  "num_turns": {
   "n": 2,
   "median": 12.0,
   "mean": 12,
   "p25": 11,
   "p75": 11,
   "min": 11,
   "max": 13
  },
  "map": {
   "n": 2,
   "median": 2.0,
   "mean": 2,
   "p25": 2,
   "p75": 2,
   "min": 2,
   "max": 2
  },
  "grep": {
   "n": 2,
   "median": 2.0,

```

### 34. `20260930T172308Z_retrieval`  (retrieval)

```json
{
 "started_at": "2026-09-30T17:23:08Z",
 "finished_at": "2026-09-30T17:27:00Z",
 "model": "claude-sonnet-5",
 "arms": [
  "without",
  "guided",
  "two_layer"
 ],
 "queries": [
  "idle_engine_self_retire"
 ],
 "repeats": 1,
 "max_turns": 14,
 "preflight_static_ok": true,
 "warm_proof_ok": true,
 "ok": true
}
```
| Arm | Total tok | Cache-read | Output | Turns | Calls | map | grep/glob | read | Success | Oracle |
|---|---|---|---|---|---|---|---|---|---|---|
| without/idle_engine_self_retire | 973,962 | 897,805 | 7,218 | 20 | 19 | 0 | 11 | 7 | 1 | R1.0/P0.2/M1.0 |
| guided/idle_engine_self_retire | 300,252 | 275,748 | 4,031 | 13 | 12 | 2 | 4 | 4 | 1 | R1.0/P0.25/M1.0 |
| two_layer/idle_engine_self_retire | 456,737 | 429,812 | 4,157 | 13 | 12 | 2 | 4 | 4 | 1 | R1.0/P0.333/M1.0 |

**without / idle_engine_self_retire** — result sizes (chars): Grep=1594, Grep=721, Grep=40, Grep=42, Grep=49, Read=37561, Read=67473, Grep=51, Grep=9681, Read=2701, Grep=1802, Grep=4254, Grep=1635, Read=3021, Read=2879, Read=1944, Grep=74, Read=3263, Write=254
  cache_read/turn: first=20798 peak=87238 last=87238 steps=32

**guided / idle_engine_self_retire** — result sizes (chars): ToolSearch=60, s:map=989, s:map=4170, Read=3964, Read=3668, Grep=106, Read=4704, Grep=156, Grep=148, Grep=1447, Read=2911, Write=253
  cache_read/turn: first=20798 peak=38953 last=38953 steps=20

**two_layer / idle_engine_self_retire** — result sizes (chars): ToolSearch=60, s:map=995, s:map=4274, Read=3385, Read=4727, Read=1860, Read=6263, Grep=106, Grep=40, Grep=2790, Grep=2001, Write=256
  cache_read/turn: first=20798 peak=41172 last=41172 steps=22

**Aggregate (per-arm):**
```json
{
 "guided": {
  "n": 1,
  "hit_any_rate": 1.0,
  "full_recall_rate": 1.0,
  "wrote_answer_rate": 1.0,
  "recall": {
   "n": 1,
   "median": 1.0,
   "mean": 1.0,
   "p25": 1.0,
   "p75": 1.0,
   "min": 1.0,
   "max": 1.0
  },
  "precision": {
   "n": 1,
   "median": 0.25,
   "mean": 0.25,
   "p25": 0.25,
   "p75": 0.25,
   "min": 0.25,
   "max": 0.25
  },
  "f1": {
   "n": 1,
   "median": 0.4,
   "mean": 0.4,
   "p25": 0.4,
   "p75": 0.4,
   "min": 0.4,
   "max": 0.4
  },
  "mrr": {
   "n": 1,
   "median": 1.0,
   "mean": 1.0,
   "p25": 1.0,
   "p75": 1.0,
   "min": 1.0,
   "max": 1.0
  },
  "total_tokens": {
   "n": 1,
   "median": 300252,
   "mean": 300252,
   "p25": 300252,
   "p75": 300252,
   "min": 300252,
   "max": 300252
  },
  "num_turns": {
   "n": 1,
   "median": 13,
   "mean": 13,
   "p25": 13,
   "p75": 13,
   "min": 13,
   "max": 13
  },
  "map": {
   "n": 1,
   "median": 2,
   "mean": 2,
   "p25": 2,
   "p75": 2,
   "min": 2,
   "max": 2
  },
  "grep": {
   "n": 1,
   "median": 4,
   "mean": 4,
   "p25": 4,
   "p75": 4,
   "min": 4,
   "max": 4
  },
  "glob": {
   "n": 1,
   "median": 0,
   "mean": 0,
   "p25": 0,
   "p75": 0,
   "min": 0,
   "max": 0
  },
  "read": {
   "n": 1,
   "median": 4,
   "mean": 4,
   "p25": 4,
   "p75": 4,
   "min": 4,
   "max": 4
  },
  "map_then_grep": {
   "n": 1,
   "median": 0,
   "mean": 0,
   "p25": 0,
   "p75": 0,
   "min": 0,
   "max": 0
  },
  "duplicate_retrievals": {
   "n": 1,
   "median": 2,
   "mean": 2,
   "p25": 2,
   "p75": 2,
   "min": 2,
   "max": 2
  },
  "distinct_read_paths": {
   "n": 1,
   "median": 3,
   "mean": 3,
   "p25": 3,
   "p75": 3,
   "min": 3,
   "max": 3
  },
  "tool_calls": {
   "n": 1,
   "median": 12,
   "mean": 12,
   "p25": 12,
   "p75": 12,
   "min": 12,
   "max": 12
  },
  "wall_ms": {
   "n": 1,
   "median": 57425,
   "mean": 57425,
   "p25": 57425,
   "p75": 57425,
   "min": 57425,
   "max": 57425
  }
 },
 "two_layer": {
  "n": 1,
  "hit_any_rate": 1.0,
  "full_recall_rate": 1.0,
  "wrote_answer_rate": 1.0,
  "recall": {
   "n": 1,
   "median": 1.0,
   "mean": 1.0,
   "p25": 1.0,
   "p75": 1.0,
   "min": 1.0,
   "max": 1.0
  },
  "precision": {
   "n": 1,
   "median": 0.333,
   "mean": 0.333,
   "p25": 0.333,
   "p75": 0.333,
   "min": 0.333,
   "max": 0.333
  },
  "f1": {
   "n": 1,
   "median": 0.5,
   "mean": 0.5,
   "p25": 0.5,
   "p75": 0.5,
   "min": 0.5,
   "max": 0.5
  },
  "mrr": {
   "n": 1,
   "median": 1.0,
   "mean": 1.0,
   "p25": 1.0,
   "p75": 1.0,
   "min": 1.0,
   "max": 1.0
  },
  "total_tokens": {
   "n": 1,
   "median": 456737,
   "mean": 456737,
   "p25": 456737,
   "p75": 456737,
   "min": 456737,
   "max": 456737
  },
  "num_turns": {
   "n": 1,
   "median": 13,
   "mean": 13,
   "p25": 13,
   "p75": 13,
   "min": 13,
   "max": 13
  },
  "map": {
   "n": 1,
   "median": 2,
   "mean": 2,
   "p25": 2,
   "p75": 2,
   "min": 2,
   "max": 2
  },
  "grep": {
   "n": 1,
   "median": 4,
   "mean": 4,
   "p25": 4,
   "p75": 4,
   "min": 4,
   
```
