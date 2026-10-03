# GUIDED vs POLICY — the two rule sets, side by side

Both are appended to the agent's workspace `CLAUDE.md`. Both expose the **same** tool surface
(`map` + `gate`/`status` only). They differ **only** in the rule text below. Source of truth:
`scripts/claude_sdk_harness/policies.py`.

- **GUIDED** = our current best-on-cost variant (when-to-use guidance).
- **POLICY** = the research-informed candidate (goal-first + decision boundaries + causal reasons
  + adaptivity/anti-loop + strength tiers + compact examples).

---

## GUIDED (current)

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

## POLICY (research-informed candidate)

```
## Scubiee retrieval policy (map is the only Scubiee locate tool: `map`, plus `gate`/`status`)

Goal: reach the next correct action with the LEAST unnecessary exploration. Retrieve the smallest
context that removes your current uncertainty — not the most context. Native tools
(Read/Grep/Glob/Edit/Write/Bash) are always available; use whichever is cheapest for the situation.

`map` is semantic code search: a short code-vocabulary query returns ranked cards
(`file`, `loc` = `path:start-end`, `symbol`, why-matched). It finds code by meaning, so it works
when you don't know the exact name.

Choose the tool by what you already know (strong preferences, not a fixed sequence):
- You DON'T know where the relevant code is, or the request is conceptual / doesn't match code
  literally, or several modules may be involved → prefer `map`. One good semantic query beats a
  series of keyword guesses.
- You ALREADY know the exact file / path / symbol → open it directly with Read/Edit. Don't `map`
  what you can already point to.
- You need an exact literal string, import, or identifier you already know → use Grep.

After a `map` returns relevant locations: read those `loc` spans directly. Do not re-search the
same concept to "confirm" it — the map already located it, so another search adds a turn and new
tokens without adding new evidence. Prefer the returned line range over reading the whole file.

Retrieval is adaptive, not a ritual:
- If a retrieval attempt doesn't reduce your uncertainty, CHANGE strategy based on what you learned
  (different query, different tool, or read a neighbor) — do not repeat the same failed search.
- Do not re-map an area you already understand unless a genuinely new question needs different
  context.

MUST (hard): do not repeat an identical failed search; do not read a whole large file when a line
range was given. Everything else above is a strong preference you may override when the situation
clearly calls for it.

Examples:
- "Where is cache invalidation handled?" → map (semantic).
- "Find the literal string `cache miss`." → grep.
- "Edit `src/cache/manager.ts` function `invalidate()`." → Read/Edit directly; no map.
- map returns `src/cache/manager.ts:180-240` → read that span; don't grep the concept again.
- map returns weak/irrelevant candidates → refine the query or switch to grep; don't remap the same.
```

---

## What POLICY adds over GUIDED (the deltas under test)

| Element | GUIDED | POLICY |
|---|---|---|
| **Framing** | "when to use map" (tool-centric) | "reach the next correct action with least exploration" (goal/uncertainty-centric) |
| **Decision boundaries** | soft preferences | explicit by what-you-know: unknown→map, known path→native, literal→grep |
| **Causal reason for "don't re-grep after map"** | bare "don't re-grep what map found" | + *why*: "the map already located it, so another search adds a turn and tokens without new evidence" |
| **Adaptivity / anti-loop** | none | "if retrieval doesn't reduce uncertainty, CHANGE strategy; don't repeat a failed search; don't remap what you understand" |
| **Strength tiers** | flat list | explicit **MUST** (hard) vs **strong preference** (overridable) |
| **Examples** | 5 inline | 5 structured, incl. a "map returned weak candidates → adapt" case |

**Hypotheses these deltas test** (from the research): goal-first framing + explicit boundaries +
causal reasons + an anti-loop clause should reduce the `map→grep` redundancy and grep-walk loops we
observed, without adding turns — i.e. keep GUIDED's low cost while improving correctness reliability.
This is what the repeated-run benchmark (`run_policy_bench.py`) is set up to measure.
```
