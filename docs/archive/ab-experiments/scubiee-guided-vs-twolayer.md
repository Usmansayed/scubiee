# GUIDED (current) vs the new two-layer POLICY artifact

Both are the map-only instruction the agent sees (tool surface is identical: `map` + `gate`/`status`).
- **GUIDED** = our current best-on-cost variant: a single ~ mid-size rule block.
- **POLICY (new)** = the research-informed artifact, split into two layers as required:
  **RULES** (persistent anchor, hard limit <200 tokens) + **INSTRUCTIONS** (operating manual, <1000).

Verified token counts (tiktoken `cl100k_base`):

| Artifact | tokens | limit | status |
|---|---:|---|---|
| GUIDED (single block) | ~250 | — | (no split; for reference) |
| **POLICY · RULES** | **112** | <200 | OK |
| **POLICY · INSTRUCTIONS** | **510** | <1000 | OK |

Source of truth: `scripts/claude_sdk_harness/policies.py` (GUIDED) and `two_layer.py` (RULES, INSTRUCTIONS).

---

## GUIDED (current — single block)

```
## Scubiee map — when to use it (map is the only Scubiee locate tool here)
A managed Scubiee context system is available, but the ONLY Scubiee locate tool exposed is `map`
(plus `gate`/`status`). Use your native tools (Read/Grep/Glob/Edit/Write/Bash) freely otherwise.
`map` is a semantic code locator: a short code-vocabulary query returns ranked cards with `file`,
`loc` (`path:start-end`), symbol, and why it matched. It searches by meaning, not literal string.
Follow this guidance (be strict about following it; you are NOT required to call map every task):
- Prefer `map` for semantic / "where does this happen" search.
- Use `map` when you don't know exactly what you're looking for; strongest at the start of an
  unfamiliar area.
- If unsure of a keyword/function/concept/location, consider `map` over speculative greps.
- After a `map`, read the `loc` spans directly; don't re-grep what map found; don't dump whole files.
- When you already know the exact file/symbol/path, use native tools; don't call map.
- Reach for `map` when broader context / multi-file relationships matter.
Examples: "where/how X" → map; "unknown keyword" → map; known `foo` in `bar.py` → just edit;
literal `"cache miss"` → grep; map returns `x.py:120-176` → read that span.
```

---

## POLICY — LAYER A: RULES  (persistent anchor · 112 tokens · <200 ✓)

> Short, non-negotiable behavioral contract. No examples, no rationale, no decision trees.

```
Scubiee is your semantic code retrieval layer. When you need to find code whose location
or name you do not already know, use Scubiee `map` for that discovery rather than blind
grep/glob sweeps. When you already know the exact file, symbol, path, or literal, go straight
to native tools. After map returns locations, read those spans directly — do not re-search
what map already found, and never repeat a search that already failed. Follow the Scubiee
instructions for how to choose.
```

## POLICY — LAYER B: INSTRUCTIONS  (operating manual · 510 tokens · <1000 ✓)

> The detailed decision boundaries, rationale, examples, and recovery guidance.

```
## Scubiee retrieval — operating manual

Objective: reach the next correct action with the least unnecessary exploration. Retrieve the
smallest context that removes your current uncertainty, not the most context. Extra retrieved
tokens degrade attention; a successful task with slightly more retrieval beats a cheap failure.

`map` = semantic code search. A short code-vocabulary query returns ranked cards, each with
`file`, `loc` (`path:start-end`), `symbol`, and why it matched. It finds code by meaning, so it
works when you don't know the exact name.

Choose retrieval by what you already know (strong preferences, not a fixed order):
- Location/name UNKNOWN, request is conceptual, or several modules may be involved → prefer `map`.
  One good semantic query beats a chain of keyword guesses.
- Exact file/path/symbol KNOWN → open it directly with Read/Edit. Don't map what you can point to.
- Exact literal / import / identifier you already know → grep.

After `map` returns relevant locations: read those `loc` spans directly. Do not re-search the same
concept to confirm it — map already located it, so another search spends a turn without adding new
evidence. Prefer the returned line range over reading the whole file.

Retrieval is adaptive, not a ritual:
- If an attempt does not reduce uncertainty, CHANGE strategy (refine the query, switch tool, or read
  a neighbor). Do NOT repeat a search that already failed — repeating identical input yields
  identical output.
- Do not remap an area you already understand; map again only when the task moves into genuinely
  new semantic territory.
- Stop retrieving once you know enough to make the next edit; then edit.

Strength: MUST — never repeat an identical failed search; never read a whole large file when a line
range was given. Everything else is a strong default you may override when the situation clearly
warrants it.

Good patterns:
- "Where is cache invalidation handled?" → map → read the top card's loc → edit.
- Known symbol `invalidate()` in `src/cache/manager.ts` → Read/Edit directly.
- Literal string `cache miss` → grep → read the hit.

Bad patterns (avoid):
- map, then grep the same concept anyway.
- grep → grep → grep sweeping the tree.
- map, then read the whole file instead of the returned span.
- repeat the same query/search after it returned nothing new.
```

---

## What the two-layer POLICY changes vs GUIDED (and why)

| Element | GUIDED | POLICY (two-layer) | Why (evidence) |
|---|---|---|---|
| **Structure** | one flat block | RULES anchor + INSTRUCTIONS manual | instruction-hierarchy / modularity; a short persistent anchor + a detailed manual reads more reliably than one mid-size lump |
| **Framing** | tool-centric ("when to use map") | goal/uncertainty-centric ("reach next correct action with least exploration; smallest context that removes uncertainty") | Anthropic context-rot: minimize context, not maximize |
| **Decision boundaries** | soft bullet preferences | explicit by what-you-know: unknown→map, known→native, literal→grep | our per-query traces; Sourcegraph "mix tools, few calls" |
| **Causal reason** | "don't re-grep what map found" | + *why*: "map already located it, so another search spends a turn without new evidence" | rationale-for-generalization hypothesis |
| **Anti-loop / recovery** | none | "if it doesn't reduce uncertainty, CHANGE strategy; never repeat a failed search; stop when you know enough" | tool-loop practitioner reports ("model reads 10 failed searches as 'search harder'"); our grep-walk |
| **Strength tiers** | flat | explicit **MUST** (hard) vs strong default (overridable) | instruction-hierarchy; stops the model treating every line as absolute |
| **Examples** | 5 inline, mixed | separated **good** vs **bad** contrastive patterns | DSPy: demonstrations matter; negative examples flag the failure modes we observed |

**Hypotheses under test** (not yet proven): the two-layer POLICY keeps GUIDED's low turn/token cost
while improving correctness reliability, by (a) giving one causal reason instead of a bare
prohibition, (b) an explicit anti-loop/adapt clause targeting the `map→grep` and grep-walk failures,
and (c) separating a short persistent anchor from the detailed manual so the core contract survives
long-context attention decay. The repeated multi-category benchmark (`run_policy_bench.py`) is built
to measure this; results are pending the run.

**Important confound note:** in this benchmark all Scubiee arms ship *bare* server instructions
(`CTX_MCP_BARE_INSTRUCTIONS=1`) so the stock Scubiee ladder text ("MUST map→pack_context;
map-only = FAIL") — which references tools we don't expose — no longer contradicts the arm's rule.
Earlier map-only runs did **not** have this fix, so their agents saw conflicting instructions; keep
that in mind when comparing to older numbers.
```
