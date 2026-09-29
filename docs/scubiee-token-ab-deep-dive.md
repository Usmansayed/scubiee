# Deep dive: does Scubiee save tokens, why it didn't here, and how to make it

This documents everything learned across the Claude Code SDK A/B session — the
mistakes in the first design, what the traces actually showed, *why* the
Scubiee arm burned more tokens, and concrete, testable changes to flip Scubiee
from a token *cost* into a token *saving*.

Everything below is grounded in real runs under
`.ab_workspaces/claude_sdk_harness/` measured from the Claude Agent SDK's real
`model_usage` (Sonnet 5 + the small internal Haiku), not estimates.

---

## 0. TL;DR

- Scubiee did **not** save tokens in any measured run. Aggregate over the first
  5 runs: **+26.6%** (WITH used more). In the hardest, most realistic run
  (vague prompt) WITH used **+79%** (1.34M vs 750k tokens).
- The cause is **not** that Scubiee's locate is bad. It's that:
  1. Early prompts were **grep-able** (they leaked class/field names), so the
     agent never needed locate at all.
  2. The Scubiee **rule text is re-sent every turn** as cached context — a flat
     tax even when Scubiee is never called.
  3. When the agent *did* call `map`, it used it **additively** — it ran `map`
     and then **grepped the same thing anyway** to verify, paying for both.
- Making Scubiee actually save tokens is a **product + prompting** problem, not
  a "run it again" problem. Concrete fixes are in §6.

---

## 1. What we were really testing

Question: *does having Scubiee available make a coding agent spend fewer tokens
on the same task?* Fair test = **same task, same model (Sonnet 5), same starting
tree**; the only difference is whether Scubiee's MCP tools + its GATE rules are
present.

Token total per run = sum across all models in `ResultMessage.model_usage` of
`inputTokens + outputTokens + cacheReadInputTokens + cacheCreationInputTokens`.
The number is **dominated by `cacheRead`**, because every agent turn re-sends the
prior transcript (served from cache). So **more turns ≈ more tokens**, almost
linearly. Keep that in mind: token cost is mostly a function of *how many
back-and-forth turns the agent takes*, which is a function of *how quickly it
finds the code*.

---

## 2. Mistake #1 — the prompt leaked keywords (the big one)

The first prompts named the exact structures:

> "…add an optional integer field … it MUST be named `cached_tokens` … add a
> property named `effective_tokens` … `round((tokens-cached)+0.1*cached)` …"

and even for the "broad" task: "`truncate(text, max_chars=...)`",
"`DEFAULT_MAX_CHARS`".

With names like that, Sonnet 5 just runs one precise grep — e.g.
`class.*Comparison|tokens_saved` or `def truncate\(` — and lands on the file in
a single shot. **There is nothing for a semantic locate tool to do.** A locate
system only earns its keep when the agent does *not* already know the symbols.

So the first experiment was rigged against Scubiee: it measured "grep-able task
+ extra rules" and unsurprisingly found the rules were dead weight.

**Fix applied:** rewrote to ONE vague, human-worded request — a Slack-style
message describing the *goal and the pain*, with **no symbol, file, class, or
formula**:

> "We've got something that measures how much context our smart retrieval feeds
> the model versus just grepping a bunch of files and dumping them… those
> savings numbers make us look worse than we are because cached tokens are
> basically free but counted at full price. Can you make that comparison
> cache-aware…"

Effect (run `20260929T131109Z_vague`): discovery exploded — the WITHOUT arm did
**14 greps**, the WITH arm did 9 greps **plus** Scubiee. This is finally the
regime where locate *could* matter.

---

## 3. Mistake #2 — the oracle graded field names, not behavior

Making the prompt vague created a new problem: a vague prompt lets the agent
choose its *own valid design*. In the vague run the WITH agent implemented
cache-awareness as a **rate model** (`cache_hit_rate`, `billed_*` fields)
instead of the count model (`cached_tokens`, `effective_tokens`) my oracle
probed for. That is a perfectly reasonable reading of the request — but the
oracle only gave it 2/5 because it looked for specific accessor names.

Lesson: **when the prompt is vague, the oracle must grade pure outcome behavior
through whatever public surface the agent built**, e.g. "construct the
comparison with equal raw tokens but more cache on the smart arm; assert the
reported paid/effective saving goes up." It must not assume names. (This is the
next fix to land in `harness_task.py`'s oracle — see §6.4.)

This is itself a finding: **vague prompt ⇄ deterministic oracle is a real
tension.** You buy locate-relevance at the cost of grading strictness, and the
oracle has to be written to only depend on observable behavior.

---

## 4. Why the Scubiee arm burned MORE tokens — mechanism, with receipts

Three compounding effects, all visible in traces.

### 4a. Flat rule tax (every run, even when Scubiee is untouched)
The WITH arm's `CLAUDE.md` carries the full Scubiee GATE policy ("MUST Use
Scubiee MCP for locate", the ladder, the forbid-first rules…). That text is part
of the system/context and is **re-billed as `cacheRead` on every turn**. In the
one early run where WITH used the *exact same 5 tools* as baseline, it still
cost **+9.9%** — that delta is essentially pure rule tax.

### 4b. Additive use, not substitutive (the expensive failure mode)
Run `20260928T234149Z` (scoped) and `20260929T131109Z_vague` (vague) both show
the same pattern when Scubiee *is* used:

```
ToolSearch → mcp__scubiee__gate → mcp__scubiee__map → status → map(again)
→ Grep → Grep → … → Read → Edit
```

The agent calls `map`, gets cards, and **then greps for the same symbols anyway**
before trusting itself to edit. In the vague run the WITH arm ran `map` twice
**and 9 greps** and **1 Glob**. So it paid the full native-grep discovery cost
*plus* the Scubiee ladder cost *plus* the `ToolSearch` discovery step *plus*
more turns (30 vs 24). Net: **1.34M vs 750k tokens (+79%)**.

### 4c. Turn inflation dominates
Because cost ≈ turns × transcript size, the extra Scubiee turns (gate/status/
map/map + a ToolSearch) each drag the whole growing transcript through cache
again. Scubiee added ~6 turns; at a ~40–50k-token transcript that alone is
hundreds of thousands of `cacheRead` tokens.

### 4d. `ToolSearch` overhead
Under the Claude Code SDK, MCP tools aren't free to have available — the agent
emitted a `ToolSearch` call (`select:mcp__scubiee__map,…`) to discover the
Scubiee tools before using them. That's an extra turn + tokens that the WITHOUT
arm never pays.

---

## 5. Secondary findings & anomalies (worth keeping)

- **`map` can surface non-code files that `pack_context` can't seed on.** During
  a warm-proof, `map` returned my own `docs/…report.md` as the top card and
  `pack_context` rejected it: `seed not found: file='docs/…report.md'
  symbol=''`. Fix in the harness: pick a **code** seed (`.py/.ts/...`) and fall
  back through candidates. Product implication: `pack_context` should either
  skip non-seedable cards automatically or return a clearer "pick a code seed"
  affordance, and `map`'s `suggested_seed` should prefer a seedable code symbol.
- **`pack_context` has a cold-AST penalty.** First call after idle returns
  `error: "ast_warming"`; it must be retried. Any client (or the agent) that
  treats the first empty pack as "no results" will wrongly fall back to grep.
- **Claude Code always bills a little `claude-haiku-4-5`** (~1.1–1.5k tokens/run)
  for internal bookkeeping. Include it in totals; it's ~equal across arms.
- **Variance is large.** Baseline totals for the *same* task ranged 161k–750k
  depending on how the exploration went. Any real claim needs n ≥ 10 per cell.
- **Correctness was a wash / prompt-sensitive.** With grep-able prompts both
  arms passed 5/5. With the vague prompt neither fully passed the strict oracle
  (design divergence, §3). Scubiee never *improved* correctness in any run.

---

## 6. How to actually make Scubiee SAVE tokens

The goal: make `map`/`pack` a **replacement** for the grep-and-read hunt, not an
addition to it, and stop paying for it when it isn't used. Concrete levers:

### 6.1 Make locate substitutive, not additive (biggest win)
The agent greps *after* `map` because it doesn't trust the cards enough to edit.
Two ways to fix:
- **Return editable evidence, not just pointers.** `pack_context` already
  returns a heatmap with `loc` spans — if the pack response includes the actual
  code bodies of the top spans (bounded), the agent can go straight to `Edit`
  with no confirming grep/read. The rule "after a heatmap → Read `loc` spans
  only; re-Grep of packed ground = FAIL" is correct; the product should make
  following it *cheaper than* re-grepping by handing over the span text inline.
- **Rule wording:** the GATE should explicitly say "if `pack_context` returned
  span bodies, edit from them; do NOT re-grep to confirm." Right now the agent
  hedges.

### 6.2 Stop paying the rule tax when idle
The GATE block is ~40–60 lines re-sent every turn. Options:
- **Shrink the always-on rule to a one-liner** ("For locating unfamiliar code,
  prefer the Scubiee `map`→`pack` tools; details on demand") and move the full
  ladder into the tool descriptions / a `gate` response the agent fetches only
  when it decides to locate. Cost moves from "every turn" to "once, when used."
- Measured impact ceiling: the pure-rule-tax run was +9.9%; removing most of
  that text recovers most of it.

### 6.3 Avoid the `ToolSearch` tax
Pre-authorize the Scubiee tools so the agent doesn't spend a turn discovering
them. In the SDK, keep the tool set small and explicitly allowed (we already
pass `allowed_tools`), and consider fewer exposed Scubiee tools (just
`map`+`pack_context`+`status`) so there's nothing to "search".

### 6.4 Target the regime where locate wins, and grade behavior only
- Use tasks that are **genuinely un-greppable**: the target is described by
  behavior, lives among many similar-named modules, and the *right* file shares
  no distinctive token with the prompt. That's when a 1-turn `map` beats a
  10-grep hunt — and 6 saved turns is a real token win.
- Rewrite the oracle to assert **outcome through the public surface** (construct
  the comparison, vary cache, assert the paid/effective saving moves the right
  way) without probing field names, so a correct-but-differently-named solution
  still scores.

### 6.5 Measure the mechanism directly (cheap, high-signal)
Add a micro-benchmark that, for the *same* discovery question, compares:
- native: the token cost of the grep+read sequence the baseline actually ran;
- scubiee: the token cost of one `map`+`pack` that returns span bodies.
This isolates "cost of finding the code" from whole-task noise and is where the
saving, if any, will show up first. It also sidesteps the huge whole-run
variance.

### 6.6 Force-use arm (for ceiling measurement only)
To measure Scubiee's *best case* (not its adopted case), add a third arm whose
system prompt requires locating via `map`/`pack` and forbids grep for discovery.
Compare its turn count to the baseline's grep hunt. This won't be "fair
adoption", but it answers "if the agent fully trusted Scubiee, would it be
cheaper?" — which tells us whether 6.1 is worth building.

---

## 7. Harness bugs found & fixed along the way

These were harness defects, not Scubiee results; every reported number is from
runs *after* the fix:
- Missing `import os` in the oracle scorer.
- `git archive` binary tar decoded as text → `UnicodeDecodeError`; now read as
  bytes.
- Base conda env has a broken `opentelemetry` pytest plugin that crashes
  collection → oracle runs with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
- Warm-proof seeded `pack_context` on a `.md` doc card → now filters to code
  seeds with fallback (§5).
- Report markdown crashed on `None` values → null-safe formatting.
- Per-arm results now persisted immediately (`arm_without.json` / `arm_with.json`)
  so a late crash never loses an expensive agent run.

---

## 7b. Definitive vague-prompt runs (confirming the pattern)

After fixing the prompt (§2) and rewriting the oracle to grade behavior, not
names (§3), two full vague-prompt runs both reproduced the same result:

| Run | WITHOUT tokens | WITH tokens | Δ | WITH Scubiee calls | Pattern |
|---|---:|---:|---:|:--:|---|
| `20260929T131109Z_vague` | 750,033 | 1,344,822 | **+79.3%** | 4 (gate, map×2, status) | map → then 9 greps + glob |
| `20260929T132601Z_vague` | 1,024,516 | 1,339,345 | **+30.7%** | 4 (gate, map×2, status) | map → then 7 greps + 4 reads |

Both arms produced *working* cache-aware implementations (different designs:
the WITHOUT arm built a `CachePricing` rate model on the comparison; the WITH
arm added `cache_hit_rate`/`billed_*`). The token verdict is unchanged and now
reproduced under the fair prompt: **WITH costs 30–79% more, every time,** and
the extra spend traces directly to Scubiee being used *on top of* the same grep
hunt the baseline did — plus the `ToolSearch` + rule-tax turns.

## 7c. Root cause: it's the PACK PAYLOAD FORMAT, not retrieval quality

To settle "is it the embedding model, or pack's semantics?", I replayed the WITH
agent's exact `map` query against the warm engine over raw MCP stdio and
inspected what `map` and `pack_context` actually return
(`scripts/claude_sdk_harness/_probe_quality.py`). Result:

**Map quality is excellent — not the problem.** For query
`"retrieval benchmark token savings comparison smart retrieval vs grep dump
baseline"`:

| rank | file | score |
|---|---|---:|
| **0** | **`packages/pipeline/token_meter.py`** (the true target) | **36.31** |
| 1 | docs/scubiee-token-ab-deep-dive.md | 3.91 |
| 2 | docs/…retrieval-trajectory-research.md | 3.86 |

The target ranked **#0 by a ~9× score margin**, with a correct "why"
("Estimate tokens for retrieval paths (baseline vs Context Engine)"). The
embedding/ranking model found exactly the right file first. **Your "embedding
not good enough" hypothesis is ruled out.**

**Pack targeting is also correct — not the problem.** `pack_context` returned 7
spans, all inside `token_meter.py`, at exactly the right lines: `45-58`
(`QueryCompare`), `18-28` (`estimate_tokens`), `32-41` (`ArmResult`), `66-126`
and `129-190` (the two functions). Semantically it pinpointed the code the task
needed. **Your "pack has no semantic understanding" hypothesis is also ruled
out** — pack pointed at precisely the right structures.

**The actual defect is the pack RESPONSE PAYLOAD:**

```
pack_top_keys      = ["heat", "id", "loc", "r", "s", "sc"]
pack_returns_bodies = false          # ← coordinates only, no code text
per-span "file"     = ""             # ← human-readable file blank on each span
```

So `pack_context` hands back **pointers without bodies** — `loc:
"packages/pipeline/token_meter.py:45-58"` and terse scores (`r`,`s`,`sc`), but
**not the code at those lines**. Consequences:

1. To actually see what it's editing, the agent must now **open the file and
   read those line ranges** — i.e. exactly the Read/Grep round-trip it would
   have done natively. Pack did the hard semantic locating and then made the
   agent pay a *second* trip to materialize it.
2. The keys are opaque and the per-span `file` is blank, so the model can't
   cheaply reason over the heatmap; it re-greps for names it trusts
   (`ArmResult|QueryCompare|compare_queries`) to reconstruct context.

**That is the whole token-waste mechanism, precisely located:** map + pack are
*correct and high quality*, but because pack returns **locations, not code**,
the agent still performs the full read/grep hunt on top of the Scubiee calls —
so Scubiee's tokens are pure addition, not substitution. It's a **payload/
contract problem, not a model-quality problem.**

### The fix (now specific, and verified against the live engine)
I probed whether the bodies are even reachable (`_probe_bodies.py`):

- `pack_context(..., include_bodies=1)` — **did NOT return bodies.** The
  response morphed to keys `["chain","cold","pack","seed",...]` and still
  carried no code text. So the advertised `include_bodies` knob does not put
  code into the pack the agent first sees.
- `collect_hot_context` — **DOES return real code**, e.g.
  `{"id":"…token_meter.py::QueryCompare.tokens_saved","loc":"…:51-52",
  "text":"def tokens_saved(self)…return max(0, …)"}`. So the bodies exist, but
  only via a **separate third tool call**.

So the agent's natural flow is `map → pack`, and **`pack` returns pointers only**.
To actually see code it must make a *third* call (`collect_hot_context`) that
the default flow doesn't push it toward — so it falls back to native Read/Grep
every time, and Scubiee's tokens become pure addition.

Concrete fixes, in priority order:
1. **Make the first `pack_context` return bounded span bodies by default** (or
   make `include_bodies=1` actually work), with a readable `file` per span and
   non-opaque keys. One `map`+`pack` should be enough to edit.
2. **Fix the rule to close the loop:** "after `pack`, if you need the code, call
   `collect_hot_context` on those spans and edit from its `text`; do NOT re-open
   or re-grep packed ground." Right now the ladder stops at pointers.
3. Only then does `map`+`pack(+collect)` **replace** the grep+read hunt instead
   of adding to it — the only way turn count, and thus token count, drops below
   baseline.

## 7d. Experiment: pack heatmap-only vs pack-with-bodies (testing the fix)

`scripts/claude_sdk_harness/pack_bodies_experiment.py`. Both arms are **WITH
Scubiee**; the ctx locate surface (`find`/`pack`/`status`) is identical; the
**only** variable is whether `pack` returns code bodies. Bodies are produced by
having the `pack` tool auto-fill each hot span via `collect_hot_context` (ids
match between the heatmap and collect, verified). One human prompt bundling
**3 real tasks** (cache-aware savings; harden the token-estimate fallback; add a
plain-English savings line), graded by **one** behavior oracle (the cache-aware
task). Byte-identical snapshots per arm.

| Run | pack actually used? | heatmap-only | with-bodies | Δ | reads-after-pack (H→B) | success (H / B) |
|---|:--:|---:|---:|---:|:--:|:--:|
| 1 `…161856Z` | **yes** | 1,184,314 | 903,487 | **−23.7%** | **6 → 3** | ❌ / ✅ |
| 2 `…162905Z` | no (0 pack calls) | 1,554,947 | 1,307,031 | −15.9% | 0 → 0 | ✅ / ✅ |

**Interpretation (careful about signal vs noise):**

- **Run 1 is the valid test** — the agent actually called `pack`. Giving it
  bodies **cut tokens 23.7%**, **halved the confirming reads after pack (6→3)**,
  cut 9 turns (31→22), and the bodies arm **passed the task while the
  heatmap-only arm failed** (it thrashed — 6 reads, 5 greps, a stray
  `WebSearch`/`Skill` — trying to reconstruct what pack had already found). This
  is exactly the predicted mechanism: bodies → fewer confirming round-trips →
  fewer turns → fewer tokens.
- **Run 2 is NOT evidence about bodies** — neither arm called `pack` (0 calls),
  so the −15.9% is pure exploration variance, not the bodies effect. Honest
  reporting: only count runs where pack is on the path.

**Takeaway:** the single clean run supports the fix strongly (−24% + a
correctness flip), and the mechanism (reads-after-pack 6→3) is visible rather
than inferred. But n=1 on the pack-used condition — to make it a firm claim,
run ~10 pairs and keep only the pack-used ones. The direction is consistent with
§7c: **the bottleneck is pack handing over pointers, and inlining bodies fixes
it.** It also confirms the product change is worth building (return bounded span
bodies from the first `pack`, or make `include_bodies=1` actually populate them).

## 8. Honest conclusion

On every task measured, **Scubiee increased token usage** (from +10% up to +79%),
while never improving correctness. But the *reason* is specific and fixable:
under a neutral/vague prompt Sonnet 5 either ignores Scubiee (paying only the
rule tax) or uses it **on top of** its own grep hunt (paying twice) — because the
current flow gives it pointers it doesn't trust enough to skip grepping. It is
**not** evidence that semantic locate is inherently wasteful.

To make Scubiee save tokens, the product must make locate **replace** the grep+
read hunt (return editable span bodies, tell the agent to edit from them,
§6.1), stop charging the rule tax on idle turns (§6.2), and be evaluated on
un-greppable tasks with behavior-only oracles (§6.4). Until locate is
substitutive rather than additive, an available-but-optional Scubiee will keep
costing more than it saves for a capable model with good native grep.

Reproduce: `python scripts/claude_sdk_harness/run_harness.py --skip-live-probe`
(single vague task). Raw traces: `.ab_workspaces/claude_sdk_harness/<run>_vague/`.
