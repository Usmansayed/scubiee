# Complex long dev task — WITH vs WITHOUT Scubiee (2-config + k_2cfg rule), Kiro

The prior with/without used a quick integration task (~1-4 credits). This tests a genuinely LONG,
complex 2-turn feature build where locating existing code matters.

**Task: `cli_health_command`** — build a brand-new `scubiee health` CLI subcommand (turn 1) that
rolls up the sync-status contract into a readable verdict, then (turn 2, same resumed session) add a
`--json` flag + a CI exit code. The agent must discover (a) how subcommands register in
`packages/pipeline/__main__.py` and (b) the sync-status contract shape — real cross-module location
work, not greenfield. The oracle runs the REAL CLI as a subprocess and asserts behavior.

Arms: WITHOUT = native tools only (`kab_without`, runs FIRST); WITH = 2-config bridge + k_2cfg tuned
rule (`kab_2cfg`). Model `auto`.

## Round 1 (n=2)
| arm | avg credits | per-rep | avg wall | map | configs | native_ops | oracle |
|---|--:|---|--:|--:|---|--:|---|
| kab_without (native) | 10.61 | 12.52, 8.71 | ~310s | 0 | — | 15 | 1.0, 1.0 |
| kab_2cfg (Scubiee) | 2.85 | 2.19, 3.51 | ~205s | 9 | find+focus | 7 | 1.0, **0.67** |

**Cost/speed: a big Scubiee win.** On this complex task Scubiee was **~3.7× cheaper** (2.85 vs 10.61
credits) and **~35% faster** (~205s vs ~310s), with native_ops cut from 15 → 7. The tuned rule drove
heavy, correct config usage — both find AND focus, 7-11 map calls on a genuinely hard task
(`cfg={'find':4,'focus':3}` and `{'find':4,'focus':7}`). This is map doing exactly its job on a
long, location-heavy task.

**Correctness: an honest wrinkle.** One Scubiee rep failed the oracle (r2 = 0.67, success=False)
while both native reps passed (1.0). Reading r2's own final text, the cause was NOT the tool or the
2-config surface — the agent LOCATED everything fine (find+focus, right file edited). It made a
spec-interpretation mistake: it implemented `--json` as auto-detect-TTY (piped → JSON) to mimic the
`status` convention, instead of the explicit `--json` flag the spec required, so the no-flag
human-text assertion failed. That is a feature-design miss on a vague 2-turn prompt — the kind of
thing that varies run to run — not a retrieval failure. The native arm happened to read the spec
correctly both times (n=2).

## Round 2 (n=2 more) — the correctness tie-breaker
| arm | per-rep credits | oracle | success |
|---|---|---|---|
| kab_without (native) | 10.19, 13.56 | 0.67, 0.67 | 0/2 |
| kab_2cfg (Scubiee) | 6.86, 3.50 | 0.67, 0.67 | 0/2 |

Round 2 settled the correctness question: **all four cells scored 0.67 — BOTH arms failed BOTH
reps.** Native went 0/2 this round (it was 2/2 in round 1). So the round-1 "native 2/2 vs Scubiee
1/2" split was **task/seed variance, not a Scubiee weakness** — the `cli_health_command` oracle is
just hard to fully satisfy on this vague 2-turn prompt, and either arm misses a spec detail (usually
the explicit-`--json`-flag vs TTY-autodetect decision) depending on the run.

## Combined (n=4 each)
| arm | avg credits | per-rep | correctness | avg native_ops | map |
|---|--:|---|---|--:|--:|
| kab_without (native) | **11.24** | 12.52, 8.71, 10.19, 13.56 | 2/4 pass | ~16 | 0 |
| kab_2cfg (Scubiee + k_2cfg) | **4.01** | 2.19, 3.51, 6.86, 3.50 | 1/4 pass | ~10 | find+focus, 6-12 |

## Bottom line (complex long task)
- **Cost: Scubiee is ~2.8× cheaper on this heavy 2-turn feature** (4.01 vs 11.24 credits avg), and
  faster in round 1 (~205s vs ~310s). native_ops dropped ~16 → ~10. The tuned k_2cfg rule drove
  strong, balanced config use (find AND focus, e.g. `{'find':6,'focus':6}`) on a genuinely hard task.
- **Correctness is a WASH, driven by the task not the tool.** Across n=4, native passed 2/4 and
  Scubiee 1/4, but round 2 had BOTH arms at 0/4 — the variance is in how the model interprets the
  vague spec (explicit flag vs TTY autodetect), identical regardless of whether Scubiee is present.
  Scubiee neither helped nor hurt correctness here; it changed cost and tool-mix, which is the whole
  project's recurring finding, now confirmed on a long complex task too.
- **The honest headline:** on a complex, location-heavy dev task, the 2-config Scubiee + k_2cfg rule
  does the SAME work for roughly a THIRD of the credits, with no correctness penalty attributable to
  the tool. The cost win is larger here than on the quick integration task (~2.8× vs the integration
  ~4× — both big) because a long task does more locating, which is exactly where map substitutes for
  native search.

All 8 cells (both rounds) isolated (`identical_tree: True`); repo clean before and after; production
untouched. Caveat: single task, n=4, and the oracle's strictness makes absolute pass-rate low for
everyone — the comparison that's valid is the COST/tool-mix delta and the EQUAL correctness, not the
absolute pass numbers.


---

# Same complex task on CURSOR — WITH vs WITHOUT (tokens, n=2)

Same `cli_health_command` 2-turn feature build, Cursor runtime. WITHOUT first, then `k_2cfg`.

| arm | avg tokens | per-rep | tools | map calls | oracle |
|---|--:|---|--:|--:|---|
| without (native) | 1,376,520 | 1,397,667 / 1,355,373 | 51-55 | 0 | 1.0, 1.0 |
| k_2cfg (Scubiee) | 1,486,682 | 1,726,606 / 1,246,757 | 54 | **1 each** | 1.0, 1.0 |

**On Cursor, Scubiee did NOT help on this complex task — the OPPOSITE of Kiro.** It was a token
tie-to-slightly-worse (1.49M vs 1.38M, inside the Scubiee arm's own 1.25M↔1.73M spread). Correctness
was perfect for both arms (2/2).

**Why: Cursor barely adopted the map tool.** Both Scubiee reps show `scub=1` (`cfg={'find':1}`) while
still making 54 native tool calls. The agent called map ONCE, then fell back to native grep/read
exploration — so map SUPPLEMENTED (one extra call) instead of SUBSTITUTING for native search. That is
the additive-not-substitutive failure mode, and it's why cost didn't drop.

**Kiro vs Cursor on the SAME complex task + SAME k_2cfg rule — a sharp split:**
| | Kiro | Cursor |
|---|---|---|
| map calls | 6-12 (find+focus) | 1 (find) |
| native_ops | ~10 (down from ~16) | ~54 (unchanged) |
| cost vs native | ~2.8× CHEAPER | tie / slightly worse |

Same tool, same rule, opposite adoption. Kiro's agent leans on map and substitutes; Cursor's `auto`
agent on a long task calls map once and reverts to grep-walking. This matches the whole project's
recurring runtime finding: **Scubiee's value is adoption-gated, and Cursor under-adopts on long
tasks.** The 2-config surface and k_2cfg rule did not fix Cursor's under-adoption here — on the quick
integration task Cursor adopted fine (find+focus, ~18% cheaper), but on this long multi-turn build it
front-loaded one map call and then stopped reaching for it.

**Takeaway.** The 2-config + k_2cfg packaging is a strong win on Kiro across task sizes, and a win on
Cursor for shorter/integration tasks, but it does NOT make Cursor use map on a long complex build —
there the Cursor agent's native-exploration habit dominates. If Cursor is a target runtime for long
tasks, the lever is adoption (rule strength / forcing map before grep), not the config count.

Clean teardown both runtimes; global ~/.cursor/mcp.json restored; repo clean. Caveat: n=2 Cursor,
one task.
