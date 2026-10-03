# Scubiee search tool: what inputs and outputs it should have

Evidence from 86 of our harness coding sessions, 200 TraceLab sessions (743,819 tool calls) and 5,851 SWE-chat sessions.

Analysis script: `scripts/claude_sdk_harness/study_sessions.py`. Raw numbers: `research/session_study.json`.

Evidence tags:
- **[OBS]** measured directly in this data
- **[STR]** several sources agree
- **[WEAK]** small sample
- **[HYP]** design bet that still needs a test

---

## 1. The short answer

**Why map gets called only once per run:**
- One map answers the one question it can answer: "where is the code for X". In every run where the edited file could be checked, map ranked it first (9 of 9).
- Every follow-up question the agent has after that is a different kind of question:
  - who calls this
  - who imports this
  - where is this other symbol defined
  - which of these exact names exist
- Map can't answer those, so the agent switches to Grep. Only 3 of 53 greps run after a map searched for a symbol map had already returned. The other 50 were new questions. **[OBS]**
- Our own rule told it "one map is enough". **[OBS]**
- The 2-calls-per-session median is inflated: 24 of the 81 map calls in the harness were failed first calls ("Server disconnected") that the agent retried. **[OBS]**

**What to add**, in priority order:
1. Split the input into `query` (meaning) and `keywords` (exact names).
2. Add a `mode` for the relation questions agents currently answer with grep: `definition`, `usages`, `importers`, `related`.
3. Control the output: `detail` (locations, snippets or code bodies), `budget_chars`, `scope` (code, tests, docs) and code-first ordering.
4. Return session-aware results: mark or skip what this session already has, and suggest alternatives when nothing matches.
5. Allow several questions in one call (`queries: [...]`).

Keep the tool count at one, and make every option optional: `search(query="...")` alone must still work well.

---

## 2. Data studied

| Source | What it has | Size | Limits |
|---|---|---|---|
| Our harness sessions | every tool call with its inputs (grep pattern, map query, Read offset/limit); result sizes and map response bodies for the instrumented ones | 86 sessions: 50 fully instrumented, 46 with Scubiee | one repo, a few task types, Claude Sonnet only |
| TraceLab v0.0.2 | tool name, executable, command shape, input/result sizes, errors | 743,819 calls, 200 sessions (Claude + Codex) | sanitized: no arguments or paths, so search intent can't be read directly |
| SWE-chat | per-session files touched, research vs action counts, position of first write, tokens, agent | 5,851 sessions (4,852 Claude Code) | aggregates only; the success field couldn't be used |

The intent analysis (what agents search for) comes from our harness, because it is the only source with real arguments. TraceLab and SWE-chat check whether the same patterns hold at scale.

---

## 3. Findings

### F1. Agents already write "query + a set of keywords". They just put it all into grep alternation. [STR]
- **51% of our 402 greps are keyword sets** (`a|b|c`): a median of 3 alternatives and 4 identifiers per pattern, up to 11 alternatives.
- Examples: `token_meter|compare_queries|QueryCompare|ArmResult|tokens_saved`, `porcelain|dirty|strip\(\)|git_dirty`.
- Map queries look the same: a **median of 21 words, almost all identifiers**, for example "tokens saved retrieval benchmark grep baseline comparison summary". That's a keyword list stuffed into one semantic sentence, so the embedding has to treat a long list of names as if it were a meaning.
- At scale, TraceLab has **15,183 shell calls that run more than one grep in a single command**.

**Implication:** separate the two signals.
- `query` is a short statement of intent.
- `keywords` is a list of exact names that must count heavily in ranking.

This is your query + comma-separated keywords idea, and it matches how agents already search.

### F2. After map, agents ask relation questions, not "where" again. [OBS]

| Grep intent | All greps | After a map |
|---|---:|---:|
| keyword set | 50.7% | 120 |
| definition (`def X`, `class X`) | 16.2% | 32 |
| single identifier | 15.7% | 24 |
| call sites (`X\(`) | 7.5% | 18 |
| literal / regex | 7.5% | 1 |
| importers (`from … import X`) | 2.5% | 6 |

- After a map, the greps are about **how the found code connects to the rest**: who calls `compare_queries(`, who imports `token_meter`, where `git_dirty_files` is used, where `FreshnessReport` is defined.
- Only 3 of 53 post-map greps re-searched a symbol map had returned.
- Example: in the `dirty_files_cap` with-Scubiee run, after one map the agent ran 6 greps (`git_dirty_files\(`, `dirty_files|dirty\[:`, …), all of them looking for call sites.

**Implication:** a `mode` for relations would let these follow-ups go through Scubiee in 1 call instead of chains of 2–10 greps (median chain 2, p90 4, max 10).

### F3. A lot of search is wasted on empty or repeated results. [OBS]
- 21.5% of greps returned nothing or almost nothing.
- 44% of globs returned "No files found".
- 85 grep patterns were exact repeats within the same session.
- TraceLab: a median of **110 duplicate call signatures and 65 duplicate read signatures per session**, and 6.5% of shell greps error out.

**Implication:** when nothing matches, the tool should return something useful instead of an empty list: close identifiers that do exist, likely files, or a broader query. It should also notice a repeat and say "already returned".

### F4. Reading is the biggest token cost, and most of it is whole files. [STR]
- In our sessions, **59% of Reads were whole files**: median 8,837 chars, against 2,490 for ranged reads (about 3.5× larger).
- Reads of files the agent **never edited** have a median of 11,184 chars (for example `harness_task.py` at 16,734 and `conftest.py` at 12,553).
- The same file was re-read a median of once per session, with a maximum of 25 times.
- TraceLab: `cat`/`sed`/`head` reads are 17.9% of all calls (median 3,085 chars), and there are **19 reads of 10k+ chars per session** (median).
- In TraceLab, **108,369 shell calls pipe into `head`/`sed`/`tail`**: agents cut the output down themselves because the tool won't.

**Implication:**
- Search should be able to return the code body of the top hits within a character budget, so the agent doesn't follow up with a whole-file Read.
- It should never return more than `budget_chars`.

### F5. Map's ranking is fine; what it returns alongside the right file is not. [OBS, n is small]
- When the file the agent later edited appeared in the cards, it was **rank 1 every time (9 of 9)**.
- But a median of 8 cards came back, and **50–60% of them were tests, docs or scripts**.
- The agent read the top card next in 21 of 33 responses and used the line range in 29 of 33.
- The two biggest wasted reads in our v2/v3 runs were files map listed but that weren't part of the fix.

**Implication:** keep the ranking. Change the composition:
- code first
- tests and docs collapsed to one line each (`related_tests: [...]`)
- a `scope` filter

### F6. Real tasks touch several files across directories. [STR]
- In SWE-chat, the **median session touches 3 files**: 68% touch 2 or more, and 37% touch 5 or more.
- Of the multi-file sessions, **only 15% stay inside one directory**.
- The first write comes at a median of tool call 7.
- Research is 31% of tool calls (median).

**Implication:**
- One query returning one best file is not enough for most real tasks.
- Results should be groupable by file.
- A `related` mode should return the cards connected to a result: callers, callees, sibling tests, the same symbol used elsewhere.

### F7. Agents barely use the parameters map has now. [OBS]
- Inputs passed across 81 map calls: `query` 81 times, `project_id` 24, `root` 15, `k` 4 (always 12).
- No one tuned anything. Options need good defaults, and the instructions have to show when each one is worth using.

---

## 4. Proposed tool surface

One tool (call it `search`, or keep the name `map`). Every argument is optional except `query`.

### 4.1 Inputs

| Parameter | Type / default | What it does | Evidence | Priority |
|---|---|---|---|---|
| `query` | str | Short intent in plain words ("where the savings summary is computed"). Drives the semantic signal. | F1: today's 21-word queries mix intent and names | required |
| `keywords` | list[str], default `[]` | Exact identifiers or literals that must count in ranking (`["compare_queries","ArmResult","cache_read"]`). Matching is case-sensitive on identifiers. | F1: 51% of greps are keyword sets; agents already think this way | **P1** |
| `keyword_weight` | float 0–1, default 0.6 | Balance between keyword and semantic signals. 0 = pure semantic, 1 = keyword hits first and semantic only breaks ties. One number, not a matrix. | F1; your request to weight keywords higher | **P1** |
| `mode` | `locate` (default) \| `definition` \| `usages` \| `importers` \| `related` | `locate` = where is X. `definition` = where are these keywords defined. `usages` = where they're called or referenced. `importers` = which files import this module/symbol. `related` = callers, callees and tests around one result. | F2: 26% of greps are definition/call-site/importer lookups, and they dominate after map | **P1** |
| `scope` | `code` (default) \| `tests` \| `docs` \| `all` | Filters what kinds of files come back. | F5: 50–60% of cards are non-code | **P2** |
| `paths` | list[glob], default all | Limits results to a subtree (`["packages/pipeline/**"]`). | F3: 44% of globs empty; agents use Glob to narrow scope by hand | P3 |
| `queries` | list of {query, keywords, mode} | Several questions in one call, answered in one response. | F1: 15k multi-grep shell calls; serial calls cost a model round-trip each | P3 |
| `k` | int, default 8 | Maximum number of results. | F7: never tuned, keep the default | keep |

### 4.2 Outputs

| Parameter | Type / default | What it does | Evidence | Priority |
|---|---|---|---|---|
| `detail` | `locations` \| `snippets` (default) \| `spans` | `locations` = file:line + symbol only. `snippets` = plus about 3 lines around the hit, with matched keywords marked. `spans` = the full code body of the top results, so no follow-up Read is needed. | F4: whole-file reads are the biggest cost | **P1** |
| `budget_chars` | int, default 4000 | Hard cap on response size. The tool trims bodies to fit and reports what it left out. | F4: 108k shell calls piped to head/sed; agents already want a cap | **P1** |
| `group_by` | `none` (default) \| `file` | Groups hits by file, so a multi-file change reads as a list of files with spans under each. | F6: median 3 files touched, 85% across directories | P2 |
| `exclude_seen` | bool, default true | Marks or skips spans this session already received, and says so ("already returned at turn 3"). | F3: 85 repeated patterns; TraceLab median 65 duplicate reads per session | P2 |

**What each result card contains.** Keep it slim (today's cards are about 370 chars, many fields redundant):
- `loc` (`path:start-end`)
- `symbol` and `kind` (function, class, method)
- `why`: a short snippet, with the matched keywords marked
- `match`: `{"semantic": 0.71, "keywords": ["compare_queries"]}`, so the agent can see whether the result is a keyword hit, a semantic guess or both

Drop `file` (it's already in `loc`), `rank` (it's the position), `source` and `role`. Keep telemetry behind a debug flag.

**What the response contains at the top level:**
- `confidence`: `high` \| `medium` \| `low`, plus a one-line reason. The rules can tell the agent to stop on high and to refine or switch tools on low.
- `related_tests`: one line per test (`tests/test_freshness.py::test_git_dirty_keeps_the_first_filename_intact`). Test names are useful pointers, but they don't need full cards.
- `no_match` (only when empty): close identifiers that do exist, likely files, and a broader query to try. This replaces the 21.5% empty greps and 44% empty globs (F3).
- `next`: only actions the agent can actually take with the tools it has. Today's `next` suggests `pack_context` even when it isn't exposed.

### 4.3 Example calls

```text
# Conceptual "where"
search(query="where the token savings summary is computed",
       keywords=["tokens_saved","compare_queries"], detail="spans", budget_chars=4000)

# Follow-up that used to be 3–6 greps
search(query="callers of the dirty files helper",
       keywords=["git_dirty_files"], mode="usages", detail="snippets")

# Multi-file change
search(query="how cache tokens are represented across the code",
       keywords=["cache_read","cache_creation"], group_by="file", scope="code")

# Two questions, one round-trip
search(queries=[{"query":"definition","keywords":["ArmResult"],"mode":"definition"},
                {"query":"who imports token_meter","keywords":["token_meter"],"mode":"importers"}])
```

---

## 5. What not to add

Every option is another way for the model to misuse the tool. These would cost more than they give:
- **Free regex inside search.** Grep already does this well. Exact-pattern searches belong in Grep (the "literal / regex" intent was only 7.5%).
- **More than one weighting knob.** No separate bm25/dense/graph weights. `keyword_weight` covers the need the agents showed.
- **Graph depth or hop controls.** `related` with a fixed depth of 1 is enough. Deeper graphs return large, low-value payloads.
- **More than five modes.** `locate`, `definition`, `usages`, `importers` and `related` cover 92.5% of the grep intents (everything except literal/regex).
- **A separate tool per mode.** Today's eight-tool surface wasn't used: agents called the subset they were given and ignored the rest.

---

## 6. How to build it without touching core Scubiee

The engine already has HTTP routes for most of this. `server.py` exposes `/v1/search`, `/v1/grep_ident`, `/v1/follow_imports`, `/v1/graph_neighbors`, `/v1/outline` and `/v1/read_span`. I have only confirmed that these routes exist; I haven't verified their payloads against these needs.

| Option | Built where | How |
|---|---|---|
| `query` + `keywords` + `keyword_weight` | bridge | Call `/v1/search` with a wider `top_k` (about 3×). Score keyword hits in each hit's snippet and symbol. Mix the two as `w·keyword + (1−w)·semantic`. Return the top `k`. Limit: a keyword-only match missing from the semantic top-3k won't surface; add a `/v1/grep_ident` pass for keywords to cover it. |
| `mode=definition` / `usages` | bridge | `/v1/grep_ident` per keyword, split into definition lines and reference lines. |
| `mode=importers` | bridge | `/v1/follow_imports` or `/v1/grep_ident` on the module name. |
| `mode=related` | bridge | `/v1/graph_neighbors` on the top result's file plus its test file. |
| `detail=spans`, `budget_chars` | bridge | `/v1/read_span` for the top hits, trimmed to the budget. |
| `scope`, `paths`, code-first, `related_tests` | bridge | Filter and reorder the hits by path. |
| `exclude_seen` | bridge | Keep a per-session set of spans already returned. |
| True weighted fusion inside the index | core (later) | Only if the bridge re-rank measurably misses keyword-relevant files. |

The mini bridge (`scripts/claude_sdk_harness/mini_mcp_bridge.py`) is the natural place to prototype, since it already sits in front of the engine and is fully ours.

---

## 7. Rule changes that go with it

The tool alone won't change behavior; the rules taught the agent to call map once.
- Replace "one map is enough" with: **"For each new question (where is it, who calls it, who imports it, where is it defined), use `search` with the matching `mode` instead of chains of greps."**
- "Put exact names in `keywords`, and a short intent in `query`."
- "Use `detail="spans"` when you plan to edit the result; use `locations` when you only need to know where."
- Keep from v3: don't read files you won't edit; stop once the span answers the question.

---

## 8. How to validate

Run an A/B on the three dev tasks (`cache_aware_savings`, `dirty_files_cap`, `health_reason_flag`), n≥3 each, with no Bash and no self-testing:

| Arm | Tools | Rule |
|---|---|---|
| without | native only | none |
| v3 | mini bridge `map` | v3 |
| rich | mini bridge `search` with the options above | v3 + section 7 |

Metrics:
- tokens and model calls
- grep count after the first search
- result chars per tool
- whole-file reads
- reads of files never edited
- which options were used and how often
- oracle pass rate

Success means the rich arm cuts post-search greps and whole-file reads while matching pass rate, and costs less than v3 on the median. If agents ignore the new options, the fault is in the rule and examples, not the tool. That is the F7 risk.

---

## 9. Limits of this study

- The intent analysis comes from our own sessions: one repo, few task types, Claude Sonnet only. TraceLab and SWE-chat confirm the scale of the patterns (search-heavy sessions, multi-file work, oversized reads, self-truncation), but they can't confirm intents, because their arguments are sanitized or missing.
- "Edited file ranked first, 9 of 9" is a small sample.
- Grep intent comes from regex shape heuristics (`def`, `\(`, `import`, `|`). Individual patterns can be misclassified; the overall split is robust to that.
- The bridge-side keyword re-rank (section 6) is a design bet **[HYP]** until tested against true fusion.
