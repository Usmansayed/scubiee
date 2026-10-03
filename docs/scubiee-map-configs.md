# Scubiee `map` configs, designed from what agents actually ask for

> **Shipped surface (Map V3 — current product).** The design study below explored a
> five-config set (`find` / `refs` / `open` / `around` / `outline`). What actually
> ships in `pipeline.map_v3_server` is the distilled **four-config** surface:
>
> | Shipped config | Answers | Folds in the study's |
> |---|---|---|
> | `find` | "Where is the code for this?" (ranked locations + top result's code inline) | `find` |
> | `focus` | "Show me this name's code **and** its wiring" (full body + callers/callees + sibling names, one unit) | `open` + `around` + `refs` relations |
> | `related` | "Given a chunk I have, what else relates?" (related bodies in one call) | `open` (multi) + `around` |
> | `graph` | "Orient me" (files → symbol names + call edges, no bodies) | `outline` + `around`, abstracted |
>
> Plus `gate` and `status` for health. There is **one** `map` tool; pick one config,
> act on the first good answer, stop. The old pack/expand/collect tool surface and the
> `scubiee pack|expand` CLI are retired (archived under `archive/old-mcp-map/`); the
> CLI equivalent is `scubiee map --config find|focus|related|graph`. The research and
> rationale below are kept as the design record that led here.

This doc goes beyond counting tool calls. For each retrieval call it asks what the agent was trying to learn, which part of the result it used, and what it did next. The 10 recurring needs that come out of that drive a set of 5 map configs.

**Sources:**

| Source | What it has | Scale |
|---|---|---|
| Our harness sessions | real arguments and map response bodies | 50 fully instrumented of 86 total |
| TraceLab raw DB | tool calls in session order | 743,819 calls across 7,244 sessions (the earlier "200" was only the processed subset) |
| SWE-chat | the first user prompt of each session | 4,321 non-empty first prompts |

**Scripts:** `scripts/claude_sdk_harness/study_sessions.py` and `study_requirements.py`. Raw numbers are in `research/session_study.json` and `research/requirements_study.json`.

**Evidence tags:** **[OBS]** measured here · **[STR]** two or more sources agree · **[WEAK]** small sample or heuristic · **[HYP]** design bet to be tested.

---

## 1. What the agent needs (requirement catalog)

| # | Need | Evidence | What the agent uses from the result | What it costs today |
|---|---|---|---|---|
| R1 | **Locate code by concept**: "where does X happen?", with no names | 30.8% of SWE-chat first prompts have no file, symbol or error. Before its first edit the agent spends a median of 8 retrieval calls in our runs and 16 in TraceLab, pulling in a median of 63k chars (TraceLab). **[STR]** | File, symbol, line range | The first exploration phase of a session (before the first edit) is the biggest retrieval cost |
| R2 | **See the matching lines, not a file list** | Grep was called in content mode 115 times and with `-n` (line numbers) 136 times, against 76 file-list calls. `-C` (context lines) 22 times. **[OBS]** | The matching line, its line number, a couple of lines around it | A file-list result forces a second call to see the lines |
| R3 | **Read the enclosing code, not the matched chunk** | After a map, Reads were a median of 60 lines against a 24-line card span (2.5×). 97% were wider than the card, and only 53% fully contained it: the agent read mostly *after* the card (median +31 lines, p75 +115). **[OBS]** | The whole function or class the hit is in, plus a bit of what follows | Map's chunk boundary is the wrong unit. The agent guesses a range, often re-reads, or reads the whole file (59% of reads were whole files) |
| R4 | **Find every occurrence of known names** (definitions, call sites, imports) | 51% of our greps were followed by another grep; 35.7% in TraceLab. 29% of greps reused names that had appeared in an earlier map result (56 of 191). When the first prompt names a symbol, the research share of the session doubles (median 0.62 vs about 0.30). **[STR]** | A complete list of occurrences, grouped by file, with one line each | Chains of 2–10 greps; 21.5% of them come back empty |
| R5 | **Read several related pieces in a row** | In TraceLab, 52% of reads are followed by another read. SWE-chat sessions touch a median of 3 files, and 85% of multi-file sessions span more than one directory. **[STR]** | Several function bodies across files | One round-trip per file. Each extra model call re-reads about 35–40k tokens of context (our runs) |
| R6 | **Get an overview of the layout** | List commands (`ls`, `find`, `tree`) are 10.4% of TraceLab retrieval, and 28% of them are followed by another listing. Reads in the first 20% of a session are larger (median 4.5k vs 3.1k chars). **[STR]** | Which files exist, and what each one contains | Repeated `ls`/`find`, then large reads early in the session just to understand the layout |
| R7 | **Recover when a search finds nothing** | 44% of failed TraceLab greps are followed straight away by another grep. 21.5% of our greps and 44% of our globs came back empty. **[STR]** | Something to try next | Blind retries |
| R8 | **Check something before editing**: does X exist, is it used elsewhere | 12 greps were followed directly by an Edit. Retrieval bursts after the first edit are tiny (median 1 call ours, 3 TraceLab). **[OBS]** | A count, and where the occurrences are | Usually cheap, but a broad pattern returns huge output |
| R9 | **Keep the output bounded** | 108,369 TraceLab shell calls pipe into `head`/`sed`/`tail`. **[OBS]** | The first N relevant results | Without that trimming, outputs reach megabytes |
| R10 | **Don't receive the same thing twice** | TraceLab: a median of 65 duplicate read signatures per session. Our runs: a median of 1 re-read of the same file per session (max 25). **[STR]** | Only what's new | The repeat is billed again on every later turn |

**What the agent knows at the start** (SWE-chat first prompts, n=4,321):

| Starting point | Share |
|---|---:|
| Conceptual only, no names | 30.8% |
| Plan or spec to implement (usually lists several files) | 17.9% |
| Names a source file | 13.4% |
| Names a symbol or command (in backticks) | 13.2% |
| Describes an error with no location | 2.3% |
| Other: only workspace paths or URLs | ~22% |

So sessions start almost evenly split between "no idea where" (R1) and "I have names or files" (R4, R5). Both need first-class support. **[WEAK]**: these categories come from regex rules, and "names a file" was hand-corrected for system paths and URLs.

**One more fact shapes the design:** every successful map response (33 of 33) was followed by a Read within 3 calls. **Map has never been enough on its own.** The agent always needs code next, so the configs should hand over the right code in the same call whenever they're confident.

---

## 2. The configs

There's one `map` tool with a `config` field. **There are at most five configs; that's a hard limit (see 2.6).** Each config has at most three arguments that matter.

| config | Answers | Needs covered | Replaces |
|---|---|---|---|
| `find` | "Where is the code for this?" | R1, R2, R3, R7, R9 | today's map, keyword greps, the first Read |
| `refs` | "Where else are these names?" | R4, R8, R9 | grep chains for `def X`, `X(`, `import X` |
| `open` | "Show me these pieces of code" | R3, R5, R10 | read chains, whole-file reads, guessed ranges |
| `around` | "What's connected to this?" | R5 (callers, callees, tests) | grep + read hops between files |
| `outline` | "What's in this directory or file?" | R6 | `ls`/`find`/`tree`, orientation reads |

Exact literal or regex search stays with native Grep (3.2% of our calls), and change history stays with `git`. Neither is worth putting into map.

### 2.1 `find` — locate by concept

```json
{"config": "find",
 "query": "where the token savings summary is computed",
 "keywords": ["tokens_saved", "compare_queries"]}
```

| Argument | Default | Why |
|---|---|---|
| `query` | required | A short intent. Today's queries average 21 words of identifiers, which mixes intent and names (F1 in the earlier study). |
| `keywords` | `[]` | Exact names that get extra weight in ranking. Matching is case-insensitive, since agents used `-i` 43 times. 51% of greps were already keyword sets. |
| `scope` | `code` | `code` · `tests` · `docs` · `all`. About half of today's map cards are tests, docs or scripts. |

Response:

```text
confidence: high — "keywords tokens_saved, compare_queries match in packages/pipeline/token_meter.py"
1. packages/pipeline/token_meter.py:142-198  compare_queries()  [keyword+semantic]
   148:     tokens_saved = baseline.tokens - arm.tokens
   151:     pct_saved = ...
   ── body of compare_queries() (enclosing function, lines 142-198) ──
   <code, within budget>
2. packages/pipeline/token_meter.py:60-88   ArmResult           [semantic]
   61: class ArmResult:
3. packages/pipeline/locate.py:701-730      _savings_payload()  [semantic]
related tests: tests/test_token_meter.py::test_compare_queries_pct
```

- **Matched lines with line numbers** for every hit (R2). This is the content of `grep -n -C1`, but ranked.
- **When confidence is high, the top hit's enclosing function or class is included inline** (R3), capped at about 2,500 chars, the median ranged read. This removes the Read that followed every single map call. When confidence is medium or low, only lines are returned, so a wrong guess doesn't cost a code body.
- **Tests and docs are one line each** under `related tests`.
- **When nothing matches** (R7), it returns close identifiers that do exist, likely file names (which also replaces a fuzzy Glob), and a broader query to try. It never returns a bare empty list.
- **Budget:** 4,000 chars by default (R9). Anything trimmed is reported as `+N more hits`.

### 2.2 `refs` — every occurrence of known names

```json
{"config": "refs", "names": ["git_dirty_files"], "kind": "uses"}
```

| Argument | Default | Why |
|---|---|---|
| `names` | required | One or more identifiers, which covers the alternation-style greps. |
| `kind` | `all` | `def` · `uses` · `imports` · `all`. Covers definition (16.2%), call-site (7.5%) and importer (2.5%) greps. |
| `scope` | `code` | Same as `find`. |

Response:

```text
git_dirty_files — 1 definition, 4 uses, 2 imports (7 total)
def   packages/pipeline/freshness.py:105        def git_dirty_files(root: Path) -> list[str]:
uses  packages/pipeline/sync_loop.py:212        dirty = git_dirty_files(root)
      packages/pipeline/freshness.py:188        files = git_dirty_files(repo)[:limit]
      packages/pipeline/live_reindex.py:41      for p in git_dirty_files(root):
      tests/test_freshness.py:130               assert git_dirty_files(tmp_path)[0] == "a.py"
imports packages/pipeline/sync_loop.py:9        from pipeline.freshness import git_dirty_files
```

- **A complete count comes first** (R8): "is this used elsewhere?" is answered in one line.
- Results are grouped by kind, one line per occurrence, with line numbers. The agent asked for the list, so this config doesn't attach code bodies.
- It is **complete, not ranked**: the agent asks for every occurrence before a rename or signature change. If the list is over budget, it says `showing 40 of 112` and gives the file distribution.
- This replaces the post-map grep chains (51% of greps were followed by another grep).

### 2.3 `open` — the right code for one or more targets

```json
{"config": "open",
 "targets": ["token_meter.py::compare_queries", "freshness.py:105", "sync_loop.py::SyncLoop.mark_dirty"]}
```

| Argument | Default | Why |
|---|---|---|
| `targets` | required | `file::symbol`, `path:line` or a file path, in plain text. No result IDs or handles: agents ignored the handle-based session tools in an earlier test, and handles can't survive a bridge restart. |
| `margin` | 10 lines | Lines of context around each symbol. Agents read a median of 31 lines past the card, so some margin is needed. |
| `budget_chars` | 6,000 | Across all targets, split fairly between them. |

- Each target is expanded to its **enclosing symbol** (function or class), plus the margin (R3). A `path:line` target becomes the symbol that contains that line, which fixes the "map span was the wrong unit" problem.
- **Several targets in one call** (R5): this replaces read → read chains, which are 52% of what follows a read in TraceLab.
- Anything this session has already received is replaced by `(already shown, turn 4)`, unless the file changed since (R10).
- A whole file is never sent by default. A file path with no symbol returns that file's `outline`.
- Native `Read` still works for anything unusual. `open` exists because the agent can't know symbol boundaries and native Read can't batch.

### 2.4 `around` — what's connected to a piece of code

```json
{"config": "around", "target": "token_meter.py::compare_queries"}
```

| Argument | Default | Why |
|---|---|---|
| `target` | required | Plain-text target, same forms as `open`. |
| `want` | `callers,callees,tests` | Any of `callers` · `callees` · `tests` · `siblings` (same-file symbols). One hop only; no depth control. |

- Returns one line per neighbor (`loc` + signature). Bodies come from a follow-up `open` call, which can batch several of them.
- Covers the "found the main function, now what surrounds it" step that today takes a grep and a read per hop.
- Lowest priority of the five: `refs kind=uses` already answers "callers" for most needs.

### 2.5 `outline` — what's here

```json
{"config": "outline", "path": "packages/pipeline", "query": "freshness"}
```

| Argument | Default | Why |
|---|---|---|
| `path` | repo root | A directory or a file. |
| `query` | none | Optional filter on file and symbol names. This also covers "find the file named something like X" (44% of our globs found nothing). |
| `depth` | 1 | Directory levels. |

- **For a directory:** each file with its top-level symbols and a one-line docstring.
- **For a file:** its symbols with line ranges and signatures, and no bodies.
- Replaces `ls`/`find`/`tree` chains (28% of listings are followed by another listing) and the large reads early in a session.

### 2.6 The five-config limit

`map` never has more than five configs. Every extra config is one more choice the agent can get wrong, and one more line in the instructions. When a new need shows up, it goes into one of these places, in this order:

1. **A default that applies to every config**, so the agent doesn't have to choose anything (section 3).
2. **An argument on an existing config**, with a default that leaves behavior unchanged when it isn't passed.
3. **Native tools** (Grep, Read, git), if the need is exact-text, history or anything else outside code location.

Where the likely future needs would go:

| Possible future need | Goes into |
|---|---|
| Find a file by name | `outline` with `query`; also `find`'s recovery when nothing matches |
| Several questions in one call | `open` takes several targets; `refs` takes several names |
| Callers only | `refs kind=uses` |
| Type or interface implementations | `refs kind=def` with the interface name |
| Config, docs or test search | `scope` on `find` and `refs` |
| Recently changed code | native `git` |
| Exact regex | native Grep |

**If the A/B shows a config is rarely used, merge it rather than keep it.** The first candidate is `around`: it can become `refs kind=callers|callees|tests`, which brings the count down to four. Fewer configs is fine; more than five is not.

---

### 2.7 Prefer one complete answer over a lean one that forces a follow-up

Measured cost model (this study): **tokens ≈ context size × number of model
calls**, and the call count is the term that runs away. Every extra call
re-reads the whole transcript — about 35–40k tokens in our runs — and keeps
paying it on every later turn. Returning a few thousand extra characters costs
those characters once; forcing another call costs ~35k and compounds.

So every config is tuned to **finish the question in one call** rather than
return the minimum:
- `find` includes the top result's code on **high and medium** confidence, not
  high only. One possibly-unused body (a few k chars) is cheaper than the `open`
  call it saves. Only `low` holds back, where a wrong file would mislead.
- Budgets are generous (find 8k, open 10k, refs/around/outline 6k), sized to
  carry the enclosing function plus a neighbor, not trimmed so tight the agent
  re-asks.
- `open` takes several targets and `refs`/`around` take several names, so a
  multi-part question is one call.

This does **not** mean "return everything." Each config still caps at its budget,
drops to lines-only when unsure, and never repeats what the session already has.
The rule is: spend characters to save calls, not characters for their own sake.

## 3. Defaults that apply to every config

These need no decision from the agent:

| Default | Need | Rule |
|---|---|---|
| Line numbers on every line | R2 | Agents asked for `-n` on 136 of 191 greps |
| Budget always enforced | R9 | Per-config default; trimmed results reported as `+N more` |
| Already-seen marking | R10 | Per session; resets for a file when it changes on disk |
| Code before tests/docs | R1 | `scope=code` default; tests summarized in one line |
| No-match recovery | R7 | Close identifiers, file names, a broader query; never an empty list |
| Confidence + reason | R1, R3 | Decides whether `find` includes a body; tells the agent when to stop |
| `next` names only tools that exist | — | Today's `next` field suggests `pack_context` even when that tool isn't available |
| Slim result line | R9 | `loc`, `symbol`, match type (`keyword` / `semantic` / both), one line. Drop `file` (it's in `loc`), `rank`, `source`, `role` and telemetry |

---

## 4. What the agent's instructions become

```text
Scubiee map — pick the config by what you know:
- No idea where it is ............... map find  (query + any names you know as keywords)
- Know the names, need every place .. map refs  (names, kind=def|uses|imports)
- Need the code of specific places .. map open  (targets; batch several in one call)
- Need what calls/uses/tests it ..... map around
- Need what's in a directory/file ... map outline
Exact string or regex → Grep. History → git.
find usually includes the top function's code; don't Read it again.
For each NEW question, call map again with the right config instead of chaining greps.
```

That's 10 lines, and it replaces the current two-layer prompt.

---

## 5. Expected effect on a typical session

Take a typical locate → understand → edit task (median 3 files touched):

| Step | Today (observed) | With configs |
|---|---|---|
| Locate | map (+ a retry after the first-call failure) | `find` (includes the top body) |
| Read target | Read (always followed map, 33/33), often re-read | — |
| Find uses / defs | 2–10 greps (median chain 2, p90 4) | 1 `refs` |
| Read the other files | one Read per file (read → read 52%) | 1 `open` with several targets |
| Check before editing | grep | the count is already in the `refs` result |
| **Retrieval model calls** | **~8 median (ours), ~16 (TraceLab)** | **~3** |

Each model call saved means about 35–40k tokens of context not re-read (our measurement). So going from about 8 to 3 retrieval calls is roughly 175–200k tokens on a typical task in our setup. That is a **[HYP]** until it's tested.

---

## 6. What's deliberately left out

| Left out | Why |
|---|---|
| Regex inside map | Grep does it; only 3.2% of greps were literal or regex |
| More than one ranking knob | `keywords` presence is the weighting; no bm25/dense/graph weights |
| Graph depth | `around` is one hop; deeper graphs return large, low-value payloads |
| Git history | 1.4% of our retrieval calls, 6.2% in TraceLab; native `git` is fine |
| Result IDs / handles | Agents ignored the handle-based session tools; plain-text targets work from any source |
| A separate batch config | `open` takes several targets and `refs` takes several names, which is where batching was needed |

---

## 7. How to build it (without touching core Scubiee)

Everything here sits in front of the engine routes that already exist in `server.py`. I've confirmed these routes exist; I haven't checked their payloads against these needs.

| config | Engine routes | Bridge work |
|---|---|---|
| `find` | `/v1/search` (asking for about 3× `k`) | Keyword re-rank, matched-line extraction, enclosing-symbol expansion for the top hit, confidence, recovery when nothing matches |
| `refs` | `/v1/grep_ident` | Split matches into def / use / import, count, group, apply the budget |
| `open` | `/v1/outline` + `/v1/read_span` | Map each target to its enclosing symbol, apply the margin, split the budget, mark already-seen |
| `around` | `/v1/graph_neighbors` | One hop; one line per neighbor |
| `outline` | `/v1/outline` + a directory walk | Name filter, depth |

Prototype it in `scripts/claude_sdk_harness/mini_mcp_bridge.py`, which already proxies the engine and doesn't affect the shipped product.

**Build order:** `find`, `refs` and `open` first. They cover R1–R5 and R7–R10, which account for most of the volume. Then `outline`, then `around`.

---

## 8. How to validate

Run an A/B on the three dev tasks, n≥3 per arm, with no Bash and no self-testing:

| Arm | Tools |
|---|---|
| without | native tools only |
| v3 | today's map with the v3 rules |
| configs | the 5 configs with the section 4 instructions |

Measure:
- retrieval model calls before the first edit
- greps after the first map
- Reads after `find` (it should rarely need one)
- whole-file reads
- reads of files the agent never edited
- result chars
- total tokens
- oracle pass rate
- which configs were used

**Success:** the configs arm has the fewest retrieval calls and tokens at the same pass rate, and agents actually use `refs` and `open` rather than falling back to grep and Read. If they fall back, fix the instructions and examples before changing the tool.

---

## 9. Limits

- Our sessions are one repo, a few task types, and Claude Sonnet. TraceLab and SWE-chat confirm the patterns at scale (chains, read-after-read, overview listing, self-truncation), but they can't show arguments.
- The span comparison (R3) uses 96 Read/card pairs from our runs only.
- The starting-point split uses regex rules on first prompts and is approximate (**[WEAK]**).
- The call savings in section 5 are a projection (**[HYP]**) until the A/B runs.
