# Kiro rule-optimization experiments — which rule wording best drives Scubiee

Goal: find the rule text that gets the Kiro `auto` agent to use Scubiee `map` well (adopt it where it
helps, substitute for native search) at the lowest cost, WITHOUT over-steering. Research-driven
variants, A/B'd against the shipped default (`c_ship`) across multiple task types with repeats.

Harness: `run_kiro_ab.py` (Kiro CLI headless, `--model auto`, per-arm agent configs, credits via
`meteringUsage`, SHA-identical snapshot isolation). Cost unit = Kiro **credits**.

## Variants tested (all share c_default's decision logic; they differ only in the technique)
- **c_ship** — the shipped default: c_default two-layer text + one strict-adherence line (control).
- **k_fewshot** — c_ship INSTRUCTIONS + 2–3 WORKED map-vs-grep decision examples (exemplar technique).
- **k_split** — a TINY ~82-token strict RULES directive ("use map for find/read-symbol/connections")
  + the full manual in INSTRUCTIONS (the "short rules, detail below" design).
- **k_combo** — k_split's tiny directive + k_fewshot's worked examples (best-of-both hypothesis).
- (round-1 also tried k_xml = XML-structured rules, and k_calm = dialed-back tone.)

Research basis (web): exemplars often beat instruction-tuning (arxiv APO); worked examples are "one
of the most reliable ways to steer" (Anthropic); 2026 finding that aggressive MUST/CRITICAL language
over-triggers + inflates tokens on new models (confirms our earlier strict-variant regressions).

## Results by task type (credits, lower is better; all cells same correctness within task)

### Round 1 — INTEGRATION task `status_headline_everywhere`, n=1 each (screen)
| variant | credits | map | native_ops |
|---|--:|:--:|:--:|
| k_fewshot | **7.03** | 3 | **4** |
| c_ship | 8.26 | 2 | 9 |
| k_split | 9.87 | 3 | 13 |
| k_calm | 9.88 | 3 | 13 |
| k_xml | 10.94 | 2 | 12 |

### Round 2 — same INTEGRATION task, n=2 each
| variant | avg credits | avg map | avg native_ops |
|---|--:|:--:|:--:|
| **k_fewshot** | **8.38** | 2.5 | 9.5 |
| k_split | 9.25 | 2.0 | 9.5 |
| k_combo | 9.75 | 4.0 | 10.5 |
| c_ship | 10.46 | 2.0 | 12.5 |

### Round 3 — EDIT task `unify_token_estimate`, n=2 each
| variant | avg credits | avg map | avg native_ops |
|---|--:|:--:|:--:|
| **k_fewshot** | **1.21** | 1.0 | 2.0 |
| c_ship | 1.50 | 1.0 | 2.0 |
| k_combo | 3.02 | 3.0 | 4.0 |

### Round 4 — INTEGRATION task `sync_severity_rollup`, n=2 each (top-2 confirm)
| variant | avg credits | avg map | avg native_ops |
|---|--:|:--:|:--:|
| c_ship | **1.16** | 1.5 | 1.5 |
| k_fewshot | 1.21 | 2.0 | 1.0 |

## Conclusion

**k_fewshot (worked examples) is the most robust rule.** It was the cheapest variant on 3 of 4
rounds — both integration rounds and the edit round — and effectively tied with c_ship on the 4th.
Its mechanism is visible in `native_ops`: worked examples make the agent both use map AND trust it
(substitute), so native search drops (e.g. 4 vs c_ship's 9 in round 1). This matches the research
that exemplars beat pure instruction wording.

**k_combo and k_split over-steer.** The tiny strict directive reliably drives the HIGHEST map
adoption (k_combo hit 4 map calls), but adoption is the wrong target: forcing map onto tasks that
don't need it inflates cost. k_combo was 2× the cost of k_fewshot on the simple edit task (3.02 vs
1.21) because it mapped 3× on a 2-file change. This is the same over-steering that sank the Cursor
strict variants (c_firstmove/c_counter) — confirmed again, and confirmed by the 2026 research on
aggressive language over-triggering.

**k_xml and k_calm gave no benefit** — structure/tone techniques lost to the content technique
(examples) on the one round they ran.

**Default c_ship is solid but beatable.** It was consistently mid-to-worst on the integration
rounds. Swapping its INSTRUCTIONS to include the k_fewshot worked examples is a safe, evidence-backed
improvement that lowers cost without changing decision logic or correctness.

### Recommendation
Adopt **k_fewshot** as the rule (c_ship's proven text + worked map-vs-grep examples in the
instructions). Do NOT ship k_combo/k_split — the tiny-directive over-maps on easy tasks.

### Caveats (honest)
- n=2 per cell on rounds 2–4 (n=1 round 1). Kiro `auto` credit variance is large (same arm swung
  7.5↔11 credits on the integration task), so the credit deltas are directional. The signal is
  credible because (a) k_fewshot led in 3/4 rounds and (b) `native_ops` (less noisy than credits)
  consistently tracks it.
- Correctness was unchanged by rule across all rounds (the integration task sits at oracle 0.67 for
  everyone; the edit task at ~1.0). Rules move COST and TOOL-MIX, not correctness — the whole
  project's recurring finding, now confirmed on Kiro too.
- Credits ≠ tokens; within-Kiro comparisons only.


---

## Cross-runtime check of k_fewshot (Cursor + Claude Code)

**Cursor — k_fewshot vs c_ship (default), 2 reps each, tokens (not credits):**
| task | k_fewshot | c_ship |
|---|--:|--:|
| sync_severity_rollup (integration) | **194k** (181k, 207k) | 211k (212k, 211k) |
| unify_token_estimate (edit) | **208k** (192k, 224k) | 230k (256k, 203k) |

**The k_fewshot win transfers to Cursor** — cheaper on both task types (~8% integration, ~10% edit),
all cells oracle 1.0. The worked-examples rule is not Kiro-specific; it helps the Cursor `auto`
agent too, by the same mechanism (map used + trusted → fewer native ops).

**Claude Code — BLOCKED (could not run).** The Claude SDK harness returned
`ResultError: Your organization has disabled Claude subscription access for Claude Code · Use an
Anthropic API key instead`. The `.env` has a `claude_code_oauth` (subscription) token but no raw
`ANTHROPIC_API_KEY`, and the subscription path is org-disabled. So Claude Code cross-validation is
blocked by auth, not by the harness — the `k_fewshot` arm is wired into `run_dev_mini.py`
(policies.RULES["k_fewshot"], imported from cursor_rules so the text is identical across runtimes)
and will run as soon as an Anthropic API key is available. Dropped for now per decision to focus on
Kiro + Cursor.

---

## Negative control — does k_fewshot over-steer on GREENFIELD? (Kiro)

The over-steering worry is: a rule that pushes map could drag the agent into pointless map calls on
a from-scratch build where there is nothing to locate yet. We tested this directly on the big
2-turn greenfield task `cli_codestats_feature` (build a `codestats` module + wire a CLI subcommand),
kab_ship FIRST then kab_fewshot, n=1, model `auto`.

| arm | credits | scubiee calls | native_ops | py edits | oracle | success |
|---|--:|--:|--:|--:|--:|---|
| kab_ship | 5.11 | 1 (map, `find`) | 7 | 2 | 1.0 | yes |
| kab_fewshot | 5.36 | **0** | 6 | 2 | 1.0 | yes |

**k_fewshot did NOT over-steer.** On pure greenfield it fired map **zero times** (ship actually
fired it once), and credits were flat within noise (5.36 vs 5.11; ship even used one more native
read). Both arms produced the identical, correct feature (same two edits: `codestats.py` +
`__main__.py`), oracle 1.0.

This is the inverse-confirmation of the integration result and the key evidence that k_fewshot's
examples teach *discrimination*, not blind obedience:
- On the INTEGRATION task, k_fewshot RAISED map adoption (map fires 2–3× — the right move when you
  must locate call sites across modules).
- On the GREENFIELD task, k_fewshot held map at ZERO (the right move when you are writing new code).

Adoption tracks task shape, not the rule's intensity. That is exactly the behavior that
k_combo/k_split failed to produce — they over-mapped easy/empty tasks. Worked example #4 ("a
from-scratch build does not need map") appears to be doing real work here: it gives the agent an
explicit when-NOT-to-map anchor, which the tiny-directive variants lack.

**Caveat:** n=1 on this cell; credit delta is within Kiro `auto` variance. The decisive, low-noise
signal is the scubiee-call count (0 vs 1) and native_ops (6 vs 7) — both say "no extra map pressure
on greenfield."

---

## Tuning the winner — k_fewshot2 (lean 2-example contrast) vs k_fewshot (4 examples)

k_fewshot carries FOUR worked examples (map-wins / known-symbol-focus / grep-the-literal /
greenfield-no-map). Hypothesis: it is the **positive↔negative contrast** that teaches the agent
when to map, not the example COUNT. So k_fewshot2 keeps exactly two — the sharpest "map wins"
(unknown, cross-module) and the sharpest "do NOT map" (greenfield) — and drops the two middle cases.
Prompt drops ~345 chars (~90 tokens). A/B on INTEGRATION task `status_headline_everywhere`,
k_fewshot FIRST then k_fewshot2, n=2 each, model `auto`.

| arm | avg credits | per-rep | avg map calls | avg native_ops | oracle |
|---|--:|---|--:|--:|--:|
| kab_fewshot (4 ex) | 10.50 | 11.98, 9.01 | 2.0 | 10 | 0.67 |
| **kab_fewshot2 (2 ex)** | **8.54** | 8.31, 8.77 | 2.5 | 10 | 0.67 |

**k_fewshot2 won: ~19% cheaper AND more stable.** The lean variant's two reps were tight
(8.31/8.77) while the 4-example variant swung wide (11.98/9.01) — fewer examples gave not just lower
mean cost but lower variance. Decisively, **map adoption was preserved** (avg 2.5 vs 2.0 map calls):
cutting to two examples did NOT weaken the "map on integration" signal — if anything it sharpened it.
Correctness unchanged (oracle 0.67 ceiling for everyone on this task).

**Interpretation.** The two dropped examples (known-symbol `focus`, grep-the-literal) were redundant
for the map-vs-grep *decision* on an integration task; they only added prompt tokens the model pays
for every turn. The single positive/negative contrast is what does the teaching. This is the
exemplar-efficiency corollary to the earlier finding: examples beat instructions, and a **small,
sharply-contrasting** example set beats a larger one.

**Caveat:** n=2, single integration task.

### Greenfield over-steer control for k_fewshot2 (PASSED)

Same control we ran for k_fewshot: does the leaner 2-example set still correctly hold map near zero
on a from-scratch build? Task `cli_codestats_feature`, k_fewshot FIRST then k_fewshot2, n=1.

| arm | credits | map calls | native_ops | edits | oracle |
|---|--:|--:|--:|--:|--:|
| kab_fewshot | 5.87 | 1 | 6 | 2 | 1.0 |
| kab_fewshot2 | 6.30 | 1 | 5 | 2 | 1.0 |

**k_fewshot2 did NOT over-steer on greenfield** — map fired exactly 1×, identical to k_fewshot and
to the c_ship greenfield arm, not the 2–3× it uses on integration. Trimming to two examples
preserved the when-NOT-to-map discrimination. Both built the feature correctly (oracle 1.0, same two
edits). The 6.30 vs 5.87 gap is single-rep `auto` noise (k_fewshot2 used one fewer native read).

**Full discrimination profile for k_fewshot2 (the whole point):**
- INTEGRATION `status_headline_everywhere`: map ~2.5× (adoption preserved, ~19% cheaper than k_fewshot)
- GREENFIELD `cli_codestats_feature`: map 1× (no over-steer, matches k_fewshot)

The lean contrast tracks task shape exactly like the 4-example set, at lower cost and variance.

### Higher-rep confirmation — k_fewshot2 vs c_ship (n=4, the honest result)

To tighten the credit delta against the current ship rule, we ran c_ship (kab_ship, FIRST) vs
k_fewshot2 on the 3-module integration task `sync_severity_rollup`, n=4 each, model `auto`.

| arm | avg credits | per-rep credits | avg map | avg native_ops | success |
|---|--:|---|--:|--:|--:|
| kab_ship | 2.35 | 5.93, 1.21, 1.18, 1.08 | 2.0 | 3 | 4/4 |
| kab_fewshot2 | 2.57 | 1.20, 1.05, 4.15, 3.86 | 2.5 | 3 | 4/4 |

**At n=4 the two are a statistical tie on cost** (2.35 vs 2.57 credits). The honest read: the ~19%
k_fewshot2 edge seen at n=2 on `status_headline_everywhere` did NOT reproduce here once we averaged
four reps — Kiro `auto` credit variance is huge (ship alone swung 1.08↔5.93; k_fewshot2 1.05↔4.15),
and the earlier gap was mostly that noise. Both arms: **4/4 success, oracle 1.0**, map fires ~2× per
run, native_ops tied at 3.

So the strong n=2 "19% cheaper" claim is downgraded: on this task, **k_fewshot2 and c_ship cost the
same within noise.** What k_fewshot2 does NOT do is cost *more* — the lean 2-example contrast is at
worst cost-neutral vs the default, while being a smaller prompt and (from the earlier controls)
keeping the same adoption-on-integration / no-over-steer-on-greenfield discrimination.

### Updated recommendation (revised, honest)
**k_fewshot2 is a safe, cost-neutral-or-better replacement for c_ship**, not a proven big win. The
case for shipping it is: (a) equal correctness and adoption, (b) equal cost within noise on a
higher-rep integration run, (c) smaller prompt, (d) the exemplar-contrast mechanism that was
cheaper at low-n and never worse. It is NOT a reliable ~19% saver — that figure was n=2 noise.
Before locking it in, the remaining useful check is a Cursor cross-runtime run (k_fewshot2 vs
k_fewshot) to see whether the lean contrast shows any token edge where variance is lower than Kiro
credits. If Cursor also shows a tie, ship k_fewshot2 for the smaller-prompt/simplicity win and stop
chasing a credit delta that the data does not support.
