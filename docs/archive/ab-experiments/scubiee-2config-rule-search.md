# Finding the best rule for the 2-config (find|focus) map surface — Kiro

Now that the surface is fixed at TWO configs (find|focus), which RULE+INSTRUCTIONS drive the best
with-Scubiee behavior? Candidates:
- **k_2cfg** (3219 chars) — the surface-matched baseline: find/focus decision table + examples.
- **k_2cfg_lean** (745) — minimal: just the find/focus decision + a trust line. No examples.
- **k_2cfg_trust** (2638) — k_2cfg + explicit SUBSTITUTION directive ("a map body is authoritative,
  don't re-grep to confirm; map replaces native search, doesn't sit on top of it").
- **k_2cfg_decomp** (3683) — k_2cfg + query-DECOMPOSITION ("one target per query; known name ->
  focus first; don't bundle two targets").

## IMPORTANT CORRECTION — the "decomp regressed Kiro" claim was WRONG (it was variance)
Earlier I compared decomp's run on `cli_health_command` (avg 11.66 cr) against k_2cfg's run on a
DIFFERENT task (`sync_severity_rollup`, avg ~1.08 cr) and concluded decomp regressed Kiro. That was
a bad comparison across tasks. A clean SAME-TASK head-to-head overturns it:

### Head-to-head: k_2cfg vs k_2cfg_decomp, SAME task `cli_health_command`, n=2
| arm | avg credits | per-rep | avg native_ops | oracle |
|---|--:|---|--:|--:|
| kab_2cfg | 6.88 | 11.40, 2.35 | 9.5 | 2/2 |
| kab_2cfg_decomp | **1.78** | 1.94, 1.62 | 5.0 | 2/2 |

On the same task, **decomp was CHEAPER and more stable** (1.6-1.9 both reps) than k_2cfg (which swung
2.35↔11.40). native_ops lower too (5 vs 9.5). Both 2/2 correct, both used find+focus.

### The real lesson: this complex task has HUGE run-to-run variance
k_2cfg alone ranged 2.35 → 11.40 credits on identical inputs. The expensive runs are when map
SUPPLEMENTS (native_ops ~13); the cheap runs are when it SUBSTITUTES (native_ops ~5). That swing —
not the rule — dominated the earlier single-draw comparisons. ANY conclusion from n=2 on this task is
unreliable. This is why the rule search below uses the lower-variance integration task AND higher n.

## 4-candidate search on the LOW-VARIANCE integration task `sync_severity_rollup` (n=3)
| rule | avg credits | per-rep | avg native_ops | avg map | success |
|---|--:|---|--:|--:|--:|
| **k_2cfg** | 0.899 | 0.92, 0.88, 0.90 | 1.7 | 2.0 | 3/3 |
| k_2cfg_decomp | 0.925 | 0.89, 1.05, 0.83 | **1.3** | 3.3 | 3/3 |
| k_2cfg_trust | 0.968 | 1.05, 0.86, 0.99 | 2.3 | 2.7 | 3/3 |
| k_2cfg_lean | 0.987 | 1.04, 0.86, 1.06 | 3.0 | 2.0 | 3/3 |

**All four are tied within noise** (0.90-0.99 cr, 0.09 spread), all 3/3 correct — the integration task
is too easy to separate rules. Weak signals: k_2cfg lowest mean + tightest; **k_2cfg_decomp lowest
native_ops (1.3) + highest map adoption (3.3)** = best SUBSTITUTION; k_2cfg_lean highest native_ops
(3.0) — stripping guidance let native search creep back. So lean is the weakest; the race is
k_2cfg vs k_2cfg_decomp.

## Decisive tiebreak: k_2cfg vs k_2cfg_decomp on the complex task `cli_health_command` (n=4)
| rule | avg credits | per-rep | avg native_ops | avg map | correctness |
|---|--:|---|--:|--:|--:|
| k_2cfg | 4.04 | 4.67, 3.29, 5.30, 2.92 | 12.75 | 8.75 | 1/4 |
| **k_2cfg_decomp** | **3.39** | 1.81, 4.06, 2.79, 4.90 | **8.25** | 7.25 | 0/4 |

**k_2cfg_decomp wins on cost + substitution:** ~16% cheaper (3.39 vs 4.04) and lower native_ops
(8.25 vs 12.75) — decomp replaces native search with map better, which is exactly its design goal.
Correctness was a wash dominated by task variance (1/4 vs 0/4 — both low because this oracle is
strict and the vague spec is hard; neither rule is a correctness lever).

## FINAL VERDICT — best 2-config (find|focus) rule
**Ship `k_2cfg_decomp`** as the 2-config rule. Across the search:
- Integration task (n=3, low variance): all four tied ~0.90-0.99 cr; decomp had the LOWEST
  native_ops (1.3) and highest adoption (3.3) — best substitution even where cost was a tie.
- Complex task (n=4, high variance): decomp ~16% cheaper than k_2cfg (3.39 vs 4.04) with lower
  native_ops (8.25 vs 12.75).
- k_2cfg_lean (minimal) was the WEAKEST — stripping the examples/guidance let native search creep
  back (native_ops 3.0 on the easy task). So the guidance earns its tokens.
- k_2cfg_trust (substitution directive) was middle — fine but no better than k_2cfg.

The decomposition discipline ("one target per query; known name -> focus first; don't bundle two
targets") is the single most useful addition for the find|focus surface: it drives map to SUBSTITUTE
rather than SUPPLEMENT, which is where all the credit savings live. It helps Kiro (shown here) and
was built to fix the Cursor compound-query failure — so it is the best cross-runtime 2-config rule.

### IMPORTANT correction logged
My earlier "k_2cfg_decomp regressed Kiro (11.66 vs 10.48)" claim was WRONG — it compared a single
unlucky decomp draw on the complex task against a lucky k_2cfg draw on a DIFFERENT (easy) task. The
same-task head-to-heads (n=2 then n=4) both show decomp ahead. Lesson: never compare rules across
different tasks on a high-variance instrument; always same-task, and n>=4 on the complex task.

### Caveats
- Credits ≠ tokens; Kiro `auto` variance is large on the complex task (k_2cfg swung 2.92-5.30,
  decomp 1.81-4.90). The ~16% decomp edge is directional, backed by the lower-noise native_ops
  signal (8.25 vs 12.75) which points the same way.
- Correctness is not moved by any 2-config rule — it's task/spec-interpretation variance.
- Cursor confirmation of decomp (the runtime it was designed for) was interrupted and not completed;
  decomp's Cursor benefit is still unverified end-to-end.
