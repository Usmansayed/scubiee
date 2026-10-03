# Scubiee — RULES and INSTRUCTIONS (the two layers)

Two separate artifacts. RULES = short persistent anchor (<200 tokens). INSTRUCTIONS = detailed
operating manual (<1000 tokens). Verified token counts (tiktoken cl100k_base): RULES = 112,
INSTRUCTIONS = 510.

---

# RULES  (persistent anchor — 112 tokens, limit <200 ✓)

```
Scubiee is your semantic code retrieval layer. When you need to find code whose location
or name you do not already know, use Scubiee `map` for that discovery rather than blind
grep/glob sweeps. When you already know the exact file, symbol, path, or literal, go straight
to native tools. After map returns locations, read those spans directly — do not re-search
what map already found, and never repeat a search that already failed. Follow the Scubiee
instructions for how to choose.
```

---

# INSTRUCTIONS  (operating manual — 510 tokens, limit <1000 ✓)

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

## For contrast: the current GUIDED rule (single block, no separate instruction layer)

GUIDED does not split into rules + instructions — it is one block. Shown here so you can compare
wording; it is the thing the new two-layer artifact replaces.

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

Source of truth: `scripts/claude_sdk_harness/two_layer.py` (RULES, INSTRUCTIONS) and
`policies.py` (GUIDED).
