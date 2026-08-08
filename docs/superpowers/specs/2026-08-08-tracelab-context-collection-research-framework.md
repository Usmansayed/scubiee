# TraceLab Context-Collection Research Framework

**Status:** Phase 1 approved → Phase 3–5 in progress (Nova Pro extraction)  
**Date:** 2026-08-08  
**Dataset:** SyFI TraceLab **v0.0.2** (`syfi_coding_trace.duckdb`, SHA256 `a7bab286…e744`)  
**LLM summarizer:** Amazon Nova Pro via Bedrock (`eu.amazon.nova-pro-v1:0`, region from `.env`)  
**Goal:** Reverse-engineer how frontier coding agents collect context, so we can design a better context engine. **Not** model training.  
**Sample:** 100 Claude + 100 Codex frontier sessions → structural JSON + Nova workflow summaries → 6 generalized workflows.

---

## 0. Scope decisions (locked from exploration)

| Decision | Choice |
|---|---|
| Corpus | Public TraceLab v0.0.2 DuckDB only (sanitized) |
| Agents | **100 Claude + 100 Codex** sessions |
| Cursor | **Unavailable** in this release — defer; do not invent Cursor rows |
| Model priority | Top frontier models only (see §3) |
| Analysis mode | **Structural / behavioral** (tool sequences, sizes, tokens, latency). Semantic fields (paths, queries, message text) are stripped |
| Deliverable | Research report + “Ideas for a Better Context Engine” list grounded in multi-session evidence |

**Hard limit of the public data**

| Available | Not available |
|---|---|
| Tool name, order, latency, errors | Tool input JSON / paths / queries |
| `input_chars` / `result_chars` | Tool result text |
| Token totals + prefix/append split | User / assistant message text |
| Bash `executables` + `command_skeleton` | Exact file identities |
| Session / project / user / model ids | Repository contents |

Implication: every metric and schema field must be either (a) computable from the above, or (b) explicitly marked `unavailable_due_to_sanitization` / `proxy_only`.

---

## 1. Research questions

Grouped by what they drive for a context engine.

### 1.1 Session anatomy — how context collection starts

1. What is the **first retrieval action** after a user message (tool family + shell-exe proxy)?
2. How often does the session open with **orientation** (ls/find/glob/README-ish reads) vs **targeted search** (grep/rg) vs **direct Read**?
3. How many retrieval actions occur **before the first edit** (`Edit` / `Write` / `apply_patch`)?
4. What is the typical **bootstrap length** (rounds and tool calls until first mutation)?
5. Does bootstrap differ by provider (Claude vs Codex) and by frontier model family?

### 1.2 Retrieval repertoire — which tools for which job

6. For each provider, which tools dominate **locate / read / mutate / verify / plan / external** roles?
7. How often is search done via **dedicated tools** (`Grep`/`Glob`) vs **shell** (`grep`/`rg`/`find`/`ls`/`cat` in `executables`)?
8. When is `Read` used vs shell `cat`/`head`/`sed`?
9. What role do `Agent` / `Task*` / `update_plan` / `TaskCreate` play relative to retrieval?
10. How are **WebFetch / WebSearch / ToolSearch** interleaved with local retrieval?

### 1.3 Evolution over the session

11. How does the **mix of locate vs read vs mutate vs verify** change across session percentiles (0–10%, 10–40%, 40–70%, 70–100%)?
12. When does the agent **stop collecting** and start mostly editing/verifying?
13. Are there recurring **phase machines** (e.g. Orient → Search → Read → Edit → Test → Repair)?
14. After an edit failure (`is_error` on mutate tools), does retrieval **widen** (new searches) or **deepen** (re-read same area — proxied by similar size/tool patterns)?
15. How does **context size** (`input_tokens_total`, `prefix_tokens`, `newly_append_tokens`) evolve across phases?

### 1.4 Waste, duplication, and loops

16. How often do we see **repeated identical tool signatures** (same `tool_name` + similar `input_chars` ±ε within a short window)?
17. How often are **Read-like** actions repeated with nearly identical size footprints (proxy for reopening the same file)?
18. How often do **search loops** occur (consecutive locate tools without intervening mutate/verify success)?
19. What fraction of append tokens after mid-session are attributable to **tool results** vs user messages (`current_tool_result_chars` / `current_user_message_chars`)?
20. Which retrieval actions look **unnecessary** given later behavior (e.g. search immediately followed by unrelated search; large result never followed by edit/read deepen)?
21. Where are **tokens wasted**: large `result_chars` with no subsequent mutate; ballooning `newly_append_tokens`; low prefix-hit rounds after long idle gaps?

### 1.5 Stopping, confidence, and success proxies

22. What tool sequences precede **session end** or long human wait (`user_message` gap)?
23. After retrieval, how quickly does the agent emit an edit (retrieval→mutation latency in rounds)?
24. Do high-`result_chars` searches correlate with faster mutation, or with more follow-up search (success vs thrash)?
25. Error-driven retrieval: rate of `is_error` on locate/read and the next-action distribution.

### 1.6 Cross-session patterns (for context-engine design)

26. Which **n-gram tool sequences** recur most across the 200 sessions?
27. Which patterns are **Claude-specific** vs **Codex-specific** vs shared?
28. Which retrieval jobs look **deterministic** (could be done by an engine without an LLM call)?
29. Which jobs still need an **LLM** (disambiguation, intent, synthesis)?
30. For each inefficiency, what would **map / workspace / focus**-style APIs (our engine) have returned instead?

### 1.7 Explicit non-questions (until richer traces exist)

- Exact file paths opened first  
- Exact search query strings  
- Verbatim “what was missing before the search”  
- Whether retrieved text was cited in the final answer  

These become **hypotheses labeled clearly**, or fields set to `null` with reason `sanitized`.

---

## 2. Metrics

All metrics are computed per session, then aggregated across the 200-session sample. Units noted.

### 2.1 Session overview metrics

| ID | Metric | Definition |
|---|---|---|
| S1 | `rounds` | Count of LLM rounds in session |
| S2 | `tool_calls` | Count of tool_calls rows |
| S3 | `user_turns` | Count of `timing_events.event_type='user_message'` |
| S4 | `primary_model` | Mode of `rounds.model` |
| S5 | `provider` | `claude` \| `codex` |
| S6 | `project_id` | Pseudonymous project (Claude); null for Codex |
| S7 | `duration_ms` | Max−min timestamp over timing_events |
| S8 | `total_input_tokens` | Sum `input_tokens_total` |
| S9 | `total_append_tokens` | Sum `newly_append_tokens` |
| S10 | `total_output_tokens` | Sum `output_tokens` |
| S11 | `mean_prefix_hit_ratio` | Mean `prefix_tokens / input_tokens_total` |
| S12 | `frontier_tier` | `opus` \| `sonnet` \| `gpt5.x` \| `codex-specialized` \| other |

### 2.2 Tool taxonomy (role labels)

Every tool call is mapped to a **role** (deterministic rules):

| Role | Members (non-exhaustive; extend in code) |
|---|---|
| `locate` | `Grep`, `Glob`, `LS`, `ToolSearch`, `TaskSearch`, shell exe ∈ {`grep`,`rg`,`find`,`ls`,`fd`,`ag`} |
| `read` | `Read`, shell exe ∈ {`cat`,`head`,`tail`,`sed`,`less`,`bat`} |
| `mutate` | `Edit`, `Write`, `NotebookEdit`, `apply_patch` |
| `exec_generic` | `Bash`, `exec_command`, `exec`, `shell`, `shell_command`, `write_stdin` without locate/read exe |
| `verify` | shell exe ∈ {`pytest`,`npm`,`cargo`,`go`,`make`,`tsc`,`eslint`,…} + test-ish skeletons |
| `plan` | `update_plan`, `TaskCreate`, `TaskUpdate` |
| `delegate` | `Agent`, `Task` |
| `web` | `WebFetch`, `WebSearch` |
| `wait` | `wait` |
| `other` | remainder / `custom_tool_N` |

Metrics:

| ID | Metric |
|---|---|
| T1 | Counts & share by role |
| T2 | Counts & share by raw `tool_name` |
| T3 | Shell exe histogram (from `executables`) |
| T4 | Mean/p50/p90 `input_chars`, `result_chars` by role |
| T5 | Error rate by role |
| T6 | Mean latency by role (`tool_internal_latency_ms` else wall) |
| T7 | Tool transition matrix (role→role bigrams) |
| T8 | Top role trigrams |

### 2.3 Retrieval-process metrics

| ID | Metric | Definition |
|---|---|---|
| R1 | `first_retrieval_role` | Role of first locate/read/exec_generic-with-locate-exe |
| R2 | `first_retrieval_tool` | Raw tool name / primary exe |
| R3 | `actions_before_first_mutate` | Tool calls before first `mutate` |
| R4 | `rounds_before_first_mutate` | Rounds before first mutate |
| R5 | `locate_before_first_mutate` | Locate-role count in bootstrap |
| R6 | `read_before_first_mutate` | Read-role count in bootstrap |
| R7 | `search_to_edit_ratio` | `(locate+read) / max(mutate,1)` |
| R8 | `retrieval_depth` | Max consecutive locate/read streak |
| R9 | `retrieval_loops` | Streaks ≥3 locate/read with no mutate/verify |
| R10 | `phase_role_shares` | Role mix in session quartiles |
| R11 | `stop_collecting_index` | First round where rolling mutate+verify share > locate+read share for K rounds |
| R12 | `post_error_retrieval_spike` | Δ locate/read rate in next 5 tools after any error |

### 2.4 Duplication & waste proxies

Because paths/queries are absent, duplication is **signature-based**:

`sig = (tool_name, bucket(input_chars), bucket(result_chars), primary_exe?)`

| ID | Metric |
|---|---|
| W1 | Duplicate signature rate (same sig ≥2 in session) |
| W2 | Near-duplicate Read rate (Read with input_chars within ±10% and result_chars within ±10% of a prior Read) |
| W3 | Repeated shell locate rate (same primary exe + skeleton token pattern) |
| W4 | Large unused result rate: `result_chars` ≥ P90 and no mutate within next N tool calls |
| W5 | Append bloat: rounds where `newly_append_tokens` > P90 and role was locate/read |
| W6 | Low-cache rounds: `prefix_hit_ratio < 0.5` after session start |
| W7 | Estimated wasted append tokens (sum append on duplicate-signature tool rounds) — **proxy, labeled** |
| W8 | Tool calls with `is_error` followed by identical signature retry |

### 2.5 Token & context-growth metrics

| ID | Metric |
|---|---|
| C1 | Context growth curve: `input_tokens_total` vs `round_index` |
| C2 | Append composition proxy: `current_tool_result_chars` vs `current_user_message_chars` |
| C3 | Output/input ratio per round |
| C4 | Reasoning token share when present |
| C5 | Tokens per successful mutate (total append before each mutate) |

### 2.6 Timing metrics

| ID | Metric |
|---|---|
| L1 | Tool wall/internal latency distributions by role |
| L2 | Inter-tool gap ms |
| L3 | Human wait: gaps before `user_message` |
| L4 | Generation proxy from timing_events (per TraceLab defs) |

### 2.7 Context-engine opportunity scores (derived)

Per session, score hypothetical engine interventions 0–1:

| ID | Opportunity | Heuristic |
|---|---|---|
| O1 | `workspace_map_would_help` | Long orient (many ls/find/Glob) before first Grep/Read |
| O2 | `semantic_locate_would_help` | Many grep/rg with low follow-up mutate rate |
| O3 | `focus_would_help` | Repeated near-duplicate Reads |
| O4 | `pin_hot_files_would_help` | High re-read signature rate mid-session |
| O5 | `deterministic_symbol_index` | Shell locate heavy + later mutate clustered |
| O6 | `result_budgeting` | Frequent huge `result_chars` with weak follow-through |

These feed the “Ideas for a Better Context Engine” list.

---

## 3. Session selection (≈100 + ≈100)

### 3.1 Frontier model allowlists

**Claude (prefer in order):**
1. `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-opus-4-5*`, `claude-opus-4-1*`
2. Then fill with `claude-sonnet-4-6`, `claude-sonnet-5`, `claude-sonnet-4-5*`, `claude-fable-5`
3. **Exclude** as primary: `claude-haiku*`, `minimax/*`, `glm-*` unless needed to fill quota (should not be needed)

**Codex (prefer in order):**
1. `gpt-5.5`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.4`, `gpt-5.3-codex`, `gpt-5.2-codex`, `gpt-5-codex`, `gpt-5.1-codex*`
2. Then other `gpt-5*` 
3. **Deprioritize** `codex-auto-review`, `*-mini`, `*-spark` unless needed for diversity of long coding sessions

**Cursor:** not in corpus → `cursor_sessions = 0` with note.

### 3.2 Quality filters (must pass)

A session is eligible if:

1. `primary_model` ∈ allowlist  
2. `rounds >= 30`  
3. `tool_calls >= 40`  
4. At least **15** `locate+read` role calls **or** ≥10 shell-retrieval exes (`grep|rg|find|ls|cat|head`)  
5. At least **1** `mutate` tool (real coding work, not chat-only)  
6. Not pathological outliers alone: exclude `rounds > 2000` from the *default* sample (keep a separate `appendix_extreme` list of up to 5/provider)

### 3.3 Ranking score (higher = better)

```
score =
  3.0 * log1p(locate + read) +
  2.0 * log1p(mutate) +
  1.5 * log1p(verify_proxy) +
  1.0 * log1p(rounds) +
  1.0 * frontier_rank_bonus +
  0.5 * unique_tool_name_count -
  2.0 * (1 if rounds > 1500 else 0)
```

Select top **100 per provider**. Tie-break: more recent `max(timing_events.timestamp)`, then more `mutate`.

### 3.4 Stratification (soft quotas inside each 100)

| Stratum | Target |
|---|---|
| Opus / GPT-5.5–5.6 heavy | ≥60 |
| Long sessions (p90+ rounds within eligible) | ≥25 |
| Search-heavy (locate share ≥35%) | ≥25 |
| Edit-heavy (mutate share ≥20%) | ≥20 |
| Multi-turn (≥5 user_messages) | ≥30 |

If strata conflict, **frontier + score** win; document shortfalls.

### 3.5 Selection artifact

Write `research/tracelab/processed/selection/selected_sessions.json` with for each session:

- ids, provider, model, score, stratum tags  
- **why_selected** (human-readable bullets from metrics)  
- reject log for near-misses (optional top 50)

---

## 4. Output schema (per session JSON)

File: `research/tracelab/processed/sessions/<provider>/<session_id>.json`

```json
{
  "schema_version": "1.0.0",
  "dataset": {
    "name": "tracelab-syfi-coding-trace",
    "release": "v0.0.2",
    "db_sha256": "a7bab286bc640844560850965ccf47975cf66407154132abaab90f27ec9be744"
  },
  "session": {
    "session_id": "string",
    "provider": "claude|codex",
    "project": "string|null",
    "user": "string",
    "primary_model": "string",
    "models_seen": ["string"],
    "frontier_tier": "string",
    "why_selected": ["string"],
    "selection_score": 0.0
  },
  "overview": {
    "rounds": 0,
    "tool_calls": 0,
    "user_turns": 0,
    "duration_ms": 0,
    "total_input_tokens": 0,
    "total_append_tokens": 0,
    "total_output_tokens": 0,
    "mean_prefix_hit_ratio": 0.0,
    "first_mutate_round_index": 0,
    "actions_before_first_mutate": 0
  },
  "tool_timeline": [
    {
      "seq": 0,
      "round_pk": 0,
      "round_index": 0,
      "tool_index": 0,
      "tool_name": "string",
      "role": "locate|read|mutate|exec_generic|verify|plan|delegate|web|wait|other",
      "primary_executable": "string|null",
      "executables": ["string"],
      "command_skeleton": "string|null",
      "input_chars": 0,
      "result_chars": 0,
      "is_error": false,
      "latency_ms": 0,
      "signature": "string",
      "intent_proxy": "orient|search|deep_read|edit|test|plan|other|unknown",
      "notes": "string|null"
    }
  ],
  "retrieval_timeline": {
    "first_retrieval": {},
    "bootstrap": {},
    "phases": [
      {
        "name": "orient|search|read|edit|verify|repair|wind_down|other",
        "start_seq": 0,
        "end_seq": 0,
        "role_share": {},
        "append_tokens": 0
      }
    ],
    "stop_collecting_seq": 0
  },
  "files_opened_proxy": {
    "availability": "proxy_only",
    "read_events": [
      {
        "seq": 0,
        "input_chars": 0,
        "result_chars": 0,
        "signature": "string",
        "repeat_of_seq": null
      }
    ],
    "unique_read_signatures": 0,
    "repeat_read_rate": 0.0
  },
  "search_queries_proxy": {
    "availability": "proxy_only",
    "events": [
      {
        "seq": 0,
        "channel": "Grep|Glob|shell_grep|shell_rg|shell_find|other",
        "command_skeleton": "string|null",
        "input_chars": 0,
        "result_chars": 0,
        "followed_by_mutate_within": null
      }
    ]
  },
  "repeated_retrieval": {
    "duplicate_signatures": [],
    "loops": []
  },
  "token_waste": {
    "duplicate_signature_append_proxy": 0,
    "large_unused_results": [],
    "low_cache_rounds": [],
    "notes": []
  },
  "missed_context_hypotheses": [
    {
      "seq": 0,
      "hypothesis": "string",
      "evidence": ["string"],
      "confidence": "low|medium|high",
      "label": "hypothesis"
    }
  ],
  "context_growth": {
    "per_round": [
      {
        "round_index": 0,
        "input_tokens_total": 0,
        "prefix_tokens": 0,
        "newly_append_tokens": 0,
        "output_tokens": 0,
        "tool_result_chars": 0,
        "user_message_chars": 0
      }
    ]
  },
  "opportunities": {
    "O1_workspace_map": 0.0,
    "O2_semantic_locate": 0.0,
    "O3_focus": 0.0,
    "O4_pin_hot_files": 0.0,
    "O5_deterministic_index": 0.0,
    "O6_result_budgeting": 0.0,
    "ideas": [
      {
        "observed_behavior": "string",
        "why_inefficient": "string",
        "engine_improvement": "string",
        "expected_benefits": ["token_savings", "fewer_tool_calls", "lower_latency"],
        "confidence": "low|medium|high",
        "evidence_seqs": [0]
      }
    ]
  },
  "confidence": {
    "structural": "high",
    "semantic": "none",
    "caveats": ["sanitized_inputs", "no_paths", "no_message_text"]
  }
}
```

**Rules**
- No free-form session essays in Phase 4 — only structured fields.  
- Anything inferred beyond observables must set `"label": "hypothesis"` and a confidence.  
- Unavailable semantics → `availability: "unavailable_due_to_sanitization"`.

Cross-session outputs:

- `processed/cross/tool_transition_matrix.json`  
- `processed/cross/role_trigrams.json`  
- `processed/cross/metric_distributions.parquet`  
- `processed/cross/ideas_for_better_context_engine.json`  
- `processed/cross/provider_comparison.json`

---

## 5. Pipeline design (automation, resumable)

```
research/tracelab/
  raw/                          # immutable downloads
    syfi_coding_trace.duckdb
    SOURCE.md                   # URL, sha256, date
  scratch/                      # probes (already started)
  processed/
    selection/
    sessions/claude|codex/
    cross/
    checkpoints/                # per-phase done flags
  scripts/
    01_verify_db.py
    02_select_sessions.py
    03_extract_session.py       # one session → JSON
    04_run_batch.py             # resumable map over selection
    05_cross_session.py
    06_render_report.py
  reports/
    FINAL_REPORT.md             # Phase 6 only
```

**Resumability:** `04_run_batch.py` skips sessions with existing valid JSON (`schema_version` present).  
**No notebooks required** for the main path; optional notebook only for ad-hoc plots.

**Phase gate:** Do not run 02–06 until this framework is approved.

---

## 6. Final report structure (Phase 6)

1. **Executive summary** — how frontier agents collect context; top 5 engine opportunities  
2. **Data & methods** — TraceLab v0.0.2, sanitization limits, 100+100 selection criteria, metric defs  
3. **How agents collect context** — tool repertoire, shell vs dedicated search, bootstrap patterns (with multi-session examples)  
4. **Retrieval evolution** — phase machines, stop-collecting points, Claude vs Codex  
5. **Token & context dynamics** — growth curves, append composition, cache behavior  
6. **Waste & failure modes** — duplicates, loops, unused large results, error retries  
7. **Deterministic vs LLM-needed retrieval** — classification table with evidence  
8. **Ideas for a Better Context Engine** — master list (observed → fix → benefit), ranked by frequency × impact  
9. **Mapping to our APIs** — `map` / `workspace` / `focus` (and related) opportunities  
10. **Limitations & threats to validity** — sanitization, no Cursor, proxy metrics  
11. **Appendix** — selection table, schema, extra figures, extreme sessions  

**Claim rule:** Every non-hypothesis claim cites ≥2 sessions (ids) or an aggregate with N.

---

## 7. Ideas-for-engine running list (always-on)

Throughout Phases 4–6, append to `ideas_for_better_context_engine.json`:

```json
{
  "id": "IDEA-001",
  "observed_behavior": "",
  "why_inefficient": "",
  "engine_improvement": "",
  "expected_benefits": [],
  "frequency": {"claude": 0, "codex": 0},
  "example_sessions": [],
  "priority": "P0|P1|P2"
}
```

Seed candidates (to validate, not assert yet):

1. Replace ls/find orientation cascades with one **workspace map**  
2. Replace repeated grep/rg thrash with **semantic + graph locate**  
3. Replace near-duplicate Reads with **focus / pinned hot files**  
4. Budget tool results (**truncate + cite pointers**) to cut append tokens  
5. Deterministic **symbol/path index** for exact-name lookups (no LLM round)  
6. Detect retrieval loops and force a **strategy switch** (widen → structure → ask user)

---

## 8. Success criteria for this research

- 200 session JSON files valid against schema  
- Cross-session stats for all metrics in §2 with Claude vs Codex splits  
- Report answers RQ groups 1.1–1.6 with evidence  
- ≥15 concrete engine ideas with frequency counts  
- Explicit honesty about sanitization limits — no fake path/query claims  

---

## 9. Approval checklist

Please confirm or adjust:

1. **Sample size:** 100 Claude + 100 Codex (no Cursor)  
2. **Frontier-first selection** + score in §3  
3. **Structural-only analysis** with proxy fields for files/queries  
4. **Schema + report outline** in §§4–6  
5. Proceed to Phase 2 (documented schema dive is partly done) → Phase 3 selection scripts  

**STOP here until approved.** No batch extraction / full analysis until you sign off.
